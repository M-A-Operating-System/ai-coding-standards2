#!/usr/bin/env python3
"""Weekly aggregator for ai-agile/metrics records.jsonl (issue #533).

Reads raw per-invocation records from the ai-agile/metrics branch, computes
weekly aggregate records for the previous full Mon-Sun week, and writes them
to stdout as JSONL (one compact JSON object per line, no output when nothing
has changed).

RECORD FORMAT
-------------
Aggregate rows share the same JSONL format as raw per-invocation rows.  Two
fields distinguish them from raw rows:

  period    "week" (or "month" for a future monthly aggregate -- same shape,
            same file, just a different period value)
  agent_id  "metrics-aggregator" for the blended weekly total row, or the
            real agent name (e.g. "03_execute/coder") for a per-agent
            breakdown row.

A reader filters aggregate rows with:
  agent_id == "metrics-aggregator" AND period == "week"
  -- or --
  period == "week"  (to include per-agent breakdown rows)

FIELD-NAMING CONVENTION
-----------------------
Aggregate metric fields follow the pattern:

  {aggregation_fn}_{base_metric}[-{dimension}]

where:
  aggregation_fn  sum, ave, count, ratio, min, max, median
  base_metric     short form of the underlying granular field, e.g. cost_usd,
                  tot_tokens, duration_ms, retry_count
  -dimension      only when the metric requires grouping by something beyond
                  the row's own key fields before rolling up -- e.g. -issue for
                  a metric computed per issue then averaged across issues

UNIT DISCIPLINE
---------------
  cost_usd fields  USD, the ground truth.  Never a token-count proxy.
  _tokens fields   Raw token counts (input/output/cache).  Never implied as
                   cost even when model costs differ per token type.

Usage:
  python3 -I metrics_aggregator.py [--period week] [--now ISO-8601]

--now overrides the current UTC time (for testing and manual backfills).
"""

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

METRICS_BRANCH = "ai-agile/metrics"
METRICS_RECORDS_FILE = "records.jsonl"

# Reserved agent_id written into all blended aggregate rows.
METRICS_AGGREGATOR_ID = "metrics-aggregator"

# Agents counted as value-add (issue-level contribution to ratio_value_add-issue).
# "sizer" is included because it contributes when triggered; if it did not run
# for an issue, it contributes 0 (no records to sum).
_VALUE_ADD_AGENTS = frozenset({
    "issue-classifier", "sizer", "prd-writer", "prd-docs-updater",
})
_CODER_AGENT = "03_execute/coder"

# Issue classifications that count toward each side of ratio_classification_mix.
_FEATURE_RESEARCH_CLASSIFICATIONS = frozenset({"enhancement", "spike"})
_CORRECTIVE_CLASSIFICATIONS = frozenset({"bug", "tech-debt", "security"})


# ---------------------------------------------------------------------------
# Record reading (mirrors read_metrics_records in pipeline_orchestrator.py)
# ---------------------------------------------------------------------------

def read_records() -> list:
    """Read every record from records.jsonl on the metrics branch, oldest first.

    Returns [] when the branch or file does not exist.
    """
    try:
        subprocess.run(
            ["git", "fetch", "origin", METRICS_BRANCH],
            check=True, capture_output=True,
        )
        show = subprocess.run(
            ["git", "show", f"origin/{METRICS_BRANCH}:{METRICS_RECORDS_FILE}"],
            capture_output=True, text=True,
        )
    except Exception:
        return []
    if show.returncode != 0:
        return []
    records = []
    for line in show.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            records.append(entry)
    return records


# ---------------------------------------------------------------------------
# Bucket helpers
# ---------------------------------------------------------------------------

def week_bucket(now: datetime):
    """Return (start, end) of the previous Mon-Sun week relative to now.

    start is Monday 00:00:00 UTC; end is the following Sunday 23:59:59 UTC.
    Both are timezone-aware (UTC).
    """
    days_since_monday = now.weekday()  # Monday=0
    this_monday = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_since_monday)
    last_monday = this_monday - timedelta(weeks=1)
    last_sunday = this_monday - timedelta(seconds=1)
    return last_monday, last_sunday


