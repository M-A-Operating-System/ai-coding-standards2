# Feature: Pdd Measurement Backfill Mode

## Scenario: Backfill skips issues that already have a measurement record
**Given** a repository with a `prd-writer:approved` issue that already has a `pdd_measurements` record in `ai-agile/metrics:records.jsonl`
**When** an operator runs `python pipeline/calculate_pdd_measurements.py --backfill`
**Then** no additional record is written for that issue in `records.jsonl`

## Scenario: Backfill records the artefact comment timestamp as both measurement timestamps
**Given** a `prd-writer:approved` issue exists with no existing `pdd_measurements` record in `ai-agile/metrics:records.jsonl`
**And** the issue has an `<!-- ai-agile/artefact/v1 by 01_product_docs/prd-writer -->` comment with `created_at` equal to `2026-01-15T10:00:00Z`
**When** an operator runs `python pipeline/calculate_pdd_measurements.py --backfill`
**Then** the written record has `timestamp_start` equal to `2026-01-15T10:00:00Z` and `timestamp_end` equal to `2026-01-15T10:00:00Z`

## Scenario: Backfill skips and logs an approved issue with no prd-writer artefact comment
**Given** a `prd-writer:approved` issue exists with no existing `pdd_measurements` record
**And** the issue has no `<!-- ai-agile/artefact/v1 by 01_product_docs/prd-writer -->` comment
**When** an operator runs `python pipeline/calculate_pdd_measurements.py --backfill`
**Then** no record is written for that issue
**And** the skip reason is logged

## Scenario: Backfill continues after a malformed issue
**Given** a batch of `prd-writer:approved` issues exists, one of which is malformed
**When** an operator runs `python pipeline/calculate_pdd_measurements.py --backfill`
**Then** the malformed issue is logged with the reason and skipped
**And** measurement records are written for the remaining valid issues in the batch

## Scenario: Backfill measures closed approved issues
**Given** a `prd-writer:approved` issue in closed state has no existing `pdd_measurements` record
**And** the issue has an `<!-- ai-agile/artefact/v1 by 01_product_docs/prd-writer -->` comment
**When** an operator runs `python pipeline/calculate_pdd_measurements.py --backfill`
**Then** a measurement record is written for the closed issue in `records.jsonl`

## Scenario: Backfill records pass the same structural validation rules as live-path records
**Given** a `prd-writer:approved` issue exists with no existing `pdd_measurements` record
**And** the issue PRD body is well-formed
**When** an operator runs `python pipeline/calculate_pdd_measurements.py --backfill`
**Then** the written record passes all field, type, section-boundary, fenced-code-exclusion, zero-step-malformed, and AI_AGILE_STATUS validation checks that the live pipeline applies
**And** the record contains no `score`, `index`, `band`, `threshold`, or `coefficient` field

## Scenario: Running without --backfill preserves live pipeline behavior
**Given** the `pipeline/calculate_pdd_measurements.py` script is invoked without the `--backfill` argument
**When** a `prd-writer:approved` event triggers the live pipeline
**Then** the script produces the same output as before this change was introduced
