# Roadmap

This document describes the MVP scope of AI Agile, the agent merges that reduce
complexity for the initial rollout, and the phased plan to reach the full design
described in the rest of these docs.

---

## MVP scope

The MVP covers Phases 1–7 of the per-ticket pipeline only. It does not include
the continuous meta-loop phases (8, 9, 10), and it defers several agents and
gates that require the pipeline to be stable with real tickets before they can
be tuned effectively.

### What ships in MVP

All seven per-ticket phases (product docs through evaluate), with the agent
merges described below applied. The pipeline can take a ticket from a GitHub
issue to a merged PR and a retrospective, with human gates at each step.

### Explicit non-goals for MVP

| Out of scope | Reason |
|---|---|
| Phase 8 (Learn) | Requires audit log with ≥ 50 closed tickets to mine meaningfully |
| Phase 9 (Gap assessment) | Requires multiple shipped product surfaces before drift is detectable |
| Phase 10 (Tech debt) | Requires codebase mass and history for structural metrics |
| `security-review:approved` gate (Persona 5) | Deferred until gate set is stable; Security Owner persona is defined but not gated in MVP |
| `data-migration:approved` gate (Persona 6) | Deferred until gate set is stable; Data Owner persona is defined but not gated in MVP |
| `super-issue-grouper` agent | Humans manually group small tickets for MVP |
| XL `issue-decomposer` agent | Humans manually decompose XL tickets for MVP |
| Phase 8 prompt mutation | Agent prompts are edited manually by the standards owner in MVP |
| Cross-issue concurrency cap enforcement | Manual for MVP; the risk is accepted |
| Per-agent cost/budget hard limits | Tracked aspirationally; not enforced by the orchestrator in MVP |
| Comment-edit auditing | Audit log captures label events; comment edits are not snapshotted in MVP |
| GitHub App bot identity | A PAT is acceptable for MVP; see prerequisite below |

### Agent identity prerequisite

The GitHub App (or bot account) must be resolved before any production claim.
`actor.kind` in the audit log is self-attested until then: the orchestrator
records who it believes is acting, but the identity is not cryptographically
tied to a verified app installation. This is a **go/no-go condition for
production**, not a nice-to-have.

---

## Agent merges for MVP

The full design defines 22 agents. For MVP, four merges reduce that to
approximately 14, eliminating agents whose logic is simple enough to fold into
an adjacent agent without losing the separation of concerns that matters.

| Merge | Result | Gate |
|---|---|---|
| `dependency-planner` + `task-decomposer` → `task-decomposer` | Single agent posts the child task list and the dependency order in one comment | `plan:approved` |
| `coverage-enforcer` → `test-runner` | Single agent posts test results and coverage delta in one comment | `coverage:approved` |
| `adr-proposer` → `architect` | ADR logic runs as the last step of the architect's work | No separate gate |
| `product-standards-checker` → `prd-writer` | Standards check runs inline; violations appear in the PRD comment | `prd:approved` |

### Detail

**`task-decomposer` absorbs `dependency-planner`.** The merged agent produces
both the ordered child task list and the critical-path dependency order. Nothing
is lost — the output is richer than `task-decomposer` alone and identical in
shape to what `dependency-planner` would have produced separately. The single
agent posts both in one comment. Gate: `plan:approved`.

**`test-runner` absorbs `coverage-enforcer`.** The merged agent runs the test
suite and computes the coverage delta in one pass, then posts both in one
comment. The `coverage:approved` gate applies to the combined output. A single
rejection-and-rerun cycle covers both concerns.

**`architect` runs `adr-proposer` logic inline.** At the end of its work, the
architect evaluates whether any decision in the design is ADR-worthy. If no ADR
is needed, it notes this explicitly. If ADRs are needed, it drafts stubs in the
same design comment. The stubs are reviewed as part of `design:approved`. There
is no separate `adr-proposer:review` gate.

**`prd-writer` runs `product-standards-checker` inline.** Violations of
product-layer standards are noted directly in the PRD comment and must be
resolved before the stakeholder applies `prd:approved`. The checker does not
post a separate comment or require a separate label.

