#!/usr/bin/env bash
# create-pr.sh
#
# Creates the shared issue branch and opens a draft PR immediately after
# the PRD is approved, before any documentation or code agents run.
# All subsequent agent commits (docs, code) accumulate in this PR.
#
# Idempotent: if the branch and PR already exist, emits complete and exits.
#
# Environment (set by orchestrator):
#   REPO            — owner/repo
#   ISSUE_NUMBER    — the issue being processed
#   GITHUB_TOKEN    — token with repo write access (used for all git/gh calls)
#   AI_AGILE_BOT_TOKEN — optional PAT used only for gh pr create when org policy
#                        blocks GITHUB_TOKEN from creating pull requests

set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: ISSUE_NUMBER is not a valid integer: ${ISSUE_NUMBER}" >&2
  exit 1
fi

BRANCH="issue-${ISSUE_NUMBER}"

# Idempotency: if an open PR already exists for this branch, nothing to do.
EXISTING_PR=$(
  gh pr list \
    --repo "${REPO}" \
    --head "${BRANCH}" \
    --state open \
    --json number \
    -q '.[0].number // empty' \
  2>/dev/null || true
)
if [[ -n "${EXISTING_PR}" ]]; then
  echo "PR #${EXISTING_PR} already exists for branch ${BRANCH}; nothing to do."
  echo "AI_AGILE_STATUS: complete"
  exit 0
fi

# Resolve the repo's default branch for the PR base.
DEFAULT_BRANCH=$(
  gh repo view "${REPO}" --json defaultBranchRef -q '.defaultBranchRef.name' \
  2>/dev/null || echo "main"
)
echo "DEBUG: DEFAULT_BRANCH='${DEFAULT_BRANCH}' BRANCH='${BRANCH}'"

# Get issue title for the PR title.
ISSUE_TITLE=$(gh issue view "${ISSUE_NUMBER}" --repo "${REPO}" --json title -q '.title')
PR_TITLE="issue-${ISSUE_NUMBER}: ${ISSUE_TITLE:0:60}"

# Create the branch from the default branch HEAD if it doesn't exist on the remote.
if ! git ls-remote --exit-code --heads origin "${BRANCH}" &>/dev/null; then
  git fetch origin "${DEFAULT_BRANCH}"
  git checkout "${DEFAULT_BRANCH}"
  git checkout -b "${BRANCH}"
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git config user.name "github-actions[bot]"
  git commit --allow-empty -m "chore: open branch for issue-${ISSUE_NUMBER}"
  git push -u origin "${BRANCH}"
  echo "Created branch ${BRANCH} from ${DEFAULT_BRANCH} with placeholder commit."
else
  echo "Branch ${BRANCH} already exists on remote."
fi

# Ensure the branch has ≥1 commit ahead of base — GitHub rejects PR creation
# (HTTP 422) when head and base point to the same commit.
echo "DEBUG: fetching origin/${DEFAULT_BRANCH} and origin/${BRANCH} for rev-list..."
git fetch origin "${DEFAULT_BRANCH}" 2>&1 || echo "WARN: fetch of ${DEFAULT_BRANCH} failed"
git fetch origin "${BRANCH}" 2>&1 || echo "WARN: fetch of ${BRANCH} failed"
AHEAD=$(git rev-list --count "origin/${DEFAULT_BRANCH}..origin/${BRANCH}" 2>/dev/null || echo "error")
echo "DEBUG: commits origin/${DEFAULT_BRANCH}..origin/${BRANCH} = ${AHEAD}"

if [[ "${AHEAD}" == "error" || "${AHEAD}" -eq 0 ]]; then
  echo "Branch has 0 (or unknown) commits ahead — adding placeholder commit..."
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git config user.name "github-actions[bot]"
  git checkout "${BRANCH}" 2>/dev/null || git checkout -b "${BRANCH}" "origin/${BRANCH}"
  git commit --allow-empty -m "chore: open branch for issue-${ISSUE_NUMBER}"
  git push origin "${BRANCH}"
  echo "Added placeholder commit to ${BRANCH}."
else
  echo "Branch has ${AHEAD} commit(s) ahead of ${DEFAULT_BRANCH} — no placeholder needed."
fi

# Open the draft PR via the REST API. Use AI_AGILE_BOT_TOKEN when available —
# org policy may block GITHUB_TOKEN from creating PRs. REST avoids the GraphQL
# "Could not resolve to a Repository" error that gh pr create can trigger.
_PR_TOKEN="${AI_AGILE_BOT_TOKEN:-${GH_TOKEN:-${GITHUB_TOKEN}}}"
_TOKEN_SOURCE="${AI_AGILE_BOT_TOKEN:+AI_AGILE_BOT_TOKEN}"
_TOKEN_SOURCE="${_TOKEN_SOURCE:-${GH_TOKEN:+GH_TOKEN}}"
_TOKEN_SOURCE="${_TOKEN_SOURCE:-GITHUB_TOKEN}"

# Pre-flight: log which user the token authenticates as, then verify repo access.
_TOKEN_USER=$(GH_TOKEN="${_PR_TOKEN}" gh api "/user" --jq '.login' 2>/dev/null || echo "unknown")
echo "PR token source: ${_TOKEN_SOURCE}, authenticated as: ${_TOKEN_USER}"

REPO_CHECK_ERR=$(GH_TOKEN="${_PR_TOKEN}" gh api "/repos/${REPO}" --jq '.full_name' 2>&1 >/dev/null) || {
  echo "ERROR: Token (${_TOKEN_SOURCE}, user=${_TOKEN_USER}) cannot access repo ${REPO}." >&2
  echo "       API error: ${REPO_CHECK_ERR}" >&2
  echo "       Ensure the token owner is an org member with write access to this repo." >&2
  exit 1
}

echo "DEBUG: PR params: head='${BRANCH}' base='${DEFAULT_BRANCH}' title='${PR_TITLE}'"

PR_JSON=$(
  GH_TOKEN="${_PR_TOKEN}" gh api \
    --method POST \
    "/repos/${REPO}/pulls" \
    -f "title=${PR_TITLE}" \
    -f "body=Closes #${ISSUE_NUMBER}" \
    -f "head=${BRANCH}" \
    -f "base=${DEFAULT_BRANCH}" \
    -F "draft=true" 2>&1
) || {
  echo "ERROR: PR creation failed (422 details): ${PR_JSON}" >&2
  exit 1
}

PR_NUMBER=$(echo "${PR_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin)['number'])" 2>/dev/null) || {
  echo "ERROR: Could not parse PR number from response: ${PR_JSON}" >&2
  exit 1
}
PR_URL="https://github.com/${REPO}/pull/${PR_NUMBER}"

echo "Opened draft PR #${PR_NUMBER} for issue #${ISSUE_NUMBER} on branch ${BRANCH}."

# Apply source-issue:{N} label to the PR immediately.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO}" ISSUE_NUMBER="${ISSUE_NUMBER}" PR_NUMBER="${PR_NUMBER}" \
  bash "${SCRIPT_DIR}/link-pr-to-issue.sh"

echo "AI_AGILE_STATUS: complete"
