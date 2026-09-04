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
# This is a thin wrapper: it delegates to create-pr.sh, reusing its tested
# token/freshness/idempotency logic under its own announcement identity. The
# branch (issue-{N}-docs) and the non-closing body are NOT set here -- they come
# from the flow's naming.pull_requests "docs" entry, which the orchestrator
# resolves and exports as AI_AGILE_BRANCH / PR_CLOSES_ISSUE (issue #406).
#
# Environment (set by orchestrator): REPO, ISSUE_NUMBER, AI_AGILE_BRANCH,
#   PR_CLOSES_ISSUE, and the system identity lib/github-identity.sh resolves.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CREATE_PR_AGENT="01_product_docs/create-docs-pr" \
  exec bash "${_SCRIPT_DIR}/create-pr.sh"
