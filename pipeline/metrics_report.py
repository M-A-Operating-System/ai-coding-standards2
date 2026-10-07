#!/usr/bin/env python3
"""Weekly performance report generator for ai-agile/metrics (issue #534).

Reads weekly-aggregate (period=week) and daily-aggregate (period=day) rows
from records.jsonl on the ai-agile/metrics branch, generates per-metric
charts with matplotlib, assembles them into a print-styled HTML document,
and renders to PDF via WeasyPrint.

REPORT LAYOUT
-------------
Portrait A4, four chart rows per page (CSS break-after: page). Each metric
appears as one row containing two charts side by side:
  Left:  last 12 months of data, sourced from period=week aggregate rows.
  Right: last 4 weeks of data, sourced from period=day aggregate rows.

By-agent breakdown metrics (cost, duration by agent_id) use bar charts
per window instead of line charts, showing where spending goes and
making agent-mix shifts visible.

METRIC PRIORITY ORDER (v1)
--------------------------
1. Cost by agent_id (bar chart) -- where spending goes; decouples
   agent-mix shifts from performance trends in all other charts.
2. Duration by agent_id (bar chart).
3. Throughput: issues per week (count_issues from blended rows).
4. Cost per completed issue (ave_cost_usd-issue).
5. Value-add ratio (ratio_value_add-issue) -- spike carve-out applied by
   metrics-aggregator; values here reflect that definition directly and
   are not recomputed.
6. Classification mix (ratio_classification_mix) -- spike carve-out applied
   by metrics-aggregator; values here reflect that definition directly and
   are not recomputed.
7. Cache efficiency (ratio_cache_efficiency).
8. Blocked/failed rate per invocation (ratio_error_rate).
9. Any additional scalar aggregate fields discovered dynamically from the
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
  determines the 12-month and 4-week lookback cutoffs).

Runtime requirements (not in requirements.txt -- install separately):
  matplotlib >= 3.7
  weasyprint >= 61
"""

import argparse
import base64
import html
import io
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

METRICS_BRANCH = "ai-agile/metrics"
METRICS_RECORDS_FILE = "records.jsonl"
METRICS_AGGREGATOR_ID = "metrics-aggregator"

ROWS_PER_PAGE = 4
WINDOW_12MO_WEEKS = 52
WINDOW_4WK_DAYS = 28

_LINE = "line"
_BAR_AGENT = "bar_agent"

# Priority-ordered metric definitions: (field_name, title, ylabel, chart_type).
# Any additional scalar aggregate fields found in the blended records but not
# listed here are appended after in discovery order, so a new field added by
# a future metrics-aggregator update is rendered automatically.
_KNOWN_METRICS = [
    # By-agent bar charts (sourced from per-agent breakdown rows).
    ("sum_cost_usd",    "Cost by agent",     "cost (USD)",    _BAR_AGENT),
    ("sum_duration_ms", "Duration by agent", "duration (ms)", _BAR_AGENT),
    # Blended time-series line charts (sourced from blended weekly-aggregate rows).
    ("count_issues",             "Throughput (issues per week)",                    "issues",      _LINE),
    ("ave_cost_usd-issue",       "Cost per completed issue",                        "cost (USD)",  _LINE),
    ("ratio_value_add-issue",    "Value-add ratio",                                 "ratio (0-1)", _LINE),
    ("ratio_classification_mix", "Classification mix (feature and research / total)", "ratio (0-1)", _LINE),
    ("ratio_cache_efficiency",   "Cache efficiency (cache reads / total cache tokens)", "ratio (0-1)", _LINE),
    ("ratio_error_rate",         "Blocked/failed rate per invocation",              "ratio (0-1)", _LINE),
]

