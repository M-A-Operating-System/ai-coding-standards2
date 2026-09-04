#!/usr/bin/env bash
set -euo pipefail

: "${REPO:?REPO must be set}"
: "${WORK_ITEM_KIND:?WORK_ITEM_KIND must be set}"
: "${WORK_ITEM_NUMBER:?WORK_ITEM_NUMBER must be set}"

pr_number=""

if [ "${WORK_ITEM_KIND}" = "pr" ]; then
    pr_number="${WORK_ITEM_NUMBER}"
elif [ "${WORK_ITEM_KIND}" = "issue" ]; then
    # The branch comes from the step's flow naming, exported by the
    # orchestrator (issue #406) -- never derived from the issue number here.
    : "${AI_AGILE_BRANCH:?AI_AGILE_BRANCH must be set -- the branch declared by this step flow naming}"
    pr_number=$(gh api "repos/${REPO}/pulls?head=${REPO%%/*}:${AI_AGILE_BRANCH}&state=open&per_page=1" --jq '.[0].number // empty')
    if [ -z "${pr_number}" ]; then
        pr_number=$(gh api "repos/${REPO}/issues?state=open&labels=source-issue:${WORK_ITEM_NUMBER}&per_page=100" --jq '[.[] | select(.pull_request) | .number] | first // empty')
    fi
fi

if [ -z "${pr_number}" ]; then
    echo "mark-pr-ready: no open PR found for ${WORK_ITEM_KIND} #${WORK_ITEM_NUMBER} — skipping" >&2
    exit 0
fi

# Check whether the PR is already ready (draft: false) before attempting the call.
# gh pr ready has no REST equivalent and is blocked in restricted interactive sessions;
# the idempotency check avoids a deterministic failure when the PR was already marked
# ready by the driver's MCP assist or the agent's own action.
_pr_draft=$(gh api "repos/${REPO}/pulls/${pr_number}" --jq '.draft')
if [ "${_pr_draft}" = "false" ]; then
    echo "mark-pr-ready: PR #${pr_number} is already ready for review — skipping"
    exit 0
fi

echo "mark-pr-ready: marking PR #${pr_number} ready for review"
# gh pr ready has no REST equivalent; works on the CI runner. In a restricted interactive session the /maos-run driver marks the PR ready via the GitHub MCP tool.
gh pr ready "${pr_number}" --repo "${REPO}"
