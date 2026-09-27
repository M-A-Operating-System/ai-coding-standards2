# Feature: Metrics

## Scenario: Agent-type record carries the work item classification label
**Given** a work item labelled `classification: enhancement`
**When** the orchestrator records metrics for a completed agent step on that work item
**Then** the resulting `records.jsonl` entry has `classification` equal to `"enhancement"`

## Scenario: Scripted-type record carries the classification field for parity
**Given** a work item labelled `classification: bug`
**When** the orchestrator records metrics for a completed scripted step on that work item
**Then** the resulting `records.jsonl` entry has `classification` equal to `"bug"`

## Scenario: Classification field is null for an unclassified work item
**Given** a work item with no `classification:` label
**When** the orchestrator records metrics for any step on that work item
**Then** the resulting `records.jsonl` entry has `classification` equal to `null`

## Scenario: issue-classifier's own record reflects the classification it applied in the same step
**Given** a work item with no classification label
**When** issue-classifier runs and applies a `classification: enhancement` label, and metrics are recorded for that step
**Then** issue-classifier's own `records.jsonl` entry has `classification` equal to `"enhancement"`, not `null`