def _parse_ts(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z") + "+00:00")
    except ValueError:
        return None


def _in_bucket(record: dict, bucket_start: datetime, bucket_end: datetime) -> bool:
    ts = _parse_ts(record.get("timestamp_end") or record.get("timestamp_start"))
    if ts is None:
        return False
    return bucket_start <= ts <= bucket_end


def _is_aggregate(record: dict) -> bool:
    return bool(record.get("period"))


def already_aggregated(records: list, bucket_start: datetime, period: str) -> bool:
    """True when a blended aggregate record for this bucket already exists."""
    bucket_start_str = bucket_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    for rec in records:
        if (rec.get("agent_id") == METRICS_AGGREGATOR_ID
                and rec.get("period") == period
                and rec.get("timestamp_start") == bucket_start_str):
            return True
    return False


# ---------------------------------------------------------------------------
# Safe numeric helpers
# ---------------------------------------------------------------------------

def _float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Base record template
# ---------------------------------------------------------------------------

def _base_record(
    agent_id: str,
    bucket_start: datetime,
    bucket_end: datetime,
    period: str,
) -> dict:
    """Skeleton record satisfying the required METRICS_SCHEMA fields.

    Aggregate records set duration_ms / input_tokens / output_tokens / etc.
    to their zero values because those fields carry per-invocation semantics.
    The actual aggregate figures live in the sum_* / ave_* / ratio_* fields.
    """
    return {
        "timestamp_start": bucket_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timestamp_end":   bucket_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "github_issue_number": None,
        "agent_id":    agent_id,
        "period":      period,
        "cycle_id":    str(uuid.uuid4()),
        "duration_ms": 0,
        "input_tokens":  0,
        "output_tokens": 0,
        "retry_count":  0,
        "retry_errors": [],
        "classification": None,
    }


# ---------------------------------------------------------------------------
# Per-agent breakdown rows
# ---------------------------------------------------------------------------

def compute_per_agent_records(
    bucket_records: list,
    bucket_start: datetime,
    bucket_end: datetime,
    period: str,
) -> list:
    """One aggregate row per distinct real agent_id found in the bucket.

    Carries sum_cost_usd, sum_duration_ms, token sums, and basic error/retry
    counts for that agent over the period.  The per-agent breakdown is
    mandatory alongside any blended metric so a model-mix or agent-mix shift
    cannot be misread as a performance trend.
    """
    by_agent: dict = {}
    for rec in bucket_records:
        aid = rec.get("agent_id", "")
        if not aid or aid == METRICS_AGGREGATOR_ID:
            continue
        by_agent.setdefault(aid, []).append(rec)

    result = []
    for agent_id, recs in sorted(by_agent.items()):
        base = _base_record(agent_id, bucket_start, bucket_end, period)
        base.update({
            "count_invocations": len(recs),
            "count_is_error":    sum(1 for r in recs if r.get("is_error")),
            "sum_cost_usd":      sum(_float(r.get("total_cost_usd")) for r in recs),
            "sum_duration_ms":   sum(_int(r.get("duration_ms")) for r in recs),
            "sum_input_tokens":  sum(_int(r.get("input_tokens")) for r in recs),
            "sum_output_tokens": sum(_int(r.get("output_tokens")) for r in recs),
            "sum_cache_creation_input_tokens": sum(
                _int(r.get("cache_creation_input_tokens")) for r in recs
            ),
            "sum_cache_read_input_tokens": sum(
                _int(r.get("cache_read_input_tokens")) for r in recs
            ),
            "sum_retry_count": sum(_int(r.get("retry_count")) for r in recs),
            "sum_num_turns":   sum(_int(r.get("num_turns")) for r in recs),
        })
        result.append(base)
    return result


# ---------------------------------------------------------------------------
# Blended metric helpers
# ---------------------------------------------------------------------------

def compute_value_add_ratio(bucket_records: list) -> Optional[float]:
    """ratio_value_add-issue: average (value_add / total) cost ratio across issues.

    value_add definition (PRD, issue #533):
      - Non-spike: issue-classifier + sizer (if present) + prd-writer +
        prd-docs-updater + FIRST 03_execute/coder invocation (by timestamp_start).
      - Spike: issue-classifier + prd-writer + prd-docs-updater only -- no
        coder step exists for spike issues.

    Unit: total_cost_usd (USD).  A separate token-count view would be stored as
    a distinct, explicitly named field, never as a replacement for this ratio.
    """
    by_issue: dict = {}
    for rec in bucket_records:
        num = rec.get("github_issue_number")
        if not isinstance(num, int):
            continue
        by_issue.setdefault(num, []).append(rec)

    ratios = []
    for _, recs in by_issue.items():
        total_cost = sum(_float(r.get("total_cost_usd")) for r in recs)
        if total_cost == 0:
            continue

        classification = None
        for r in recs:
            c = r.get("classification")
            if c:
                classification = c
                break

        value_add_base = sum(
            _float(r.get("total_cost_usd"))
            for r in recs
            if r.get("agent_id") in _VALUE_ADD_AGENTS
        )

        if classification == "spike":
            value_add = value_add_base
        else:
            coder_recs = [r for r in recs if r.get("agent_id") == _CODER_AGENT]
            first_coder_cost = 0.0
            if coder_recs:
                first_coder = min(coder_recs, key=lambda r: r.get("timestamp_start") or "")
                first_coder_cost = _float(first_coder.get("total_cost_usd"))
            value_add = value_add_base + first_coder_cost

        ratios.append(value_add / total_cost)

    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def compute_classification_mix(bucket_records: list) -> Optional[float]:
    """ratio_classification_mix: feature&research / (feature&research + corrective).

    Feature & research: enhancement + spike.
    Corrective: bug + tech-debt + security.

    Computed per unique issue; null-classified issues are excluded from the
    denominator (not counted as either side).
    """
    by_issue: dict = {}
    for rec in bucket_records:
        num = rec.get("github_issue_number")
        if not isinstance(num, int):
            continue
        c = rec.get("classification")
        if c and num not in by_issue:
            by_issue[num] = c

    feature_research = sum(
        1 for c in by_issue.values() if c in _FEATURE_RESEARCH_CLASSIFICATIONS
    )
    corrective = sum(
        1 for c in by_issue.values() if c in _CORRECTIVE_CLASSIFICATIONS
    )
    total = feature_research + corrective
    if total == 0:
        return None
    return feature_research / total


# ---------------------------------------------------------------------------
# Blended weekly total row
# ---------------------------------------------------------------------------

def compute_blended_record(
    bucket_records: list,
    bucket_start: datetime,
    bucket_end: datetime,
    period: str,
) -> dict:
    """Blended weekly total row (agent_id: metrics-aggregator).

    All cost metrics in total_cost_usd (USD).  All token metrics in raw token
    counts, named with a _tokens suffix so the two unit families are never
    confused.  See field-naming convention in module docstring.
    """
    base = _base_record(METRICS_AGGREGATOR_ID, bucket_start, bucket_end, period)

    total_cost = sum(_float(r.get("total_cost_usd")) for r in bucket_records)
    total_input_tokens  = sum(_int(r.get("input_tokens")) for r in bucket_records)
    total_output_tokens = sum(_int(r.get("output_tokens")) for r in bucket_records)
    total_cache_creation = sum(
        _int(r.get("cache_creation_input_tokens")) for r in bucket_records
    )
    total_cache_read = sum(
        _int(r.get("cache_read_input_tokens")) for r in bucket_records
    )
    total_duration_ms  = sum(_int(r.get("duration_ms")) for r in bucket_records)
    total_retry_count  = sum(_int(r.get("retry_count")) for r in bucket_records)
    total_num_turns    = sum(_int(r.get("num_turns")) for r in bucket_records)
    count_invocations  = len(bucket_records)
    count_is_error     = sum(1 for r in bucket_records if r.get("is_error"))

    unique_issues = {
        r.get("github_issue_number")
        for r in bucket_records
        if isinstance(r.get("github_issue_number"), int)
    }
    count_issues = len(unique_issues)

    model_costs: dict = {}
    for r in bucket_records:
        m = r.get("model")
        if m:
            model_costs[m] = model_costs.get(m, 0.0) + _float(r.get("total_cost_usd"))

    base.update({
        "count_invocations": count_invocations,
        "count_is_error":    count_is_error,
        "count_issues":      count_issues,
        "sum_cost_usd":      total_cost,
        "sum_duration_ms":   total_duration_ms,
        "sum_input_tokens":  total_input_tokens,
        "sum_output_tokens": total_output_tokens,
        "sum_cache_creation_input_tokens": total_cache_creation,
        "sum_cache_read_input_tokens":     total_cache_read,
        "sum_retry_count": total_retry_count,
        "sum_num_turns":   total_num_turns,
    })

    # Optional blended metrics -- only stored when computable.
    value_add_ratio = compute_value_add_ratio(bucket_records)
    if value_add_ratio is not None:
        base["ratio_value_add-issue"] = round(value_add_ratio, 6)

    classification_mix = compute_classification_mix(bucket_records)
    if classification_mix is not None:
        base["ratio_classification_mix"] = round(classification_mix, 6)

    if count_issues > 0:
        base["ave_cost_usd-issue"] = round(total_cost / count_issues, 6)

    total_cache = total_cache_creation + total_cache_read
    if total_cache > 0:
        base["ratio_cache_efficiency"] = round(total_cache_read / total_cache, 6)

    if count_invocations > 0:
        blocked_failed_rate = count_is_error / count_invocations
        base["ratio_error_rate"] = round(blocked_failed_rate, 6)

    if model_costs:
        base["model_mix_cost_usd"] = model_costs

    return base


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_weekly_aggregates(records: list, now: datetime) -> list:
    """Compute weekly aggregate records for the previous full Mon-Sun week.

    Returns [] when:
      - the bucket is already aggregated (idempotent re-run);
      - no raw records fall within the bucket (nothing to aggregate).

    Aggregate rows produced (all period=="week"):
      1. One per distinct real agent_id in the bucket (per-agent breakdown).
      2. One blended total row (agent_id=="metrics-aggregator").
    """
    bucket_start, bucket_end = week_bucket(now)

    if already_aggregated(records, bucket_start, "week"):
        return []

    bucket_records = [
        r for r in records
        if not _is_aggregate(r)       # skip prior aggregate rows
        and not r.get("event")        # skip schedule.claim/release bookkeeping
        and _in_bucket(r, bucket_start, bucket_end)
    ]

    if not bucket_records:
        return []

    result = []
    result.extend(compute_per_agent_records(bucket_records, bucket_start, bucket_end, "week"))
    result.append(compute_blended_record(bucket_records, bucket_start, bucket_end, "week"))
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute weekly aggregate records and write them to stdout as JSONL."
    )
    parser.add_argument(
        "--period", default="week", choices=["week"],
        help="Aggregation period (default: week)",
    )
    parser.add_argument(
        "--now", default=None,
        help="Override current UTC time in ISO 8601 format (for testing/backfills)",
    )
    args = parser.parse_args()

    if args.now:
        now = datetime.fromisoformat(args.now.rstrip("Z") + "+00:00")
    else:
        now = datetime.now(timezone.utc)

    records = read_records()
    aggregates = compute_weekly_aggregates(records, now)

    for rec in aggregates:
        print(json.dumps(rec, separators=(",", ":")))


if __name__ == "__main__":
    main()
