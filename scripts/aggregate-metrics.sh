#!/usr/bin/env bash
# aggregate-metrics.sh -- weekly metrics aggregation scheduled pipeline step.
#
# Reads records.jsonl from the ai-agile/metrics branch, computes per-agent and
# blended weekly aggregate records for the previous Mon-Sun week, and appends
# each record back into the same file using append-metrics-record.sh.
#
# Aggregate rows are identifiable by:
#   agent_id == "metrics-aggregator"  (blended total row)
#   period   == "week"                (both per-agent and blended rows)
#
# Emits AI_AGILE_STATUS: complete | blocked as the last stdout line.
# All diagnostic output goes to stderr.
#
# Required env (injected by the orchestrator):
#   AI_AGILE_ROOT  -- repo root, used to locate metrics_aggregator.py

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

ROOT="${AI_AGILE_ROOT:-$(cd -- "${SCRIPT_DIR}/.." && pwd)}"
AGGREGATOR="${ROOT}/pipeline/metrics_aggregator.py"
APPEND_SCRIPT="${SCRIPT_DIR}/append-metrics-record.sh"

if [[ ! -f "$AGGREGATOR" ]]; then
    echo "aggregate-metrics: ERROR: metrics_aggregator.py not found at ${AGGREGATOR}" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

if [[ ! -f "$APPEND_SCRIPT" ]]; then
    echo "aggregate-metrics: ERROR: append-metrics-record.sh not found at ${APPEND_SCRIPT}" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

# Compute aggregate records.  python3 -I (isolated mode) prevents the data
# directory from being treated as a module root.
output=$(python3 -I "$AGGREGATOR" 2>&1)
exit_code=$?

if (( exit_code != 0 )); then
    echo "aggregate-metrics: ERROR: metrics_aggregator.py exited ${exit_code}:" >&2
    echo "$output" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

if [[ -z "$output" ]]; then
    echo "aggregate-metrics: no records to append (already aggregated or no data for the period)" >&2
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

# Append each record line.
tmpdir=$(mktemp -d)
trap 'rm -rf -- "$tmpdir"' EXIT

appended=0
while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    tmpfile="${tmpdir}/record_${appended}.jsonl"
    printf '%s\n' "$line" > "$tmpfile"

    AI_AGILE_METRICS_BRANCH="ai-agile/metrics" \
    AI_AGILE_METRICS_FILE="records.jsonl" \
    AI_AGILE_METRICS_COMMIT_MESSAGE="metrics: weekly aggregate" \
    AI_AGILE_METRICS_RETRIES="3" \
    bash "$APPEND_SCRIPT" "$tmpfile"

    appended=$(( appended + 1 ))
done <<< "$output"

echo "aggregate-metrics: appended ${appended} record(s)" >&2
echo "AI_AGILE_STATUS: complete"
