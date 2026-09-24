# Feature: PR reviewer

The PR reviewer supplies evidence-backed structured findings, each a
`defect` (something that must be true) or an `improvement` (genuinely
optional). The orchestrator computes the verdict through
`pipeline/review_outcome.py`; it also owns current human-review state,
comment rendering, and PR state changes.

## Scenario: A blocking defect starts a fix cycle

**Given** a high-confidence defect finding not covered by a verified ADR
exception, with severity Critical, High, or Medium
**When** the reviewer writes it to `result.review.findings`
**Then** the orchestrator marks it `blocking: true` and requests changes

## Scenario: A non-blocking defect does not request changes

**Given** a defect finding with severity Low or Informational
**When** the orchestrator computes the review outcome
**Then** the finding is marked `blocking: false`

## Scenario: An improvement never blocks approval

**Given** any finding categorized as `improvement`
**When** the orchestrator computes the review outcome
**Then** the finding is marked `blocking: false`, regardless of its effort

## Scenario: A simple improvement is eligible for an already-required coder pass

**Given** an improvement finding with `effort: "simple"`
**When** the orchestrator computes the review outcome
**Then** the finding's disposition is `fix-if-coder-cycle` -- eligible to be
implemented during a coder pass a Required item already triggered, never a
reason to start one by itself

## Scenario: A medium improvement requires a human decision

**Given** an improvement finding with `effort: "medium"`
**When** the orchestrator computes the review outcome
**Then** the finding's disposition is `ask-human` and it is flagged
prominently in the rendered review -- a human who agrees it matters leaves a
real REQUEST_CHANGES review, which independently hard-blocks

## Scenario: A complex improvement is deferred

**Given** an improvement finding with `effort: "complex"`
**When** the orchestrator computes the review outcome
**Then** the finding's disposition is `defer` and it is bundled into a
follow-up GitHub issue the orchestrator raises on the reviewer's behalf

## Scenario: The coder obeys the computed blocking status and disposition

**Given** structured review feedback reaches the coder through the review loop
**When** the coder categorizes feedback
**Then** findings marked `blocking: true` are Required, a simple improvement
disposed `fix-if-coder-cycle` is eligible for this pass only, and every other
finding is not required -- the coder never recomputes severity, confidence,
ADR validity, or improvement disposition to reclassify a finding

## Scenario: Review state is deterministic

**Given** structured findings, current human blockers, standards, and ADRs
**When** the review step completes
**Then** the orchestrator computes APPROVE or REQUEST CHANGES without relying
on an advisory model verdict

## Scenario: The reviewer produces one finding per distinct issue and verifies its evidence

**Given** the same defect independently observed through two or more review
lenses
**When** the reviewer produces structured findings
**Then** it appears once, with severity based on technical impact alone, and
its evidence has been re-checked against the diff or PR-head content before
being reported
