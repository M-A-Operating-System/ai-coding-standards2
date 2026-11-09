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
#   (none for path resolution -- metrics_aggregator.py is located via SUBMODULE_ROOT)

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
SUBMODULE_ROOT="$(dirname -- "$SCRIPT_DIR")"
AGGREGATOR="${SUBMODULE_ROOT}/pipeline/metrics_aggregator.py"
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

# Split JSONL output into one file per bucket (grouped by timestamp_start).
# All rows for one bucket share the same timestamp_start; buckets are oldest first.
split_py="${tmpdir}/split_buckets.py"
cat > "${split_py}" << 'PYEOF'
import json, os, sys
records_file, out_dir = sys.argv[1], sys.argv[2]
buckets = []
seen = {}
with open(records_file) as fh:
    for line in fh:
        line = line.rstrip()
        if not line:
            continue
        try:
            ts = json.loads(line).get("timestamp_start", "")
        except Exception:
            ts = ""
        if ts not in seen:
            seen[ts] = len(buckets)
            buckets.append((ts, []))
        buckets[seen[ts]][1].append(line + "\n")
for i, (ts, lines) in enumerate(buckets):
    path = os.path.join(out_dir, "bucket_%04d.jsonl" % i)
    with open(path, "w") as fh:
        fh.writelines(lines)
    print(path + "\t" + ts)
PYEOF

bucket_index="${tmpdir}/bucket_index.txt"
if ! python3 -I "$split_py" "$records_file" "$tmpdir" > "$bucket_index"; then
    echo "aggregate-metrics: ERROR: split_buckets.py failed" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

bucket_files=()
bucket_starts=()
while IFS=$'\t' read -r bfile bstart; do
    bucket_files+=("$bfile")
    bucket_starts+=("$bstart")
done < "$bucket_index"

bucket_count=${#bucket_files[@]}

if (( DRY_RUN )); then
    echo "aggregate-metrics: DRY RUN -- would append ${record_count} record(s) across ${bucket_count} bucket(s) to ai-agile/metrics:records.jsonl:" >&2
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

# Commit one bucket at a time so a crash mid-run leaves already-committed
# buckets intact and idempotent on re-run (issue #670). Within each bucket,
# all rows (per-agent breakdown rows + blended total row) land in a single
# append-metrics-record.sh call -- the write is atomic per bucket (issue #533,
# RV-002). Fail closed (STD-ARCH-014): on any push failure the error is
# reported and the remaining buckets are skipped.
#
# set -e is deliberately not relied on here (RV-001): a bare command failure
# under set -e exits with no AI_AGILE_STATUS sentinel, which the orchestrator
# would otherwise have to treat as a crash rather than a reported `blocked`.
appended_total=0
for i in "${!bucket_files[@]}"; do
    bucket_file="${bucket_files[$i]}"
    bucket_start="${bucket_starts[$i]}"
    bucket_record_count=$(grep -c . -- "$bucket_file")

    if ! AI_AGILE_METRICS_BRANCH="ai-agile/metrics" \
         AI_AGILE_METRICS_FILE="records.jsonl" \
         AI_AGILE_METRICS_COMMIT_MESSAGE="metrics: ${PERIOD} aggregate ${bucket_start} (${bucket_record_count} record(s))" \
         AI_AGILE_METRICS_RETRIES="3" \
         bash "$APPEND_SCRIPT" "$bucket_file"; then
        echo "aggregate-metrics: ERROR: append-metrics-record.sh failed for bucket ${bucket_start} -- previously committed buckets remain intact" >&2
        echo "AI_AGILE_STATUS: blocked"
        exit 0
    fi
    appended_total=$(( appended_total + bucket_record_count ))
done

echo "aggregate-metrics: appended ${appended_total} record(s) across ${bucket_count} bucket(s)" >&2
echo "AI_AGILE_STATUS: complete"
