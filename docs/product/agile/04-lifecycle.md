# Lifecycle

Every change passes through seven per-ticket phases. Three additional
phases run continuously across all tickets — learning from the
pipeline itself, finding gaps between the product design and what
actually shipped, and surfacing tech debt for remediation. Each phase
has clearly defined inputs, outputs, agents, and (where applicable) a
human gate.

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

## The ten phases

Phases 1–7 run per ticket, in order. Phases 8, 9, and 10 run
continuously across all tickets, each mining a different input to
produce a different kind of improvement proposal.

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
| 9 | Gap assessment | Continuous | Find drift between product design (PRDs, vision, principles) and what was actually shipped | Gap-issue proposals, design-vs-implementation reports |
| 10 | Tech debt | Continuous | Surface poor architecture or implementation choices that warrant remediation | Tech-debt issue proposals, remediation roadmaps |

Each per-ticket phase produces an artefact that is the input to the
next. Skipping a phase is not supported — the orchestrator will not
invoke a downstream agent until its declared dependencies are
satisfied. Phases 8, 9, and 10 do not block any per-ticket flow; they
operate independently and feed back into the queue as new issues
(gap-issues, debt-issues) or as proposals against `pipeline.json` and
the standards.

**Why three continuous phases, not one.** They have different inputs,
different cadences, different review bars, and different consumers:

| | Phase 8 (Learn) | Phase 9 (Gap assessment) | Phase 10 (Tech debt) |
|---|---|---|---|
| Inputs | Audit log + retrospectives | PRDs/vision + shipped code | Codebase + ADRs + standards |
| Looks at | The pipeline | The product | The implementation |
| Output | Pipeline/agent improvements | New "fill the gap" issues | New "remediate this" issues |
| Approver | Standards owner | Stakeholder + standards owner | Engineer + standards owner |
| Cadence | Daily / weekly / monthly | Weekly | Weekly |

---

## How the pipeline advances

