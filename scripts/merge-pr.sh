#!/usr/bin/env bash
# merge-pr.sh -- deterministically merge a pull request and delete its branch.
#
# Finds the right PR for the given number, verifies it is open and not
# conflicting, merges it, and deletes the head branch. No LLM/agent judgement --
# pure commands, like create-pr.sh. Safe to re-run (idempotent on an already-
# merged PR: it just ensures the branch is gone).
#
# Usage:
#   merge-pr.sh <number> [--merge|--squash|--rebase]
#
#   <number>  a PR number, or an issue number whose issue-{N} branch has an
#             open PR. Resolved PR-number-first, then by the issue-{N} branch.
#   [method]  merge method; defaults to --merge.
#
# Env:
#   REPO                 owner/repo (required)
#   GITHUB_TOKEN / GH_TOKEN   auth for gh, resolved by lib/github-identity.sh
#
# Exit codes:
#   0  merged (or already merged) and branch deleted
#   1  refused: PR is closed-unmerged, or has merge conflicts
#   2  usage / not-found error

set -euo pipefail

# The identity every headless system action on GitHub uses (MI-7): the
# dedicated bot when the repository configures one, otherwise exactly the token
# this script used before. Resolved in one place, never here.
# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

NUMBER="${1:?usage: merge-pr.sh <pr-or-issue-number> [--merge|--squash|--rebase]}"
METHOD="${2:---merge}"

: "${REPO:?REPO must be set (owner/repo)}"

if ! [[ "${NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: number must be a positive integer, got: ${NUMBER}" >&2
  exit 2
fi
case "${METHOD}" in
  --merge|--squash|--rebase) ;;
  *) echo "ERROR: method must be --merge, --squash, or --rebase, got: ${METHOD}" >&2; exit 2 ;;
esac

# --- Resolve the target PR --------------------------------------------------
# PR-number first (matches "merge <PR>"); fall back to the open PR whose head
# branch is issue-${NUMBER} (matches "merge <issue>").
if gh api "repos/${REPO}/pulls/${NUMBER}" >/dev/null 2>&1; then
  PR="${NUMBER}"
else
  PR=$(gh api "repos/${REPO}/pulls?head=${REPO%%/*}:issue-${NUMBER}&state=open&per_page=1" \
         --jq '.[0].number // empty' 2>/dev/null || true)
  if [[ -z "${PR}" ]]; then
    echo "ERROR: no PR #${NUMBER} in ${REPO}, and no open PR for branch issue-${NUMBER}." >&2
    exit 2
  fi
fi

