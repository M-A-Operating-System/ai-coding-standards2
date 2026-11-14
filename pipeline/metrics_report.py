#!/usr/bin/env python3
"""Weekly performance report generator for ai-agile/metrics (issue #534).

Reads weekly-aggregate (period=week) and daily-aggregate (period=day) rows
from records.jsonl on the ai-agile/metrics branch, generates per-metric
charts with matplotlib, assembles them into a print-styled HTML document,
and renders to PDF via WeasyPrint.

REPORT LAYOUT
-------------
Portrait US Letter (8.5in x 11in), four chart rows per page (CSS
break-after: page). Each metric appears as one row containing two charts
side by side:
  Left:  last 12 months of data, sourced from period=week aggregate rows.
  Right: last 2 months of data, sourced from period=day aggregate rows.

By-agent breakdown metrics (cost, duration by agent_id) use bar charts
per window instead of line charts, showing where spending goes and
making agent-mix shifts visible.

METRIC PRIORITY ORDER (v1)
--------------------------
1. Cost by agent_id (bar chart) -- where spending goes; decouples
   agent-mix shifts from performance trends in all other charts.
2. Tokens by agent_id (stacked bar chart; input vs output tokens, one color
   per direction) -- total token spend per agent in the period.
3. Duration by agent_id (bar chart).
4. Throughput: issues per week (count_issues from blended rows).
5. Cost per completed issue (ave_cost_usd-issue).
6. Value-add ratio (ratio_value_add-issue) -- spike carve-out applied by
   metrics-aggregator; values here reflect that definition directly and
   are not recomputed.
7. Classification mix (ratio_classification_mix) -- spike carve-out applied
   by metrics-aggregator; values here reflect that definition directly and
   are not recomputed.
8. Cache efficiency (ratio_cache_efficiency).
9. Blocked/failed rate per invocation (ratio_error_rate).
10. Coder runs per issue (ratio_coder_invocations-issue) -- reconstructed
    from invocation counts; review-cycle:N is a GitHub label only, never a
    metrics-record field.
11. Total agent invocations, invocations ending in error, retries, agent
    turns, cache tokens written, cache tokens read -- field definitions
    mirror pipeline_orchestrator.py's METRICS_SCHEMA (the authoritative
    field reference published to ai-agile/metrics as schema.json), itself
    sourced from the Anthropic API usage object and the Claude Code CLI's
    own init/result events where applicable.
12. Any additional scalar aggregate fields discovered dynamically from the
    records are appended after the above, in discovery order.

UNIT DISCIPLINE
---------------
Fields with "usd" in the name are labeled "cost (USD)" on the axis.
Fields with "tokens" in the name are labeled "tokens" on the axis.
Fields prefixed "ratio_" are labeled "ratio (0-1)".
Fields with "_ms" in the name are labeled "duration (ms)".
count_* and sum_* fields not matching the above are labeled "count".

Usage:
  python3 -I metrics_report.py [--output path/to/report.pdf] [--now ISO-8601]

--now overrides the current UTC time (for testing and manual backfills;
  determines the 12-month and 2-month lookback cutoffs).

Runtime requirements (not in requirements.txt -- install separately):
  matplotlib >= 3.7
  weasyprint >= 61
"""

import argparse
import base64
import html
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

METRICS_SCHEMA_PATH = Path(__file__).parent / "schemas" / "metrics.schema.json"

METRICS_BRANCH = "ai-agile/metrics"
METRICS_RECORDS_FILE = "records.jsonl"
METRICS_AGGREGATOR_ID = "metrics-aggregator"

DOC_TITLE = "M&A Operating System AI-Agile Performance Report"
ABOUT_TEXT = (
    "This document contains aggregated summary data for various ai-agile "
    "metrics. For more information on this process go to "
    "https://github.com/M-A-Operating-System/ai-coding-standards2."
)

ROWS_PER_PAGE = 4
WINDOW_12MO_WEEKS = 52
WINDOW_2MO_DAYS = 60

