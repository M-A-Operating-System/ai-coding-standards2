#!/usr/bin/env bash
set -euo pipefail

# The identity every headless system action on GitHub uses (MI-7): the
# dedicated bot when the repository configures one, otherwise exactly the token
# this script used before. Resolved in one place, never here.
# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

: "${REPO:?REPO must be set}"

# The orchestrator already resolves PR_NUMBER for this invocation (issue
# #431/#433) -- pr-reviewer, whose post_step this is, declares
# resolve_pr_number, so PR_NUMBER arrives set whether the work item is the
# PR itself or the issue it's for. No re-derivation, no WORK_ITEM_KIND branch.
if [ -z "${PR_NUMBER:-}" ]; then
    echo "mark-pr-ready: no PR_NUMBER resolved — skipping" >&2
    exit 0
fi
pr_number="${PR_NUMBER}"

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
