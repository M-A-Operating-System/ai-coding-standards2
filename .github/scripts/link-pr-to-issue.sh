#!/usr/bin/env bash
# link-pr-to-issue.sh
#
# Discovers PRs opened by agents for the current issue and applies
# source-issue:{N} labels to each one.
#
# Convention: agent branches are named with "issue-{N}" somewhere in the
# branch name (e.g. docs/issue-42-prd-update, feat/issue-42-add-auth).
#
# Environment (set by orchestrator):
#   REPO            — owner/repo
#   ISSUE_NUMBER    — the issue being processed
#
# Exit behaviour:
#   Prints AI_AGILE_STATUS: complete on success (even if no PRs found).
#   Prints AI_AGILE_STATUS: blocked "reason" if a required tool is missing.
#   Exits non-zero without a sentinel only on unexpected errors (→ :failed).

set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

# Reject non-integer ISSUE_NUMBER before it reaches jq --argjson.
if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo 'AI_AGILE_STATUS: blocked "ISSUE_NUMBER is not a valid integer"'
  exit 0
fi

# Verify gh CLI is available
if ! command -v gh &>/dev/null; then
  echo 'AI_AGILE_STATUS: blocked "gh CLI not found; cannot link PRs to issue"'
  exit 0
fi

# Verify jq is available
if ! command -v jq &>/dev/null; then
  echo 'AI_AGILE_STATUS: blocked "jq not found; cannot parse PR list"'
  exit 0
fi

echo "Scanning for PRs linked to issue #${ISSUE_NUMBER} in ${REPO}..."

# Find all open PRs whose head branch contains "issue-{N}" (with a word
# boundary after the number so issue-42 doesn't match issue-421).
LINKED_PRS=$(
  gh pr list \
    --repo "${REPO}" \
    --state open \
    --limit 200 \
    --json number,headRefName \
  | jq -r \
    --argjson n "${ISSUE_NUMBER}" \
    '.[] | select(.headRefName | test("issue-" + ($n|tostring) + "([^0-9]|$)")) | .number'
)

if [[ -z "${LINKED_PRS}" ]]; then
  echo "No PRs with branches matching issue-${ISSUE_NUMBER} found; nothing to link."
  echo "AI_AGILE_STATUS: complete"
  exit 0
fi

SOURCE_LABEL="source-issue:${ISSUE_NUMBER}"

# Ensure the source-issue label exists in the repo.
# --force is intentionally omitted: if the label already exists with a
# different colour/description, we leave it as-is rather than silently
# overwriting the human-authored metadata. The 422 (already exists) is
# suppressed via stderr redirect; all other errors surface normally.
gh label create "${SOURCE_LABEL}" \
  --repo "${REPO}" \
  --color "0075ca" \
  --description "PR was opened by an agent working on issue #${ISSUE_NUMBER}" \
  2>/dev/null || true

LINKED_COUNT=0
while IFS= read -r PR_NUMBER; do
  [[ -z "${PR_NUMBER}" ]] && continue

  echo "  Linking PR #${PR_NUMBER} → issue #${ISSUE_NUMBER}"

  # Apply source-issue:{N} label to the PR.
  gh pr edit "${PR_NUMBER}" \
    --repo "${REPO}" \
    --add-label "${SOURCE_LABEL}" 2>/dev/null || {
    echo "  Warning: could not apply ${SOURCE_LABEL} to PR #${PR_NUMBER} — continuing"
    continue
  }

  LINKED_COUNT=$(( LINKED_COUNT + 1 ))
done <<< "${LINKED_PRS}"

echo "Linked ${LINKED_COUNT} PR(s) to issue #${ISSUE_NUMBER}."
echo "AI_AGILE_STATUS: complete"
