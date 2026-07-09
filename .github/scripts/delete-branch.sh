#!/usr/bin/env bash
# delete-branch.sh
#
# Deletes the head branch of a closed PR when it matches the issue-{N} pattern.
# Called by the orchestrator's _wake() when GITHUB_EVENT_NAME=pull_request,
# action=closed, and the PR was merged. Idempotent -- silently succeeds if the
# branch is already gone.
#
# Environment:
#   REPO   -- owner/repo
#   BRANCH -- the branch to delete (typically from GITHUB_HEAD_REF)

set -euo pipefail

: "${REPO:?REPO must be set}"
: "${BRANCH:?BRANCH must be set}"

# Only delete branches that match the issue-{N} pattern.
if ! [[ "${BRANCH}" =~ ^issue-[0-9]+$ ]]; then
  echo "Branch '${BRANCH}' does not match issue-{N} pattern -- skipping."
  echo "AI_AGILE_STATUS: complete"
  exit 0
fi

echo "Deleting branch '${BRANCH}' from ${REPO}..."

# Delete via the GitHub API. A 404/422 means the ref is already gone (the
# idempotent case). Any other failure (auth, permissions, rate limit) is a
# real error and must not be silently reported as "already deleted".
if DELETE_OUTPUT=$(gh api \
  --method DELETE \
  "/repos/${REPO}/git/refs/heads/${BRANCH}" \
  2>&1); then
  echo "Branch '${BRANCH}' deleted."
elif echo "${DELETE_OUTPUT}" | grep -qE "HTTP 404|HTTP 422|Reference does not exist"; then
  echo "Branch '${BRANCH}' already gone -- nothing to do."
else
  echo "Failed to delete branch '${BRANCH}': ${DELETE_OUTPUT}" >&2
  exit 1
fi

echo "AI_AGILE_STATUS: complete"