_LINE = "line"
_BAR_AGENT = "bar_agent"
_BAR_AGENT_STACKED = "bar_agent_stacked"


# Priority-ordered metric definitions: (field_name, title, ylabel, chart_type,
# description). field_name is a plain string for _LINE/_BAR_AGENT entries, or
# a (field_in, field_out) tuple for a _BAR_AGENT_STACKED entry (two series
# stacked in one bar, one color per component). The description is rendered
# as a short paragraph between each metric's H2 heading and its charts. Any
# additional scalar aggregate fields found in the blended records but not
# listed here are appended after in discovery order (with a generic
# description), so a new field added by a future metrics-aggregator update
# is rendered automatically.
#
# Loaded from pipeline/schemas/metrics.schema.json's `derived_metrics`
# section rather than hardcoded here, so the schema file is the single
# source of truth for both this report's chart catalogue and the
# orchestrator's published schema.json -- see that section's own $comment.
def _load_known_metrics() -> tuple:
    """Build (_KNOWN_METRICS, stacked_labels) from metrics.schema.json's
    `derived_metrics` section, preserving that section's key order as the
    report's priority order. stacked_labels maps a (field_in, field_out)
    tuple to the (label_in, label_out) strings a _BAR_AGENT_STACKED entry's
    components declare, for use by prepare_report_data()."""
    schema = json.loads(METRICS_SCHEMA_PATH.read_text())
    derived = schema["derived_metrics"]
    known_metrics = []
    stacked_labels = {}
    for key, entry in derived.items():
        if key == "$comment":
            continue
        chart_type = entry["chart_type"]
        if chart_type == _BAR_AGENT_STACKED:
            components = entry["components"]
            field = (components["in"], components["out"])
            stacked_labels[field] = (components["label_in"], components["label_out"])
        else:
            field = key
        known_metrics.append((
            field, entry["title"], entry["ylabel"], chart_type,
            entry["business_description"],
        ))
    return known_metrics, stacked_labels


_KNOWN_METRICS, _STACKED_LABELS = _load_known_metrics()


def _flatten_field(field) -> set:
    """A _BAR_AGENT_STACKED entry's field is a (field_in, field_out) tuple;
    every other entry's field is a plain string. Flatten both shapes to the
    set of raw record keys they consume, so the dynamic-discovery loop below
    can exclude them -- otherwise sum_input_tokens/sum_output_tokens would
    also show up a second time as generic auto-discovered line charts."""
    return set(field) if isinstance(field, tuple) else {field}


_KNOWN_FIELD_NAMES: set = set()
for _m in _KNOWN_METRICS:
    _KNOWN_FIELD_NAMES |= _flatten_field(_m[0])
del _m


def _generic_description(field: str) -> str:
    """Fallback description for a scalar aggregate field discovered at
    runtime that is not yet listed in _KNOWN_METRICS with its own text."""
    return (
        f"Additional aggregate metric discovered from the metrics records "
        f"(field '{field}'); no further description has been written for "
        f"it yet."
    )