A single, deterministic, Python-based orchestrator has the sole
responsibility for reacting to events and deciding which agent runs
next. See [P-14](02-principles.md#p-14--deterministic-python-orchestrator-with-sole-routing-authority)
for the full architectural commitment; the rest of this section
describes the operational mechanics.

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

If `ticket-sizer` returns `XL`, the **`issue-decomposer`** agent runs.
It drafts a roadmap of proposed child issues — each a smaller business
outcome — and posts the roadmap as a comment on the parent. A human
approves the decomposition by applying `decomposition:approved`. On
approval, the agent auto-creates the child issues and links them back
to the parent. Each child re-enters the pipeline at `issue-classifier`
and runs through its own full lifecycle. The parent waits and closes
when all children close, with a roll-up retrospective.

This matters most when an issue represents a high-level product
outcome (e.g. "self-service onboarding") that needs to be broken into
a roadmap of smaller business outcomes (email verification, profile
setup, walkthrough), each itself a feature.

Distinct from `task-decomposer` (Phase 4): `task-decomposer` breaks a
*sized* feature into implementation tasks (one file, one concern)
that all ship in one PR. `issue-decomposer` runs *before* sizing
clears, breaking a too-large issue into smaller business-outcome
issues, each of which gets its own PR.

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

A typical small ticket flows like this. The table below reflects the
**full design** with all 22 agents present. The MVP rollout (per
[`10-roadmap.md`](10-roadmap.md)) merges some adjacent agents
(`adr-proposer` into `architect`, `dependency-planner` into
`task-decomposer`, `coverage-enforcer` into `test-runner`,
`product-standards-checker` into `prd-writer`); in MVP the same
phases run, but with fewer named agents.

| Time | Object | Agent | Event | Outcome label |
|---|---|---|---|---|
| T+0 | Issue | Stakeholder | Opens issue | — |
| T+2m | Issue | `product-docs/issue-classifier` | Validates required fields | `product-docs/issue-classifier:complete` |
| T+5m | Issue | `product-docs/prd-writer` | Posts PRD | `product-docs/prd-writer:review` |
| T+1h | Issue | Stakeholder | Approves PRD | `01_product_docs/prd-writer:approved` |
| T+10m | Issue | `product-docs/product-standards-checker`, `product-docs/impact-assessor`, `product-docs/dependency-resolver` | Run in sequence | `product-docs/dependency-resolver:complete` |
| T+5m | Issue | `product-docs/ticket-sizer` | Posts size | `product-docs/ticket-sizer:review` |
| T+30m | Issue | Engineer | Approves size | `size:approved` |
| T+15m | Issue | `technical-docs/architect` | Posts technical design | `technical-docs/architect:review` |
| T+1h | Issue | Engineer | Approves design | `design:approved` |
| T+5m | Issue | `technical-docs/adr-proposer` | Runs (no ADRs needed) | `technical-docs/adr-proposer:complete` |
| T+10m | Issue | `testing-spec/test-spec-writer`, `testing-spec/test-coverage-auditor` | Generate spec and audit coverage | `testing-spec/test-coverage-auditor:review` |
| T+30m | Issue | Engineer | Approves test spec | `test-spec:approved` |
| T+10m | Issue | `build-plan/task-decomposer`, `build-plan/dependency-planner` | Decompose and order child tasks | `build-plan/dependency-planner:review` |
| T+15m | Issue | Engineer | Approves plan | `plan:approved` |
| T+5m | Issue → PR | `execute/coder` | Opens draft PR on first commit | (event) `pr.draft_opened` |
| T+30m | PR | `execute/coder` | Commits per child task; CI runs from commit 1 | (event) `pr.draft_synchronized` |
| T+5m | PR | `execute/coder` | Marks PR ready-for-review | (event) `pr.draft_ready` |
| T+10m | PR | `execute/standards-compliance-reviewer`, `execute/pr-reviewer` | Review against design and standards | `execute/pr-reviewer:review` |
| T+1h | PR | Engineer | Approves PR | `pr:approved` |
| T+10m | PR | `test/test-writer`, `test/test-runner`, `test/coverage-enforcer` | Write tests, run suite, enforce coverage | `test/coverage-enforcer:review` |
| T+15m | PR | Engineer | Approves coverage; PR merges | `coverage:approved` + (event) `pr.merged` |
| T+5m | Issue | `evaluate/release-noter` | Opens changelog PR, closes child issues | `evaluate/release-noter:complete` |
| T+5m | Issue | `evaluate/retrospective-writer` | Posts retrospective | `evaluate/retrospective-writer:complete` |
| Weekly | Issue (all) | `evaluate/standards-evolver` | Reviews retrospectives, drafts proposals | `evaluate/standards-evolver:review` |

The **Agent** column shows the actor for that step. Lower-case
slash-separated names (e.g. `product-docs/prd-writer`) are agents
from [`pipeline.json`](../../../ai-agile/pipeline/pipeline.json),
formatted as `{phase}/{short-name}` (see
[`12-agent-spec.md`](12-agent-spec.md#naming-convention));
capitalised names (e.g. Stakeholder, Engineer) are human personas
from [`03-personas.md`](03-personas.md).

The **Outcome label** column shows the label applied to the object at
the end of that step. `agent:complete` and `agent:review` are agent
status labels (see [`06-status-model.md`](06-status-model.md)); the
plain `*:approved` labels are human gates (see
[`07-human-gates.md`](07-human-gates.md)). Rows marked **(event)** are
GitHub-driven state changes that emit audit-log events but do not
themselves apply a status label.

Total wall-clock human time: minutes. Total elapsed time: hours.

---

## Phases 8–10 — the continuous meta-loops

Phases 8, 9, and 10 are continuously running meta-loops, not per-ticket
steps. Each treats a different corpus as its primary input and produces
a different kind of improvement proposal. None blocks the per-ticket
pipeline; they feed it new issues and proposals.

---

## Phase 8 — Learn

Phase 8 treats the audit log branch
(see [`08-audit-log.md`](08-audit-log.md)) and the corpus of closed
retrospectives as its primary inputs and proposes improvements to the
pipeline itself.

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

**Agents.**

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

- **`pipeline-change:approved`** — standards owner approves any
  change to `pipeline.json` proposed by `pipeline-tuner`.
- **`prompt-change:approved`** — agent owner approves any change to
  an agent prompt proposed by `prompt-tuner`.
- **`process-review:approved`** — standards owner *and* a principal
  stakeholder approve any coordinated change proposed by
  `process-reviewer`. The dual approval reflects the cross-cutting
  nature of these changes.
- Changes from `knowledge-curator` follow normal PR review.

**Why Phase 8 is its own phase.**

- Per-ticket retrospectives surface ticket-shaped lessons.
  Cross-ticket meta-analysis surfaces system-shaped lessons. They
  use different inputs and produce different outputs.
- Changes in Phase 8 affect all subsequent tickets, so they need
  higher review bars than per-ticket standards changes.
- Separating Phase 8 lets us scale the cadence: daily metrics,
  weekly knowledge curation, monthly tuning — without entangling
  with the per-ticket lifecycle.

---

## Phase 9 — Gap assessment

Phase 9 looks for **drift between the product design and what was
actually shipped**. The per-ticket pipeline is good at delivering what
each ticket asks for, but it does not, by itself, ensure the *whole
product* still matches the *whole design*. Acceptance criteria slip,
edge cases get pruned during execution, PRDs evolve faster than code,
and over time the cumulative gap becomes invisible to anyone not
explicitly looking for it.

**Inputs.**

- The corpus of approved PRDs (issue comments tagged with the PRD
  marker).
- The product vision ([`01-vision.md`](01-vision.md)) and any
  product-layer standards.
- The shipped codebase: code, tests, public API surface, UI flows.
- Closed retrospectives — sometimes a retrospective notes "we cut
  scope X" and the gap-issue is the formal follow-up.

**Outputs.** New GitHub issues — *gap-issues* — proposing work to
close a gap. Gap-issues re-enter the per-ticket pipeline at
`issue-classifier` and run through Phases 1–7 like any other ticket;
the difference is their provenance, which is recorded in the issue
body via a `Gap-source: ai-agile/gap-assessor` trailer for audit
purposes.

**Agents.**

- **`gap-assessor`** — runs weekly. Walks the approved PRDs and
  cross-checks each acceptance criterion against the test suite, the
  shipped code, and the changelog. Flags criteria that have no
  matching test, no shipped behaviour, or whose shipped behaviour
  diverges from the spec.
- **`vision-aligner`** — runs weekly. Reads the product vision and
  product-layer standards and checks the codebase for *missing*
  capabilities the vision implies but no ticket has yet captured.
  Drafts gap-issues for the discovered gaps.
- **`gap-curator`** — runs weekly. De-duplicates and clusters
  candidate gaps from `gap-assessor` and `vision-aligner`, prioritises
  them by severity (broken acceptance criterion > missing capability >
  divergent behaviour), and posts a single rolled-up gap report as the
  artefact for human review.

**Human gates.**

- **`gap-report:approved`** — stakeholder *and* standards owner
  approve which gap-issues actually become issues. Dual approval keeps
  the queue from being flooded with churn issues that don't reflect
  real product intent.

**Why Phase 9 is its own phase.**

- The input corpus (PRDs + shipped code) is different from Phase 7's
  per-ticket retrospective and Phase 8's audit log.
- Gap-issues are *new product work*, not pipeline tweaks — they go
  back through the per-ticket pipeline rather than being applied
  directly.
- The approver shape is different: gap-issues need product judgement
  (is this still a real gap or has the product moved on?), which is
  the stakeholder's call, not the standards owner's alone.

---

## Phase 10 — Tech debt

Phase 10 looks for **poor architecture or implementation choices that
warrant remediation**. The per-ticket pipeline blocks `required`
standards violations at merge time, but it does not catch slower
problems: layered shortcuts that compound, abstractions that have
ossified, modules that have grown beyond their original scope, ADRs
whose tradeoff has aged badly, and patterns that are technically
within standards but obviously wrong at scale.

**Inputs.**

- The codebase — module sizes, dependency graphs, test ratios,
  duplication, coupling metrics, hot-spot files (most-changed,
  most-bug-fixed).
- ADRs (`ai-agile/standards/adrs.json`) — particularly any with
  `status: accepted` whose context has materially changed.
- Standards (`ai-agile/standards/*.json`) — to compare actual code
  against the declared bar.
- Closed retrospectives — frequently a phrase like "we'll come back
  to this" is the seed of a debt-issue.
- Audit log — agents that consistently `:blocked` against the same
  surface area suggest that surface is structurally fragile.

**Outputs.** New GitHub issues — *debt-issues* — proposing
remediation. Like gap-issues, they re-enter the per-ticket pipeline at
`issue-classifier` and carry a `Debt-source: ai-agile/debt-finder`
trailer.

**Agents.**

- **`debt-finder`** — runs weekly. Computes structural metrics
  (module size, cyclomatic complexity, coupling, test coverage on hot
  files, churn) and surfaces outliers. Cross-references hot-spot
  files against open issues and recent retrospectives. Drafts
  candidate debt-issues with evidence (file paths, metric snapshots,
  trend over the last N weeks).
- **`adr-revisitor`** — runs monthly. Walks accepted ADRs and
  evaluates whether the *context* on which the decision was made
  still holds. Drafts revisit-this-ADR issues for those whose tradeoff
  has materially shifted.
- **`debt-curator`** — runs weekly. Like `gap-curator`: de-duplicates
  and prioritises candidate debt-issues from `debt-finder` and
  `adr-revisitor`, then posts a single rolled-up debt report as the
  artefact for human review.

**Human gates.**

- **`debt-report:approved`** — engineer (or tech lead) *and*
  standards owner approve which debt-issues become issues. The
  engineer judges feasibility and priority; the standards owner judges
  fit with architecture direction.

**Why Phase 10 is its own phase.**

- The signal is structural and slow-moving — it cannot be detected
  inside a single ticket's flow.
- The remediation cost is often material (refactor of a hot module,
  ADR superseded by a new one), so the proposal-then-approval shape is
  necessary; we do not want a Phase-10 agent quietly opening 30
  refactor issues a week.
- Distinct from Phase 8: Phase 8 changes the *pipeline*; Phase 10
  changes the *product's implementation*. Both are improvements;
  they're different surfaces.

---

## How Phases 9 and 10 integrate with the per-ticket pipeline

Both phases produce **issues**, not direct edits. This keeps a hard
boundary:

- Continuous phases never touch the codebase directly.
- Every change still flows through Phases 1–7, with the same gates,
  the same standards checks, and the same audit trail.
- Gap-issues and debt-issues are visible in the issue list alongside
  feature work, so reviewers can see and prioritise them against the
  feature backlog rather than as a hidden second queue.

The cost is some queue mixing: a busy week may see gap-issues and
debt-issues compete with feature issues for reviewer attention. The
mitigation is curation — `gap-curator` and `debt-curator` produce
prioritised, deduplicated reports rather than a firehose, and the
human gates (`gap-report:approved`, `debt-report:approved`) are the
throttle.
