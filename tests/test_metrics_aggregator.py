"""Tests for the weekly metrics aggregator (issue #533).

Covers the acceptance criteria from the issue:
- Weekly aggregate records appended with correct agent_id, period, and
  timestamp_start/timestamp_end bucket boundaries.
- Value-add ratio computed correctly for regular issues.
- Spike carve-out applied (no coder cost counted for spike-classified issues).
- Classification-mix ratio computed across issue classifications.
- Per-agent breakdown rows present alongside blended weekly total.
- Cost and token fields use unambiguous field names.
- Missing or null field values do not abort aggregation.
- Idempotency: second run returns [] when bucket already aggregated.

Traceability to feature scenarios (docs/features/weekly-aggregation-...md):
  Scenario 1 (weekly aggregate appended)   -> TestWeeklyAggregation
  Scenario 2 (value-add ratio, regular)    -> TestValueAddRatio.test_regular_issue
  Scenario 3 (spike carve-out)             -> TestValueAddRatio.test_spike_carve_out
  Scenario 4 (classification mix)          -> TestClassificationMix
  Scenario 5 (per-agent breakdown)         -> TestPerAgentBreakdown
  Scenario 6 (unambiguous field names)     -> TestFieldNames
  Scenario 7 (missing/null fields)         -> TestMissingNullFields
"""

import json
import sys
import os
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from metrics_aggregator import (
    METRICS_AGGREGATOR_ID,
    _BUCKET_FUNCS,
    already_aggregated,
    compute_blended_record,
    compute_classification_mix,
    compute_per_agent_records,
    compute_period_aggregates,
    compute_value_add_ratio,
    compute_weekly_aggregates,
    week_bucket,
)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.rstrip("Z") + "+00:00")


def _raw_record(
    agent_id: str,
    ts: str,
    github_issue_number=1,
    total_cost_usd: float = 1.0,
    classification: str = "enhancement",
    **kwargs,
) -> dict:
    """Minimal raw (non-aggregate) record."""
    return {
        "timestamp_start": ts,
        "timestamp_end": ts,
        "github_issue_number": github_issue_number,
        "agent_id": agent_id,
        "cycle_id": "c",
        "duration_ms": 100,
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 2,
        "cache_read_input_tokens": 3,
        "retry_count": 0,
        "retry_errors": [],
        "classification": classification,
        "total_cost_usd": total_cost_usd,
        "num_turns": 1,
        "is_error": False,
        **kwargs,
    }


# Monday 2026-09-28 = start of the bucket when aggregator runs on 2026-10-05
_NOW = _utc("2026-10-05T00:00:00Z")
_BUCKET_START = "2026-09-28T00:00:00Z"
_BUCKET_END   = "2026-10-04T23:59:59Z"
# A timestamp inside the bucket
_IN_BUCKET_TS = "2026-10-01T12:00:00Z"
# A timestamp outside the bucket (current week)
_OUT_TS = "2026-10-05T08:00:00Z"


class TestWeekBucket:
    def test_previous_monday_to_sunday(self):
        start, end = week_bucket(_NOW)
        assert start == _utc("2026-09-28T00:00:00Z")
        assert end   == _utc("2026-10-04T23:59:59Z")

    def test_mid_week_run_same_result(self):
        # Running on Wednesday still targets the previous full week.
        start, end = week_bucket(_utc("2026-10-07T14:30:00Z"))
        assert start == _utc("2026-09-28T00:00:00Z")
        assert end   == _utc("2026-10-04T23:59:59Z")

    def test_first_record_of_week_included(self):
        start, end = week_bucket(_NOW)
        ts = _utc(_BUCKET_START)
        assert start <= ts <= end

    def test_last_record_of_week_included(self):
        start, end = week_bucket(_NOW)
        ts = _utc(_BUCKET_END)
        assert start <= ts <= end

    def test_record_at_new_week_start_excluded(self):
        start, end = week_bucket(_NOW)
        ts = _utc("2026-10-05T00:00:00Z")
        assert not (start <= ts <= end)


