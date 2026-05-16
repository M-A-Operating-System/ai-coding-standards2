#!/usr/bin/env bash
# start-review.sh
#
# Triggered after the coder agent completes on an issue. Finds the open
# draft PR for this issue (branch issue-{N}) and applies
# pr-reviewer:requested to trigger the automated review cycle.
#
# Idempotent: gh pr edit --add-label is a no-op if the label is already present.
#
# Environment (set by orchestrator):
#   REPO          — owner/repo
#   ISSUE_NUMBER  — the issue being processed
#   GITHUB_TOKEN  — token with issues:write and pull-requests:write

set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: ISSUE_NUMBER is not a valid integer: ${ISSUE_NUMBER}" >&2
  exit 1
fi

BRANCH="issue-${ISSUE_NUMBER}"

# Find the open PR for this issue's branch.
PR_NUMBER=$(
  gh pr list \
    --repo "${REPO}" \
    --head "${BRANCH}" \
    --state open \
    --json number \
    --jq '.[0].number // empty' \
  2>/dev/null || true
)

if [[ -z "${PR_NUMBER}" ]]; then
  echo "No open PR found for branch ${BRANCH} — skipping pr-reviewer trigger."
  echo "AI_AGILE_STATUS: complete"
  exit 0
fi

echo "Found PR #${PR_NUMBER} for issue #${ISSUE_NUMBER} on branch ${BRANCH}."

gh pr edit "${PR_NUMBER}" --repo "${REPO}" --add-label "pr-reviewer:requested"

echo "Applied pr-reviewer:requested to PR #${PR_NUMBER}."
echo "AI_AGILE_STATUS: complete"
