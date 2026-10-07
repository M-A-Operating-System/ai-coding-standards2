#!/usr/bin/env bash
# generate-metrics-report.sh -- weekly performance report scheduled pipeline step.
#
# Reads weekly-aggregate rows from records.jsonl on the ai-agile/metrics branch,
# generates per-metric charts via matplotlib, assembles them into print-styled
# HTML, renders a PDF via WeasyPrint, and commits the PDF to the
# ai-agile/reports branch so it persists across runs.
#
# Emits AI_AGILE_STATUS: complete | blocked as the last stdout line.
# All diagnostic output goes to stderr.
#
# Required env (injected by the orchestrator):
#   AI_AGILE_ROOT   -- repo root, used to locate metrics_report.py
#   AI_AGILE_SCRATCH -- per-run scratch directory for the working PDF
#
# Runtime Python requirements (not in requirements.txt -- install separately):
#   matplotlib >= 3.7
#   weasyprint >= 61

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${AI_AGILE_ROOT:-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
REPORTER="${ROOT}/pipeline/metrics_report.py"
COMMIT_SCRIPT="${SCRIPT_DIR}/commit-report.sh"
SCRATCH="${AI_AGILE_SCRATCH:-/tmp}"
OUTPUT="${SCRATCH}/metrics-report.pdf"
REPORTS_BRANCH="ai-agile/reports"

if [[ ! -f "$REPORTER" ]]; then
    echo "generate-metrics-report: ERROR: metrics_report.py not found at ${REPORTER}" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

if [[ ! -f "$COMMIT_SCRIPT" ]]; then
    echo "generate-metrics-report: ERROR: commit-report.sh not found at ${COMMIT_SCRIPT}" >&2
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

# Commit the PDF to the persistent reports branch so it survives the scratch
# directory being removed at the end of the run.
report_date=$(date -u +"%Y-%m-%d")
dest_path="metrics-report-${report_date}.pdf"

if ! AI_AGILE_REPORT_BRANCH="$REPORTS_BRANCH" \
     AI_AGILE_REPORT_COMMIT_MESSAGE="metrics-report: weekly PDF report (${report_date})" \
     AI_AGILE_REPORT_RETRIES="3" \
     bash "$COMMIT_SCRIPT" "$OUTPUT" "$dest_path" >&2; then
    echo "generate-metrics-report: ERROR: commit-report.sh failed -- PDF was not persisted" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

echo "generate-metrics-report: PDF committed to ${REPORTS_BRANCH}:${dest_path}" >&2
echo "AI_AGILE_STATUS: complete"