class TestAlreadyAggregated:
    def test_empty_records(self):
        assert already_aggregated([], _utc(_BUCKET_START), "week") is False

    def test_detects_existing_blended_record(self):
        existing = {
            "agent_id": METRICS_AGGREGATOR_ID,
            "period": "week",
            "timestamp_start": _BUCKET_START,
            "timestamp_end": _BUCKET_END,
        }
        assert already_aggregated([existing], _utc(_BUCKET_START), "week") is True

    def test_ignores_raw_records(self):
        raw = _raw_record("issue-classifier", _IN_BUCKET_TS)
        assert already_aggregated([raw], _utc(_BUCKET_START), "week") is False

    def test_different_period_not_matched(self):
        existing = {
            "agent_id": METRICS_AGGREGATOR_ID,
            "period": "month",
            "timestamp_start": _BUCKET_START,
        }
        assert already_aggregated([existing], _utc(_BUCKET_START), "week") is False


class TestWeeklyAggregation:
    """Scenario 1: weekly aggregate records appended with correct shape."""

    def test_returns_empty_when_no_bucket_records(self):
        records = [_raw_record("issue-classifier", _OUT_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        assert result == []

    def test_returns_empty_when_already_aggregated(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        # First run
        result1 = compute_weekly_aggregates(records, _NOW)
        assert result1
        # Second run sees the blended record from result1
        all_records = records + result1
        result2 = compute_weekly_aggregates(all_records, _NOW)
        assert result2 == []

    def test_blended_row_fields(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        blended = next(r for r in result if r["agent_id"] == METRICS_AGGREGATOR_ID)
        assert blended["period"] == "week"
        assert blended["timestamp_start"] == _BUCKET_START
        assert blended["timestamp_end"] == _BUCKET_END

    def test_per_agent_row_fields(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        agent_rows = [r for r in result if r["agent_id"] != METRICS_AGGREGATOR_ID]
        assert len(agent_rows) == 1
        row = agent_rows[0]
        assert row["agent_id"] == "issue-classifier"
        assert row["period"] == "week"
        assert row["timestamp_start"] == _BUCKET_START
        assert row["timestamp_end"] == _BUCKET_END

    def test_excludes_records_outside_bucket(self):
        in_rec  = _raw_record("issue-classifier", _IN_BUCKET_TS)
        out_rec = _raw_record("prd-writer", _OUT_TS)
        result = compute_weekly_aggregates([in_rec, out_rec], _NOW)
        agent_ids = {r["agent_id"] for r in result if r["agent_id"] != METRICS_AGGREGATOR_ID}
        assert "prd-writer" not in agent_ids

    def test_excludes_schedule_bookkeeping_records(self):
        claim = {
            "timestamp_start": _IN_BUCKET_TS,
            "timestamp_end": _IN_BUCKET_TS,
            "agent_id": "schedule/metrics-aggregation",
            "event": "schedule.claim",
            "flow": "metrics-aggregation",
            "github_issue_number": None,
            "cycle_id": "c",
            "duration_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "retry_count": 0,
            "retry_errors": [],
            "classification": None,
        }
        result = compute_weekly_aggregates([claim], _NOW)
        assert result == []


class TestValueAddRatio:
    """Scenarios 2 and 3: value-add ratio and spike carve-out."""

    def test_regular_issue(self):
        # issue-classifier=1, prd-writer=1, prd-docs-updater=1, coder=2 => value_add=5
        # total = 6 (extra overhead=1)
        records = [
            _raw_record("issue-classifier",  _IN_BUCKET_TS, total_cost_usd=1.0),
            _raw_record("prd-writer",         _IN_BUCKET_TS, total_cost_usd=1.0),
            _raw_record("prd-docs-updater",   _IN_BUCKET_TS, total_cost_usd=1.0),
            _raw_record("03_execute/coder",   _IN_BUCKET_TS, total_cost_usd=2.0,
                        timestamp_start="2026-10-01T10:00:00Z",
                        timestamp_end="2026-10-01T10:00:00Z"),
            _raw_record("03_execute/coder",   "2026-10-01T11:00:00Z",
                        total_cost_usd=3.0,  # second coder run -- NOT value-add
                        timestamp_start="2026-10-01T11:00:00Z",
                        timestamp_end="2026-10-01T11:00:00Z"),
            _raw_record("03_execute/pr-reviewer", _IN_BUCKET_TS, total_cost_usd=1.0),
        ]
        ratio = compute_value_add_ratio(records)
        # value_add = 1+1+1+2 = 5; total = 1+1+1+2+3+1 = 9
        assert ratio is not None
        assert abs(ratio - 5.0 / 9.0) < 1e-9

    def test_spike_carve_out(self):
        # For spike: no coder step counted
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=1.0,
                        classification="spike"),
            _raw_record("prd-writer",        _IN_BUCKET_TS, total_cost_usd=1.0,
                        classification="spike"),
            _raw_record("prd-docs-updater",  _IN_BUCKET_TS, total_cost_usd=1.0,
                        classification="spike"),
            _raw_record("03_execute/pr-reviewer", _IN_BUCKET_TS, total_cost_usd=1.0,
                        classification="spike"),
        ]
        ratio = compute_value_add_ratio(records)
        # value_add = 3 (no coder); total = 4
        assert ratio is not None
        assert abs(ratio - 0.75) < 1e-9

    def test_only_first_coder_counted(self):
        ts1 = "2026-10-01T08:00:00Z"
        ts2 = "2026-10-01T12:00:00Z"
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=1.0),
            _raw_record("03_execute/coder", ts1, total_cost_usd=2.0,
                        timestamp_start=ts1, timestamp_end=ts1),
            _raw_record("03_execute/coder", ts2, total_cost_usd=5.0,
                        timestamp_start=ts2, timestamp_end=ts2),
        ]
        ratio = compute_value_add_ratio(records)
        # value_add = 1 + 2 = 3; total = 1 + 2 + 5 = 8
        assert ratio is not None
        assert abs(ratio - 3.0 / 8.0) < 1e-9

    def test_returns_none_when_no_issues(self):
        records = [
            {
                "timestamp_start": _IN_BUCKET_TS,
                "timestamp_end": _IN_BUCKET_TS,
                "agent_id": "issue-classifier",
                "github_issue_number": None,  # no issue
                "total_cost_usd": 1.0,
                "cycle_id": "c",
                "duration_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "retry_count": 0,
                "retry_errors": [],
                "classification": None,
            }
        ]
        assert compute_value_add_ratio(records) is None

    def test_zero_cost_issue_skipped(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=0.0)]
        assert compute_value_add_ratio(records) is None

    def test_multiple_issues_averaged(self):
        # Issue 1: value_add=2, total=4 -> ratio=0.5
        # Issue 2: value_add=3, total=3 -> ratio=1.0
        # Average = 0.75
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS, github_issue_number=1,
                        total_cost_usd=2.0),
            _raw_record("03_execute/pr-reviewer", _IN_BUCKET_TS, github_issue_number=1,
                        total_cost_usd=2.0),
            _raw_record("issue-classifier", _IN_BUCKET_TS, github_issue_number=2,
                        total_cost_usd=3.0),
        ]
        ratio = compute_value_add_ratio(records)
        assert ratio is not None
        assert abs(ratio - 0.75) < 1e-9


