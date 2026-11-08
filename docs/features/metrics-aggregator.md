# Feature: Metrics Aggregator

## Scenario: Multiple missing weekly buckets are appended oldest first with correct timestamps
**Given** a `records.jsonl` containing records with 3 consecutive missing weekly buckets
**When** `metrics_aggregator.py --period week` is invoked without additional flags
**Then** 3 aggregate row sets are appended in oldest-to-newest order, each with the correct `timestamp_start` and `timestamp_end` for its respective week

## Scenario: Walk halts at the first already-aggregated weekly bucket
**Given** a `records.jsonl` where 2 consecutive weekly buckets are missing and the next older bucket is already aggregated
**When** `metrics_aggregator.py --period week` is invoked
**Then** exactly 2 aggregate row sets are appended and the already-aggregated bucket is not duplicated

## Scenario: Empty records weekly walk terminates within the bounded constant
**Given** `records.jsonl` is empty
**When** `metrics_aggregator.py --period week` is invoked
**Then** the aggregator appends at most 52 aggregate row sets and exits successfully

## Scenario: Empty records daily walk terminates within the bounded constant
**Given** `records.jsonl` is empty
**When** `metrics_aggregator.py --period day` is invoked
**Then** the aggregator appends at most 366 aggregate row sets and exits successfully

## Scenario: Single missing weekly bucket produces one row set
**Given** a `records.jsonl` with exactly one missing weekly bucket
**When** `metrics_aggregator.py --period week` is invoked
**Then** exactly one aggregate row set is appended

## Scenario: --now override controls the walk start point
**Given** a `records.jsonl` with missing weekly buckets and a known most-recent complete bucket before 2024-01-14
**When** `metrics_aggregator.py --period week --now 2024-01-14` is invoked
**Then** the backward walk starts from the most recent complete weekly bucket before 2024-01-14
