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

## Scenario: Weekly aggregator commits one bucket per catch-up period
**Given** records.jsonl is missing two or more consecutive weekly bucket periods
**When** aggregate-metrics.sh is invoked once with default arguments
**Then** a separate git commit is created for each missing weekly bucket, in chronological order

## Scenario: Daily aggregator commits one bucket per catch-up period
**Given** records.jsonl is missing two or more consecutive daily bucket periods
**When** aggregate-metrics-daily.sh is invoked once with default arguments
**Then** a separate git commit is created for each missing daily bucket, in chronological order

## Scenario: Crash recovery leaves committed buckets intact on re-run
**Given** aggregate-metrics.sh has committed the first of two missing weekly buckets and then exited non-zero
**When** aggregate-metrics.sh is re-invoked with default arguments
**Then** only the second missing weekly bucket is appended and committed, and the first bucket's commit remains unchanged

## Scenario: Exactly one AI_AGILE_STATUS line emitted per run
**Given** three missing weekly bucket periods exist in records.jsonl
**When** aggregate-metrics.sh is invoked with default arguments
**Then** exactly one AI_AGILE_STATUS line is printed to standard output for that invocation

## Scenario: Oct 5-Nov 1 gap backfilled by one ordinary invocation
**Given** ai-agile/metrics:records.jsonl contains no entries between Oct 5 2026 and Nov 1 2026
**When** each aggregation script is invoked once with its default arguments
**Then** four weekly aggregate rows and the corresponding daily rows for that period are present in records.jsonl, each bucket in its own git commit

## Scenario: Single-bucket case produces exactly one commit
**Given** exactly one new weekly bucket period is due and no prior buckets are missing
**When** aggregate-metrics.sh is invoked with default arguments
**Then** exactly one git commit is created
