# Post-promotion hardening review — 2026-10-02

## Context

PR #541 promoted the next-generation target-design architecture to `main`. This review captures the remaining branch-wide findings that should be resolved or explicitly dispositioned now that `main` is the authoritative baseline.

This is not a request to clear the historical backlog. The focus is narrower: controls that affect whether the pipeline can reliably describe, validate, and report its own state.

## Priority findings

### 1. Make merge-conflict reporting fail loud — #539 — fixed on this PR

The confirmed defect is not primarily conflict detection. It is false reporting of side effects: the agent has claimed that a GitHub review/assessment was posted when no post occurred.

Root cause, found during the fix: the agent itself never claims the post succeeded — it only ever writes `result.json` (P-10/P-14, PRODUCT.md "What a step must never do"). The false claim was coming from the **orchestrator**: `_post_artefact_if_present` posts the artefact comment on the step's behalf, and silently swallowed any `post_comment` exception with a `log.warning`, letting the step's `review` outcome (and the resulting human gate) proceed regardless of whether the comment ever posted.

Required behavior, and how each is now met:

- never claim a GitHub write succeeded unless the write call returned success — `_post_artefact_if_present` now returns `False` on a failed post; `_run_agent` overrides `sentinel_status` to `failed` when that happens for a `review` outcome with no other durable record (`body_write`), so the step itself fails loud instead of gating on content nobody can see. Scoped narrowly to that case so a `complete` step's best-effort FYI comment, and a `review` step that also wrote a body (e.g. prd-writer), keep the existing swallow-and-continue behavior (`tests/test_step_result.py::test_swallows_post_comment_exception`).
- when required evidence cannot be gathered, return `blocked` with the concrete reason — added to `merge-conflict.md` directly: a denied command or an unrecoverable `git`/`gh` failure now writes `outcome: "blocked"` with the concrete command and reason, rather than guessing.
- retry denied shell forms only with directly permitted command shapes — same addition: at most one retry, only with a directly permitted equivalent shape, never the identical denied form.
- clean up temporary branches/worktrees created during investigation — Steps 2 and 3's cleanup is now an `EXIT` trap registered before either scratch branch (`_rebase_attempt`, `_conflict_assess`) is created, so a denied or failing command anywhere in the block still restores the original branch and removes the scratch branch; Step 3's checkout also switched `-b` to `-B` so a branch stranded by an earlier interrupted run can no longer make the checkout fail silently and merge onto the wrong branch.
- cover the denied-command/failure path with an eval or deterministic test — the orchestrator-level fix is covered by new deterministic tests in `tests/test_step_result.py` (`TestPostArtefactIfPresent`, `TestReviewOutcomeNeedsItsPostedArtefact`); the agent-prompt-level denied-command/blocked guidance is instructional text, not independently testable the same way.

**Second pass, after PR review of the first implementation:**

