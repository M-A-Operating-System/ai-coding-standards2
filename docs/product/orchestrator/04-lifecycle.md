# Lifecycle

Every change passes through four per-ticket phases. A fifth phase runs
continuously across all tickets — learning from the pipeline itself,
finding gaps between the product design and what actually shipped, and
surfacing tech debt for remediation. A zero-numbered on-demand group
holds human-triggered agents that sit outside the lifecycle flow. Each
phase has clearly defined inputs, outputs, agents, and (where
applicable) a human gate.

This document describes the phases conceptually. The authoritative list
of agents per phase, their dependencies, triggers, and gates lives in
[`pipeline/pipeline.json`](../../../pipeline/pipeline.json)
and per-phase mermaid charts are rendered at
[`generated/phases/`](generated/phases/).

If anything in the prose below disagrees with `pipeline.json`,
`pipeline.json` is correct. See [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated).

---

## The five phases (plus on-demand)

Phases 1–4 run per ticket, in order. Phase 5 runs continuously across
all tickets. `00_ondemand` is not a lifecycle phase: it holds agents a
human triggers explicitly (by label or manual invocation), at any time,
independent of any ticket's progress.

| # | Phase | Directory | Cadence | Purpose | Primary artefact |
|---|---|---|---|---|---|
| 0 | On-demand | `00_ondemand` | Human-triggered | Ad-hoc analysis and setup tools (codebase review, standards migration) | Varies per agent |
| 1 | Product docs | `01_product_docs` | Per ticket | Establish what is being built and whether it fits | PRD + sized ticket + dependency map |
| 2 | Design | `02_design` | Per ticket | Establish how it will be built, what "done" means, and the order of work | Technical design + ADR drafts + numbered Gherkin scenarios + ordered task list |
| 3 | Execute | `03_execute` | Per ticket | Build it and verify it | One PR (draft from first commit, per [P-13](02-principles.md#p-13--draft-prs-early-one-branch-per-pr)) including tests and coverage |
| 4 | Evaluate | `04_evaluate` | Per ticket | Record what shipped and reflect on this ticket | Changelog, per-ticket retrospective, targeted standards proposals |
| 5 | Continuous | `05_continuous` | Continuous | Improve the pipeline, the product, and the implementation from accumulated evidence | Pipeline metrics and tuning proposals, gap-issue proposals, tech-debt issue proposals |

Each per-ticket phase produces an artefact that is the input to the
next. Skipping a phase is not supported — the orchestrator will not
invoke a downstream agent until its declared dependencies are
satisfied. Phase 5 does not block any per-ticket flow; it operates
independently and feeds back into the queue as new issues (gap-issues,
debt-issues) or as proposals against `pipeline.json` and the standards.

**Phase consolidation note.** An earlier ten-phase model is consolidated into the five phases above: technical docs / testing spec / build plan became **Design**, test folded into **Execute** (tests ship in the same PR as the code), and learn / gap assessment / tech debt became three loops within one **Continuous** phase.

**The three continuous loops.** Within Phase 5, three loops mine
different inputs at different cadences:

| | Learn loop | Gap-assessment loop | Tech-debt loop |
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

A single deterministic Python orchestrator has sole authority for
routing — reacting to events and deciding which agent runs next
([P-14](02-principles.md#p-14--deterministic-python-orchestrator-with-sole-routing-authority)).
The rest of this section describes the operational mechanics.

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

Every transition emits one JSON event to stdout
(see [`08-audit-log.md`](08-audit-log.md)).

In the **Execute** phase, branch and PR ownership follows
[P-13](02-principles.md#p-13--draft-prs-early-one-branch-per-pr)
(draft PRs early, one branch per PR) and
[P-16](02-principles.md#p-16--git-commit-ownership-two-modes)
(agents own branch commits, orchestrator owns the PR lifecycle):

- The `create-pr` script step opens a draft PR immediately after PRD
  approval, establishing the branch and PR that all subsequent agent
  commits accumulate into.
- Agents (`prd-docs-updater`, `coder`) write files during their run;
  the orchestrator commits and pushes those changes to the branch after
  the agent signals `complete` (`git_ops.commit_after: true`). Agents
  may read issues and PRs, but only the orchestrator may create, commit
  to, or advance the PR.
- `pr-reviewer` issues `REQUEST_CHANGES` for any Critical, High, or
  Medium severity finding; it issues `APPROVE` only when all findings
  are Low or Informational severity.
- Human reviewer feedback is a first-class input. `pr-reviewer` reads
  all open human `REQUEST_CHANGES` reviews on the PR in addition to the
  diff and spec, and **cannot** issue `APPROVE` while any unresolved
  human `REQUEST_CHANGES` review remains open, regardless of its own
  findings. Reviews from bot accounts are excluded — only human GitHub
  accounts count.
- When the `coder` is re-invoked it reads both the `pr-reviewer`'s
  findings and any unresolved human review comments, so both sources
  are addressed in one pass.
- On `APPROVE` with no unresolved human `REQUEST_CHANGES` reviews, the
  orchestrator marks the PR ready-for-review
  (`git_ops.mark_ready_on_complete`).
- On `REQUEST_CHANGES`, the orchestrator automatically re-invokes the
  coder to address the findings (up to three cycles before requiring
  human sign-off).
- **Edge case:** if `pr-reviewer` issues `APPROVE` but one or more
  human `REQUEST_CHANGES` reviews remain open, the orchestrator does
  not mark the PR ready — it re-invokes the coder once to address the
  human feedback (this re-invocation does not count toward the
  three-cycle limit), then ci-gate and `pr-reviewer` run again.
- The linked issue closes automatically on merge via the "Closes #{N}"
  trailer in the PR body; the branch is deleted automatically by
  GitHub's "auto-delete head branches" repo setting.

---

## Forks in the path

> **Note:** Every fork below is planned design **except** `merge-conflict`,
> which is implemented and runs after CI (see "PR contains merge conflicts").
> The current pipeline runs
> `issue-classifier → prd-writer → create-pr → prd-docs-updater → coder →
> ci-gate → merge-conflict → pr-reviewer`.

### The ticket is too big

If a future `ticket-sizer` agent returns `XL`, an **`issue-decomposer`**
agent would run. It would draft a roadmap of proposed child issues —
each a smaller business outcome — and post the roadmap as a comment on
the parent. A human would approve the decomposition by applying
`decomposition:approved`. On approval, the agent would auto-create
the child issues and link them back to the parent. Each child
re-enters the pipeline at `issue-classifier` and runs through its own
full lifecycle. The parent waits and closes when all children close,
with a roll-up retrospective.

Distinct from a future `task-decomposer` (Design phase): `task-decomposer`
would break a *sized* feature into implementation tasks (one file, one
concern) that all ship in one PR. `issue-decomposer` would run *before*
sizing clears, breaking a too-large issue into smaller business-outcome
issues, each with its own PR.

### Many small tickets in a window

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

### SQL changes

When the `coder` opens a PR that touches `**/*.sql`, a future
`migration-validator` would run in addition to the standard reviewers.
Merge would be blocked on naming, RLS, and type violations regardless
of the standard review path.

---

## End-to-end happy path

A typical feature/bug/enhancement/toil ticket flows like this. The table
reflects the **current implementation** — the agents actually present in
[`pipeline.json`](../../../pipeline/pipeline.json).
The Design (2), Evaluate (4), and Continuous (5) phases described
elsewhere in this document are planned but not yet wired into the
pipeline; their directories exist but hold no agents.

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
| T+30m | Issue | `03_execute/coder` | Implements issue and sub-issues; orchestrator commits changes to `issue-{N}` | _(orchestrator commits + pushes)_ |
| T+10m | PR | `03_execute/pr-reviewer` | Reviews PR diff against spec; posts structured review | `pr-reviewer:review` |
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
orchestrator, not label transitions.

Total wall-clock human time: minutes. Total elapsed time: hours.

---

## Phase 5 — the continuous meta-loops

Phase 5 (`05_continuous`) holds three continuously running meta-loops,
not per-ticket steps. None blocks the per-ticket pipeline; they feed it
new issues and proposals. The three loops share one template: each
treats a different **corpus** as its primary input, runs a set of
**agents** on a cadence, rolls candidates into a curated report, and
gates that report behind a **human approval** before any output takes
effect. The comparison table at the top of this document
([The three continuous loops](#the-five-phases-plus-on-demand))
differentiates them at a glance; the table below records each loop's
inputs, outputs, agents, and gates in full.

| | Learn loop | Gap-assessment loop | Tech-debt loop |
|---|---|---|---|
| Targets | Improvements to the pipeline itself | Drift between the product design and what was actually shipped | Poor architecture or implementation choices that warrant remediation |
| Inputs | Audit log branch (see [`08-audit-log.md`](08-audit-log.md)); corpus of closed retrospectives | Approved PRDs (issue comments tagged with the PRD marker); product vision ([`01-vision.md`](01-vision.md)) and product-layer standards; shipped codebase (code, tests, public API surface, UI flows); closed retrospectives (a noted "we cut scope X" seeds a gap-issue) | Codebase (module sizes, dependency graphs, test ratios, duplication, coupling, hot-spot files); ADRs (`standards/adrs.json`), especially `status: accepted` whose context has changed; standards (`standards/*.json`); closed retrospectives ("we'll come back to this" seeds a debt-issue); audit log (repeated `:blocked` against one surface flags structural fragility) |
| Outputs | Proposals against the pipeline itself (`pipeline.json`, agent prompts, schedules): pipeline metrics, pipeline-graph proposals, prompt tuning, knowledge artefacts | New GitHub *gap-issues* proposing work to close a gap. They re-enter the pipeline at `issue-classifier` and run through Phases 1–4; provenance recorded via a `Gap-source: ai-agile/gap-assessor` trailer | New GitHub *debt-issues* proposing remediation. They re-enter the pipeline at `issue-classifier` and carry a `Debt-source: ai-agile/debt-finder` trailer |
| Agents | **`metrics-aggregator`** (daily) — reads the audit log; computes cycle time per phase, gate dwell time per gate, agent duration distributions, rejection rates, blocked/failed counts; writes a metrics report to `docs/product/agile/generated/metrics/` (per [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated)). **`pipeline-tuner`** (monthly) — scans metrics for systemic patterns (agents that exceed timeout, dependencies that always halt, gates that are rubber-stamped, schedules that miss work); drafts PRs against `pipeline.json`. **`prompt-tuner`** (monthly) — per agent, examines rejection rates and the diff between first draft and human-approved version; drafts targeted prompt edits at `.claude/agents/{agent}.md` as PRs. **`knowledge-curator`** (weekly) — identifies tickets with reusable patterns (recurring incident shape, novel architecture choice, useful test pattern) and drafts knowledge artefacts (runbooks, templates, teaching examples) into `docs/learnings/`. **`process-reviewer`** (quarterly) — reads principles ([`02-principles.md`](02-principles.md)), vision ([`01-vision.md`](01-vision.md)), the metrics from `metrics-aggregator`, and closed retrospectives; produces a holistic assessment (are we honoring our principles, serving our personas, where has practice drifted) and drafts *coordinated* change proposals spanning the pipeline graph, agent prompts, standards, and docs; may propose changes to the principles themselves (rare; requires an ADR). Distinct from `prompt-tuner`: tactical one-agent tuning vs. strategic multi-component review. | **`gap-assessor`** (weekly) — walks approved PRDs, cross-checks each acceptance criterion against the test suite, shipped code, and changelog; flags criteria with no matching test, no shipped behaviour, or behaviour that diverges from spec. **`vision-aligner`** (weekly) — reads the product vision and product-layer standards; checks the codebase for *missing* capabilities the vision implies but no ticket has captured; drafts gap-issues. **`gap-curator`** (weekly) — de-duplicates and clusters candidates from `gap-assessor` and `vision-aligner`, prioritises by severity (broken acceptance criterion > missing capability > divergent behaviour), posts one rolled-up gap report for human review. | **`debt-finder`** (weekly) — computes structural metrics (module size, cyclomatic complexity, coupling, test coverage on hot files, churn) and surfaces outliers; cross-references hot-spot files against open issues and recent retrospectives; drafts candidate debt-issues with evidence (file paths, metric snapshots, trend over the last N weeks). **`adr-revisitor`** (monthly) — walks accepted ADRs, evaluates whether the *context* of each decision still holds; drafts revisit-this-ADR issues for those whose tradeoff has materially shifted. **`debt-curator`** (weekly) — like `gap-curator`: de-duplicates and prioritises candidates from `debt-finder` and `adr-revisitor`, posts one rolled-up debt report for human review. |
| Human gates | **`pipeline-change:approved`** (standards owner) for `pipeline-tuner` changes to `pipeline.json`; **`prompt-change:approved`** (agent owner) for `prompt-tuner` changes to an agent prompt; **`process-review:approved`** (standards owner *and* a principal stakeholder) for `process-reviewer` coordinated changes, the dual approval reflecting their cross-cutting nature; `knowledge-curator` changes follow normal PR review | **`gap-report:approved`** — stakeholder *and* standards owner approve which gap-issues become issues. Dual approval keeps the queue from flooding with churn issues that don't reflect real product intent | **`debt-report:approved`** — engineer (or tech lead) *and* standards owner approve which debt-issues become issues. The engineer judges feasibility and priority; the standards owner judges fit with architecture direction |

The Learn loop is the only one that changes the *pipeline*; Gap and
Tech-debt both change the *product* and route their output back through
Phases 1–4 as ordinary issues (Gap = new product work, Tech-debt =
remediation of implementation choices). All three are deliberately
separated from Phase 4 (Evaluate), which closes a single ticket
(changelog, per-ticket retrospective, targeted standards proposals);
the meta-loops instead look across many tickets, so their signals are
systemic and slow-moving, their cadences vary (daily / weekly / monthly
/ quarterly) independently of any one ticket, and their changes affect
all subsequent tickets — which is why each carries a higher review bar.

---

## How the gap and debt loops integrate with the per-ticket pipeline

Both loops produce **issues**, not direct edits. This keeps a hard
boundary:

- The continuous phase never touches the codebase directly.
- Every change still flows through Phases 1–4, with the same gates,
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
