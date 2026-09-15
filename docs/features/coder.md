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

## Scenario: coder consumes orchestrator-supplied invocation mode

**Given** the orchestrator has dispatched the coder with an invocation mode environment variable (e.g. `AI_AGILE_INVOCATION_MODE`) set to `initial` or `review`
**When** the coder begins its run
**Then** the coder uses that environment variable to determine its operating mode without inspecting `human-review-pending`, `review-cycle:N`, reviewer artefacts, PR existence, branch names, or issue labels

## Scenario: confirmed pre-existing unrelated test failure does not block completion

**Given** a test failure exists after the coder's change, the failure reproduces against the pre-change baseline with one targeted verification, and no file or behaviour touched by the coder's diff is exercised by that failing test
**When** the coder has recorded the failure in `result.json` with baseline verification evidence
**Then** the coder sets `outcome: complete` without further investigation or reverification of that failure in the same invocation
