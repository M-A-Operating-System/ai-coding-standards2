"""Tests for the weekly performance report generator (issue #534).

Covers the acceptance scenarios from docs/features/generate-weekly-performance-report-pdf-from-aggregated-metrics.md:

  Scenario R1 (PDF produced from aggregate rows)   -> TestReadAndProduce
  Scenario R2 (portrait, 4 rows per page)          -> TestHtmlLayout
  Scenario R3 (line pair vs bar_agent shape)        -> TestChartTypes
  Scenario R4 (explicit unit labels)               -> TestUnitLabels
  Scenario R5 (spike carve-out values passed through) -> TestSpikeCarveOut
  Scenario R6 (at least one by-agent chart)        -> TestByAgentChart
  Scenario R7 (short data range renders without failing) -> TestShortRange
  Scenario R8 (scheduled flow in pipeline.json)    -> TestScheduledFlow
  Scenario R9 (metric selection documented in script) -> TestDocumentation
"""

import importlib
import inspect
import json
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from metrics_report import (
    METRICS_AGGREGATOR_ID,
    ROWS_PER_PAGE,
    WINDOW_12MO_WEEKS,
    WINDOW_2MO_WEEKS,
    _BAR_AGENT,
    _LINE,
    _infer_ylabel,
    _build_line,
    _build_bar_agent,
    build_html,
    prepare_report_data,
    read_aggregate_records,
)

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.rstrip("Z") + "+00:00")


def _blended(ts: str, **fields) -> dict:
    """Minimal blended aggregate record."""
    base = {
        "timestamp_start": ts,
        "timestamp_end": ts,
        "github_issue_number": None,
        "agent_id": METRICS_AGGREGATOR_ID,
        "period": "week",
        "cycle_id": "c",
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "retry_count": 0,
        "retry_errors": [],
        "classification": None,
    }
    base.update(fields)
    return base


def _agent_rec(agent_id: str, ts: str, **fields) -> dict:
    """Minimal per-agent breakdown record."""
    base = {
        "timestamp_start": ts,
        "timestamp_end": ts,
        "github_issue_number": None,
        "agent_id": agent_id,
        "period": "week",
        "cycle_id": "c",
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "retry_count": 0,
        "retry_errors": [],
        "classification": None,
    }
    base.update(fields)
    return base


def _week_ts(now: datetime, weeks_ago: int) -> str:
    dt = now - timedelta(weeks=weeks_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# R1: PDF produced from aggregate rows
# ---------------------------------------------------------------------------

class TestReadAndProduce:
    def test_read_aggregate_records_returns_only_week_rows(self, monkeypatch):
        week_rec = _blended("2026-09-01T00:00:00Z", count_issues=3)
        non_week_rec = {**week_rec, "period": "month"}
        raw_rec = {**week_rec}
        del raw_rec["period"]
        lines = "\n".join(json.dumps(r) for r in [week_rec, non_week_rec, raw_rec])
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=lines),
        ]))
        result = read_aggregate_records()
        assert len(result) == 1
        assert result[0]["agent_id"] == METRICS_AGGREGATOR_ID

    def test_read_aggregate_records_returns_empty_when_file_missing(self, monkeypatch):
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=128, stdout=""),
        ]))
        assert read_aggregate_records() == []

    def test_read_aggregate_records_skips_corrupt_lines(self, monkeypatch):
        good = json.dumps(_blended("2026-09-01T00:00:00Z", count_issues=1))
        lines = good + "\n{ not json\n"
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=lines),
        ]))
        result = read_aggregate_records()
        assert len(result) == 1

    def test_main_produces_pdf_when_records_exist(self, monkeypatch, tmp_path):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _blended(_week_ts(now, i), count_issues=5 - i)
            for i in range(4)
        ]
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout="\n".join(json.dumps(r) for r in records)),
        ]))

        fake_html_obj = MagicMock()
        fake_html_cls = MagicMock(return_value=fake_html_obj)

        with patch.dict("sys.modules", {
            "matplotlib": MagicMock(),
            "matplotlib.pyplot": MagicMock(),
            "matplotlib.dates": MagicMock(),
            "weasyprint": MagicMock(HTML=fake_html_cls),
        }):
            import metrics_report as mr
            importlib.reload(mr)

            output = str(tmp_path / "report.pdf")
            fake_chart = "aGVsbG8="  # valid base64
            descs = mr.prepare_report_data(records, now)
            pairs = [(fake_chart, fake_chart)] * len(descs)
            html = mr.build_html(descs, pairs)
            mr.render_pdf(html, output)

        fake_html_cls.assert_called_once()
        fake_html_obj.write_pdf.assert_called_once_with(output)


# ---------------------------------------------------------------------------
# R2: Portrait A4, four chart rows per page
# ---------------------------------------------------------------------------

