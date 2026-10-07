#!/usr/bin/env bash
# aggregate-metrics.sh -- metrics aggregation scheduled pipeline step.
#
# Reads records.jsonl from the ai-agile/metrics branch, computes per-agent and
# blended aggregate records for the previous complete bucket of --period (the
# previous Mon-Sun week by default, or the previous complete calendar day with
# --period day), and appends each record back into the same file using
# append-metrics-record.sh.
#
# Aggregate rows are identifiable by:
#   agent_id == "metrics-aggregator"        (blended total row)
#   period   == "week" or "day"             (both per-agent and blended rows)
#
# Emits AI_AGILE_STATUS: complete | blocked as the last stdout line.
# All diagnostic output goes to stderr.
#
# --dry-run (STD-ARCH-036): performs the same read and computation as a real
# run, but skips the append-metrics-record.sh call -- the only step that
# writes to the ledger. Reports exactly which rows (agent_id, period, bucket
# boundaries) would be appended, not merely that rows exist.
#
# Required env (injected by the orchestrator):
#   AI_AGILE_ROOT  -- repo root, used to locate metrics_aggregator.py

set -euo pipefail

DRY_RUN=0
PERIOD="week"
while [[ $# -gt 0 ]]; do
    case "${1}" in
        --dry-run) DRY_RUN=1 ;;
        --period)
            if [[ -z "${2:-}" ]]; then
                echo "aggregate-metrics: ERROR: --period requires an argument" >&2
                echo "AI_AGILE_STATUS: blocked"
                exit 0
            fi
            PERIOD="${2}"
            shift
            ;;
        --period=*) PERIOD="${1#--period=}" ;;
        *)
            echo "aggregate-metrics: ERROR: unknown argument: ${1}" >&2
            echo "AI_AGILE_STATUS: blocked"
            exit 0
            ;;
    esac
    shift
done

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

tmpdir=$(mktemp -d)
trap 'rm -rf -- "$tmpdir"' EXIT
stderr_file="${tmpdir}/stderr"
records_file="${tmpdir}/records.jsonl"

# Compute aggregate records.  python3 -I (isolated mode) prevents the data
# directory from being treated as a module root.  stdout (the computed
# records) and stderr (diagnostics) go to separate files -- merging them
# (issue #533 PR review, RV-004) would append any unexpected warning line
# to the ledger as a garbage JSONL record.
if ! python3 -I "$AGGREGATOR" --period "$PERIOD" >"$records_file" 2>"$stderr_file"; then
    echo "aggregate-metrics: ERROR: metrics_aggregator.py failed:" >&2
    cat -- "$stderr_file" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi
if [[ -s "$stderr_file" ]]; then
    echo "aggregate-metrics: metrics_aggregator.py stderr (non-fatal):" >&2
    cat -- "$stderr_file" >&2
fi

if [[ ! -s "$records_file" ]]; then
    echo "aggregate-metrics: no records to append (already aggregated or no data for the period)" >&2
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

record_count=$(grep -c . -- "$records_file")

if (( DRY_RUN )); then
    echo "aggregate-metrics: DRY RUN -- would append ${record_count} record(s) to ai-agile/metrics:records.jsonl:" >&2
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        python3 -I -c '
import json, sys
rec = json.loads(sys.argv[1])
fields = ["agent_id", "period", "timestamp_start", "timestamp_end"]
summary = " ".join(f"{k}={rec.get(k)!r}" for k in fields)
print(f"  {summary}", file=sys.stderr)
' "$line"
    done < "$records_file"
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

# Every record for this bucket (each per-agent breakdown row and the blended
# total row) is appended in ONE commit via a single append-metrics-record.sh
# call on the whole file -- never one commit per row. That makes the write
# atomic: either every row for this bucket lands, or (append-metrics-record.sh
# fails closed, STD-ARCH-014) none do. A mid-write crash can therefore never
# leave the blended row -- already_aggregated()'s idempotency key -- without
# its per-agent siblings, or vice versa (issue #533 PR review, RV-002).
#
# set -e is deliberately not relied on here (RV-001): a bare command failure
# under set -e exits with no AI_AGILE_STATUS sentinel, which the orchestrator
# would otherwise have to treat as a crash rather than a reported `blocked`.
if ! AI_AGILE_METRICS_BRANCH="ai-agile/metrics" \
     AI_AGILE_METRICS_FILE="records.jsonl" \
     AI_AGILE_METRICS_COMMIT_MESSAGE="metrics: ${PERIOD} aggregate (${record_count} record(s))" \
     AI_AGILE_METRICS_RETRIES="3" \
     bash "$APPEND_SCRIPT" "$records_file"; then
    echo "aggregate-metrics: ERROR: append-metrics-record.sh failed -- no records were appended this run" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

echo "aggregate-metrics: appended ${record_count} record(s)" >&2
echo "AI_AGILE_STATUS: complete"
