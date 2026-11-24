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

## Scenario: script does not set an Authorization Basic header when url.insteadOf is used
**Given** `GITHUB_TOKEN` is set to a non-empty token value
**When** `append-metrics-record.sh` is executed with the actual bash interpreter
**Then** none of the exported `GIT_CONFIG_VALUE_*` variables contains an `Authorization: Basic` value

## Scenario: script exports url.insteadOf git config from a real non-mocked invocation
**Given** `GITHUB_TOKEN` is set to a non-empty token value
**When** `append-metrics-record.sh` is executed with the actual bash interpreter (not a mocked subprocess call)
**Then** `GIT_CONFIG_KEY_0` is `url.https://x-access-token:<GITHUB_TOKEN>@github.com/.insteadOf` and `GIT_CONFIG_VALUE_0` is `https://github.com/`

## Scenario: scheduled flow records a claim on ai-agile/metrics after the fix is deployed
**Given** the url.insteadOf authentication fix is merged to the main branch
**When** a scheduled flow (such as weekly-release) runs in GitHub Actions
**Then** a schedule.claim record is written to the ai-agile/metrics branch

## Scenario: weekly-release publishes a GitHub Release after the fix merges
**Given** the url.insteadOf authentication fix is merged to the main branch
**When** the next weekly-release scheduled run executes
**Then** a GitHub Release is published, closing the gap that has existed since 2026-10-23

## Scenario: metrics-aggregation flow completes after a step record is appended in a private repository
**Given** a private repository with the orchestrator installed, `actions/checkout` has persisted a credential in `.git/config`, and the `ai-agile/metrics` branch exists
**When** a scheduled orchestrator run appends a step record via `append-metrics-record.sh` and then executes the `metrics-aggregation` flow
**Then** `metrics_aggregator.py` successfully fetches `ai-agile/metrics`, appends a `period=week` aggregate row, and the flow exits with `AI_AGILE_STATUS: complete`

## Scenario: append-metrics-record.sh preserves the git checkout credential when GITHUB_TOKEN is set
**Given** a repository where `actions/checkout` has written `http.https://github.com/.extraHeader` into `.git/config` and `GITHUB_TOKEN` is set in the environment
**When** `scripts/append-metrics-record.sh` runs
**Then** `http.https://github.com/.extraHeader` remains present in `.git/config`
