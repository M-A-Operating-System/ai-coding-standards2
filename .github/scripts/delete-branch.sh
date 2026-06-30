#!/usr/bin/env bash
# delete-branch.sh
#
# Deletes the head branch of a closed PR when it matches the issue-{N} pattern.
# Called by the orchestrator's _wake() when GITHUB_EVENT_NAME=pull_request and
# action=closed. Idempotent — silently succeeds if the branch is already gone.
#
# Environment:
#   REPO   — owner/repo
#   BRANCH — the branch to delete (typically from GITHUB_HEAD_REF)

set -euo pipefail

: "${REPO:?REPO must be set}"
: "${BRANCH:?BRANCH must be set}"

# Only delete branches that match the issue-{N} pattern.
if ! [[ "${BRANCH}" =~ ^issue-[0-9]+$ ]]; then
  echo "Branch '${BRANCH}' does not match issue-{N} pattern — skipping."
  echo "AI_AGILE_STATUS: complete"
  exit 0
fi

echo "Deleting branch '${BRANCH}' from ${REPO}..."

# Delete via the GitHub API. Tolerate non-zero exit so the script is idempotent
# when the branch was already deleted (GitHub returns 422 for a missing ref).
if gh api \
  --method DELETE \
  "/repos/${REPO}/git/refs/heads/${BRANCH}" \
  2>/dev/null; then
  echo "Branch '${BRANCH}' deleted."
else
  echo "Branch '${BRANCH}' already gone or could not be deleted — nothing to do."
fi

echo "AI_AGILE_STATUS: complete"