class TestHtmlLayout:
    def _fake_pair(self):
        return "aGVsbG8=", "aGVsbG8="

    def test_four_rows_fit_on_one_page(self):
        now = _utc("2026-10-06T00:00:00Z")
        descs = [
            {"field": f"f{i}", "title": f"T{i}", "ylabel": "count",
             "chart_type": _LINE, "data_12mo": [], "data_2mo": []}
            for i in range(4)
        ]
        pairs = [self._fake_pair() for _ in descs]
        html = build_html(descs, pairs)
        assert html.count('<div class="page">') == 1

    def test_five_rows_spill_onto_second_page(self):
        descs = [
            {"field": f"f{i}", "title": f"T{i}", "ylabel": "count",
             "chart_type": _LINE, "data_12mo": [], "data_2mo": []}
            for i in range(5)
        ]
        pairs = [self._fake_pair() for _ in descs]
        html = build_html(descs, pairs)
        assert html.count('<div class="page">') == 2

    def test_eight_rows_fill_exactly_two_pages(self):
        descs = [
            {"field": f"f{i}", "title": f"T{i}", "ylabel": "count",
             "chart_type": _LINE, "data_12mo": [], "data_2mo": []}
            for i in range(ROWS_PER_PAGE * 2)
        ]
        pairs = [self._fake_pair() for _ in descs]
        html = build_html(descs, pairs)
        assert html.count('<div class="page">') == 2

    def test_html_declares_portrait_page_size(self):
        html = build_html([], [])
        assert "portrait" in html
        assert "A4" in html

    def test_last_page_has_break_after_auto(self):
        html = build_html([], [])
        assert "break-after: auto" in html

    def test_each_row_has_two_images(self):
        desc = {"field": "f", "title": "T", "ylabel": "count",
                "chart_type": _LINE, "data_12mo": [], "data_2mo": []}
        html = build_html([desc], [self._fake_pair()])
        assert html.count("<img ") == 2

    def test_rows_per_page_constant_is_four(self):
        assert ROWS_PER_PAGE == 4


# ---------------------------------------------------------------------------
# R3: Time-series metrics use line pair; by-agent metrics use bar_agent
# ---------------------------------------------------------------------------

class TestChartTypes:
    def test_time_series_field_gets_line_descriptor(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, 2), count_issues=5)]
        descs = prepare_report_data(records, now)
        throughput = next((d for d in descs if d["field"] == "count_issues"), None)
        assert throughput is not None
        assert throughput["chart_type"] == _LINE

    def test_by_agent_field_gets_bar_agent_descriptor(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _agent_rec("03_execute/coder", _week_ts(now, 2), sum_cost_usd=1.5),
        ]
        descs = prepare_report_data(records, now)
        cost_agent = next((d for d in descs if d["field"] == "sum_cost_usd"), None)
        assert cost_agent is not None
        assert cost_agent["chart_type"] == _BAR_AGENT

    def test_line_descriptor_has_12mo_and_2mo_data(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, 2), count_issues=5)]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        assert "data_12mo" in throughput
        assert "data_2mo" in throughput

    def test_bar_agent_descriptor_has_series_and_agents(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_agent_rec("coder", _week_ts(now, 2), sum_cost_usd=2.0)]
        descs = prepare_report_data(records, now)
        cost_agent = next(d for d in descs if d["field"] == "sum_cost_usd")
        assert "agents" in cost_agent
        assert "series" in cost_agent
        assert "coder" in cost_agent["agents"]

    def test_line_12mo_window_is_left_and_2mo_is_right(self):
        now = _utc("2026-10-06T00:00:00Z")
        old_ts = _week_ts(now, 20)
        recent_ts = _week_ts(now, 2)
        records = [
            _blended(old_ts, count_issues=10),
            _blended(recent_ts, count_issues=5),
        ]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        assert len(throughput["data_12mo"]) == 2
        assert len(throughput["data_2mo"]) == 1


# ---------------------------------------------------------------------------
# R4: Cost and efficiency charts carry explicit unit labels
# ---------------------------------------------------------------------------

