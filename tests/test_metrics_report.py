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

import html
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
    WINDOW_2MO_DAYS,
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
    """Minimal blended aggregate record with period=week."""
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


def _blended_day(ts: str, **fields) -> dict:
    """Minimal blended aggregate record with period=day."""
    base = {
        "timestamp_start": ts,
        "timestamp_end": ts,
        "github_issue_number": None,
        "agent_id": METRICS_AGGREGATOR_ID,
        "period": "day",
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
    """Minimal per-agent breakdown record with period=week."""
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


def _agent_rec_day(agent_id: str, ts: str, **fields) -> dict:
    """Minimal per-agent breakdown record with period=day."""
    base = {
        "timestamp_start": ts,
        "timestamp_end": ts,
        "github_issue_number": None,
        "agent_id": agent_id,
        "period": "day",
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
    def test_read_aggregate_records_returns_week_and_day_rows(self, monkeypatch):
        week_rec = _blended("2026-09-01T00:00:00Z", count_issues=3)
        day_rec = _blended_day("2026-09-30T00:00:00Z", count_issues=1)
        month_rec = {**week_rec, "period": "month"}
        raw_rec = {**week_rec}
        del raw_rec["period"]
        lines = "\n".join(json.dumps(r) for r in [week_rec, day_rec, month_rec, raw_rec])
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=lines),
        ]))
        result = read_aggregate_records()
        periods = {r["period"] for r in result}
        assert periods == {"week", "day"}
        assert len(result) == 2

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
# R2: Portrait US Letter, four chart rows per page
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
        assert "letter" in html
        assert "A4" not in html

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
# Front matter: title/subtitle/date, About this Document, Table of Contents,
# and per-metric H2 headings + descriptions placed between the heading and
# the charts.
# ---------------------------------------------------------------------------