class TestClassificationMix:
    """Scenario 4: classification-mix ratio."""

    def test_all_feature_research(self):
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=1, classification="enhancement"),
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=2, classification="spike"),
        ]
        ratio = compute_classification_mix(records)
        assert ratio == 1.0

    def test_mixed_portfolio(self):
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=1, classification="enhancement"),
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=2, classification="spike"),
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=3, classification="bug"),
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=4, classification="tech-debt"),
        ]
        # feature_research=2, corrective=2, total=4 -> 0.5
        ratio = compute_classification_mix(records)
        assert ratio is not None
        assert abs(ratio - 0.5) < 1e-9

    def test_null_classification_excluded(self):
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=1, classification="enhancement"),
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=2, classification=None),  # excluded
        ]
        ratio = compute_classification_mix(records)
        # Only issue 1 counts: feature_research=1, corrective=0, total=1 -> 1.0
        assert ratio == 1.0

    def test_returns_none_when_no_classified_issues(self):
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS, classification=None)
        ]
        assert compute_classification_mix(records) is None

    def test_each_issue_counted_once(self):
        # Same issue seen from two records -- should count once.
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS,
                        github_issue_number=1, classification="bug"),
            _raw_record("prd-writer", _IN_BUCKET_TS,
                        github_issue_number=1, classification="bug"),
        ]
        ratio = compute_classification_mix(records)
        # 0 feature_research, 1 corrective -> 0.0
        assert ratio is not None
        assert ratio == 0.0


