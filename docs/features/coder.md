# Feature: Coder

## Scenario: A genuine first dispatch runs Mode A even though the dispatch-time counter is non-zero

**Given** `coder` is dispatched for the first time on an issue (no prior `coder:complete`/`coder:failed`, no pr-reviewer artefact, no human REQUEST_CHANGES)
**When** `coder` runs Step 0
**Then** it detects Mode A (initial build) regardless of whether `review-cycle:1` has already been applied by dispatch-time bookkeeping

## Scenario: A genuine re-invocation after review feedback still runs Mode B

**Given** `pr-reviewer` posted REQUEST CHANGES (or a human left an unresolved REQUEST_CHANGES review) and the orchestrator re-invokes `coder` per `review_loop`
**When** `coder` runs Step 0
**Then** it detects Mode B and reads the actual feedback to address

## Scenario: max_cycles enforcement is unaffected

**Given** `pr-reviewer` requests changes 3 times in a row (the configured `max_cycles`)
**When** the review loop runs its course
**Then** the cycle limit still triggers human sign-off at the same point it does today -- the fix does not silently loosen or tighten `max_cycles`