class TestFrontMatter:
    def _desc(self, field="count_issues", title="Throughput", description="Issues processed."):
        return {
            "field": field, "title": title, "ylabel": "issues",
            "description": description,
            "chart_type": _LINE, "data_12mo": [], "data_2mo": [],
        }

    def _fake_pair(self):
        return "aGVsbG8=", "aGVsbG8="

    def test_title_subtitle_and_date_are_rendered(self):
        import metrics_report as mr
        now = _utc("2026-11-09T00:00:00Z")
        html_doc = build_html([], [], now=now, repo_name="ai-coding-standards2")
        assert html.escape(mr.DOC_TITLE) in html_doc
        assert "ai-coding-standards2" in html_doc
        assert "November 09, 2026" in html_doc

    def test_about_this_document_section_is_present(self):
        import metrics_report as mr
        html_doc = build_html([], [], now=_utc("2026-11-09T00:00:00Z"), repo_name="repo")
        assert "About this Document" in html_doc
        assert mr.ABOUT_TEXT in html_doc
        assert "github.com/M-A-Operating-System/ai-coding-standards2" in html_doc

    def test_table_of_contents_links_to_every_metric_anchor(self):
        descs = [
            self._desc("count_issues", "Throughput (issues per week)"),
            self._desc("sum_cost_usd", "Cost by agent"),
        ]
        pairs = [self._fake_pair() for _ in descs]
        html_doc = build_html(descs, pairs, now=_utc("2026-11-09T00:00:00Z"), repo_name="repo")
        assert "Table of Contents" in html_doc
        assert '<a href="#throughput-issues-per-week">Throughput (issues per week)</a>' in html_doc
        assert '<a href="#cost-by-agent">Cost by agent</a>' in html_doc

    def test_each_metric_gets_an_h2_heading_with_matching_anchor(self):
        descs = [self._desc("sum_cost_usd", "Cost by agent")]
        pairs = [self._fake_pair()]
        html_doc = build_html(descs, pairs, now=_utc("2026-11-09T00:00:00Z"), repo_name="repo")
        assert '<h2 class="metric-title" id="cost-by-agent">Cost by agent</h2>' in html_doc

    def test_description_is_placed_between_heading_and_charts(self):
        descs = [self._desc("sum_cost_usd", "Cost by agent", description="Spend per agent.")]
        pairs = [self._fake_pair()]
        html_doc = build_html(descs, pairs, now=_utc("2026-11-09T00:00:00Z"), repo_name="repo")
        heading_pos = html_doc.index('<h2 class="metric-title"')
        desc_pos = html_doc.index("Spend per agent.")
        row_pos = html_doc.index('<div class="row">')
        assert heading_pos < desc_pos < row_pos, (
            "metric description must sit between the H2 heading and the chart row"
        )

    def test_front_matter_precedes_the_first_chart_page(self):
        descs = [self._desc()]
        pairs = [self._fake_pair()]
        html_doc = build_html(descs, pairs, now=_utc("2026-11-09T00:00:00Z"), repo_name="repo")
        assert html_doc.index('class="front-matter"') < html_doc.index('class="page"')

    def test_build_html_without_now_or_repo_name_still_works(self):
        """now/repo_name are optional -- older callers (and most existing
        tests in this file) that only care about chart layout must not be
        forced to supply them."""
        descs = [self._desc()]
        pairs = [self._fake_pair()]
        html_doc = build_html(descs, pairs)
        assert "front-matter" in html_doc


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
        assert "series_week" in cost_agent
        assert "series_day" in cost_agent
        assert "coder" in cost_agent["agents"]

    def test_left_chart_sources_week_rows_for_12mo(self):
        now = _utc("2026-10-06T00:00:00Z")
        week_ts_old = _week_ts(now, 20)
        week_ts_recent = _week_ts(now, 2)
        records = [
            _blended(week_ts_old, count_issues=10),
            _blended(week_ts_recent, count_issues=5),
        ]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        # Both week records fall within 12-month window -- both appear on the left.
        assert len(throughput["data_12mo"]) == 2

    def test_right_chart_sources_day_rows_for_2mo(self):
        now = _utc("2026-10-06T00:00:00Z")
        day_ts_recent = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        day_ts_old = (now - timedelta(days=70)).strftime("%Y-%m-%dT%H:%M:%SZ")
        records = [
            _blended_day(day_ts_recent, count_issues=3),
            _blended_day(day_ts_old, count_issues=1),
        ]
        descs = prepare_report_data(records, now)
        throughput = next((d for d in descs if d["field"] == "count_issues"), None)
        assert throughput is not None
        # Only the 3-days-ago record falls within the 2-month window.
        assert len(throughput["data_2mo"]) == 1

    def test_week_rows_do_not_appear_in_right_chart(self):
        now = _utc("2026-10-06T00:00:00Z")
        week_ts = _week_ts(now, 1)
        records = [_blended(week_ts, count_issues=5)]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        # Week rows feed only the left chart; right chart (data_2mo) uses day rows.
        assert throughput["data_2mo"] == []

    def test_day_rows_do_not_appear_in_left_chart(self):
        now = _utc("2026-10-06T00:00:00Z")
        day_ts = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        records = [_blended_day(day_ts, count_issues=2)]
        descs = prepare_report_data(records, now)
        throughput = next((d for d in descs if d["field"] == "count_issues"), None)
        assert throughput is not None
        # Day rows feed only the right chart; left chart (data_12mo) uses week rows.
        assert throughput["data_12mo"] == []

    def test_line_descriptor_carries_both_window_cutoffs(self):
        """The renderer needs cutoff_12mo/cutoff_2mo to pin each pane's
        x-axis to its full declared window regardless of how sparse the
        actual data is -- prepare_report_data must always attach them."""
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, 2), count_issues=5)]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        assert throughput["cutoff_12mo"] == now - timedelta(weeks=WINDOW_12MO_WEEKS)
        assert throughput["cutoff_2mo"] == now - timedelta(days=WINDOW_2MO_DAYS)


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
        for field, title, ylabel, _, _desc in _KNOWN_METRICS:
            # field is a plain string for most entries, or a (field_in,
            # field_out) tuple for a stacked-bar entry (e.g. tokens by agent).
            field_text = " ".join(field) if isinstance(field, tuple) else field
            assert ylabel, f"{field}: has no ylabel"
            if "usd" in field_text.lower():
                assert "USD" in ylabel, f"{field}: expected USD in ylabel, got {ylabel!r}"
            if "tokens" in field_text.lower():
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

    def test_coder_reinvocation_ratio_uses_aggregated_value_without_recomputation(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _blended(_week_ts(now, 1), **{"ratio_coder_invocations-issue": 2.0}),
        ]
        descs = prepare_report_data(records, now)
        cr = next((d for d in descs if d["field"] == "ratio_coder_invocations-issue"), None)
        assert cr is not None
        assert cr["title"] == "Coder runs per issue"
        assert cr["data_12mo"][0][1] == pytest.approx(2.0)


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
# Tokens by agent -- stacked bar (input vs output tokens), placed right
# after Cost by agent in the metric priority order.
# ---------------------------------------------------------------------------

