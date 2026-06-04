# Lifecycle

Every change passes through seven per-ticket phases. Three additional
phases run continuously across all tickets — learning from the
pipeline itself, finding gaps between the product design and what
actually shipped, and surfacing tech debt for remediation. Each phase
has clearly defined inputs, outputs, agents, and (where applicable) a
human gate.

This document describes the phases conceptually. The authoritative list
of agents per phase, their dependencies, triggers, and gates lives in
[`pipeline/pipeline.json`](../../../pipeline/pipeline.json)
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

## Issue classification taxonomy

Every issue entering the pipeline is classified by `issue-classifier` as exactly one of five types. The classification is recorded both in an artefact comment on the issue and as a `classification: {type}` label applied automatically at classification time. Five `classification:` labels are pre-created in the repository — one per type — so the full taxonomy is always available for filtering in the GitHub interface.

| Classification | Label | Definition | Qualifying criterion |
|---|---|---|---|
| `bug` | `classification: bug` | Broken behaviour — something that used to work and no longer does, or behaviour that violates the target state in the product docs. | By definition the code has drifted from the product-docs target ([P-15](02-principles.md#p-15--product-led-target-state-in-product-docs-leads-code)); the fix is to correct the code, not the docs. |
| `enhancement` | `classification: enhancement` | An improvement to an **existing** capability — making a feature richer, faster, more accessible, or more reliable. | The capability exists in production today; the issue moves it closer to the target state but does not add a new user-observable outcome. |
| `feature` | `classification: feature` | A **new** capability the product cannot do today. | Adds a fresh user-observable outcome to the target state; deserves a full PRD with new acceptance criteria. |
| `spike` | `classification: spike` | Research or investigation whose primary output is knowledge — a recommendation, an ADR, or a prototype — not shipped code. | Time-boxed; the result feeds a later issue that ships the actual change. |
| `toil` | `classification: toil` | Operational or maintenance work that does not change product capability. | Dependency upgrades, infrastructure changes, refactors, internal API rewrites, doc-only fixes — tied to a non-functional requirement in the product docs, not a user-facing feature. |

When two classifications are plausible, prefer the one with the higher review bar: `bug` over `toil`; `feature` over `enhancement`; `enhancement` over `toil`. The distinction between `feature` and `enhancement` matters because a feature adds new product surface (heavier review); an enhancement refines an existing one (lighter review against the existing PRD).

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
4. The agent does its work and emits exactly one terminal status as the
   last line of its stdout: `AI_AGILE_STATUS: complete`,
   `AI_AGILE_STATUS: review`, or `AI_AGILE_STATUS: blocked`. The
   orchestrator reads the sentinel and applies the matching label.
5. If the agent crashes without emitting a sentinel, the orchestrator
   applies `:failed` and posts a comment.

A halted pipeline (`review`, `blocked`, `failed`) resumes the moment a
human removes the offending label. There is no separate "retry" button.

Every transition emits one event to the audit log branch
(see [`08-audit-log.md`](08-audit-log.md)).

In the **Execute** phase the `create-pr` script step opens a draft PR
immediately after PRD approval, establishing the branch and PR that all
subsequent agent commits accumulate into. Agents (`prd-docs-updater`,
`coder`) write files during their run; the orchestrator commits and
pushes those changes to the branch after the agent signals `complete`
(`git_ops.commit_after: true`). Reading issues and PRs is allowed,
but only the orchestrator may create, commit to, or advance the PR. `pr-reviewer` issues `REQUEST_CHANGES` when any Critical, High, or Medium severity finding is present; it issues `APPROVE` only when all findings are Low or Informational severity. When `pr-reviewer` completes with APPROVE, the
orchestr ator marks the PR ready-for-review (`git_ops.mark_ready_on_complete`); when it issues `REQUEST_CHANGES`, the orchestrator automatically re-invokes the coder to address the findings (up to three cycles before requiring human sign-off).
The linked issue closes automatically on merge via the "Closes #{N}"
trailer in the PR body; the branch is deleted automatically by GitHub's
"auto-delete head branches" repo setting.
See [P-13](02-principles.md#p-13--draft-prs-early-one-branch-per-pr)
and [P-16](02-principles.md#p-16--agents-own-branch-commits-orchestrator-owns-the-pr-lifecycle).

---

## Forks in the path

### The ticket is too big _(planned)_

If a future `ticket-sizer` agent returns `XL`, an **`issue-decomposer`**
agent would run. It would draft a roadmap of proposed child issues —
each a smaller business outcome — and post the roadmap as a comment on
the parent. A human would approve the decomposition by applying
`decomposition:approved`. On approval, the agent would auto-create
the child issues and link them back to the parent. Each child
re-enters the pipeline at `issue-classifier` and runs through its own
full lifecycle. The parent waits and closes when all children close,
with a roll-up retrospective.

Distinct from a future `task-decomposer` (Phase 4): `task-decomposer`
would break a *sized* feature into implementation tasks (one file, one
concern) that all ship in one PR. `issue-decomposer` would run *before*
sizing clears, breaking a too-large issue into smaller business-outcome
issues, each with its own PR.

### Many small tickets in a window _(planned)_

If a future `ticket-sizer` returns `S` and the issue is the Nth small
bug or chore in a configured window, the orchestrator would suggest
grouping under a super-issue before sizing completes. On approval the
super-issue becomes the shippable unit
(see [P-5](02-principles.md#p-5--one-shippable-unit-one-pr)): it runs
through the full pipeline as a single unit, the grouped children pause
their own pipelines and attach, and one PR closes the super-issue and
all its children on merge. See
[P-6](02-principles.md#p-6--group-small-work-under-a-super-issue).

### PR contains merge conflicts

After CI passes, a **`merge-conflict`** agent runs automatically before
pr-reviewer. It checks the PR's mergeability via the GitHub API. If the
branch is clean, the agent emits complete and the orchestrator auto-advances
the pipeline to pr-reviewer without any human action (clean PRs are
unaffected). If conflicts are found, the agent fetches both branches
locally, simulates the merge, and posts a prioritised list of resolution
recommendations on the PR — one entry per file, each naming the conflict
scope and the suggested resolution approach. The pipeline pauses at a
`merge-conflict:approved` gate (see [`07-human-gates.md`](07-human-gates.md)).
On approval, the coding agent is re-invoked with the approved resolution
plan as context; it applies the resolutions and pushes the updated branch.

### SQL changes _(planned)_

When the `coder` opens a PR that touches `**/*.sql`, a future
`migration-validator` would run in addition to the standard reviewers.
Merge would be blocked on naming, RLS, and type violations regardless
of the standard review path.

---

## End-to-end happy path

A typical feature/bug/enhancement/toil ticket flows like this. The table
reflects the **current implementation** — the agents actually present in
[`pipeline.json`](../../../pipeline/pipeline.json).
Phases 2–4, 6–7, and 8–10 described elsewhere in this document are
planned but not yet wired into the pipeline.

**Spike issues** (`classification: spike`) stop after `prd-writer:approved`.
`create-pr`, `prd-docs-updater`, and `coder` are excluded for spikes —
there is no code to ship, so no branch or PR is created.

| Time | Object | Actor | Event | Outcome label |
|---|---|---|---|---|
| T+0 | Issue | Stakeholder | Opens issue | — |
| T+2m | Issue | `01_product_docs/issue-classifier` | Validates required fields; classifies issue type | `issue-classifier:complete` |
| T+5m | Issue | `01_product_docs/prd-writer` | Drafts PRD; rewrites issue body in user-story + Gherkin format | `prd-writer:review` |
| T+1h | Issue | Stakeholder | Approves PRD | `prd-writer:approved` → `prd-writer:complete` |
| T+2m | Issue → PR | `01_product_docs/create-pr` (script) | Creates `issue-{N}` branch; opens draft PR with "Closes #{N}"; posts PR number and link as a comment on the issue | `create-pr:complete` |
| T+5m | PR | `01_product_docs/prd-docs-updater` | Cross-checks PRD against product docs; commits any updates | `prd-docs-updater:review` |
| T+30m | PR | Stakeholder | Approves doc updates | `prd-docs-updater:approved` → `prd-docs-updater:complete` |
| T+30m | Issue | `05_execute/coder` | Implements issue and sub-issues; orchestrator commits changes to `issue-{N}` | _(orchestrator commits + pushes)_ |
| T+10m | PR | `05_execute/pr-reviewer` | Reviews PR diff against spec; posts structured review | `pr-reviewer:review` |
| T+30m | PR | Engineer | Approves review | `pr-reviewer:approved` → orchestrator marks PR ready |
| — | PR | Engineer | Reviews and merges PR | `pr.merged` → issue auto-closes |

The **Actor** column shows who performs each step — agent names
formatted as `{phase}/{short-name}` (see
[`12-agent-spec.md`](12-agent-spec.md#naming-convention));
capitalised names (Stakeholder, Engineer) are human personas from
[`03-personas.md`](03-personas.md).

The **Outcome label** column shows the label applied at the end of
the step. `agent:complete` and `agent:review` are agent status labels
(see [`06-status-model.md`](06-status-model.md)); the `*:approved`
labels are human gates (see [`07-human-gates.md`](07-human-gates.md)).
Rows marked _(orchestrator …)_ are git operations run directly by the
orchestr ator, not label transitions.

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
| Changes | Standards (`standards/*.json`) | The pipeline itself (`pipeline.json`, agent prompts, schedules) |

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
  prompt at `.claude/agents/{agent}.md` as PRs.
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
- ADRs (`standards/adrs.json`) — particularly any with
  `status: accepted` whose context has materially changed.
- Standards (`standards/*.json`) — to compare actual code
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
