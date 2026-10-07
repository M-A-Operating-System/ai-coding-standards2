#!/usr/bin/env bash
# generate-metrics-report.sh -- weekly performance report scheduled pipeline step.
#
# Reads weekly-aggregate rows from records.jsonl on the ai-agile/metrics branch,
# generates per-metric charts via matplotlib, assembles them into print-styled
# HTML, and renders a PDF via WeasyPrint.
#
# The PDF is written to ${AI_AGILE_SCRATCH}/metrics-report.pdf.
#
# Emits AI_AGILE_STATUS: complete | blocked as the last stdout line.
# All diagnostic output goes to stderr.
#
# Required env (injected by the orchestrator):
#   AI_AGILE_ROOT   -- repo root, used to locate metrics_report.py
#   AI_AGILE_SCRATCH -- per-run scratch directory for the output PDF
#
# Runtime Python requirements (not in requirements.txt -- install separately):
#   matplotlib >= 3.7
#   weasyprint >= 61

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${AI_AGILE_ROOT:-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
REPORTER="${ROOT}/pipeline/metrics_report.py"
SCRATCH="${AI_AGILE_SCRATCH:-/tmp}"
OUTPUT="${SCRATCH}/metrics-report.pdf"

if [[ ! -f "$REPORTER" ]]; then
    echo "generate-metrics-report: ERROR: metrics_report.py not found at ${REPORTER}" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

tmpdir=$(mktemp -d)
trap 'rm -rf -- "$tmpdir"' EXIT
stderr_file="${tmpdir}/stderr"

if ! python3 -I "$REPORTER" --output "$OUTPUT" 2>"$stderr_file"; then
    echo "generate-metrics-report: ERROR: metrics_report.py failed:" >&2
    cat -- "$stderr_file" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

if [[ -s "$stderr_file" ]]; then
    cat -- "$stderr_file" >&2
fi

if [[ ! -f "$OUTPUT" ]]; then
    echo "generate-metrics-report: no PDF produced (no aggregate data or renderable metrics)" >&2
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

echo "generate-metrics-report: PDF produced at ${OUTPUT}" >&2
echo "AI_AGILE_STATUS: complete"