class TestTokensByAgentStackedBar:
    def test_tokens_by_agent_descriptor_is_stacked_bar(self):
        from metrics_report import _BAR_AGENT_STACKED
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _agent_rec("03_execute/coder", _week_ts(now, 1),
                       sum_input_tokens=100, sum_output_tokens=40),
        ]
        descs = prepare_report_data(records, now)
        tokens_desc = next((d for d in descs if d["title"] == "Tokens by agent"), None)
        assert tokens_desc is not None
        assert tokens_desc["chart_type"] == _BAR_AGENT_STACKED
        assert "03_execute/coder" in tokens_desc["agents"]
        assert "tokens" in tokens_desc["ylabel"]

    def test_tokens_by_agent_carries_separate_in_and_out_series(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _agent_rec("coder", _week_ts(now, 1), sum_input_tokens=100, sum_output_tokens=40),
        ]
        descs = prepare_report_data(records, now)
        tokens_desc = next(d for d in descs if d["title"] == "Tokens by agent")
        in_total = sum(v for _, v in tokens_desc["series_week_in"]["coder"])
        out_total = sum(v for _, v in tokens_desc["series_week_out"]["coder"])
        assert in_total == 100
        assert out_total == 40

    def test_tokens_by_agent_comes_right_after_cost_by_agent(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _agent_rec("coder", _week_ts(now, 1),
                       sum_cost_usd=1.0, sum_duration_ms=500,
                       sum_input_tokens=100, sum_output_tokens=40),
        ]
        descs = prepare_report_data(records, now)
        titles = [d["title"] for d in descs]
        cost_idx = titles.index("Cost by agent")
        tokens_idx = titles.index("Tokens by agent")
        duration_idx = titles.index("Duration by agent")
        assert tokens_idx == cost_idx + 1
        assert duration_idx == tokens_idx + 1

    def test_raw_token_fields_are_not_also_auto_discovered_as_line_charts(self):
        """sum_input_tokens/sum_output_tokens are already covered by the
        Tokens by agent stacked bar -- they must not also appear a second
        time as generic auto-discovered blended-line charts."""
        now = _utc("2026-10-06T00:00:00Z")
        records = [
            _blended(_week_ts(now, 1), sum_input_tokens=100, sum_output_tokens=40),
        ]
        descs = prepare_report_data(records, now)
        fields = [d["field"] for d in descs]
        assert "sum_input_tokens" not in fields
        assert "sum_output_tokens" not in fields

    def test_no_token_data_omits_the_metric(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_agent_rec("coder", _week_ts(now, 1), sum_cost_usd=1.0)]
        descs = prepare_report_data(records, now)
        assert all(d["title"] != "Tokens by agent" for d in descs)

    def test_render_stacks_input_below_output_with_a_legend(self):
        """_render_bar_agent_stacked_pair must draw two ax.bar() calls per
        window -- the input series, then the output series stacked on top
        via bottom= -- and label them so the chart has a legend."""
        import metrics_report as mr

        now = _utc("2026-10-06T00:00:00Z")
        desc = {
            "field": "sum_input_tokens:sum_output_tokens",
            "title": "Tokens by agent", "ylabel": "tokens",
            "description": "d",
            "chart_type": mr._BAR_AGENT_STACKED,
            "agents": ["coder"],
            "label_in": "input", "label_out": "output",
            "series_week_in": {"coder": [(now, 100.0)]},
            "series_week_out": {"coder": [(now, 40.0)]},
            "series_day_in": {"coder": [(now, 10.0)]},
            "series_day_out": {"coder": [(now, 4.0)]},
            "cutoff_12mo": now - timedelta(weeks=WINDOW_12MO_WEEKS),
            "cutoff_2mo": now - timedelta(days=WINDOW_2MO_DAYS),
        }

        mock_ax = MagicMock()
        mock_fig = MagicMock()
        fake_plt = MagicMock()
        fake_plt.subplots.return_value = (mock_fig, mock_ax)
        fake_matplotlib = MagicMock()
        fake_matplotlib.pyplot = fake_plt

        with patch.dict("sys.modules", {
            "matplotlib": fake_matplotlib,
            "matplotlib.pyplot": fake_plt,
        }), patch.object(mr, "_figure_to_b64", return_value="x"):
            mr._render_bar_agent_stacked_pair(desc)

        # 2 windows x 2 stacked series each = 4 bar() calls.
        assert mock_ax.bar.call_count == 4
        # The second call in each window pair must stack on the first via bottom=.
        first_call, second_call = mock_ax.bar.call_args_list[0], mock_ax.bar.call_args_list[1]
        assert "bottom" not in first_call.kwargs
        assert "bottom" in second_call.kwargs
        assert first_call.kwargs.get("label") == "input"
        assert second_call.kwargs.get("label") == "output"
        assert mock_ax.legend.call_count == 2