def _slugify(text: str) -> str:
    """A stable, URL-safe anchor id for a chart's H2 heading."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def _resolve_repo_name() -> str:
    """Best-effort repo name for the report's subtitle.

    Tries $GITHUB_REPOSITORY (owner/repo, set by the orchestrator workflow)
    first, then falls back to parsing the local git remote 'origin' URL.
    Never raises -- a report with a generic subtitle is far better than no
    report at all over a cosmetic field.
    """
    env_repo = os.environ.get("GITHUB_REPOSITORY")
    if env_repo:
        return env_repo.rstrip("/").rsplit("/", 1)[-1]
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        )
        name = result.stdout.strip().rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name or "unknown repository"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown repository"


# Fields present in every aggregate record that are not plottable metrics.
_NON_METRIC_FIELDS = frozenset({
    "timestamp_start", "timestamp_end", "github_issue_number", "agent_id",
    "period", "cycle_id", "duration_ms", "input_tokens", "output_tokens",
    "retry_count", "retry_errors", "classification", "model_mix_cost_usd",
    "event", "flow",
})


def _infer_ylabel(field_name: str) -> str:
    """Derive an axis label from a metric field name per the naming convention."""
    n = field_name.lower()
    if "usd" in n:
        return "cost (USD)"
    if "tokens" in n:
        return "tokens"
    if n.startswith("ratio_"):
        return "ratio (0-1)"
    if "_ms" in n:
        return "duration (ms)"
    return "count"


# ---------------------------------------------------------------------------
# Record reading (mirrors metrics_aggregator.py -- deliberately not imported
# from that module; see that module's read_records() docstring for rationale).
# ---------------------------------------------------------------------------

def read_aggregate_records() -> list:
    """Return aggregate rows (period=week and period=day) from records.jsonl.

    Fetches the branch, reads all lines, and filters for rows with a known
    period value ("week" or "day").  Returns [] when the branch exists but
    the file does not, or when no aggregate rows are present.  A git fetch
    failure propagates as CalledProcessError (fail-closed, STD-ARCH-014).
    """
    subprocess.run(
        ["git", "fetch", "origin", METRICS_BRANCH],
        check=True, capture_output=True,
    )
    show = subprocess.run(
        ["git", "show", f"origin/{METRICS_BRANCH}:{METRICS_RECORDS_FILE}"],
        capture_output=True, text=True,
    )
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
        if isinstance(entry, dict) and entry.get("period") in ("week", "day"):
            records.append(entry)
    return records


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def _parse_ts(value: object) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, with or without a trailing "Z".

    A result with no timezone (no "Z", no explicit offset) is assumed UTC --
    the only format metrics_aggregator.py writes -- so it can still be
    compared against the UTC-aware 12mo/2mo cutoffs below without raising
    TypeError on a naive/aware comparison.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        if value.endswith("Z"):
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cutoff_weeks(now: datetime, weeks: int) -> datetime:
    return now - timedelta(weeks=weeks)


def _cutoff_days(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def prepare_report_data(records: list, now: datetime) -> list:
    """Build a list of chart descriptor dicts from aggregate records.

    Each descriptor has these keys:
      field      -- metric field name
      title      -- display title for the chart row
      ylabel     -- y-axis label (encodes the unit)
      chart_type -- _LINE or _BAR_AGENT
      data_12mo  -- (line only) list of (dt, float) pairs; period=week rows, last 12 months
      data_2mo   -- (line only) list of (dt, float) pairs; period=day rows, last 2 months
      agents     -- (bar_agent only) sorted list of agent_id strings
      series_week-- (bar_agent only) {agent_id: [(dt, float), ...]} from period=week rows
      series_day -- (bar_agent only) {agent_id: [(dt, float), ...]} from period=day rows
      cutoff_12mo-- (bar_agent only) 12-month window cutoff datetime
      cutoff_2mo -- (bar_agent only) 2-month window cutoff datetime

    Returns descriptors in the priority order defined by _KNOWN_METRICS,
    followed by any additional fields discovered from the records.
    When a field has no data at all it is omitted from the result.
    When data spans fewer periods than a window, the available range is used.
    """
    week_records = [r for r in records if r.get("period") == "week"]
    day_records = [r for r in records if r.get("period") == "day"]

    blended_week = [r for r in week_records if r.get("agent_id") == METRICS_AGGREGATOR_ID]
    blended_day = [r for r in day_records if r.get("agent_id") == METRICS_AGGREGATOR_ID]
    per_agent_week = [
        r for r in week_records
        if r.get("agent_id") and r.get("agent_id") != METRICS_AGGREGATOR_ID
        and not r.get("event")
    ]
    per_agent_day = [
        r for r in day_records
        if r.get("agent_id") and r.get("agent_id") != METRICS_AGGREGATOR_ID
        and not r.get("event")
    ]

    blended_week_sorted = sorted(blended_week, key=lambda r: r.get("timestamp_start") or "")
    blended_day_sorted = sorted(blended_day, key=lambda r: r.get("timestamp_start") or "")
    per_agent_week_sorted = sorted(per_agent_week, key=lambda r: r.get("timestamp_start") or "")
    per_agent_day_sorted = sorted(per_agent_day, key=lambda r: r.get("timestamp_start") or "")

    cutoff_12mo = _cutoff_weeks(now, WINDOW_12MO_WEEKS)
    cutoff_2mo = _cutoff_days(now, WINDOW_2MO_DAYS)

    # Discover scalar fields in blended records not in _KNOWN_METRICS.
    extra_fields = []
    seen_fields = set(_KNOWN_FIELD_NAMES) | _NON_METRIC_FIELDS
    for rec in blended_week_sorted + blended_day_sorted:
        for key, val in rec.items():
            if key in seen_fields:
                continue
            if isinstance(val, (int, float)):
                extra_fields.append((key, key, _infer_ylabel(key), _LINE, _generic_description(key)))
            seen_fields.add(key)

    result = []
    for field, title, ylabel, chart_type, description in list(_KNOWN_METRICS) + extra_fields:
        if chart_type == _BAR_AGENT_STACKED:
            field_in, field_out = field
            label_in, label_out = _STACKED_LABELS.get(
                (field_in, field_out), ("input", "output")
            )
            desc = _build_bar_agent_stacked(
                title, ylabel,
                per_agent_week_sorted, per_agent_day_sorted,
                cutoff_12mo, cutoff_2mo,
                field_in, field_out, label_in=label_in, label_out=label_out,
                description=description,
            )
        elif chart_type == _BAR_AGENT:
            desc = _build_bar_agent(
                field, title, ylabel,
                per_agent_week_sorted, per_agent_day_sorted,
                cutoff_12mo, cutoff_2mo,
                description=description,
            )
        else:
            desc = _build_line(
                field, title, ylabel,
                blended_week_sorted, blended_day_sorted,
                cutoff_12mo, cutoff_2mo,
                description=description,
            )
        if desc is not None:
            result.append(desc)

    return result


def _build_line(
    field: str,
    title: str,
    ylabel: str,
    blended_week: list,
    blended_day: list,
    cutoff_12mo: datetime,
    cutoff_2mo: datetime,
    description: str = "",
) -> Optional[dict]:
    week_points = []
    for rec in blended_week:
        val = rec.get(field)
        if val is None:
            continue
        dt = _parse_ts(rec.get("timestamp_start"))
        if dt is None:
            continue
        try:
            week_points.append((dt, float(val)))
        except (TypeError, ValueError):
            continue

    day_points = []
    for rec in blended_day:
        val = rec.get(field)
        if val is None:
            continue
        dt = _parse_ts(rec.get("timestamp_start"))
        if dt is None:
            continue
        try:
            day_points.append((dt, float(val)))
        except (TypeError, ValueError):
            continue

    if not week_points and not day_points:
        return None

    data_12mo = [(dt, v) for dt, v in week_points if dt >= cutoff_12mo]
    data_2mo = [(dt, v) for dt, v in day_points if dt >= cutoff_2mo]
    if not data_12mo:
        data_12mo = week_points
    if not data_2mo:
        data_2mo = day_points

    return {
        "field": field,
        "title": title,
        "ylabel": ylabel,
        "description": description,
        "chart_type": _LINE,
        "data_12mo": data_12mo,
        "data_2mo": data_2mo,
        # Window bounds, kept alongside the data so the renderer can force
        # each pane's x-axis to span the full declared window (12 months /
        # 2 months) even when the actual data inside it is sparse or short
        # -- a thin cluster of points must not visually imply a short
        # window just because matplotlib's default autoscale hugs the data.
        "cutoff_12mo": cutoff_12mo,
        "cutoff_2mo": cutoff_2mo,
    }


def _build_bar_agent(
    field: str,
    title: str,
    ylabel: str,
    per_agent_week: list,
    per_agent_day: list,
    cutoff_12mo: datetime,
    cutoff_2mo: datetime,
    description: str = "",
) -> Optional[dict]:
    series_week: dict = {}
    for rec in per_agent_week:
        val = rec.get(field)
        if val is None:
            continue
        dt = _parse_ts(rec.get("timestamp_start"))
        if dt is None:
            continue
        agent = rec.get("agent_id", "")
        if not agent:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        series_week.setdefault(agent, []).append((dt, fval))

    series_day: dict = {}
    for rec in per_agent_day:
        val = rec.get(field)
        if val is None:
            continue
        dt = _parse_ts(rec.get("timestamp_start"))
        if dt is None:
            continue
        agent = rec.get("agent_id", "")
        if not agent:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        series_day.setdefault(agent, []).append((dt, fval))

    if not series_week and not series_day:
        return None

    agents = sorted(set(series_week) | set(series_day))
    return {
        "field": field,
        "title": title,
        "ylabel": ylabel,
        "description": description,
        "chart_type": _BAR_AGENT,
        "agents": agents,
        "series_week": series_week,
        "series_day": series_day,
        "cutoff_12mo": cutoff_12mo,
        "cutoff_2mo": cutoff_2mo,
    }


def _collect_agent_series(records: list, field: str) -> dict:
    """{agent_id: [(dt, float), ...]} for one scalar field across per-agent
    breakdown records -- the shared accumulation _build_bar_agent and
    _build_bar_agent_stacked both need, one field at a time."""
    series: dict = {}
    for rec in records:
        val = rec.get(field)
        if val is None:
            continue
        dt = _parse_ts(rec.get("timestamp_start"))
        if dt is None:
            continue
        agent = rec.get("agent_id", "")
        if not agent:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        series.setdefault(agent, []).append((dt, fval))
    return series


def _build_bar_agent_stacked(
    title: str,
    ylabel: str,
    per_agent_week: list,
    per_agent_day: list,
    cutoff_12mo: datetime,
    cutoff_2mo: datetime,
    field_in: str,
    field_out: str,
    label_in: str = "input",
    label_out: str = "output",
    description: str = "",
) -> Optional[dict]:
    """Like _build_bar_agent, but for two components stacked in one bar per
    agent (e.g. input vs output tokens) instead of a single summed field."""
    series_week_in = _collect_agent_series(per_agent_week, field_in)
    series_week_out = _collect_agent_series(per_agent_week, field_out)
    series_day_in = _collect_agent_series(per_agent_day, field_in)
    series_day_out = _collect_agent_series(per_agent_day, field_out)

    if not (series_week_in or series_week_out or series_day_in or series_day_out):
        return None

    agents = sorted(
        set(series_week_in) | set(series_week_out)
        | set(series_day_in) | set(series_day_out)
    )
    return {
        "field": f"{field_in}:{field_out}",
        "title": title,
        "ylabel": ylabel,
        "description": description,
        "chart_type": _BAR_AGENT_STACKED,
        "agents": agents,
        "label_in": label_in,
        "label_out": label_out,
        "series_week_in": series_week_in,
        "series_week_out": series_week_out,
        "series_day_in": series_day_in,
        "series_day_out": series_day_out,
        "cutoff_12mo": cutoff_12mo,
        "cutoff_2mo": cutoff_2mo,
    }


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------

def _figure_to_b64(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _render_line_pair(desc: dict) -> tuple:
    """Return (img_12mo_b64, img_2mo_b64) PNG base64 strings for a line chart row.

    Each pane's x-axis is pinned to its full declared window (the 12-month
    window on the left, the 2-month window on the right) via set_xlim, not
    left to matplotlib's default autoscale-to-data-range behavior. Without
    this, a window with only a few early data points (a metric just added,
    or a gap like the one metrics-aggregator backfilling fixed) renders with
    an x-axis that silently shrinks to hug those points -- visually implying
    a short window when the declared window is actually 12 months / 2 months.
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    windows = [
        ("12 months", desc["data_12mo"], desc.get("cutoff_12mo"), "weeks", WINDOW_12MO_WEEKS),
        ("2 months", desc["data_2mo"], desc.get("cutoff_2mo"), "days", WINDOW_2MO_DAYS),
    ]

    imgs = []
    for window_label, data, cutoff, unit, amount in windows:
        fig, ax = plt.subplots(figsize=(5.5, 3.4))
        if data:
            xs = [dt for dt, _ in data]
            ys = [v for _, v in data]
            ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.5)
        if cutoff is not None:
            window_end = cutoff + (
                timedelta(weeks=amount) if unit == "weeks" else timedelta(days=amount)
            )
            ax.set_xlim(mdates.date2num(cutoff), mdates.date2num(window_end))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate(rotation=30, ha="right")
        ax.set_title(f"{desc['title']} ({window_label})")
        ax.set_ylabel(desc["ylabel"])
        ax.grid(True, alpha=0.3)
        imgs.append(_figure_to_b64(fig))
    return imgs[0], imgs[1]


