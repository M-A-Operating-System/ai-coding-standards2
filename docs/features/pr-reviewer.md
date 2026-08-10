# Feature: Pr Reviewer

## Scenario: A trivially-fixable Low finding forces a fix cycle

**Given** a PR review whose only findings are Low severity, one of which meets the fix-now bar (e.g. a stale comment, an unused import, a broken relative link)
**When** `pr-reviewer` posts its verdict
**Then** the finding is tagged `[fix-now]` and `VERDICT=REQUEST CHANGES`, so `coder` is re-invoked to fix it in this cycle rather than the PR being marked ready with the defect still present

## Scenario: A genuinely subjective Low finding does not block

**Given** a Low finding that is a style preference or requires a judgement call (e.g. "consider renaming this variable for clarity")
**When** `pr-reviewer` posts its verdict
**Then** the finding is tagged `[defer-ok]` and does not force `REQUEST CHANGES` on its own

## Scenario: coder treats a fix-now finding as Required, not Suggested

**Given** a `[fix-now]`-tagged finding reaches `coder` via the review loop
**When** `coder` categorises feedback (Step 10)
**Then** the finding is bucketed as Required (must fix), not Suggested (do not address in code / open a follow-up issue)

## Scenario: No new pipeline machinery is introduced

**Given** the existing `review_loop` (max_cycles, coder re-invoke, ci-gate re-check)
**When** this change lands
**Then** `pipeline.json` and `pipeline_orchestrator.py` are unchanged -- the fix-now mechanism is expressed entirely in `pr-reviewer.md` and `coder.md`'s prompts

## Scenario: Cycle budget is not abused

**Given** a `[fix-now]` finding gets fixed by coder in one cycle
**When** `pr-reviewer` re-reviews
**Then** it does not re-flag the same finding (existing Step 9 consolidation / re-diff behaviour already ensures this), so fix-now-only reviews resolve in one extra cycle in the normal case