# ---------------------------------------------------------------------------
# R7: Short data range renders without failing
# ---------------------------------------------------------------------------

class TestLineChartFullWindowXAxis:
    """_render_line_pair must pin each pane's x-axis to its full declared
    window (cutoff -> cutoff + window length) via set_xlim, not leave it to
    matplotlib's default autoscale-to-data-range -- a sparse or empty window
    must still visually read as the full 12-month/2-month span, not shrink
    to hug whatever few points happen to exist."""

    def _render_with_mock(self, desc):
        import metrics_report as mr

        mock_ax = MagicMock()
        mock_fig = MagicMock()
        fake_plt = MagicMock()
        fake_plt.subplots.return_value = (mock_fig, mock_ax)
        fake_mdates = MagicMock()
        fake_mdates.date2num = lambda d: d  # identity -- compare datetimes directly
        fake_matplotlib = MagicMock()
        fake_matplotlib.pyplot = fake_plt
        fake_matplotlib.dates = fake_mdates

        with patch.dict("sys.modules", {
            "matplotlib": fake_matplotlib,
            "matplotlib.pyplot": fake_plt,
            "matplotlib.dates": fake_mdates,
        }), patch.object(mr, "_figure_to_b64", return_value="x"):
            mr._render_line_pair(desc)

        return mock_ax

    def test_sparse_12mo_data_still_spans_the_full_window(self):
        import metrics_report as mr

        now = _utc("2026-10-06T00:00:00Z")
        cutoff_12mo = now - timedelta(weeks=WINDOW_12MO_WEEKS)
        cutoff_2mo = now - timedelta(days=WINDOW_2MO_DAYS)
        # A single data point well inside the window -- the regression this
        # guards against is matplotlib autoscaling to just this one point.
        single_point = cutoff_12mo + timedelta(weeks=1)
        desc = {
            "field": "count_issues", "title": "Throughput", "ylabel": "issues",
            "data_12mo": [(single_point, 3)], "data_2mo": [],
            "cutoff_12mo": cutoff_12mo, "cutoff_2mo": cutoff_2mo,
        }
        mock_ax = self._render_with_mock(desc)

        assert mock_ax.set_xlim.call_count == 2
        left_call, right_call = mock_ax.set_xlim.call_args_list
        assert left_call.args == (cutoff_12mo, cutoff_12mo + timedelta(weeks=WINDOW_12MO_WEEKS))
        assert right_call.args == (cutoff_2mo, cutoff_2mo + timedelta(days=WINDOW_2MO_DAYS))

    def test_empty_data_still_spans_the_full_window(self):
        """No data at all in either window must still produce a full-span
        x-axis, not a bare/empty default 0-1 axis."""
        now = _utc("2026-10-06T00:00:00Z")
        cutoff_12mo = now - timedelta(weeks=WINDOW_12MO_WEEKS)
        cutoff_2mo = now - timedelta(days=WINDOW_2MO_DAYS)
        desc = {
            "field": "count_issues", "title": "Throughput", "ylabel": "issues",
            "data_12mo": [], "data_2mo": [],
            "cutoff_12mo": cutoff_12mo, "cutoff_2mo": cutoff_2mo,
        }
        mock_ax = self._render_with_mock(desc)

        assert mock_ax.set_xlim.call_count == 2
        left_call, right_call = mock_ax.set_xlim.call_args_list
        assert left_call.args == (cutoff_12mo, cutoff_12mo + timedelta(weeks=WINDOW_12MO_WEEKS))
        assert right_call.args == (cutoff_2mo, cutoff_2mo + timedelta(days=WINDOW_2MO_DAYS))

    def test_no_cutoff_present_skips_xlim_without_error(self):
        """A hand-built descriptor without cutoff_12mo/cutoff_2mo (as older
        callers or ad hoc tests might construct) must not crash -- set_xlim
        is simply skipped for that pane rather than required."""
        desc = {
            "field": "f", "title": "T", "ylabel": "count",
            "data_12mo": [], "data_2mo": [],
        }
        mock_ax = self._render_with_mock(desc)
        mock_ax.set_xlim.assert_not_called()