def _render_bar_agent_pair(desc: dict) -> tuple:
    """Return (img_12mo_b64, img_2mo_b64) PNG base64 strings for a by-agent bar row."""
    import matplotlib.pyplot as plt

    imgs = []
    for window_label, series_key, cutoff in [
        ("12 months", "series_week", desc["cutoff_12mo"]),
        ("2 months",  "series_day",  desc["cutoff_2mo"]),
    ]:
        fig, ax = plt.subplots(figsize=(5.5, 3.4))
        series = desc[series_key]
        totals = {
            agent: sum(v for dt, v in series.get(agent, []) if dt >= cutoff)
            for agent in desc["agents"]
        }
        active = [(a, totals[a]) for a in desc["agents"] if totals[a] > 0]
        if not active:
            # No data falls within the cutoff window -- fall back to the full
            # available range (same short-range behavior as _build_line's
            # line charts; issue #547 PR review RV-001) rather than silently
            # rendering an empty bar chart.
            fallback_totals = {
                agent: sum(v for _, v in series.get(agent, []))
                for agent in desc["agents"]
            }
            active = [(a, fallback_totals[a]) for a in desc["agents"] if fallback_totals[a] > 0]
        if active:
            labels, values = zip(*active)
            ax.bar(range(len(labels)), values)
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.set_title(f"{desc['title']} ({window_label})")
        ax.set_ylabel(desc["ylabel"])
        ax.grid(True, alpha=0.3, axis="y")
        imgs.append(_figure_to_b64(fig))
    return imgs[0], imgs[1]


