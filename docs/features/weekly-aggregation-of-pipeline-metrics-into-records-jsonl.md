# Feature: Weekly Aggregation Of Pipeline Metrics Into Records Jsonl

## Scenario: Weekly aggregate records appended to records.jsonl
**Given** `records.jsonl` on the `ai-agile/metrics` branch contains per-invocation records from the past week
**When** the weekly aggregation flow runs
**Then** new records are appended to `records.jsonl` with `agent_id` set to `metrics-aggregator`, a `period` field set to `week`, `timestamp_start` and `timestamp_end` covering the week boundary, and metric fields named using the `{aggregation_fn}_{base_metric}[-{dimension}]` convention

## Scenario: Value-add ratio computed for regular issues
**Given** `records.jsonl` contains invocation records for a completed week including at least one non-spike issue with records for `issue-classifier`, `prd-writer`, `prd-docs-updater`, and `03_execute/coder` steps
**When** the weekly aggregation flow runs
**Then** the aggregate record includes a `ratio_value_add-issue` field whose value equals the sum of `total_cost_usd` for `issue-classifier`, `prd-writer`, `prd-docs-updater`, and the earliest `03_execute/coder` invocation divided by the `total_cost_usd` of all records sharing that `github_issue_number`

## Scenario: Spike carve-out applied for spike-classified issues
**Given** `records.jsonl` contains invocation records for a `spike`-classified issue with records for `issue-classifier`, `prd-writer`, and `prd-docs-updater` but no `03_execute/coder` step
**When** the weekly aggregation flow runs
**Then** the `ratio_value_add-issue` contribution for that issue counts only `issue-classifier`, `prd-writer`, and `prd-docs-updater` cost as value-add, with no coder cost included

## Scenario: Classification-mix ratio computed across issue classifications
**Given** `records.jsonl` contains records for a week with issues classified as `enhancement`, `spike`, `bug`, and `tech-debt`
**When** the weekly aggregation flow runs
**Then** the aggregate record includes a `ratio_classification_mix` field equal to the count of `enhancement` and `spike` issues divided by the count of all classified issues for that week

## Scenario: Per-agent breakdown rows present alongside blended weekly total
**Given** `records.jsonl` contains records from multiple distinct agent steps in the same week
**When** the weekly aggregation flow runs
**Then** `records.jsonl` contains both individual aggregate rows (one per distinct real `agent_id` from that week) carrying that agent's own cost, duration, and token aggregates, and a separate row with `agent_id` set to `metrics-aggregator` and `period` set to `week` carrying the blended totals across all agents

## Scenario: Cost and token metrics use unambiguous field names
**Given** `records.jsonl` contains records with both `total_cost_usd` and token-count fields
**When** the weekly aggregation flow runs
**Then** all cost-based aggregate fields in the appended records have names containing `cost_usd`, and all token-count aggregate fields have names ending in `_tokens`, with no field name implying token counts are a cost figure

## Scenario: Missing or null field values do not abort aggregation
**Given** `records.jsonl` contains records where some rows have `classification: null` or are missing optional fields such as `retry_count` or `duration_ms`
**When** the weekly aggregation flow runs
**Then** the aggregation completes without error and appends aggregate records, treating null or missing per-record values as absent from the affected metric calculations rather than raising an exception