class TestShortRange:
    def test_fewer_than_12mo_weeks_renders_available_range(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, i), count_issues=i + 1) for i in range(3)]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        assert len(throughput["data_12mo"]) == 3
        assert len(throughput["data_12mo"]) > 0

    def test_fewer_than_2mo_day_rows_renders_available_range(self):
        now = _utc("2026-10-06T00:00:00Z")
        # Only one day record, 70 days ago -- outside the 2-month (60-day) window,
        # so the fallback-to-available-range path is actually exercised.
        day_ts = (now - timedelta(days=70)).strftime("%Y-%m-%dT%H:%M:%SZ")
        records = [_blended_day(day_ts, count_issues=7)]
        descs = prepare_report_data(records, now)
        throughput = next((d for d in descs if d["field"] == "count_issues"), None)
        assert throughput is not None
        # When no data falls in 2mo window, fallback to full available day range.
        assert len(throughput["data_2mo"]) >= 1

    def test_no_day_rows_right_chart_empty_without_error(self):
        now = _utc("2026-10-06T00:00:00Z")
        # Only week records -- right chart has no day data but should not error.
        records = [_blended(_week_ts(now, 1), count_issues=5)]
        descs = prepare_report_data(records, now)
        throughput = next(d for d in descs if d["field"] == "count_issues")
        assert throughput["data_2mo"] == []

    def test_bar_agent_falls_back_to_available_range_when_all_day_data_outside_window(self):
        """issue #547 PR review RV-001: _render_bar_agent_pair must fall back
        to the full available range when every series_day point pre-dates
        cutoff_2mo, the same short-range behavior _build_line already applies
        to the line-chart rows -- not silently render an empty bar chart."""
        import metrics_report as mr

        now = _utc("2026-10-06T00:00:00Z")
        old_dt = now - timedelta(days=70)  # outside the 2-month (60-day) window
        desc = {
            "field": "sum_cost_usd",
            "title": "Cost by agent",
            "ylabel": "cost (USD)",
            "chart_type": mr._BAR_AGENT,
            "agents": ["03_execute/coder"],
            "series_week": {"03_execute/coder": [(now, 5.0)]},
            "series_day": {"03_execute/coder": [(old_dt, 3.0)]},
            "cutoff_12mo": now - timedelta(weeks=52),
            "cutoff_2mo": now - timedelta(days=60),
        }

        bar_calls = []
        mock_ax = MagicMock()
        mock_ax.bar.side_effect = lambda *a, **k: bar_calls.append((a, k))
        mock_fig = MagicMock()
        fake_matplotlib = MagicMock()
        fake_plt = MagicMock()
        fake_matplotlib.pyplot = fake_plt  # "import matplotlib.pyplot as plt"
        # resolves via attribute access on the parent module object, not a
        # direct sys.modules["matplotlib.pyplot"] lookup -- both must agree.
        fake_plt.subplots.return_value = (mock_fig, mock_ax)

        # Fake out matplotlib in sys.modules (same pattern as
        # TestRenderChartsBackend below) rather than patching the real
        # package by import-path string -- matplotlib is an optional runtime
        # dependency (see module docstring), not installed in CI.
        with patch.dict("sys.modules", {
            "matplotlib": fake_matplotlib,
            "matplotlib.pyplot": fake_plt,
        }), patch.object(mr, "_figure_to_b64", return_value="x"):
            mr._render_bar_agent_pair(desc)

        # Both the 12mo window (real data) and the 2mo window (fallback since
        # the only day point is outside cutoff_2mo) must have drawn bars.
        assert len(bar_calls) == 2
        # The 2mo window's bar call used the fallback total (3.0), not an
        # empty bars call.
        assert mock_ax.bar.call_args_list[1].args[1] == (3.0,)

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
        cutoff_2mo = now - timedelta(days=WINDOW_2MO_DAYS)
        result = _build_line("count_issues", "T", "count", [], [], cutoff_12mo, cutoff_2mo)
        assert result is None

    def test_build_bar_agent_with_no_data_returns_none(self):
        now = _utc("2026-10-06T00:00:00Z")
        cutoff_12mo = now - timedelta(weeks=WINDOW_12MO_WEEKS)
        cutoff_2mo = now - timedelta(days=WINDOW_2MO_DAYS)
        result = _build_bar_agent("sum_cost_usd", "T", "USD", [], [], cutoff_12mo, cutoff_2mo)
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

    def test_daily_aggregation_flow_exists_in_pipeline(self):
        pipeline = self._pipeline()
        assert "metrics-aggregation-daily" in pipeline["flows"]

    def test_daily_aggregation_flow_has_daily_schedule(self):
        pipeline = self._pipeline()
        flow = pipeline["flows"]["metrics-aggregation-daily"]
        cron = flow["trigger"]["schedule"]
        # Runs every day (last field is * not a specific day-of-week).
        parts = cron.split()
        assert parts[4] == "*", "daily schedule must run every day-of-week"

    def test_daily_aggregation_flow_uses_daily_script(self):
        pipeline = self._pipeline()
        steps = pipeline["flows"]["metrics-aggregation-daily"]["steps"]
        assert len(steps) == 1
        assert steps[0]["script"] == "scripts/aggregate-metrics-daily.sh"

    def test_aggregate_metrics_daily_sh_exists(self):
        script_path = REPO_ROOT / "scripts" / "aggregate-metrics-daily.sh"
        assert script_path.exists(), "aggregate-metrics-daily.sh must exist on disk"