def _render_bar_agent_stacked_pair(desc: dict) -> tuple:
    """Return (img_12mo_b64, img_2mo_b64) PNG base64 strings for a stacked
    by-agent bar row -- e.g. input vs output tokens, one color per
    component, stacked in a single bar per agent."""
    import matplotlib.pyplot as plt

    imgs = []
    for window_label, in_key, out_key, cutoff in [
        ("12 months", "series_week_in", "series_week_out", desc["cutoff_12mo"]),
        ("2 months",  "series_day_in",  "series_day_out",  desc["cutoff_2mo"]),
    ]:
        fig, ax = plt.subplots(figsize=(5.5, 3.4))
        series_in = desc[in_key]
        series_out = desc[out_key]

        def _totals(series, cutoff=cutoff):
            return {
                agent: sum(v for dt, v in series.get(agent, []) if dt >= cutoff)
                for agent in desc["agents"]
            }

        totals_in = _totals(series_in)
        totals_out = _totals(series_out)
        active = [a for a in desc["agents"] if totals_in[a] > 0 or totals_out[a] > 0]
        if not active:
            # No data falls within the cutoff window -- fall back to the full
            # available range, same short-range behavior as the single-field
            # by-agent bar chart (issue #547 PR review RV-001).
            totals_in = {a: sum(v for _, v in series_in.get(a, [])) for a in desc["agents"]}
            totals_out = {a: sum(v for _, v in series_out.get(a, [])) for a in desc["agents"]}
            active = [a for a in desc["agents"] if totals_in[a] > 0 or totals_out[a] > 0]
        if active:
            xs = range(len(active))
            in_vals = [totals_in[a] for a in active]
            out_vals = [totals_out[a] for a in active]
            ax.bar(xs, in_vals, label=desc["label_in"])
            ax.bar(xs, out_vals, bottom=in_vals, label=desc["label_out"])
            ax.set_xticks(list(xs))
            ax.set_xticklabels(active, rotation=30, ha="right", fontsize=8)
            ax.legend(fontsize=7)
        ax.set_title(f"{desc['title']} ({window_label})")
        ax.set_ylabel(desc["ylabel"])
        ax.grid(True, alpha=0.3, axis="y")
        imgs.append(_figure_to_b64(fig))
    return imgs[0], imgs[1]


