# Feature: Add Issue Audit Schema And Deterministic Verdict Function

## Scenario: Valid audit object passes schema validation
**Given** `pipeline/schemas/issue-audit.schema.json` is loaded
**When** a JSON object with `issue_number` and an `evidence` array containing items each with `type`, `confidence`, `citation`, and `excerpt` is validated against the schema
**Then** validation succeeds with no errors

## Scenario: Non-unverifiable evidence item without citation fails schema validation
**Given** `pipeline/schemas/issue-audit.schema.json` is loaded
**When** a JSON object contains an evidence item with a type other than `unverifiable` and no `citation` field
**Then** schema validation fails

## Scenario: Unverifiable evidence item without citation passes schema validation
**Given** `pipeline/schemas/issue-audit.schema.json` is loaded
**When** a JSON object contains an evidence item with `type` set to `unverifiable` and no `citation` field
**Then** schema validation succeeds

## Scenario: Verdict function returns OBSOLETE at exactly 0.85 confidence threshold
**Given** `pipeline/issue_audit_outcome.py` is imported
**When** the verdict function is called with evidence items all supporting closure with an aggregate confidence of exactly 0.85
**Then** the returned verdict is `OBSOLETE`

## Scenario: Verdict function returns STILL-VALID just below 0.85 confidence threshold
**Given** `pipeline/issue_audit_outcome.py` is imported
**When** the verdict function is called with evidence items supporting closure with an aggregate confidence just below 0.85
**Then** the returned verdict is `STILL-VALID`

## Scenario: Verdict function returns SUPERSEDED-BY-#N when a superseding issue is cited
**Given** `pipeline/issue_audit_outcome.py` is imported
**When** the verdict function is called with evidence items that identify superseding issue number N with confidence at or above 0.85
**Then** the returned verdict is `SUPERSEDED-BY-#N` with N substituted as the superseding issue number

## Scenario: Verdict function returns NEEDS-HUMAN-REVIEW for conflicting evidence
**Given** `pipeline/issue_audit_outcome.py` is imported
**When** the verdict function is called with evidence items containing conflicting signals where some support closure and others oppose it
**Then** the returned verdict is `NEEDS-HUMAN-REVIEW`

## Scenario: Batch selection interleaves never-reviewed and reviewed issues by a single age key
**Given** a never-reviewed issue created before a reviewed issue's `reviewed-*` label date, and a never-reviewed issue created after another reviewed issue's `reviewed-*` label date
**When** batch selection is performed
**Then** the never-reviewed issue with the earlier creation date sorts ahead of the reviewed issue with the later `reviewed-*` date, and the never-reviewed issue with the later creation date sorts behind the reviewed issue with the earlier `reviewed-*` date