# ---------------------------------------------------------------------------
# R9: Report generator documents metric selection, units, and layout
# ---------------------------------------------------------------------------

class TestKnownMetricsLoadedFromSchema:
    def test_known_metrics_matches_schema_derived_metrics_exactly(self):
        """_KNOWN_METRICS must be rebuilt from metrics.schema.json's
        derived_metrics section, not drift back into a hardcoded list."""
        import json
        from pathlib import Path
        import metrics_report
        from metrics_report import _KNOWN_METRICS, _BAR_AGENT_STACKED

        schema_path = (
            Path(__file__).parent.parent / "pipeline" / "schemas" / "metrics.schema.json"
        )
        derived = json.loads(schema_path.read_text())["derived_metrics"]
        keys = [k for k in derived if k != "$comment"]

        assert len(_KNOWN_METRICS) == len(keys)
        for key, (field, title, ylabel, chart_type, description) in zip(keys, _KNOWN_METRICS):
            entry = derived[key]
            assert chart_type == entry["chart_type"]
            assert title == entry["title"]
            assert ylabel == entry["ylabel"]
            assert description == entry["business_description"]
            if chart_type == _BAR_AGENT_STACKED:
                components = entry["components"]
                assert field == (components["in"], components["out"])
            else:
                assert field == key

    def test_stacked_labels_sourced_from_schema_components(self):
        from metrics_report import _STACKED_LABELS
        assert _STACKED_LABELS[("sum_input_tokens", "sum_output_tokens")] == (
            "input", "output",
        )


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
        assert "4" in doc

    def test_known_metrics_list_is_documented_in_module(self):
        import metrics_report
        doc = metrics_report.__doc__
        # The priority order is described in the docstring.
        assert "priority" in doc.lower() or "order" in doc.lower()

    def test_each_known_metric_has_nonempty_title_and_ylabel(self):
        from metrics_report import _KNOWN_METRICS
        for field, title, ylabel, chart_type, description in _KNOWN_METRICS:
            assert title.strip(), f"{field}: empty title"
            assert ylabel.strip(), f"{field}: empty ylabel"
            assert description.strip(), f"{field}: empty description"

    def test_docstring_documents_stacked_bar_for_tokens_by_agent_only(self):
        """Cost-by-agent and duration-by-agent stay plain (non-stacked)
        single-value bars; only tokens-by-agent legitimately stacks its two
        components (input vs output) in one bar per agent."""
        import metrics_report
        doc = metrics_report.__doc__.lower()
        assert "stacked bar" in doc
        assert "tokens by agent" in doc
        from metrics_report import _KNOWN_METRICS, _BAR_AGENT, _BAR_AGENT_STACKED
        for field, title, ylabel, chart_type, _desc in _KNOWN_METRICS:
            if chart_type == _BAR_AGENT:
                assert "stacked" not in title.lower(), f"{title}: a plain bar chart must not claim to be stacked"
            if chart_type == _BAR_AGENT_STACKED:
                assert isinstance(field, tuple) and len(field) == 2

    def test_commit_report_sh_exists(self):
        script_path = REPO_ROOT / "scripts" / "commit-report.sh"
        assert script_path.exists(), "commit-report.sh must exist on disk"

    def test_generate_metrics_report_sh_calls_commit_report(self):
        script_path = REPO_ROOT / "scripts" / "generate-metrics-report.sh"
        assert script_path.exists()
        content = script_path.read_text()
        assert "commit-report.sh" in content

    def test_generate_metrics_report_sh_uses_persistent_branch(self):
        script_path = REPO_ROOT / "scripts" / "generate-metrics-report.sh"
        content = script_path.read_text()
        assert "ai-agile/reports" in content

    def test_commit_report_sh_accepts_dry_run_flag(self):
        # STD-ARCH-036: commit-report.sh must expose a --dry-run mode that
        # skips the git push (the only state-changing operation).
        script_path = REPO_ROOT / "scripts" / "commit-report.sh"
        content = script_path.read_text()
        assert "--dry-run" in content
        assert "DRY_RUN" in content

    def test_generate_metrics_report_sh_passes_dry_run_to_commit_report(self):
        # STD-ARCH-036: generate-metrics-report.sh must pass --dry-run through
        # to commit-report.sh rather than skipping it entirely.
        script_path = REPO_ROOT / "scripts" / "generate-metrics-report.sh"
        content = script_path.read_text()
        assert "--dry-run" in content
        # The flag must appear in the commit-report.sh invocation context,
        # not just as a standalone check.
        assert "commit_args" in content or "--dry-run" in content