def render_charts(chart_descriptors: list) -> list:
    """Render each descriptor to a (img_12mo_b64, img_2mo_b64) pair of PNG base64 strings."""
    import matplotlib
    matplotlib.use("Agg")
    pairs = []
    for desc in chart_descriptors:
        if desc["chart_type"] == _BAR_AGENT_STACKED:
            pairs.append(_render_bar_agent_stacked_pair(desc))
        elif desc["chart_type"] == _BAR_AGENT:
            pairs.append(_render_bar_agent_pair(desc))
        else:
            pairs.append(_render_line_pair(desc))
    return pairs


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

_HTML_HEADER = (
    "<!DOCTYPE html>\n"
    "<html lang=\"en\">\n"
    "<head>\n"
    "<meta charset=\"UTF-8\">\n"
    "<style>\n"
    "  @page { size: letter portrait; margin: 10mm; }\n"
    "  body { font-family: sans-serif; font-size: 10pt; }\n"
    "  .page { break-after: page; }\n"
    "  .page:last-child { break-after: auto; }\n"
    "  .front-matter { break-after: page; }\n"
    "  .front-matter h1 { font-size: 20pt; margin: 0 0 2mm; }\n"
    "  .front-matter .subtitle { font-size: 13pt; color: #374151; margin: 0 0 2mm; }\n"
    "  .front-matter .date { font-size: 10pt; color: #6b7280; margin: 0 0 8mm; }\n"
    "  .front-matter h2 { font-size: 13pt; margin: 6mm 0 2mm; }\n"
    "  .front-matter p { margin: 0 0 4mm; }\n"
    "  .front-matter ul.toc { list-style: none; padding-left: 0; margin: 0; }\n"
    "  .front-matter ul.toc li { margin: 0 0 1.5mm; }\n"
    "  .front-matter ul.toc a { color: inherit; text-decoration: none; }\n"
    "  h2.metric-title { font-size: 12pt; margin: 0 0 1mm; }\n"
    "  p.metric-desc { font-size: 9pt; color: #374151; margin: 0 0 2mm; }\n"
    "  .row { display: flex; align-items: flex-start; margin-bottom: 4mm; }\n"
    "  .row img { width: 50%; height: auto; }\n"
    "</style>\n"
    "</head>\n"
    "<body>\n"
)

