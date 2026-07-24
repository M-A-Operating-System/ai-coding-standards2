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
#   GITHUB_TOKEN / GH_TOKEN / AI_AGILE_BOT_TOKEN   auth for gh
#
# Exit codes:
#   0  merged (or already merged) and branch deleted
#   1  refused: PR is closed-unmerged, or has merge conflicts
#   2  usage / not-found error

set -euo pipefail

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
if gh pr view "${NUMBER}" --repo "${REPO}" --json number >/dev/null 2>&1; then
  PR="${NUMBER}"
else
  PR=$(gh pr list --repo "${REPO}" --head "issue-${NUMBER}" --state open \
         --json number --jq '.[0].number // empty' 2>/dev/null || true)
  if [[ -z "${PR}" ]]; then
    echo "ERROR: no PR #${NUMBER} in ${REPO}, and no open PR for branch issue-${NUMBER}." >&2
    exit 2
  fi
fi

# --- Read PR state (one API call, parsed without an external jq) ------------
PR_JSON=$(gh pr view "${PR}" --repo "${REPO}" \
  --json state,merged,mergeable,headRefName,isCrossRepository 2>/dev/null) || {
    echo "ERROR: could not read pull request #${PR} in ${REPO}." >&2
    exit 2
  }
{
  read -r STATE
  read -r MERGED
  read -r MERGEABLE
  read -r BRANCH
  read -r CROSS
} < <(printf '%s' "${PR_JSON}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d['state'])
print(str(d['merged']).lower())
print(d['mergeable'])
print(d['headRefName'])
print(str(d['isCrossRepository']).lower())
")

# --- Guard rails ------------------------------------------------------------
if [[ "${MERGED}" == "true" ]]; then
  echo "PR #${PR} is already merged."
elif [[ "${STATE}" != "OPEN" ]]; then
  echo "ERROR: PR #${PR} is ${STATE} (not open, not merged) -- refusing to merge." >&2
  exit 1
elif [[ "${MERGEABLE}" == "CONFLICTING" ]]; then
  echo "ERROR: PR #${PR} has merge conflicts (mergeable=${MERGEABLE}) -- resolve them first." >&2
  exit 1
fi

# --- Merge (unless already merged), deleting the branch ---------------------
if [[ "${MERGED}" != "true" ]]; then
  gh pr merge "${PR}" --repo "${REPO}" "${METHOD}" --delete-branch
  echo "Merged PR #${PR} (${METHOD#--}) and deleted branch '${BRANCH}'."
  exit 0
fi

# Already merged: ensure the head branch is gone (idempotent). Skip fork
# branches (cross-repo) -- they live in the fork, not this repo.
if [[ -n "${BRANCH}" && "${CROSS}" != "true" ]]; then
  if gh api --method DELETE "/repos/${REPO}/git/refs/heads/${BRANCH}" >/dev/null 2>&1; then
    echo "Deleted branch '${BRANCH}'."
  else
    echo "Branch '${BRANCH}' already gone."
  fi
fi
echo "Done."