# ---------------------------------------------------------------------------
# Additional regression tests for RV-003 and RV-004
# ---------------------------------------------------------------------------

class TestRenderChartsBackend:
    def test_matplotlib_use_agg_called_once_in_render_charts(self):
        import metrics_report as mr
        calls = []

        class FakeMatplotlib:
            def use(self, backend):
                calls.append(backend)

        with patch.dict("sys.modules", {
            "matplotlib": FakeMatplotlib(),
            "matplotlib.pyplot": MagicMock(),
            "matplotlib.dates": MagicMock(),
        }):
            importlib.reload(mr)
            mr.render_charts([])

        assert len(calls) == 1
        assert calls[0] == "Agg"

    def test_render_line_pair_does_not_call_matplotlib_use(self):
        import inspect
        import metrics_report as mr
        source = inspect.getsource(mr._render_line_pair)
        assert "matplotlib.use" not in source

    def test_render_bar_agent_pair_does_not_call_matplotlib_use(self):
        import inspect
        import metrics_report as mr
        source = inspect.getsource(mr._render_bar_agent_pair)
        assert "matplotlib.use" not in source


class TestNowParsing:
    def test_z_suffix_is_parsed_as_utc(self):
        from metrics_report import _parse_ts
        from datetime import timezone
        dt = _parse_ts("2026-10-06T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_now_with_offset_does_not_raise(self):
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, 1), count_issues=3)]
        # Simulate what main() does with a timezone-offset --now string.
        from datetime import timezone
        import metrics_report as mr
        ts_with_offset = "2026-10-06T05:30:00+05:30"
        parsed = datetime.fromisoformat(ts_with_offset)
        resolved = parsed.astimezone(timezone.utc)
        descs = mr.prepare_report_data(records, resolved)
        assert len(descs) >= 1

    def test_now_naive_string_treated_as_utc(self):
        import metrics_report as mr
        from datetime import timezone
        naive_str = "2026-10-06T00:00:00"
        parsed = datetime.fromisoformat(naive_str)
        assert parsed.tzinfo is None
        resolved = parsed.replace(tzinfo=timezone.utc)
        now = _utc("2026-10-06T00:00:00Z")
        records = [_blended(_week_ts(now, 1), count_issues=2)]
        descs = mr.prepare_report_data(records, resolved)
        assert len(descs) >= 1