_HTML_FOOTER = "</body>\n</html>\n"


def _build_front_matter(chart_descriptors: list, now: datetime, repo_name: str) -> str:
    """Title/subtitle/date, an "About this Document" blurb, and a Table of
    Contents listing every metric section by its H2 anchor -- mirrors the
    front-matter convention used for generated reports elsewhere (title,
    subtitle, date, About, Table of Contents), adapted to this report's own
    chart-based layout rather than a markdown pipeline."""
    date_str = now.strftime("%B %d, %Y")
    toc_items = "".join(
        f'<li><a href="#{_slugify(desc["title"])}">{html.escape(desc["title"])}</a></li>'
        for desc in chart_descriptors
    )
    return (
        '<div class="front-matter">\n'
        f"<h1>{html.escape(DOC_TITLE)}</h1>\n"
        f'<p class="subtitle">{html.escape(repo_name)}</p>\n'
        f'<p class="date">{html.escape(date_str)}</p>\n'
        "<h2>About this Document</h2>\n"
        f"<p>{html.escape(ABOUT_TEXT)}</p>\n"
        "<h2>Table of Contents</h2>\n"
        f'<ul class="toc">{toc_items}</ul>\n'
        "</div>"
    )


def build_html(
    chart_descriptors: list, chart_pairs: list,
    now: Optional[datetime] = None, repo_name: Optional[str] = None,
) -> str:
    """Assemble an HTML document with base64-embedded chart images.

    Front matter (title/subtitle/date, About this Document, Table of
    Contents) renders on its own page, followed by one H2-headed section per
    metric -- its title, a short description, then its chart pair. Chart
    rows are grouped into pages of ROWS_PER_PAGE using CSS break-after: page;
    each metric's heading/description stay attached to its own chart row so
    a page break never separates them from the charts they describe.

    now/repo_name default to the real current time / a resolved repo name
    when omitted, so a caller that only cares about the chart layout (tests,
    ad hoc inspection) need not supply them.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if repo_name is None:
        repo_name = _resolve_repo_name()

    front_matter = _build_front_matter(chart_descriptors, now, repo_name)

    rows_html = []
    for desc, (img_12mo, img_2mo) in zip(chart_descriptors, chart_pairs):
        title = html.escape(desc["title"])
        anchor = _slugify(desc["title"])
        description = html.escape(desc.get("description", ""))
        row = (
            f'<h2 class="metric-title" id="{anchor}">{title}</h2>\n'
            f'<p class="metric-desc">{description}</p>\n'
            '<div class="row">'
            f'<img src="data:image/png;base64,{img_12mo}" alt="{title} 12mo">'
            f'<img src="data:image/png;base64,{img_2mo}" alt="{title} 2mo">'
            "</div>"
        )
        rows_html.append(row)

    pages = []
    for i in range(0, max(len(rows_html), 1), ROWS_PER_PAGE):
        page_rows = rows_html[i: i + ROWS_PER_PAGE]
        page = '<div class="page">\n' + "\n".join(page_rows) + "\n</div>"
        pages.append(page)

    return _HTML_HEADER + front_matter + "\n" + "\n".join(pages) + "\n" + _HTML_FOOTER


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def render_pdf(html_doc: str, output_path: str) -> None:
    """Render the HTML string to a PDF file at output_path via WeasyPrint."""
    import weasyprint
    weasyprint.HTML(string=html_doc).write_pdf(output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a PDF performance report from weekly-aggregate records.",
    )
    parser.add_argument(
        "--output", default="metrics-report.pdf",
        help="Output path for the PDF (default: metrics-report.pdf)",
    )
    parser.add_argument(
        "--now", default=None,
        help="Override current UTC time in ISO 8601 (for testing/backfills)",
    )
    args = parser.parse_args()

    if args.now:
        _parsed = datetime.fromisoformat(args.now.rstrip("Z") + "+00:00" if args.now.endswith("Z") else args.now)
        if _parsed.tzinfo is None:
            now = _parsed.replace(tzinfo=timezone.utc)
        else:
            now = _parsed.astimezone(timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    records = read_aggregate_records()
    if not records:
        print("metrics_report: no aggregate records found -- no PDF produced", file=sys.stderr)
        return

    chart_descriptors = prepare_report_data(records, now)
    if not chart_descriptors:
        print("metrics_report: no renderable metrics found -- no PDF produced", file=sys.stderr)
        return

    chart_pairs = render_charts(chart_descriptors)
    repo_name = _resolve_repo_name()
    html_doc = build_html(chart_descriptors, chart_pairs, now, repo_name)
    render_pdf(html_doc, args.output)
    print(f"metrics_report: PDF written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
