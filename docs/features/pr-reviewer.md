# Feature: PR reviewer

The PR reviewer supplies evidence-backed structured findings. The orchestrator
computes the verdict through `pipeline/review_outcome.py`; it also owns current
human-review state, comment rendering, and PR state changes.

## Scenario: A blocking finding starts a fix cycle

**Given** a high-confidence finding that is not an optional improvement or
covered by a verified ADR exception
**When** the reviewer writes it to `result.review.findings`
**Then** the orchestrator marks it `blocking: true` and requests changes

## Scenario: An optional improvement does not block

**Given** a non-Critical finding categorized as `improvement`
**When** the orchestrator computes the review outcome
**Then** the finding is marked `blocking: false`

## Scenario: The coder follows the computed result

**Given** structured review feedback reaches the coder through the review loop
**When** the coder categorizes feedback
**Then** findings marked `blocking: true` are Required and non-blocking findings
are Suggested

## Scenario: Review state is deterministic

**Given** structured findings, current human blockers, standards, and ADRs
**When** the review step completes
**Then** the orchestrator computes APPROVE or REQUEST CHANGES without relying on
an advisory model verdict or effort classification