_KNOWN_FIELD_NAMES = {m[0] for m in _KNOWN_METRICS}

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
      data_4wk   -- (line only) list of (dt, float) pairs; period=day rows, last 4 weeks
      agents     -- (bar_agent only) sorted list of agent_id strings
      series_week-- (bar_agent only) {agent_id: [(dt, float), ...]} from period=week rows
      series_day -- (bar_agent only) {agent_id: [(dt, float), ...]} from period=day rows
      cutoff_12mo-- (bar_agent only) 12-month window cutoff datetime
      cutoff_4wk -- (bar_agent only) 4-week window cutoff datetime

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
    cutoff_4wk = _cutoff_days(now, WINDOW_4WK_DAYS)

    # Discover scalar fields in blended records not in _KNOWN_METRICS.
    extra_fields = []
    seen_fields = set(_KNOWN_FIELD_NAMES) | _NON_METRIC_FIELDS
    for rec in blended_week_sorted + blended_day_sorted:
        for key, val in rec.items():
            if key in seen_fields:
                continue
            if isinstance(val, (int, float)):
                extra_fields.append((key, key, _infer_ylabel(key), _LINE))
            seen_fields.add(key)

    result = []
    for field, title, ylabel, chart_type in list(_KNOWN_METRICS) + extra_fields:
        if chart_type == _BAR_AGENT:
            desc = _build_bar_agent(
                field, title, ylabel,
                per_agent_week_sorted, per_agent_day_sorted,
                cutoff_12mo, cutoff_4wk,
            )
        else:
            desc = _build_line(
                field, title, ylabel,
                blended_week_sorted, blended_day_sorted,
                cutoff_12mo, cutoff_4wk,
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
    cutoff_4wk: datetime,
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
    data_4wk = [(dt, v) for dt, v in day_points if dt >= cutoff_4wk]
    if not data_12mo:
        data_12mo = week_points
    if not data_4wk:
        data_4wk = day_points

    return {
        "field": field,
        "title": title,
        "ylabel": ylabel,
        "chart_type": _LINE,
        "data_12mo": data_12mo,
        "data_4wk": data_4wk,
    }


def _build_bar_agent(
    field: str,
    title: str,
    ylabel: str,
    per_agent_week: list,
    per_agent_day: list,
    cutoff_12mo: datetime,
    cutoff_4wk: datetime,
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
        "chart_type": _BAR_AGENT,
        "agents": agents,
        "series_week": series_week,
        "series_day": series_day,
        "cutoff_12mo": cutoff_12mo,
        "cutoff_4wk": cutoff_4wk,
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
    """Return (img_12mo_b64, img_4wk_b64) PNG base64 strings for a line chart row."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    imgs = []
    for window_label, data in [("12 months", desc["data_12mo"]), ("4 weeks", desc["data_4wk"])]:
        fig, ax = plt.subplots(figsize=(5.5, 3))
        if data:
            xs = [dt for dt, _ in data]
            ys = [v for _, v in data]
            ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.5)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            fig.autofmt_xdate(rotation=30, ha="right")
        ax.set_title(f"{desc['title']} ({window_label})")
        ax.set_ylabel(desc["ylabel"])
        ax.grid(True, alpha=0.3)
        imgs.append(_figure_to_b64(fig))
    return imgs[0], imgs[1]


def _render_bar_agent_pair(desc: dict) -> tuple:
    """Return (img_12mo_b64, img_4wk_b64) PNG base64 strings for a by-agent bar row."""
    import matplotlib.pyplot as plt

    imgs = []
    for window_label, series_key, cutoff in [
        ("12 months", "series_week", desc["cutoff_12mo"]),
        ("4 weeks",   "series_day",  desc["cutoff_4wk"]),
    ]:
        fig, ax = plt.subplots(figsize=(5.5, 3))
        series = desc[series_key]
        totals = {
            agent: sum(v for dt, v in series.get(agent, []) if dt >= cutoff)
            for agent in desc["agents"]
        }
        active = [(a, totals[a]) for a in desc["agents"] if totals[a] > 0]
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


def render_charts(chart_descriptors: list) -> list:
    """Render each descriptor to a (img_12mo_b64, img_2mo_b64) pair of PNG base64 strings."""
    import matplotlib
    matplotlib.use("Agg")
    pairs = []
    for desc in chart_descriptors:
        if desc["chart_type"] == _BAR_AGENT:
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
    "  @page { size: A4 portrait; margin: 10mm; }\n"
    "  body { font-family: sans-serif; font-size: 10pt; }\n"
    "  .page { break-after: page; }\n"
    "  .page:last-child { break-after: auto; }\n"
    "  .row { display: flex; align-items: flex-start; margin-bottom: 4mm; }\n"
    "  .row img { width: 50%; height: auto; }\n"
    "</style>\n"
    "</head>\n"
    "<body>\n"
)

_HTML_FOOTER = "</body>\n</html>\n"


def build_html(chart_descriptors: list, chart_pairs: list) -> str:
    """Assemble an HTML document with base64-embedded chart images.

    Groups chart rows into pages of ROWS_PER_PAGE using CSS break-after: page.
    """
    rows_html = []
    for desc, (img_12mo, img_4wk) in zip(chart_descriptors, chart_pairs):
        title = html.escape(desc["title"])
        row = (
            '<div class="row">'
            f'<img src="data:image/png;base64,{img_12mo}" alt="{title} 12mo">'
            f'<img src="data:image/png;base64,{img_4wk}" alt="{title} 4wk">'
            "</div>"
        )
        rows_html.append(row)

    pages = []
    for i in range(0, max(len(rows_html), 1), ROWS_PER_PAGE):
        page_rows = rows_html[i: i + ROWS_PER_PAGE]
        page = '<div class="page">\n' + "\n".join(page_rows) + "\n</div>"
        pages.append(page)

    return _HTML_HEADER + "\n".join(pages) + "\n" + _HTML_FOOTER


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
    html_doc = build_html(chart_descriptors, chart_pairs)
    render_pdf(html_doc, args.output)
    print(f"metrics_report: PDF written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
