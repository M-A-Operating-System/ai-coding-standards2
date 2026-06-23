#!/usr/bin/env bash
# mark-pr-ready.sh — marks the PR for a given issue (or PR) ready for human
# review.  Invoked as a post_steps entry in pipeline.json after pr-reviewer
# signals :complete.
#
# Required env (set by orchestrator):
#   REPO             — GitHub repo in OWNER/REPO format
#   WORK_ITEM_KIND   — "issue" or "pr"
#   WORK_ITEM_NUMBER — work item number
#   AI_AGILE_ROOT    — path to the consuming repo root
#
# When WORK_ITEM_KIND=issue the script discovers the open PR by branch name
# (issue-{N}) or source-issue label, then calls `gh pr ready`.
# When WORK_ITEM_KIND=pr the PR number is WORK_ITEM_NUMBER directly.

set -euo pipefail

REPO="${REPO:?REPO is required}"
WORK_ITEM_KIND="${WORK_ITEM_KIND:?WORK_ITEM_KIND is required}"
WORK_ITEM_NUMBER="${WORK_ITEM_NUMBER:?WORK_ITEM_NUMBER is required}"

if [ "$WORK_ITEM_KIND" = "pr" ]; then
    PR_NUM="$WORK_ITEM_NUMBER"
else
    ISSUE_NUMBER="${ISSUE_NUMBER:-$WORK_ITEM_NUMBER}"
    PR_NUM=$(gh pr list \
        --repo "$REPO" \
        --head "issue-${ISSUE_NUMBER}" \
        --state open \
        --json number \
        --jq '.[0].number // empty')
    if [ -z "${PR_NUM:-}" ]; then
        PR_NUM=$(gh pr list \
            --repo "$REPO" \
            --state open \
            --label "source-issue:${ISSUE_NUMBER}" \
            --json number \
            --jq '.[0].number // empty')
    fi
    if [ -z "${PR_NUM:-}" ]; then
        echo "mark-pr-ready: no open PR found for issue #${ISSUE_NUMBER} — skipping" >&2
        exit 0
    fi
fi

gh pr ready "$PR_NUM" --repo "$REPO"
echo "mark-pr-ready: PR #${PR_NUM} marked ready for human review"
