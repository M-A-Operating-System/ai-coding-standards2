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
are Suggested -- the coder never reclassifies a non-blocking finding back
into something to fix now

## Scenario: A Low-severity finding's complexity decides its disposition

**Given** a Low-severity finding with `complexity: low`
**When** the orchestrator computes the review outcome
**Then** the finding is marked `blocking: true`, same as any other blocking finding

**Given** a Low-severity finding with `complexity: medium`
**When** the orchestrator computes the review outcome
**Then** the finding is marked `blocking: false` and flagged prominently in the
rendered review for a human to decide -- a human who agrees it matters leaves
a real REQUEST_CHANGES review, which independently hard-blocks

**Given** a Low-severity finding with `complexity: high`
**When** the orchestrator computes the review outcome
**Then** the finding is marked `blocking: false` and bundled into a follow-up
GitHub issue the orchestrator raises on the reviewer's behalf (STD-ARCH-007)

## Scenario: Review state is deterministic

**Given** structured findings, current human blockers, standards, and ADRs
**When** the review step completes
**Then** the orchestrator computes APPROVE or REQUEST CHANGES without relying on
an advisory model verdict or effort classification