class TestUnitLabels:
    def test_usd_field_gets_cost_usd_label(self):
        assert _infer_ylabel("sum_cost_usd") == "cost (USD)"
        assert _infer_ylabel("ave_cost_usd-issue") == "cost (USD)"

    def test_token_field_gets_tokens_label(self):
        assert _infer_ylabel("sum_input_tokens") == "tokens"
        assert _infer_ylabel("sum_output_tokens") == "tokens"
        assert _infer_ylabel("sum_cache_read_input_tokens") == "tokens"

    def test_ratio_field_gets_ratio_label(self):
        assert _infer_ylabel("ratio_value_add-issue") == "ratio (0-1)"
        assert _infer_ylabel("ratio_classification_mix") == "ratio (0-1)"
        assert _infer_ylabel("ratio_cache_efficiency") == "ratio (0-1)"
        assert _infer_ylabel("ratio_error_rate") == "ratio (0-1)"

    def test_duration_ms_field_gets_duration_label(self):
        assert _infer_ylabel("sum_duration_ms") == "duration (ms)"

    def test_known_metrics_carry_explicit_unit_labels(self):
        from metrics_report import _KNOWN_METRICS
        for field, title, ylabel, _ in _KNOWN_METRICS:
            assert ylabel, f"{field} has no ylabel"
            if "usd" in field.lower():
                assert "USD" in ylabel, f"{field}: expected USD in ylabel, got {ylabel!r}"
            if "tokens" in field.lower():
                assert "tokens" in ylabel, f"{field}: expected tokens in ylabel, got {ylabel!r}"

    def test_ylabel_in_descriptor_matches_expected_unit(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, 1), ave_cost_usd_issue=0.5)]
        descs = prepare_report_data(records, now)
        cost_desc = next(
            (d for d in descs if "cost" in d["field"].lower() and "usd" in d["field"].lower()),
            None,
        )
        if cost_desc is not None:
            assert "USD" in cost_desc["ylabel"]


# ---------------------------------------------------------------------------
# R5: Spike carve-out values pass through directly from aggregate records
# ---------------------------------------------------------------------------

class TestSpikeCarveOut:
    def test_value_add_ratio_uses_aggregated_value_without_recomputation(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _blended(_week_ts(now, 1), **{"ratio_value_add-issue": 0.75}),
        ]
        descs = prepare_report_data(records, now)
        va = next((d for d in descs if d["field"] == "ratio_value_add-issue"), None)
        assert va is not None
        # The chart data must use the value exactly as stored in the aggregate row.
        assert va["data_12mo"][0][1] == pytest.approx(0.75)

    def test_classification_mix_uses_aggregated_value_without_recomputation(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _blended(_week_ts(now, 1), ratio_classification_mix=0.6),
        ]
        descs = prepare_report_data(records, now)
        cm = next((d for d in descs if d["field"] == "ratio_classification_mix"), None)
        assert cm is not None
        assert cm["data_12mo"][0][1] == pytest.approx(0.6)

    def test_no_per_issue_recomputation_in_report_module(self):
        source = inspect.getsource(
            importlib.import_module("metrics_report")
        )
        assert "compute_value_add_ratio" not in source
        assert "compute_classification_mix" not in source


# ---------------------------------------------------------------------------
# R6: At least one chart shows a breakdown by agent_id
# ---------------------------------------------------------------------------

class TestByAgentChart:
    def test_at_least_one_bar_agent_descriptor_when_per_agent_data_present(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_agent_rec("coder", _week_ts(now, 1), sum_cost_usd=2.0)]
        descs = prepare_report_data(records, now)
        bar_descs = [d for d in descs if d["chart_type"] == _BAR_AGENT]
        assert len(bar_descs) >= 1

    def test_bar_agent_descriptor_contains_agent_ids(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _agent_rec("03_execute/coder", _week_ts(now, 1), sum_cost_usd=1.0),
            _agent_rec("01_product_docs/prd-writer", _week_ts(now, 1), sum_cost_usd=0.5),
        ]
        descs = prepare_report_data(records, now)
        cost_by_agent = next(d for d in descs if d["chart_type"] == _BAR_AGENT and d["field"] == "sum_cost_usd")
        assert "03_execute/coder" in cost_by_agent["agents"]
        assert "01_product_docs/prd-writer" in cost_by_agent["agents"]

    def test_sum_cost_usd_bar_agent_ylabel_is_cost_usd(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_agent_rec("coder", _week_ts(now, 1), sum_cost_usd=1.0)]
        descs = prepare_report_data(records, now)
        cost_desc = next(d for d in descs if d["field"] == "sum_cost_usd")
        assert "USD" in cost_desc["ylabel"]


# ---------------------------------------------------------------------------
# R7: Short data range renders without failing
# ---------------------------------------------------------------------------

