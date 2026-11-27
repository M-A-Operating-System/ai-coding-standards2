# Feature: Add Obsolete And Superseded Auto-Close Actions To Issue Obsolescence Audit

## Scenario: OBSOLETE verdict at threshold applies label, posts cited comment, and closes issue
**Given** an open issue exists in the repository
**When** the deterministic verdict function returns OBSOLETE with confidence >= 0.85
**Then** the `issue-obsolescence-audit:obsolete` label is applied to the issue
**And** a comment is posted citing the supporting evidence (file path and line, commit SHA, or issue number)
**And** the issue is closed with `state_reason: completed` in the same agent run

## Scenario: SUPERSEDED-BY-#N verdict at threshold applies label, posts cited comment, and closes issue
**Given** an open issue exists in the repository
**When** the deterministic verdict function returns SUPERSEDED-BY-#N with confidence >= 0.85
**Then** the `issue-obsolescence-audit:superseded` label is applied to the issue
**And** a comment is posted naming and linking the superseding issue (#N) with supporting evidence
**And** the issue is closed with `state_reason: completed` in the same agent run

## Scenario: Schema validation rejects a verdict with a missing citation
**Given** a verdict object with an OBSOLETE or SUPERSEDED-BY-#N verdict and confidence >= 0.85
**When** every evidence item in the verdict omits the required citation field
**Then** schema validation fails and the issue is not closed

## Scenario: OBSOLETE verdict below the confidence threshold does not auto-close
**Given** an open issue exists in the repository
**When** the deterministic verdict function returns OBSOLETE with confidence < 0.85
**Then** the issue remains open and no auto-close label or closing comment is applied

## Scenario: STILL-VALID verdict leaves the issue open
**Given** an open issue exists in the repository
**When** the deterministic verdict function returns STILL-VALID
**Then** the issue remains open and no closing label or comment is applied