# --- Read PR state (one API call, parsed without an external jq) ------------
PR_JSON=$(gh api "repos/${REPO}/pulls/${PR}" 2>/dev/null) || {
    echo "ERROR: could not read pull request #${PR} in ${REPO}." >&2
    exit 2
  }
{
  read -r STATE
  read -r MERGED
  read -r MERGEABLE
  read -r BRANCH
  read -r CROSS
  read -r BASE_REF
  read -r BASE_DEFAULT_BRANCH
  read -r CLOSE_NUMBERS
} < <(printf '%s' "${PR_JSON}" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
# REST returns a lowercase state ('open'/'closed'); upper-case it so the
# downstream comparisons ('OPEN') are preserved unchanged.
print(d['state'].upper())
print(str(d['merged']).lower())
print(d['mergeable_state'])
print(d['head']['ref'])
# REST has no isCrossRepository field; derive it by comparing the head and
# base repositories (a missing/deleted head repo is treated as cross-repo).
head_repo = (d.get('head') or {}).get('repo') or {}
base_repo = (d.get('base') or {}).get('repo') or {}
print(str(head_repo.get('full_name') != base_repo.get('full_name')).lower())
# The base branch and the repo's default branch -- GitHub's own 'Closes #N'
# keyword only auto-closes the referenced issue when the PR merges into the
# *default* branch (never on a merge into any other branch, e.g. a parent
# epic's shared integration branch, naming.base 'issue-{parent_number}').
# base.repo is a full repository projection on the REST pull response, so
# this needs no extra API call.
print((d.get('base') or {}).get('ref', ''))
print(base_repo.get('default_branch', ''))
# Every issue this PR's body says it closes, via any of GitHub's recognised
# closing keywords -- deduplicated, first-seen order.
body = d.get('body') or ''
nums = re.findall(r'(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)', body)
print(' '.join(dict.fromkeys(nums)))
")

# --- Let mergeability settle -----------------------------------------------
# REST reports mergeable_state 'unknown' for a short window after a push while
# GitHub recomputes it. Re-fetch a few times so a real conflict surfaces as
# 'dirty' at the guard below, rather than as a raw 405 from the merge call.
_tries=0
while [[ "${MERGED}" != "true" && "${STATE}" == "OPEN" \
         && ( -z "${MERGEABLE}" || "${MERGEABLE}" == "unknown" ) && ${_tries} -lt 3 ]]; do
  sleep 2
  MERGEABLE=$(gh api "repos/${REPO}/pulls/${PR}" --jq '.mergeable_state' 2>/dev/null || echo "unknown")
  _tries=$((_tries + 1))
done

# --- Guard rails ------------------------------------------------------------
if [[ "${MERGED}" == "true" ]]; then
  echo "PR #${PR} is already merged."
elif [[ "${STATE}" != "OPEN" ]]; then
  echo "ERROR: PR #${PR} is ${STATE} (not open, not merged) -- refusing to merge." >&2
  exit 1
elif [[ "${MERGEABLE}" == "dirty" ]]; then
  echo "ERROR: PR #${PR} has merge conflicts (mergeable=${MERGEABLE}) -- resolve them first." >&2
  exit 1
fi

# --- Explicitly close any issue this PR's body says it closes, but only when
# GitHub's own "Closes #N" keyword will not fire on its own: that keyword
# auto-closes only on a merge into the repository's *default* branch. A PR
# merging into any other branch (e.g. a decomposed parent epic's shared
# integration branch) never triggers it, so the referenced issue -- and, if
# it is itself an epic, every epic-completion trigger gated on that issue's
# children being closed -- would otherwise stay open forever even though the
# code has fully landed. Idempotent: closing an already-closed issue is a
# no-op.
_close_referenced_issues_if_needed() {
  if [[ -z "${CLOSE_NUMBERS}" ]]; then
    return 0
  fi
  if [[ -n "${BASE_DEFAULT_BRANCH}" && "${BASE_REF}" == "${BASE_DEFAULT_BRANCH}" ]]; then
    # Merging into the default branch -- GitHub's own keyword already covers this.
    return 0
  fi
  for _n in ${CLOSE_NUMBERS}; do
    if gh api --method PATCH "repos/${REPO}/issues/${_n}" \
         -f state=closed -f state_reason=completed >/dev/null 2>&1; then
      echo "Closed #${_n} explicitly: PR #${PR} merged into '${BASE_REF}', not the default branch -- GitHub's Closes keyword only fires on a merge to the default branch."
    else
      echo "WARNING: could not close #${_n} after merging PR #${PR} into '${BASE_REF}'." >&2
    fi
  done
}

# --- Merge (unless already merged), deleting the branch ---------------------
if [[ "${MERGED}" != "true" ]]; then
  # REST returns 405 if GitHub still deems the PR unmergeable (conflicts,
  # required checks, or a still-'unknown' state). Catch it and emit the friendly
  # refusal instead of dying under set -e.
  if ! MERGE_OUT=$(gh api --method PUT "repos/${REPO}/pulls/${PR}/merge" \
                     -f "merge_method=${METHOD#--}" 2>&1); then
    echo "ERROR: PR #${PR} could not be merged (not mergeable -- conflicts or required checks). API said: ${MERGE_OUT}" >&2
    exit 1
  fi
  _close_referenced_issues_if_needed
  # --delete-branch equivalent: only for a branch in THIS repo (skip forks);
  # best-effort ref deletion (may be blocked; must not fail the script).
  if [[ -n "${BRANCH}" && "${CROSS}" != "true" ]]; then
    if gh api --method DELETE "repos/${REPO}/git/refs/heads/${BRANCH}" >/dev/null 2>&1; then
      echo "Merged PR #${PR} (${METHOD#--}) and deleted branch '${BRANCH}'."
    elif ! gh api "repos/${REPO}/git/refs/heads/${BRANCH}" >/dev/null 2>&1; then
      echo "Merged PR #${PR} (${METHOD#--}); branch '${BRANCH}' already gone."
    else
      echo "Warning: could not delete branch '${BRANCH}'." >&2
      echo "Merged PR #${PR} (${METHOD#--})."
    fi
  else
    echo "Merged PR #${PR} (${METHOD#--}); head branch '${BRANCH}' is in a fork -- not deleting."
  fi
  exit 0
fi

# Already merged: ensure the head branch is gone (idempotent), and that any
# issue it was supposed to close (per the explicit-close rule above) still is.
_close_referenced_issues_if_needed
if [[ -n "${BRANCH}" && "${CROSS}" != "true" ]]; then
  if gh api --method DELETE "/repos/${REPO}/git/refs/heads/${BRANCH}" >/dev/null 2>&1; then
    echo "Deleted branch '${BRANCH}'."
  else
    echo "Branch '${BRANCH}' already gone."
  fi
fi
echo "Done."
