# Post-promotion hardening review — 2026-10-02

## Context

PR #541 promoted the next-generation target-design architecture to `main`. This review captures the remaining branch-wide findings that should be resolved or explicitly dispositioned now that `main` is the authoritative baseline.

This is not a request to clear the historical backlog. The focus is narrower: controls that affect whether the pipeline can reliably describe, validate, and report its own state.

## Priority findings

### 1. Make review readiness deterministic and commit-bound — #512

The PR reviewer should supply semantic findings; deterministic pipeline logic should decide whether those findings permit the lifecycle to advance.

The release baseline should guarantee that:

- a review cannot report failure while the pipeline records success;
- approval/readiness is bound to the PR head SHA actually reviewed;
- a new commit invalidates a prior review result where appropriate;
- malformed, missing, or internally inconsistent reviewer output fails closed.

This is a state-integrity concern, not a prompt-quality improvement.

### 2. Make merge-conflict reporting fail loud — #539

The confirmed defect is not primarily conflict detection. It is false reporting of side effects: the agent has claimed that a GitHub review/assessment was posted when no post occurred.

Required behavior:

- never claim a GitHub write succeeded unless the write call returned success;
- when required evidence cannot be gathered, return `blocked` with the concrete reason;
- retry denied shell forms only with directly permitted command shapes;
- clean up temporary branches/worktrees created during investigation;
- cover the denied-command/failure path with an eval or deterministic test.

### 3. Finish the executable-contract sweep — #518

`pipeline.json` should remain the authoritative executable lifecycle contract.

After the changes already landed, perform a final sweep for lifecycle behavior encoded only in:

- named-step special cases in the orchestrator;
- generator constants;
- prose descriptions;
- shell-script assumptions;
- hand-maintained retry/back edges.

Executable transitions, retry limits, gates and terminal outcomes should be structurally declared. Renderers and documentation may present the contract but should not invent behavior.

### 4. Enforce generated-artifact freshness — #465

Generated pipeline documentation should be a CI invariant.

A release/main validation path should regenerate or run every supported `--check` mode and fail when committed generated artifacts differ from the authoritative source.

This closes the gap between “generated files are currently correct” and “generated files cannot silently become stale.”

### 5. Keep full-suite validation independent of path filters

#526 demonstrated that prompt-only changes can invalidate conformance tests without necessarily causing the ordinary pytest workflow to run.

For baseline/release validation, run the complete suite unconditionally:

- full pytest suite;
- pipeline/schema validation;
- taxonomy/standards validation;
- generated-file freshness checks;
- `git diff --check`.

Path filters are an optimization for normal PRs, not sufficient evidence for a new baseline.

## Backlog reconciliation

Several open issues may describe defects that have already been superseded or partially fixed by the target-design work. Review at least:

- #510 — reviewer artefact location and coder Mode B feedback;
- #502 / #478 — coder Mode B handling of authoritative review findings;
- #398 — `commit_after` behavior for self-gating agents returning `review`;
- #460 — approval scope/consumption semantics;
- #445 — durable work when an agent exhausts its budget;
- #526 — stale coder conformance tests.

For each issue, verify against current `main`. Close it if current code/tests demonstrably resolve it; otherwise update the issue so its problem statement reflects the new baseline.

The objective is not backlog reduction for its own sake. It is to prevent historical reports from obscuring the actual risk profile of the released architecture.

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

## Release principle carried forward

The quality gate is not “zero open issues.”

The relevant invariant is:

> No known defect should undermine the trustworthiness of lifecycle state, review/approval state, committed work, or the declared executable contract.

Capability expansion — sizing/decomposition enhancements, metrics/reporting, interactive-runner improvements, and similar backlog — can remain independent of this hardening work unless it is required by the currently declared standard-delivery contract.
