# Roadmap

This document describes the MVP scope of AI Agile, the agent merges that reduce
complexity for the initial rollout, and the phased plan to reach the full design
described in the rest of these docs.

---

## MVP scope

The MVP covers the per-ticket lifecycle phases (1–4) only. It does not include
the continuous phase (5) with its meta-loops, and it defers several agents and
gates that require the pipeline to be stable with real tickets before they can
be tuned effectively.

### What ships in MVP

All four per-ticket phases (product docs through evaluate), with the agent
merges described below applied. The pipeline can take a ticket from a GitHub
issue to a merged PR and a retrospective, with human gates at each step.

### Explicit non-goals for MVP

| Out of scope | Reason |
|---|---|
| Learn loop (`05_continuous`) | Requires audit log with ≥ 50 closed tickets to mine meaningfully |
| Gap-assessment loop (`05_continuous`) | Requires multiple shipped product surfaces before drift is detectable |
| Tech-debt loop (`05_continuous`) | Requires codebase mass and history for structural metrics |
| `security-review:approved` gate (Persona 5) | Deferred until gate set is stable; Security Owner persona is defined but not gated in MVP |
| `data-migration:approved` gate (Persona 6) | Deferred until gate set is stable; Data Owner persona is defined but not gated in MVP |
| `super-issue-grouper` agent | Humans manually group small tickets for MVP |
| XL `issue-decomposer` agent | Humans manually decompose XL tickets for MVP |
| Prompt mutation (Learn loop) | Agent prompts are edited manually by the standards owner in MVP |
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
| `product-standards-checker` → `prd-writer` | Standards check runs inline; violations appear in the PRD comment | `01_product_docs/prd-writer:approved` |

Each merge folds a simple agent into an adjacent one and routes both outputs
through the surviving agent's gate; no separation of concerns that matters is
lost.

---

## Phase rollout

The pipeline is delivered in four phases. Each phase is a superset of the
previous; nothing from an earlier phase is removed when the next phase is added.

> **Status note.** The shipped pipeline has diverged from the agent names and
> phase numbering planned below. The live system runs phases `01_product_docs`,
> `03_execute`, and `00_ondemand` (issue-classifier, prd-writer, create-pr,
> prd-docs-updater, coder, ci-gate, merge-conflict, pr-reviewer, plus the
> on-demand agents). The phase plan here is retained as the original direction;
> `pipeline/pipeline.json` and the generated views are authoritative for what
> actually exists.

### Phase 0 — Skeleton

The orchestrator Python skeleton and `pipeline.json` exist. This was the
baseline from which the core loop was built.

### Phase 1 — Core loop

**Covers.** Per-ticket lifecycle phases 1–3 (product docs through execute,
excluding test generation).

**Agents.** `issue-classifier`, `prd-writer` (with `product-standards-checker`
merged in), `ticket-sizer`, `architect` (with `adr-proposer` merged in),
`task-decomposer` (with `dependency-planner` merged in), `coder`,
`standards-compliance-reviewer`, `pr-reviewer`.

**Gates.** `01_product_docs/prd-writer:approved`, `size:approved`, `design:approved`, `plan:approved`,
`pr:approved`.

**Goal.** A ticket can flow from a GitHub issue to a merged PR with a human
gate at each step. No test generation or retrospective yet.

**Acceptance criterion.** Five real tickets have shipped through the full
Phase 1 loop with no critical `:failed` events requiring manual orchestrator
intervention.

### Phase 2 — Quality layer

**Covers.** The testing-spec artefact of the Design phase (2) and the test
half of the Execute phase (3).

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

**Covers.** Per-ticket lifecycle phase 4 (evaluate) and standards evolution.

**Adds.** `release-noter`, `retrospective-writer`, `standards-evolver`.

**Gates added.** `standards-proposal:approved`.

**Goal.** Every ticket produces a changelog entry and a retrospective. Recurring
patterns in retrospectives are surfaced as standards proposals and, after
approval, become new or updated standards.

**Acceptance criterion.** The standards have been updated at least twice as a
direct result of retrospective findings processed by `standards-evolver`.

### Phase 4 — Continuous phases

**Covers.** Lifecycle phase 5 (`05_continuous`) — the Learn,
Gap-assessment, and Tech-debt loops.

**Adds.** `metrics-aggregator`, `pipeline-tuner`, `prompt-tuner`,
`knowledge-curator`, `process-reviewer` (Learn loop); `gap-assessor`,
`vision-aligner`, `gap-curator` (Gap-assessment loop); `debt-finder`,
`adr-revisitor`, `debt-curator` (Tech-debt loop).

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

The rest of these docs describe the **target state** — all five lifecycle
phases, all 22 agents, all personas including Security Owner and Data Owner
gates. This
roadmap describes how to get there incrementally. Nothing in the target-state
docs is retracted; the MVP simply defers parts of it. When a deferred item is
implemented it is added to `pipeline.json` following the normal change process.