- `_post_artefact_if_present` returned `True` (vacuously) when a step produced no `output` at all, so a `review` outcome with no `body_write` *and* no `output` still passed through with nothing posted and no failure -- the same integrity gap #539 was fixing, just without a thrown exception. Replaced the override's condition with `_review_outcome_lacks_durable_artefact(step_result, posted_ok)`, which requires an actual durable record -- `body_write`, or `output` that was both present and successfully posted -- not merely that a posting attempt (if any) didn't raise. Covered by `TestReviewOutcomeLacksDurableArtefact`, including the exact missing-output case.
- That stricter check can now also fire for a `commit_after` step that completed real file edits and returned `review` with nothing else to show -- the `commit_after` push gate (issue #429) was keyed on `final_status`, so it would have silently discarded those commits instead of just failing the gate. Fixed by keying that one check on the step's own declared outcome (`step_result.outcome`) instead of the overridden `final_status`: the push still happens (real work is still real work), the step still fails loud (no blind approval).
- `merge-conflict.md` still instructed the exact leading-variable-assignment shapes (`VAR=$(gh api ...)`, `VAR=$(git ...)`) that issue #539 itself records as denied in real runs, relying on the generic recovery instruction to paper over it rather than making the happy path directly executable. Every such assignment in the prompt now runs the command on its own line with output redirected to a file, then loads it with `read -r VAR <file` -- never an assignment-first line.
- Step 1's unknown-after-retry fallback (returns `complete` and advances) contradicted the new general "return blocked when evidence can't be gathered" rule. Resolved by making the exception explicit in the prompt: GitHub's own async computation having no answer yet is not a denied command or a recoverable failure, so it isn't a case the general rule overrides.
- Step 5's result summary said the agent "posted" the resolution plan, even though the entire point of this fix is that the agent never owns that post. Reworded to say it wrote the plan in `output` for the orchestrator to post.
- The `EXIT` trap cleanup in Steps 2 and 3 only protects commands run in the same shell process; the prompt's own "retry with split commands" guidance could have led the agent to split a block's commands across multiple Bash invocations, stranding the trap's cleanup. Added an explicit instruction: each of these two steps' blocks runs as one Bash invocation from fetch to cleanup, and if an individual command inside one must be retried, the retry stays in the same invocation, or the agent manually performs the trap's cleanup before writing `blocked`.

### 2. Finish the executable-contract sweep — #518

`pipeline.json` should remain the authoritative executable lifecycle contract.

After the changes already landed, perform a final sweep for lifecycle behavior encoded only in:

- named-step special cases in the orchestrator;
- generator constants;
- prose descriptions;
- shell-script assumptions;
- hand-maintained retry/back edges.

Executable transitions, retry limits, gates and terminal outcomes should be structurally declared. Renderers and documentation may present the contract but should not invent behavior.

### 3. Enforce generated-artifact freshness — #465 — fixed on this PR

Generated pipeline documentation should be a CI invariant.

A release/main validation path should regenerate or run every supported `--check` mode and fail when committed generated artifacts differ from the authoritative source.

This closes the gap between "generated files are currently correct" and "generated files cannot silently become stale."

Added a `generated-artifacts-freshness` job: `generate_docs.py --check`, `generate_phase_mermaid.py --check`, and `generate_schema_reference.py --check`; `generate_slash_commands.py` has no `--check` mode, so it runs in write mode followed by `git diff --check` (conflict markers/whitespace) and `git diff --exit-code` (anything differs). Verified clean against current `main` before landing.

**Second pass, after PR review of the first implementation:** that job was first added inside `validate-pipeline.yml`, which still carries a `pull_request.paths` filter -- so on a PR, the whole workflow (this job included) was skipped unless the diff touched one of `validate.py`'s own narrow paths, exactly the gap finding 4 below is about. Moved to its own workflow, `generated-artifacts-freshness.yml`, with no `paths:` filter on either its `pull_request` or `push: branches: [main]` trigger, so it runs unconditionally on every PR as well as every push to main.

### 4. Keep full-suite validation independent of path filters — fixed on this PR

#526's underlying test failures are fixed (verified: all 4 affected files pass, 0 failures), but the gap that let them go undetected is not: `test.yml`'s trigger paths (`**/*.py`, `**/*.sh`, `tests/**`, `ruff.toml`) still exclude a `.claude/agents/*.md`-only change, so the same class of drift could recur silently.

For baseline/release validation, run the complete suite unconditionally:

- full pytest suite;
- pipeline/schema validation;
- taxonomy/standards validation;
- generated-file freshness checks;
- `git diff --check`.

Path filters are an optimization for normal PRs, not sufficient evidence for a new baseline.

`test.yml` and `validate-pipeline.yml`'s `push: branches: [main]` triggers no longer carry a `paths:` filter — a push to main now always runs pytest (including the existing real-directory taxonomy/standards integration tests), the shell tests, lint, and pipeline/schema validation, regardless of which files changed. `generated-artifacts-freshness.yml` (finding 3, second pass) has no `paths:` filter on either trigger at all. PR triggers on `test.yml`/`validate-pipeline.yml` keep their path filters as a fast-feedback optimization, per the principle stated above.

### 5. Stale feature-branch references left by the promotion — fixed on this PR

Flagged during PR review of the first implementation: `docs/product/orchestrator/PRODUCT.md` still described the target design as tracked against the (now-merged) `feature/393-orchestrator-target-design` integration branch, and `docs/features/orchestrator.md`'s PR-auto-targeting Gherkin scenario used that same branch name as its literal example `naming.base` value. `main` is now the authoritative implementation (#541), so PRODUCT.md's reference was simply stale; the Gherkin example was changed to a generic illustrative branch name so a historical integration branch isn't baked into the product contract's acceptance criteria.

## Backlog reconciliation

Each candidate was verified directly against current `main` (code/tests, not issue cross-references) and dispositioned on 2026-10-02:

**Closed — confirmed resolved on `main`:**

- #512 — `outcome_policy: {kind: "review_findings", require_head_match: true}` on the pr-reviewer step, `pipeline/review_outcome.py`'s `derive_review_verdict`, and `PR_HEAD_SHA` comparison are all implemented, with inline comments citing this issue by Part number. This had been listed as the #1 release blocker in both #541 and this review before verification — the implementation predates both.
- #510 — both `coder.md` Step 7 and `pr-reviewer.md`'s own prior-artefact lookup query `issues/$ISSUE_NUMBER/comments`, not `$PR_NUMBER`.
- #502 — `coder.md` MODE B Step 7 opens with "This is the first action Mode B takes. Read the review feedback before running `git log`, `git status`, `git diff`, tests...", matching the issue's acceptance criteria verbatim.
- #398 — `commit_after` now fires on `final_status in (STATUS_COMPLETE, STATUS_REVIEW)`, not only `COMPLETE`.
- #445 — `_apply_exhausted`, `_salvage_exhausted_worktree`, and the `{agent}:exhausted-partial` label are all implemented.
- #526 — ran the 4 affected test files directly: 63 passed, 0 failures.

**Still genuinely open:**

- #460 — `dependencies_complete` (the function the issue quotes, since renamed) still checks raw label presence (`dep.human_gate_label not in labels`); the gate-consumption/subject-recording redesign it asks for has not landed.

**Ambiguous — not dispositioned, needs its own look:**

- #478 — the #502 fix (mandatory-first-action framing in Mode B) substantially reduces the odds of the anchoring symptom #478 describes, but none of #478's own proposed structural fixes (fresh session per Mode B invocation, forced retry on a zero-commit no-op) have landed, and no dedicated regression test for the anchoring mechanism itself exists. Closing #502 does not by itself resolve #478.
- #518 — too broad/qualitative (a repo-wide sweep for lifecycle behavior encoded outside `pipeline.json`) to verify as done/not-done in one pass; left open pending a dedicated audit.

The objective is not backlog reduction for its own sake. It is to prevent historical reports from obscuring the actual risk profile of the released architecture — which cuts both ways: #460 is real and should not be lost among items that already shipped.

**Scoping decision for this PR's direct fixes:** #539, #465, and finding 4 (above) were fixed directly on this branch — each was a concrete, boundable defect with a clear acceptance criterion. #460, #478, and #518 were deliberately left for a separate pass instead of an ad hoc fix here:

- #460's own issue body defers the gate-consumption/subject-recording redesign to "the PRD" — a substantial architecture change, not a direct-fix task.
- #478's own issue body says it is "not prescriptive -- prd-writer/design should evaluate," for the same reason.
- #518 is a repo-wide qualitative sweep (see finding 2) that needs its own dedicated audit, not a one-pass fix bundled into hardening cleanup.

## Operational verification

Run one representative standard-delivery flow against current `main` that includes a real review/retry cycle, not only the happy path.

Verify underlying GitHub state directly at each important boundary:

1. issue classification and PRD state;
2. approval/gate state;
3. coder commits and pushed PR head;
4. reviewer findings and the exact reviewed SHA;
5. CI-gate result;
6. retry/fix cycle;
7. merge/closure state.

Step result text is not itself proof that a side effect occurred.

This was substantially exercised while driving issue #519 through `standard-delivery` on 2026-09-30/10-01: multiple real review/retry cycles, a genuine CI failure caught and fixed, gate approvals relayed, and GitHub state (reviews, comments, PR head SHA, mergeable state) verified directly at each boundary rather than trusting step-result text. That verification is specifically what surfaced #539 — the `merge-conflict` step claiming a review was posted when nothing had been.

## Release principle carried forward

The quality gate is not “zero open issues.”

The relevant invariant is:

> No known defect should undermine the trustworthiness of lifecycle state, review/approval state, committed work, or the declared executable contract.

Capability expansion — sizing/decomposition enhancements, metrics/reporting, interactive-runner improvements, and similar backlog — can remain independent of this hardening work unless it is required by the currently declared standard-delivery contract.
