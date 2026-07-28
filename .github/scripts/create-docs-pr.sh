#!/usr/bin/env bash
# create-docs-pr.sh
#
# Design-phase variant of create-pr.sh (issue #247, two-phase design->build
# delivery). Opens the DESIGN pull request on the issue-{N}-docs branch with a
# non-closing body. prd-docs-updater then commits the docs/product/ and
# docs/features/ changes to this branch; merge-docs-pr merges it to main at the
# prd-docs-updater:approved gate, ahead of the build phase. The code PR
# (issue-{N}, Closes #{N}) is opened later by create-pr from the updated main.
#
# This is a thin wrapper: it sets the phase parameters and delegates to
# create-pr.sh, reusing its tested token/freshness/idempotency logic.
#
# Environment (set by orchestrator): REPO, ISSUE_NUMBER, GITHUB_TOKEN,
#   optionally AI_AGILE_BOT_TOKEN.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BRANCH_SUFFIX="-docs" \
PR_CLOSES_ISSUE="false" \
CREATE_PR_AGENT="01_product_docs/create-docs-pr" \
  exec bash "${_SCRIPT_DIR}/create-pr.sh"
