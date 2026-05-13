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
#   PIPELINE_PAT    — optional PAT used only for gh pr create when org policy
#                     blocks GITHUB_TOKEN from creating pull requests

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

# Get issue title for the PR title.
ISSUE_TITLE=$(gh issue view "${ISSUE_NUMBER}" --repo "${REPO}" --json title -q '.title')
PR_TITLE="issue-${ISSUE_NUMBER}: ${ISSUE_TITLE:0:60}"

# Create the branch from the default branch HEAD if it doesn't exist on the remote.
if ! git ls-remote --exit-code --heads origin "${BRANCH}" &>/dev/null; then
  git fetch origin "${DEFAULT_BRANCH}"
  git checkout "${DEFAULT_BRANCH}"
  git checkout -b "${BRANCH}"
  git push -u origin "${BRANCH}"
  echo "Created branch ${BRANCH} from ${DEFAULT_BRANCH}."
else
  echo "Branch ${BRANCH} already exists on remote."
fi

# Open the draft PR. gh pr create outputs the PR URL; extract the number from it.
# Use PIPELINE_PAT when available — org policy may block GITHUB_TOKEN from creating PRs.
PR_URL=$(
  GH_TOKEN="${PIPELINE_PAT:-${GH_TOKEN:-${GITHUB_TOKEN}}}" gh pr create \
    --repo "${REPO}" \
    --title "${PR_TITLE}" \
    --body "Closes #${ISSUE_NUMBER}" \
    --draft \
    --head "${BRANCH}" \
    --base "${DEFAULT_BRANCH}"
)
PR_NUMBER="${PR_URL##*/}"

echo "Opened draft PR #${PR_NUMBER} for issue #${ISSUE_NUMBER} on branch ${BRANCH}."

# Apply source-issue:{N} label to the PR immediately.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO}" ISSUE_NUMBER="${ISSUE_NUMBER}" PR_NUMBER="${PR_NUMBER}" \
  bash "${SCRIPT_DIR}/link-pr-to-issue.sh"

echo "AI_AGILE_STATUS: complete"
