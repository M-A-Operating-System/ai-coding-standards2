# Post-promotion hardening review — 2026-10-02

## Context

PR #541 promoted the next-generation target-design architecture to `main`. This review captures the remaining branch-wide findings that should be resolved or explicitly dispositioned now that `main` is the authoritative baseline.

This is not a request to clear the historical backlog. The focus is narrower: controls that affect whether the pipeline can reliably describe, validate, and report its own state.

## Priority findings

### 1. Make merge-conflict reporting fail loud — #539

The confirmed defect is not primarily conflict detection. It is false reporting of side effects: the agent has claimed that a GitHub review/assessment was posted when no post occurred.

Required behavior:

- never claim a GitHub write succeeded unless the write call returned success;
- when required evidence cannot be gathered, return `blocked` with the concrete reason;
- retry denied shell forms only with directly permitted command shapes;
- clean up temporary branches/worktrees created during investigation;
- cover the denied-command/failure path with an eval or deterministic test.

### 2. Finish the executable-contract sweep — #518

`pipeline.json` should remain the authoritative executable lifecycle contract.

After the changes already landed, perform a final sweep for lifecycle behavior encoded only in:

- named-step special cases in the orchestrator;
- generator constants;
- prose descriptions;
- shell-script assumptions;
- hand-maintained retry/back edges.

Executable transitions, retry limits, gates and terminal outcomes should be structurally declared. Renderers and documentation may present the contract but should not invent behavior.

### 3. Enforce generated-artifact freshness — #465

Generated pipeline documentation should be a CI invariant.

A release/main validation path should regenerate or run every supported `--check` mode and fail when committed generated artifacts differ from the authoritative source.

This closes the gap between “generated files are currently correct” and “generated files cannot silently become stale.”

### 4. Keep full-suite validation independent of path filters

#526's underlying test failures are fixed (verified: all 4 affected files pass, 0 failures), but the gap that let them go undetected is not: `test.yml`'s trigger paths (`**/*.py`, `**/*.sh`, `tests/**`, `ruff.toml`) still exclude a `.claude/agents/*.md`-only change, so the same class of drift could recur silently.

For baseline/release validation, run the complete suite unconditionally:

- full pytest suite;
- pipeline/schema validation;
- taxonomy/standards validation;
- generated-file freshness checks;
- `git diff --check`.

Path filters are an optimization for normal PRs, not sufficient evidence for a new baseline.

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