class TestPerAgentBreakdown:
    """Scenario 5: per-agent rows alongside blended total."""

    def test_one_row_per_agent(self):
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=1.0),
            _raw_record("prd-writer",        _IN_BUCKET_TS, total_cost_usd=2.0),
        ]
        result = compute_weekly_aggregates(records, _NOW)
        agent_rows = [r for r in result if r["agent_id"] != METRICS_AGGREGATOR_ID]
        agent_ids = {r["agent_id"] for r in agent_rows}
        assert agent_ids == {"issue-classifier", "prd-writer"}

    def test_blended_row_present(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        blended_rows = [r for r in result if r["agent_id"] == METRICS_AGGREGATOR_ID]
        assert len(blended_rows) == 1

    def test_per_agent_cost_sum(self):
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=1.5),
            _raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=0.5),
        ]
        start, end = week_bucket(_NOW)
        rows = compute_per_agent_records(records, start, end, "week")
        assert len(rows) == 1
        assert abs(rows[0]["sum_cost_usd"] - 2.0) < 1e-9
        assert rows[0]["count_invocations"] == 2

    def test_per_agent_token_sums(self):
        r = _raw_record(
            "prd-writer", _IN_BUCKET_TS,
            input_tokens=100, output_tokens=50,
            cache_creation_input_tokens=10, cache_read_input_tokens=20,
        )
        start, end = week_bucket(_NOW)
        rows = compute_per_agent_records([r], start, end, "week")
        assert rows[0]["sum_input_tokens"]  == 100
        assert rows[0]["sum_output_tokens"] == 50
        assert rows[0]["sum_cache_creation_input_tokens"] == 10
        assert rows[0]["sum_cache_read_input_tokens"]     == 20

    def test_blended_cost_sum_across_agents(self):
        records = [
            _raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=1.0),
            _raw_record("prd-writer",        _IN_BUCKET_TS, total_cost_usd=2.0),
        ]
        start, end = week_bucket(_NOW)
        blended = compute_blended_record(records, start, end, "week")
        assert abs(blended["sum_cost_usd"] - 3.0) < 1e-9


