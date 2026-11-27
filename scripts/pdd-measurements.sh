#!/usr/bin/env bash
# pdd-measurements.sh -- scripted pipeline step 01_product_docs/pdd-measurements
# (issue #760, part 2 of #507).
#
# Calls pipeline/calculate_pdd_measurements.py --issue $ISSUE_NUMBER. The
# Python script checks for prd-writer:approved, parses the Gherkin acceptance
# criteria, and appends one pdd_measurements record to the metrics ledger via
# scripts/append-metrics-record.sh.
#
# Emits AI_AGILE_STATUS: complete on success (including the no-op skip when
# prd-writer:approved is absent), AI_AGILE_STATUS: blocked on malformed Gherkin
# or reconciliation failure.
#
# NOT a Claude agent step -- does not invoke the Claude CLI.
#
# Environment (set by orchestrator): REPO, ISSUE_NUMBER, AI_AGILE_ROOT
# Also inherits: GH_TOKEN/GITHUB_TOKEN, AI_AGILE_BOT_TOKEN (passed through to
# the Python script's append-metrics-record.sh subprocess).

set -euo pipefail

# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname -- "$SCRIPT_DIR")"
PYTHON_SCRIPT="${REPO_ROOT}/pipeline/calculate_pdd_measurements.py"

if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo "pdd-measurements: ERROR: not found: ${PYTHON_SCRIPT}" >&2
    echo "AI_AGILE_STATUS: blocked" >&2
    exit 1
fi

export AI_AGILE_ROOT="${AI_AGILE_ROOT:-${REPO_ROOT}}"

python3 "$PYTHON_SCRIPT" --issue "$ISSUE_NUMBER"
