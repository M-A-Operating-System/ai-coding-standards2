# Feature: Pdd Measurement Pipeline Integration And Schema Extension

## Scenario: Script skips execution when approval label is absent
**Given** an issue without the `prd-writer:approved` label
**When** the measurement script is invoked for that issue
**Then** the script exits without appending any record to `ai-agile/metrics:records.jsonl`

## Scenario: Script writes complete record and emits success status for approved issue with valid Gherkin
**Given** an issue carrying the `prd-writer:approved` label with a syntactically valid Gherkin specification in the body
**When** the measurement script runs
**Then** `AI_AGILE_STATUS: complete` is emitted and a single `record_type=pdd_measurements` entry containing `github_issue_number`, `timestamp_start`, `timestamp_end`, `agent_id`, `cycle_id`, `duration_ms`, `input_tokens`, `output_tokens`, `retry_count`, and `retry_errors` is appended to `ai-agile/metrics:records.jsonl` on the `ai-agile/metrics` branch

## Scenario: Record includes hierarchy fields for a sub-issue
**Given** an approved issue carrying a `parent-issue:NNN` label with valid Gherkin
**When** the measurement script runs
**Then** the written `pdd_measurements` record contains non-null `parent_issue_number`, `root_issue_number`, and `decomposition_depth` values

## Scenario: Script emits blocked status on malformed or missing Gherkin
**Given** an issue carrying the `prd-writer:approved` label with missing or malformed Gherkin in the body
**When** the measurement script runs
**Then** `AI_AGILE_STATUS: blocked` is emitted with a corrective message identifying the Gherkin issue, and no record is appended to `ai-agile/metrics:records.jsonl`

## Scenario: Any reconciliation inconsistency in parsed step counts blocks the step
**Given** an approved issue with Gherkin where the parsed counts do not reconcile (scenarios count does not equal the length of scenario_step_counts, or total_steps does not equal the sum of per-scenario steps, or total_steps does not equal the sum of keyword counts)
**When** the measurement script runs
**Then** `AI_AGILE_STATUS: blocked` is emitted and no `pdd_measurements` record is appended to `ai-agile/metrics:records.jsonl`