---

## Phase rollout

The pipeline is delivered in four phases. Each phase is a superset of the
previous; nothing from an earlier phase is removed when the next phase is added.

### Phase 0 — Skeleton (current state)

The orchestrator Python skeleton and `pipeline.json` exist. Agents are not yet
running. This is the baseline from which Phase 1 is built.

### Phase 1 — Core loop

**Covers.** Per-ticket phases 1–5 (product docs through execute).

**Agents.** `issue-classifier`, `prd-writer` (with `product-standards-checker`
merged in), `ticket-sizer`, `architect` (with `adr-proposer` merged in),
`task-decomposer` (with `dependency-planner` merged in), `coder`,
`standards-compliance-reviewer`, `pr-reviewer`.

**Gates.** `prd:approved`, `size:approved`, `design:approved`, `plan:approved`,
`pr:approved`.

**Goal.** A ticket can flow from a GitHub issue to a merged PR with a human
gate at each step. No test generation or retrospective yet.

**Acceptance criterion.** Five real tickets have shipped through the full
Phase 1 loop with no critical `:failed` events requiring manual orchestrator
intervention.

### Phase 2 — Quality layer

**Covers.** Per-ticket phases 3 and 6 (testing spec and test).

**Adds.** `test-spec-writer`, `test-coverage-auditor`, `test-writer`,
`test-runner` (with `coverage-enforcer` merged in), `migration-validator`.

**Gates added.** `test-spec:approved`, `coverage:approved`.

**Goal.** Tests are generated from acceptance criteria and enforced; SQL
migrations are validated before merge.

**Acceptance criteria.**

- The coverage gate blocks at least one real PR (demonstrates the gate is
  live, not bypassed).
- `migration-validator` blocks at least one real migration with a violation.

### Phase 3 — Close the loop

**Covers.** Per-ticket phase 7 (evaluate) and standards evolution.

**Adds.** `release-noter`, `retrospective-writer`, `standards-evolver`.

**Gates added.** `standards-proposal:approved`.

**Goal.** Every ticket produces a changelog entry and a retrospective. Recurring
patterns in retrospectives are surfaced as standards proposals and, after
approval, become new or updated standards.

**Acceptance criterion.** The standards have been updated at least twice as a
direct result of retrospective findings processed by `standards-evolver`.

### Phase 4 — Continuous phases

**Covers.** Phases 8, 9, and 10 (Learn, Gap assessment, Tech debt).

**Adds.** `metrics-aggregator`, `pipeline-tuner`, `prompt-tuner`,
`knowledge-curator`, `process-reviewer` (Phase 8); `gap-assessor`,
`vision-aligner`, `gap-curator` (Phase 9); `debt-finder`, `adr-revisitor`,
`debt-curator` (Phase 10).

**Prerequisite.** Phase 3 has been stable for at least one quarter and the
audit log contains at least 50 closed tickets. These phases mine data; without
sufficient history the output is noise.

---

## Deferral criteria

A phase must meet the following bar before the next phase is added:

1. At least five real tickets have run through the phase end-to-end.
2. No critical `:failed` events in those tickets required manual orchestrator
   intervention (i.e., no cases where a human had to directly manipulate the
   orchestrator state to unblock a ticket).
3. Gate dwell times are measured and understood (no gates being rubber-stamped
   in under a minute or held open for more than a week without a recorded
   reason).

These criteria apply at each transition: Phase 0 → 1, 1 → 2, 2 → 3, and 3 → 4.
Phase 4's additional prerequisite (one quarter of Phase 3 stability, 50 closed
tickets) is additive, not a replacement.

---

## Relationship to the full design

The rest of these docs describe the **target state** — all ten phases, all
22 agents, all personas including Security Owner and Data Owner gates. This
roadmap describes how to get there incrementally. Nothing in the target-state
docs is retracted; the MVP simply defers parts of it. When a deferred item is
implemented it is added to `pipeline.json` following the normal change process
described in [`05-pipeline-config.md`](05-pipeline-config.md).
