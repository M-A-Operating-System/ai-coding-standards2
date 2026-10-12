#!/usr/bin/env bash
# request-sizing.sh
#
# Scripted step 01_product_docs/request-sizing (issue #565). Applies
# sizer:requested to the issue so the standalone "sizer" flow runs
# automatically before prd-writer, instead of leaving sizing to a human
# applying the label by hand.
#
# A lifecycle status label like sizer:requested is "only the orchestrator may
# write" (pipeline/validate.py's lifecycle-label check) -- no agent's own
# allowed_labels may cover one. A scripted step's actual gh calls are not
# validated against that check (the same way a post_steps script like
# mark-pr-ready.sh performs a GitHub action an agent itself cannot), so this
# is the sanctioned path for the side effect.
#
# Environment (set by orchestrator): REPO, ISSUE_NUMBER
#
# Emits AI_AGILE_STATUS: complete as the last stdout line.

set -euo pipefail

# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

# Idempotency: a retried step, or an issue a human already manually
# requested sizing on, should not error on a duplicate label.
already=$(
  gh api "repos/${REPO}/issues/${ISSUE_NUMBER}" \
    --jq '.labels[].name | select(. == "sizer:requested")' \
  2>/dev/null || true
)
if [ -n "${already}" ]; then
  echo "request-sizing: sizer:requested already on #${ISSUE_NUMBER} -- skipping"
else
  echo "request-sizing: applying sizer:requested to #${ISSUE_NUMBER}"
  gh api --method POST "repos/${REPO}/issues/${ISSUE_NUMBER}/labels" -f "labels[]=sizer:requested" >/dev/null
fi

echo "AI_AGILE_STATUS: complete"
