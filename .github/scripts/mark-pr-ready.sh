#!/usr/bin/env bash
set -euo pipefail

: "${REPO:?REPO must be set}"
: "${WORK_ITEM_KIND:?WORK_ITEM_KIND must be set}"
: "${WORK_ITEM_NUMBER:?WORK_ITEM_NUMBER must be set}"

pr_number=""

if [ "${WORK_ITEM_KIND}" = "pr" ]; then
    pr_number="${WORK_ITEM_NUMBER}"
elif [ "${WORK_ITEM_KIND}" = "issue" ]; then
    pr_number=$(gh pr list --repo "${REPO}" --head "issue-${WORK_ITEM_NUMBER}" --state open --json number --jq '.[0].number // empty')
    if [ -z "${pr_number}" ]; then
        pr_number=$(gh pr list --repo "${REPO}" --state open --label "source-issue:${WORK_ITEM_NUMBER}" --json number --jq '.[0].number // empty')
    fi
fi

if [ -z "${pr_number}" ]; then
    echo "mark-pr-ready: no open PR found for ${WORK_ITEM_KIND} #${WORK_ITEM_NUMBER} — skipping" >&2
    exit 0
fi

echo "mark-pr-ready: marking PR #${pr_number} ready for review"
gh pr ready "${pr_number}" --repo "${REPO}"