class TestFieldNames:
    """Scenario 6: unambiguous field names for cost vs token metrics."""

    def test_cost_fields_contain_cost_usd(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=1.0)]
        result = compute_weekly_aggregates(records, _NOW)
        for row in result:
            for key in row:
                if "cost" in key.lower():
                    assert "cost_usd" in key or key == "model_mix_cost_usd", (
                        f"Cost field {key!r} does not contain 'cost_usd'"
                    )

    def test_token_fields_end_with_tokens(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        for row in result:
            for key in row:
                if "token" in key.lower():
                    assert key.endswith("_tokens"), (
                        f"Token field {key!r} does not end with '_tokens'"
                    )

    def test_no_field_implies_tokens_are_cost(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        for row in result:
            for key in row:
                # A field with both "token" and "cost" would imply they are the same unit.
                if "token" in key.lower() and "cost" in key.lower():
                    pytest.fail(
                        f"Field {key!r} conflates token count with cost unit"
                    )


class TestMissingNullFields:
    """Scenario 7: missing or null fields do not abort aggregation."""

    def test_null_classification_no_error(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS, classification=None)]
        result = compute_weekly_aggregates(records, _NOW)
        assert result  # did not raise

    def test_missing_total_cost_usd(self):
        rec = _raw_record("issue-classifier", _IN_BUCKET_TS)
        del rec["total_cost_usd"]
        result = compute_weekly_aggregates([rec], _NOW)
        assert result
        blended = next(r for r in result if r["agent_id"] == METRICS_AGGREGATOR_ID)
        assert blended["sum_cost_usd"] == 0.0

    def test_missing_duration_ms(self):
        rec = _raw_record("issue-classifier", _IN_BUCKET_TS)
        del rec["duration_ms"]
        result = compute_weekly_aggregates([rec], _NOW)
        assert result

    def test_null_retry_count(self):
        rec = _raw_record("issue-classifier", _IN_BUCKET_TS)
        rec["retry_count"] = None
        result = compute_weekly_aggregates([rec], _NOW)
        assert result

    def test_null_num_turns(self):
        rec = _raw_record("issue-classifier", _IN_BUCKET_TS)
        rec["num_turns"] = None
        result = compute_weekly_aggregates([rec], _NOW)
        assert result

    def test_multiple_records_some_missing_fields(self):
        r1 = _raw_record("issue-classifier", _IN_BUCKET_TS, total_cost_usd=1.0)
        r2 = _raw_record("prd-writer", _IN_BUCKET_TS)
        del r2["total_cost_usd"]  # missing
        result = compute_weekly_aggregates([r1, r2], _NOW)
        assert result
        blended = next(r for r in result if r["agent_id"] == METRICS_AGGREGATOR_ID)
        # r1 contributes 1.0; r2 contributes 0.0 (missing handled as 0)
        assert abs(blended["sum_cost_usd"] - 1.0) < 1e-9


class TestIdempotency:
    """P-11 idempotency: a re-run does not double-apply the aggregation."""

    def test_second_run_returns_empty(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        first_pass = compute_weekly_aggregates(records, _NOW)
        assert first_pass
        second_pass = compute_weekly_aggregates(records + first_pass, _NOW)
        assert second_pass == []

    def test_required_schema_fields_present_in_blended(self):
        """Blended row satisfies METRICS_SCHEMA required fields."""
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        blended = next(r for r in result if r["agent_id"] == METRICS_AGGREGATOR_ID)
        required = [
            "timestamp_start", "timestamp_end", "github_issue_number",
            "agent_id", "cycle_id", "duration_ms",
            "input_tokens", "output_tokens", "retry_count", "retry_errors",
            "classification",
        ]
        for field in required:
            assert field in blended, f"Required field {field!r} missing from blended row"

    def test_required_schema_fields_present_in_per_agent(self):
        """Per-agent rows satisfy METRICS_SCHEMA required fields."""
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        result = compute_weekly_aggregates(records, _NOW)
        per_agent = next(r for r in result if r["agent_id"] != METRICS_AGGREGATOR_ID)
        required = [
            "timestamp_start", "timestamp_end", "github_issue_number",
            "agent_id", "cycle_id", "duration_ms",
            "input_tokens", "output_tokens", "retry_count", "retry_errors",
            "classification",
        ]
        for field in required:
            assert field in per_agent, f"Required field {field!r} missing from per-agent row"


class TestCacheEfficiency:
    def test_ratio_computed_when_cache_present(self):
        rec = _raw_record(
            "issue-classifier", _IN_BUCKET_TS,
            cache_creation_input_tokens=100, cache_read_input_tokens=300,
        )
        start, end = week_bucket(_NOW)
        blended = compute_blended_record([rec], start, end, "week")
        # ratio = 300 / (100 + 300) = 0.75
        assert "ratio_cache_efficiency" in blended
        assert abs(blended["ratio_cache_efficiency"] - 0.75) < 1e-6

    def test_ratio_absent_when_no_cache(self):
        rec = _raw_record(
            "issue-classifier", _IN_BUCKET_TS,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        start, end = week_bucket(_NOW)
        blended = compute_blended_record([rec], start, end, "week")
        assert "ratio_cache_efficiency" not in blended


class TestBucketGenericPeriod:
    """The period field is a passthrough -- month aggregates would use the same functions."""

    def test_period_field_stored_in_per_agent_row(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        start, end = week_bucket(_NOW)
        rows = compute_per_agent_records(records, start, end, "week")
        assert rows[0]["period"] == "week"

    def test_period_field_stored_in_blended_row(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        start, end = week_bucket(_NOW)
        blended = compute_blended_record(records, start, end, "week")
        assert blended["period"] == "week"


class TestComputePeriodAggregates:
    """compute_period_aggregates dispatches the bucket function by period
    (issue #533 PR review, RV-003) -- adding a later "month" period is adding
    a bucket function and one _BUCKET_FUNCS entry, not restructuring this."""

    def test_week_is_the_only_registered_period_today(self):
        assert set(_BUCKET_FUNCS) == {"week"}

    def test_week_bucket_is_the_registered_function(self):
        assert _BUCKET_FUNCS["week"] is week_bucket

    def test_unknown_period_raises_rather_than_silently_resolving(self):
        with pytest.raises(KeyError):
            compute_period_aggregates([], _NOW, period="month")

    @staticmethod
    def _without_cycle_id(rows):
        # cycle_id is a fresh uuid4 per call (see _base_record) -- excluded
        # so two independent computations can be compared structurally.
        return [{k: v for k, v in row.items() if k != "cycle_id"} for row in rows]

    def test_default_period_matches_compute_weekly_aggregates(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        assert self._without_cycle_id(
            compute_period_aggregates(records, _NOW)
        ) == self._without_cycle_id(compute_weekly_aggregates(records, _NOW))

    def test_explicit_week_period_matches_compute_weekly_aggregates(self):
        records = [_raw_record("issue-classifier", _IN_BUCKET_TS)]
        assert self._without_cycle_id(
            compute_period_aggregates(records, _NOW, period="week")
        ) == self._without_cycle_id(compute_weekly_aggregates(records, _NOW))
