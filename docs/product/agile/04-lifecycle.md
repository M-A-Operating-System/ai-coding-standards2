# Lifecycle

Every change passes through seven per-ticket phases. An eighth phase
runs continuously across all tickets to learn from the pipeline itself.
Each phase has clearly defined inputs, outputs, agents, and (where
applicable) a human gate.

This document describes the phases conceptually. The authoritative list
of agents per phase, their dependencies, triggers, and gates lives in
[`ai-agile/pipeline/pipeline.json`](../../../ai-agile/pipeline/pipeline.json)
and is rendered at:

- [`generated/phases.md`](generated/phases.md) — agents per phase
- [`generated/agents.md`](generated/agents.md) — full agent catalogue
- [`generated/pipeline.mmd`](generated/pipeline.mmd) — full mermaid flow

If anything in the prose below disagrees with the generated views, the
generated views are correct. See [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated).

---

## The eight phases

Phases 1–7 run per ticket, in order. Phase 8 runs continuously across
all tickets, mining the audit log to improve the pipeline itself.

| # | Phase | Cadence | Purpose | Primary artefact |
|---|---|---|---|---|
| 1 | Product docs | Per ticket | Establish what is being built and whether it fits | PRD + sized ticket + dependency map |
| 2 | Technical docs | Per ticket | Establish how it will be built | Technical design + ADR drafts |
| 3 | Testing spec | Per ticket | Establish what "done" means | Numbered Gherkin scenarios |
| 4 | Build plan | Per ticket | Establish the order of work | Ordered child task list |
| 5 | Execute | Per ticket | Build it | One PR (draft from first commit, per [P-13](02-principles.md#p-13--draft-prs-early-one-branch-per-pr)) |
| 6 | Test | Per ticket | Verify it | Tests, coverage report |
| 7 | Evaluate | Per ticket | Record what shipped and reflect on this ticket | Changelog, per-ticket retrospective, targeted standards proposals |
| 8 | Learn | Continuous | Improve the pipeline itself from accumulated experience | Pipeline metrics, pipeline-graph proposals, agent-prompt tuning proposals, knowledge artefacts |

Each per-ticket phase produces an artefact that is the input to the
next. Skipping a phase is not supported — the orchestrator will not
invoke a downstream agent until its declared dependencies are
satisfied. Phase 8 does not block any per-ticket flow; it operates
independently on the audit log.

---

## How the pipeline advances

A single, deterministic, **Python-based orchestrator** has the sole
responsibility for reacting to events and deciding which agent can
work on what next. It is the only component permitted to:

- Read pipeline state (labels, session comments, PR metadata).
- Translate raw GitHub events into the semantic event vocabulary
  (`issue.labeled`, `pr.draft_opened`, `agent.complete`, …).
- Evaluate the dependency graph in
  [`ai-agile/pipeline/pipeline.json`](../../../ai-agile/pipeline/pipeline.json)
  and decide which agent is eligible.
- Acquire the `:wip` mutex (see [P-4](02-principles.md#p-4--wip-is-the-mutex)).
- Invoke an agent.
- Append events to the audit log branch
  (see [`08-audit-log.md`](08-audit-log.md)).

Two design properties are enforced because the orchestrator is the
only decider:

- **Deterministic routing.** Given the same labels, the same
  `pipeline.json`, and the same session state, the orchestrator
  always reaches the same decision about who runs next. No LLM is in
  the routing path. Routing is unit-testable Python.
- **Single source of authority.** Agents do not invoke other agents.
  Agents do not read the dependency graph. Agents do their one job
  and report status. The orchestrator decides what happens next.

The orchestrator is invoked on three triggers:

1. **Label events.** Any time a label is added or removed on an issue
   or PR, the orchestrator re-evaluates eligibility.
2. **PR events.** PR opened, synchronised, ready-for-review, merged,
   closed.
3. **Schedule.** Every 15 minutes during working hours, as a backstop.

For each work item it:

1. Reads the current label set.
2. For each agent, checks whether (a) the trigger condition is satisfied,
   (b) every dependency has applied its `:complete` label, and (c) every
   required human gate label is present.
3. If yes, acquires the `:wip` mutex (see [P-4](02-principles.md#p-4--wip-is-the-mutex))
   and invokes the agent.
4. The agent does its work and applies exactly one terminal status
   (`:complete`, `:review`, or `:blocked`) via `status.sh`.
5. If the agent crashed without setting a status, the orchestrator
   applies `:failed` and posts a comment.

A halted pipeline (`review`, `blocked`, `failed`) resumes the moment a
human removes the offending label. There is no separate "retry" button.

Every transition emits one event to the audit log branch
(see [`08-audit-log.md`](08-audit-log.md)).

In the **Execute** phase the `coder` opens a draft PR on its first
commit, not after the work is complete. PR-side agent sessions
(`standards-compliance-reviewer`, `migration-validator`,
`pr-reviewer`) start running as soon as the draft exists and continue
as new commits land. The coder marks the PR ready-for-review only when
all child tasks are done; this triggers the `pr-reviewer` gate flow.
See [P-13](02-principles.md#p-13--draft-prs-early-one-branch-per-pr).

---

## Forks in the path

Two cases interrupt the linear flow:

### The ticket is too big

If `ticket-sizer` returns `XL`, the parent issue does not advance. The
human breaks the parent into child tickets; each child re-enters the
pipeline at `issue-classifier`. The parent waits and rolls up the
children for retrospective purposes.

### Many small tickets in a window

If `ticket-sizer` returns `S` and the issue is the Nth small bug or
chore in a configured window, the orchestrator suggests grouping under
a super-issue before sizing completes. On approval the super-issue
becomes the shippable unit
(see [P-5](02-principles.md#p-5--one-shippable-unit-one-pr)): it runs
through the full pipeline as a single unit, the grouped children pause
their own pipelines and attach, and one PR closes the super-issue and
all its children on merge. See
[P-6](02-principles.md#p-6--group-small-work-under-a-super-issue).

### SQL changes

When the `coder` opens a PR that touches `**/*.sql`, the
`migration-validator` runs in addition to the standard reviewers. Merge
is blocked on naming, RLS, and type violations regardless of the standard
review path.

---

## End-to-end happy path

A typical small ticket flows like this:

| Time | Event |
|---|---|
| T+0 | Stakeholder opens issue |
| T+2m | `issue-classifier` validates required fields |
| T+5m | `prd-writer` posts PRD; requests review |
| T+1h | Stakeholder approves; applies `prd:approved` |
| T+5m | Product-docs phase finishes; `ticket-sizer` posts size; requests review |
| T+30m | Engineer applies `size:approved` |
| T+15m | `architect` posts technical design; requests review |
| T+1h | Engineer applies `design:approved` |
| T+10m | Testing-spec phase runs; requests review |
| T+30m | Engineer applies `test-spec:approved` |
| T+10m | Build-plan phase runs; requests review |
| T+15m | Engineer applies `plan:approved` |
| T+30m | `coder` opens PR; reviewers run; requests PR review |
| T+1h | Engineer applies `pr:approved` |
| T+10m | Test phase runs; requests review |
| T+15m | Engineer applies `coverage:approved`; PR is merged |
| T+5m | `release-noter` opens changelog PR, closes child issues |
| T+5m | `retrospective-writer` posts retrospective on parent issue |
| Weekly | `standards-evolver` reviews retrospectives, drafts proposals |

Total wall-clock human time: minutes. Total elapsed time: hours.

---

## Phase 8 — Learn

Phase 8 is a continuously running meta-loop, not a per-ticket step. It
treats the audit log branch (see [`08-audit-log.md`](08-audit-log.md))
and the corpus of closed retrospectives as its primary inputs and
proposes improvements to the pipeline itself.

**Distinction from Phase 7.** Phase 7 closes one ticket: it writes the
changelog, records a per-ticket retrospective, and feeds targeted
standards proposals. Phase 8 looks across many tickets to find systemic
patterns and tune the system that produced them.

| Concern | Phase 7 (Evaluate) | Phase 8 (Learn) |
|---|---|---|
| Scope | One ticket | All tickets in a window |
| Cadence | On PR merge / issue close | Continuous: daily metrics, weekly tuning |
| Output | Changelog, retrospective, standards proposals | Pipeline metrics, pipeline-graph proposals, prompt tuning, knowledge artefacts |
| Changes | Standards (`ai-agile/standards/*.json`) | The pipeline itself (`pipeline.json`, agent prompts, schedules) |

**Agents (proposed; added to `pipeline.json` as Phase-8 agents).**

- **`metrics-aggregator`** — runs daily. Reads the audit log and
  computes cycle time per phase, gate dwell time per gate, agent
  duration distributions, rejection rates, blocked/failed counts.
  Writes a metrics report to `docs/product/agile/generated/metrics/`
  (per [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated)).
- **`pipeline-tuner`** — runs monthly. Looks at the metrics for
  systemic patterns: agents that consistently exceed timeout,
  dependencies that always halt, gates that are rubber-stamped,
  trigger schedules that miss work. Drafts proposals as PRs against
  `pipeline.json` for standards-owner review.
- **`prompt-tuner`** — runs monthly. For each agent, examines
  rejection rates and the diff between the agent's first draft and
  the human-approved version. Drafts targeted edits to the agent's
  prompt at `.github/agents/{agent}.md` as PRs.
- **`knowledge-curator`** — runs weekly. Identifies tickets whose
  outcomes contain reusable patterns (a recurring incident shape, a
  novel architecture choice, a useful test pattern) and drafts
  knowledge artefacts (runbooks, templates, teaching examples)
  into `docs/learnings/`.
- **`process-reviewer`** — runs quarterly. Reads the principles
  ([`02-principles.md`](02-principles.md)), the vision
  ([`01-vision.md`](01-vision.md)), the metrics produced by
  `metrics-aggregator`, and the corpus of closed retrospectives.
  Produces a holistic assessment: are we still honoring our own
  principles, is the system serving its personas, and where has
  practice drifted from intent? Drafts *coordinated* change proposals
  that span the pipeline graph, agent prompts, standards, and docs —
  not single-component edits. May also propose changes to the
  principles themselves (rare; requires an ADR).
  Distinct from `prompt-tuner`: that agent does narrow, one-agent-at-a-time
  tactical tuning. `process-reviewer` does strategic, multi-component
  review.

**Human gates.**

- **`pipeline-change:approved`** (proposed) — standards owner
  approves any change to `pipeline.json` proposed by `pipeline-tuner`.
- **`prompt-change:approved`** (proposed) — agent owner approves
  any change to an agent prompt proposed by `prompt-tuner`.
- **`process-review:approved`** (proposed) — standards owner *and*
  a principal stakeholder approve any coordinated change proposed by
  `process-reviewer`. The dual approval reflects the cross-cutting
  nature of these changes.
- Changes from `knowledge-curator` follow normal PR review.

**Why Phase 8 is its own phase.**

- Per-ticket retrospectives surface ticket-shaped lessons.
  Cross-ticket meta-analysis surfaces system-shaped lessons. They
  use different inputs and produce different outputs.
- Changes in Phase 8 affect *all future tickets*, so they need
  higher review bars than per-ticket standards changes.
- Separating Phase 8 lets us scale the cadence: daily metrics,
  weekly knowledge curation, monthly tuning — without entangling
  with the per-ticket lifecycle.

Phase 8 implementation is deferred until the per-ticket pipeline
(Phases 1–7) is running steadily and the audit log has accumulated
enough data to mine. The phase is declared here so the system is
designed for it from the start.
