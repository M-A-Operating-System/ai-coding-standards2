# Feature: Generate Weekly Performance Report Pdf From Aggregated Metrics

## Scenario: Report generator produces a PDF from weekly-aggregate rows
**Given** `records.jsonl` in `ai-agile/metrics` contains weekly-aggregate rows with `agent_id == "metrics-aggregator"` and `period == "week"`
**When** the report generator is invoked
**Then** a PDF report file is produced

## Scenario: PDF is portrait-oriented with four chart rows per page
**Given** the report generator has produced a PDF from `records.jsonl`
**When** the PDF is opened
**Then** the document is portrait-oriented and each page contains four chart rows rendered via WeasyPrint

## Scenario: Time-series metrics use dual time-window layout and by-agent metrics use grouped bar
**Given** `records.jsonl` contains weekly-aggregate rows and daily-aggregate rows for both time-series metrics (e.g. cost per completed issue, throughput) and by-agent breakdown metrics (cost and duration by `agent_id`)
**When** the report is generated
**Then** each time-series metric row contains a 12-month chart (sourced from weekly-aggregate rows) on the left and a 4-week chart (sourced from daily-aggregate rows) on the right, and by-agent breakdown rows use a grouped bar chart shape instead of a line pair

## Scenario: Cost and efficiency charts carry explicit unit labels
**Given** `records.jsonl` contains weekly-aggregate rows for both cost (USD) and token count metrics
**When** the report is generated
**Then** each cost, value, and efficiency chart's title or axis label explicitly states whether the unit is cost in USD or token count

## Scenario: Value-add ratio and classification-mix ratio apply the spike carve-out
**Given** `records.jsonl` contains weekly-aggregate rows for `ratio_value_add-issue` and `ratio_classification_mix` as produced by `metrics-aggregator`, including weeks containing spike-classified issues
**When** the report is generated
**Then** the value-add ratio and classification-mix ratio charts display values matching the aggregate rows directly, reflecting the spike carve-out per `metrics-aggregator`'s definitions

## Scenario: At least one chart shows a breakdown by agent_id
**Given** `records.jsonl` contains weekly-aggregate rows with an `agent_id` dimension for cost, duration, or token usage metrics
**When** the report is generated
**Then** the report includes at least one chart that displays cost, duration, or token usage broken down by `agent_id`

## Scenario: Short data range renders without failing
**Given** `records.jsonl` contains weekly-aggregate rows spanning fewer than 12 months for one metric and daily-aggregate rows spanning fewer than 4 weeks for another
**When** the report is generated
**Then** both affected charts render using the available data range and the report is produced without error

## Scenario: Report is produced as part of a scheduled orchestrator flow
**Given** `pipeline.json` defines a scheduled flow that sequences the `metrics-aggregator` aggregation step before the report generation step
**When** the scheduled flow triggers
**Then** the report generator runs after the aggregation step completes and produces the PDF as part of the orchestrator-managed flow

## Scenario: Report generator documents its metric selection, units, and layout
**Given** the report generator script is present in the repository
**When** the script or its accompanying documentation is examined
**Then** the metric selection, unit choices (USD vs. token count), and chart layout structure are described within the script or in an adjacent document