class TestShortRange:
    def test_fewer_than_12mo_weeks_renders_available_range(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, i), count_issues=i + 1) for i in range(3)]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        assert len(throughput["data_12mo"]) == 3
        assert len(throughput["data_12mo"]) > 0

    def test_fewer_than_2mo_weeks_renders_available_range(self):
        now = _utc("2026-10-06T00:00:00Z")
        # Only one record, 10 months ago -- inside 12mo window but outside 2mo.
        records = [_blended(_week_ts(now, 40), count_issues=7)]
        descs = prepare_report_data(records, now)
        throughput = next((d for d in descs if d["field"] == "count_issues"), None)
        assert throughput is not None
        # When no data falls in 2mo window, fallback to full available range.
        assert len(throughput["data_2mo"]) >= 1

    def test_single_record_does_not_raise(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, 1), count_issues=1)]
        descs = prepare_report_data(records, now)
        assert len(descs) >= 1

    def test_empty_records_returns_empty_list(self):
        now = _utc("2026-10-06T00:00:00Z")
        assert prepare_report_data([], now) == []

    def test_build_html_with_zero_rows_produces_valid_html(self):
        html = build_html([], [])
        assert "<html" in html
        assert "portrait" in html

    def test_build_line_with_no_data_returns_none(self):
        now = _utc("2026-10-06T00:00:00Z")
        cutoff_12mo = now - timedelta(weeks=WINDOW_12MO_WEEKS)
        cutoff_2mo = now - timedelta(weeks=WINDOW_2MO_WEEKS)
        result = _build_line("count_issues", "T", "count", [], cutoff_12mo, cutoff_2mo)
        assert result is None

    def test_build_bar_agent_with_no_data_returns_none(self):
        now = _utc("2026-10-06T00:00:00Z")
        cutoff_12mo = now - timedelta(weeks=WINDOW_12MO_WEEKS)
        cutoff_2mo = now - timedelta(weeks=WINDOW_2MO_WEEKS)
        result = _build_bar_agent("sum_cost_usd", "T", "USD", [], cutoff_12mo, cutoff_2mo)
        assert result is None


# ---------------------------------------------------------------------------
# R8: Report is produced as part of a scheduled orchestrator flow
# ---------------------------------------------------------------------------

class TestScheduledFlow:
    def _pipeline(self):
        pipeline_path = REPO_ROOT / "pipeline" / "pipeline.json"
        return json.loads(pipeline_path.read_text())

    def test_metrics_report_flow_exists_in_pipeline(self):
        pipeline = self._pipeline()
        assert "metrics-report" in pipeline["flows"]

    def test_metrics_report_flow_has_schedule_trigger(self):
        pipeline = self._pipeline()
        flow = pipeline["flows"]["metrics-report"]
        assert "schedule" in flow["trigger"]

    def test_metrics_report_schedule_is_after_aggregation(self):
        pipeline = self._pipeline()
        agg_cron = pipeline["flows"]["metrics-aggregation"]["trigger"]["schedule"]
        rep_cron = pipeline["flows"]["metrics-report"]["trigger"]["schedule"]
        # Both are Monday schedules; report hour > aggregation hour.
        agg_hour = int(agg_cron.split()[1])
        rep_hour = int(rep_cron.split()[1])
        agg_dow = agg_cron.split()[4]
        rep_dow = rep_cron.split()[4]
        assert agg_dow == rep_dow, "both flows should run on the same day"
        assert rep_hour > agg_hour, "report must be scheduled after aggregation"

    def test_metrics_report_step_names_the_script(self):
        pipeline = self._pipeline()
        steps = pipeline["flows"]["metrics-report"]["steps"]
        assert len(steps) == 1
        assert steps[0]["script"] == "scripts/generate-metrics-report.sh"

    def test_generate_metrics_report_sh_exists(self):
        script_path = REPO_ROOT / "scripts" / "generate-metrics-report.sh"
        assert script_path.exists(), "generate-metrics-report.sh must exist on disk"


# ---------------------------------------------------------------------------
# R9: Report generator documents metric selection, units, and layout
# ---------------------------------------------------------------------------

class TestDocumentation:
    def test_module_docstring_describes_metric_selection(self):
        import metrics_report
        doc = metrics_report.__doc__
        assert doc is not None
        doc_lower = doc.lower()
        assert "metric" in doc_lower

    def test_module_docstring_describes_unit_discipline(self):
        import metrics_report
        doc = metrics_report.__doc__
        assert "USD" in doc
        assert "token" in doc.lower()

    def test_module_docstring_describes_layout(self):
        import metrics_report
        doc = metrics_report.__doc__
        doc_lower = doc.lower()
        assert "portrait" in doc_lower or "layout" in doc_lower
        assert "12" in doc
        assert "2" in doc

    def test_known_metrics_list_is_documented_in_module(self):
        import metrics_report
        doc = metrics_report.__doc__
        # The priority order is described in the docstring.
        assert "priority" in doc.lower() or "order" in doc.lower()

    def test_each_known_metric_has_nonempty_title_and_ylabel(self):
        from metrics_report import _KNOWN_METRICS
        for field, title, ylabel, chart_type in _KNOWN_METRICS:
            assert title.strip(), f"{field}: empty title"
            assert ylabel.strip(), f"{field}: empty ylabel"
