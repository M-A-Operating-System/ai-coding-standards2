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
`pipeline.json` is correct. See [P-2](PRODUCT.md#as-1----one-file-tells-you-what-the-pipeline-does).

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
| 3 | Execute | `03_execute` | Per ticket | Build it and verify it | One PR (draft from first commit, per [Two-phase design-to-build delivery](#two-phase-design-to-build-delivery)) including tests and coverage |
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

**Product docs are the target state; code is the current state.**
`docs/product/` describes what should exist, and the gap between that and
what has shipped is the issue backlog: an issue is a `bug` when the code has
drifted from the target, or a `feature`/`enhancement` when the target itself
is moving forward. No code change ships unless it is already described in
`docs/product/` first -- an issue without an approved PRD does not progress
past the product-docs phase, and a PR landing code with no corresponding
target-state entry does not merge.

Every issue entering the pipeline is classified by `issue-classifier` as exactly one of five types. The classification is recorded both in an artefact comment on the issue and as a `classification: {type}` label applied automatically at classification time. Five `classification:` labels are pre-created in the repository — one per type — so the full taxonomy is always available for filtering in the GitHub interface.

| Classification | Label | Definition | Qualifying criterion |
|---|---|---|---|
| `bug` | `classification: bug` | Broken behaviour — something that used to work and no longer does, or behaviour that violates the target state in the product docs. | By definition the code has drifted from the product-docs target (see above); the fix is to correct the code, not the docs. |
| `enhancement` | `classification: enhancement` | An improvement to an **existing** capability — making a feature richer, faster, more accessible, or more reliable. | The capability exists in production today; the issue moves it closer to the target state but does not add a new user-observable outcome. |
| `feature` | `classification: feature` | A **new** capability the product cannot do today. | Adds a fresh user-observable outcome to the target state; deserves a full PRD with new acceptance criteria. |
| `spike` | `classification: spike` | Research or investigation whose primary output is knowledge — a recommendation, an ADR, or a prototype — not shipped code. | Time-boxed; the result feeds a later issue that ships the actual change. |
| `toil` | `classification: toil` | Operational or maintenance work that does not change product capability. | Dependency upgrades, infrastructure changes, refactors, internal API rewrites, doc-only fixes — tied to a non-functional requirement in the product docs, not a user-facing feature. |

When two classifications are plausible, prefer the one with the higher review bar: `bug` over `toil`; `feature` over `enhancement`; `enhancement` over `toil`. The distinction between `feature` and `enhancement` matters because a feature adds new product surface (heavier review); an enhancement refines an existing one (lighter review against the existing PRD).

---

## How the pipeline advances

A single deterministic Python orchestrator has sole authority for
routing — reacting to events and deciding which agent runs next
([PRODUCT.md](PRODUCT.md#as-2----the-orchestrator-only-coordinates)).
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
3. If yes, acquires the `:wip` mutex (see [PRODUCT.md](PRODUCT.md#the-state-machine))
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
[Two-phase design-to-build delivery](#two-phase-design-to-build-delivery)
(draft PRs early, one branch per PR) and
[PRODUCT.md](PRODUCT.md#the-step-contract)
(agents write files, the orchestrator commits and owns the PR lifecycle):

- The `create-pr` script step opens the draft **code** PR on the
  `issue-{N}` branch, cut from the post-design-merge `main`, establishing
  the branch and PR that subsequent coder commits accumulate into. The
  design phase has already merged the approved `docs/product/` +
  `docs/features/` to `main` via the `issue-{N}-docs` PR (see
  [Two-phase design-to-build delivery](#two-phase-design-to-build-delivery)),
  so the code branch starts from a tree that already contains the latest
  design.
- Agents (`coder`) write files during their run; the orchestrator commits
  and pushes those changes to the branch after the agent signals
  `complete` (`git_ops.commit_after: true`). Agents may read issues and
  PRs, but only the orchestrator may create, commit to, or advance the PR.
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
  trailer in the **code** PR body. The design PR (`issue-{N}-docs`)
  carries no closing keyword, so the issue stays open through the build
  phase; only the code PR closes it. The `issue-{N}` and `issue-{N}-docs`
  branches are deleted by the orchestrator when it receives the
  `pull_request.closed` event with `merged=true` — `_wake` calls
  `delete-branch.sh` for this. Branches from PRs closed without merging
  are not auto-deleted; they are handled by the `00_ondemand/branch-cleanup`
  agent on human request.

---

## Human gates

The mechanism -- how a gate is crossed, and by whom -- is
[MI-7](PRODUCT.md#mi-7----only-a-person-approves). This table is what each
gate in the current pipeline means for the human approving it: the
approver, the artefact they read, what approval signs off, and the cost of
getting it wrong.

| Gate label | Phase | Approver | Artefact | What you're signing off | Cost if wrong |
|---|---|---|---|---|---|
| `01_product_docs/prd-writer:approved` | Product docs | Stakeholder who opened the issue, or their delegate | The **issue body itself**, after `01_product_docs/prd-writer` rewrites it into the canonical PRD format (see [PRD format](#prd-format-and-the-prd-writer-gate) below) and rewrites the title | The problem and goal are correct; each user story names a real persona (including the System actor, [`03-personas.md`](03-personas.md) §7) and `As a developer` stories are suspect; each Gherkin scenario is falsifiable; "Out of scope" actually rules things out; success metrics are externally observable; the new title categorises the work correctly and names a real bounded context. Once approved, the PRD is the source of truth for everything downstream | The most expensive gate to skim — wrong PRD → wrong everything downstream (design, testing, evaluation) |
| `size:approved` | Product docs | Engineer who will own the work, or the tech lead | A sizing comment from `ticket-sizer` (`S`, `M`, `L`, `XL`) with rationale | That the ticket fits a single development cycle. If `XL`, you are committing to break it into children before proceeding | An XL ticket past the gate produces a sprawling design and a multi-week PR |
| `super-issue:approved` | Product docs | Engineer | The proposed grouping | The proposed grouping is correct; the super-issue becomes the shippable unit and the grouped children attach to it | — |
| `design:approved` | Technical docs | Engineer or tech lead | A technical design comment from `architect` covering data model, API contracts, component boundaries, integration points, NFRs | That this is the right design and that any ADR-worthy decisions have been flagged | Code is written against this design; a flaw found at PR stage means re-doing implementation |
| `test-spec:approved` | Testing spec | Engineer | A Gherkin scenario list from `test-spec-writer`, plus a coverage report from `test-coverage-auditor` confirming every PRD acceptance criterion maps to at least one scenario | That these scenarios — and only these — are what "done" means | Tests get written for the wrong things |
| `plan:approved` | Build plan | Engineer | A build plan showing the ordered child task list and the critical path, produced by `dependency-planner` | That the decomposition is sensible and the order is correct | Wasted work; merge conflicts; tasks that discover the design has a hole |
| `pr:approved` | Execute | Engineer | A PR review from `pr-reviewer` checking scope, design alignment, and resolution of `required` standards violations | That the code is right and ready to test | Bugs in production. Use this gate to look at the actual diff, not just the agent's review summary |
| `coverage:approved` | Test | Engineer | A coverage report showing test results, coverage delta, and any acceptance criterion without a passing test, produced by `coverage-enforcer` | That tests pass, coverage hasn't regressed, and every required scenario has a passing test | Untested code in production |
| `standards-proposal:approved` | Evaluate (weekly) | Standards owner | An issue from `standards-evolver` proposing a new or changed standard, in JSON schema format | That the proposed standard is sound, the rationale is real, and the agent guidance is unambiguous | A bad standard ripples into every subsequent ticket |
| `security-review:approved` | Execute | Security owner | The PR diff and the `impact-assessor` security-flag comment listing the sensitive surfaces touched (auth flows, RLS policies, IAM definitions, secrets, PII fields) | That the change is safe from an authentication, authorisation, and data-exposure perspective. Not a full pentest — a focused review of the flagged surface | Security vulnerabilities in production. Only required on PRs flagged by `impact-assessor`; non-flagged PRs skip this gate automatically |
| `data-migration:approved` | Execute | Data owner | The migration file(s) and the `migration-validator` report confirming or flagging forward-only, idempotent, and RLS compliance | That the migration is safe to run against production data and that the data lifecycle implications (retention, PII, rollback) are understood and accepted | Data loss or corruption in production. Only required on PRs that include `**/*.sql` files |
| `merge-conflict:approved` | Execute | Engineer | A prioritised list of conflict resolution recommendations from the `merge-conflict` agent, posted as a PR comment; each identifies the affected file, the conflict scope, and the suggested resolution approach | That the proposed resolution for each conflicting file is correct, safe, and consistent with both sides of the merge. Binary and generated files (lock files, compiled assets) may be flagged but require manual handling | Applying the wrong resolution silently drops or corrupts intentional changes. Review each conflicting hunk against the PR's stated intent. Only required on PRs that contain merge conflict markers when marked Ready for Review; clean PRs skip this gate automatically |
| `gap-report:approved` | Gap assessment | Stakeholder + Standards owner (dual approval) | The rolled-up gap report from `gap-curator` listing candidate gap-issues grouped by severity | That the identified gaps are real (not stale requirements the product has intentionally moved away from) and worth filing as tickets | Filing phantom issues wastes the per-ticket pipeline on work no one wants |
| `debt-report:approved` | Tech debt | Engineer (or tech lead) + Standards owner (dual approval) | The rolled-up debt report from `debt-curator` listing candidate debt-issues with structural evidence (metrics, ADR age, hot-spot trends) | That the identified debt is real and worth prioritising against the feature backlog | Remediating false debt distracts from delivering value |
| `pipeline-change:approved` | Learn | Standards owner | A PR against `pipeline.json` from `pipeline-tuner`, with evidence from the metrics report | That the proposed pipeline change — adjusted schedule, added dependency, changed gate — is sound and will not degrade pipeline health | A bad pipeline change affects every subsequent ticket |
| `prompt-change:approved` | Learn | The agent's designated owner (responsible for that agent's quality) | A PR against `.claude/agents/{agent}.md` from `prompt-tuner`, with rejection-rate evidence and diff | That the proposed prompt edit improves agent quality and does not introduce regression | A regressed prompt silently degrades every run of that agent |
| `process-review:approved` | Learn | Standards owner + a principal stakeholder (dual approval required) | A coordinated change proposal from `process-reviewer` spanning the pipeline graph, agent prompts, standards, and docs | That the system-level diagnosis is correct, the proposed coordinated changes are coherent, and the dual approvers together represent both the technical and product perspectives | A bad coordinated change is harder to unwind than a single-component change; the dual approval bar reflects the blast radius |

Two gates carry additional refusal/guard behaviour worth noting:

- **`size:approved`** — `ticket-sizer`'s `XL` verdict is itself the trigger
  to decompose; approving an `XL` commits you to breaking the ticket into
  children first.
- **`01_product_docs/prd-writer:approved`** — `prd-writer` will refuse to
  draft an oversized PRD. If the issue describes multiple distinct user
  outcomes or spans multiple bounded contexts, the agent set-blocks with a
  decomposition recommendation rather than producing a sprawling PRD.
  Decomposing early is cheaper than reviewing a too-big PRD.

### PRD format and the `prd-writer` gate

The artefact for `01_product_docs/prd-writer:approved` is the rewritten
issue body. Its required structure — the six sections (Problem, Goal,
User stories, Acceptance criteria, Out of scope, Success metrics), the
user-story and Gherkin formats, and the `[CATEGORY] - {module} - {Title}`
title format — is defined in the `prd-writer` / product-docs
documentation, not duplicated here. Two facts about that artefact matter
at the gate:

- **Gherkin flows downstream.** Each Gherkin scenario in an approved PRD
  becomes a numbered test scenario in Phase 3
  (`testing-spec/test-spec-writer`), tying every test back to a
  stakeholder-approved acceptance condition.
- **The original is preserved.** The stakeholder's original title and body
  — before `prd-writer` rewrote them — are kept as a one-off, immutable
  snapshot comment marked
  `<!-- ai-agile/snapshot/v1 by 01_product_docs/prd-writer -->`. It stays
  as first captured even if the PRD is rewritten after rejection,
  preserving the audit trail under the
  [MI-7](PRODUCT.md#mi-7----only-a-person-approves) carve-out that
  lets `prd-writer` edit issue title and body.

---

## Two-phase design-to-build delivery

A **shippable unit** is an issue that owns a deliverable: a feature issue, a
chore issue, or a super-issue grouping smaller items. Child issues -- tasks
decomposed from a parent, or bugs grouped under a super-issue -- are not
shippable units; they are tracking and audit units that close when their
parent's PR merges. No PR spans more than one shippable-unit issue, and every
branch produces exactly one PR.

Each issue is delivered in **two sequenced phases, each its own branch and PR**,
so the approved design reaches `main` before any code is written:

| Phase | Branch | PR | Closes issue? | Merges at |
|---|---|---|---|---|
| **Design** | `issue-{N}-docs` | design PR (`docs/product/` + `docs/features/{feature}.md`) | **No** | design approval (`prd-docs-updater:approved`) |
| **Build** | `issue-{N}` | code PR (tests + implementation) | **Yes** (`Closes #{N}`) | end of code review |

- The **design PR must not carry a closing keyword** (`Closes`/`Fixes`/`Resolves`).
  The issue stays open through the build phase; only the **code PR** closes it.
  A premature close would also trip the branch-delete / epic-close automation
  (see [Epic completion](#the-ticket-is-too-big) below).
- The **code branch (`issue-{N}`) is cut from the post-design-merge `main`**, so
  the build always starts from a tree that already contains the latest approved
  design (and the latest pipeline infrastructure).
- This keeps `main` continuously carrying the latest approved *desired state*
  (design) while the *current state* (code) catches up. It also lets parallel
  builds see each other's merged design, and surfaces overlapping-design
  conflicts at the small docs merge rather than late in two colliding code PRs.
- **Naming:** the code branch stays `issue-{N}` (unchanged, so all existing
  tooling keyed on that pattern is untouched); only the new `issue-{N}-docs`
  design branch is added. `delete-branch.sh` broadens its match to clean up both.

This refines -- it does not abandon -- the one-branch-per-PR invariant stated
above: still exactly one PR per branch, now up to two phase-PRs per issue
(design then code).

---

## Forks in the path

### The ticket is too big

If `ticket-sizer` returns `XL`, an **`issue-decomposer`** agent runs.
It drafts a roadmap of proposed child issues — each a smaller business
outcome — and posts the roadmap as a comment on the parent. A human
approves the decomposition by applying `decomposition:approved`. On
approval, the agent auto-creates the child issues and links them back
to the parent. Each child re-enters the pipeline at `issue-classifier`
and runs through its own full lifecycle.

**The epic flow (target state).** An epic is a work item whose value is in the
parts it creates and the judgement that they add up. It has five stages, and
each one is a step in its own flow rather than an exclusion from someone else's:

| Stage | What it is |
|---|---|
| Pick it up | The epic enters its flow like any other work item |
| Decompose it | Produce the child issues that are the actual work, linked back to the epic |
| Wait for the parts | The children run their own flow, independently and in parallel. Not a step -- a later step whose trigger condition is not yet met |
| Review the whole | Confirm the implementation hangs together and the sum of the parts does what the epic asked for |
| Close it | The epic is finished, with that review as the record of why |

The fourth stage is the one worth having. Every child can pass its own review and
the epic still fail: the parts can be individually correct and collectively
wrong, or leave a seam nobody owned. Closing an epic the moment its last child
closes checks that the pieces exist, not that they add up.

Declaring this as a flow needs a trigger that can say "every child of this item
is closed" -- a condition about other work items, which the current trigger
vocabulary cannot express. That is why the waiting is orchestrator-native code
today rather than configuration; see
[`PRODUCT.md`](PRODUCT.md#coordinating-work-needs-a-trigger-that-can-look-outward).

**Epic completion (as built today).** The parent (labeled `epic`) is excluded
from every pipeline stage until its children finish. On each scheduled sweep, the
orchestrator checks every open `epic`-labeled issue: if all of its
`parent-issue:{N}`-labeled children are closed, the orchestrator
re-processes the parent as a work item so it advances through its own next
eligible step — today, that means closing it with a completion comment.
This is orchestrator-native logic, not a registered agent step (a
mechanical label check needs no LLM invocation), declared in
`pipeline.json` as an `orchestrator_checks` entry rather than a pipeline
step.
The mechanism is intentionally general: future pipeline steps added to
epics (such as a whole-feature review before release) plug in by extending
what the parent's "next eligible step" is, without revisiting this check.

Because the check runs on the periodic sweep rather than on an
`issues.closed` event, there is an inherent delay of up to one sweep
interval (currently ~30 minutes between weekday ticks) between the last
child closing and the parent being processed — an accepted trade-off for a
simpler mechanism with no dependency on catching a specific webhook event.
This replaces the standalone `close-epic-on-children-complete.yml` workflow,
which is retired.

Distinct from `task-decomposer` (Design phase): `task-decomposer`
breaks a *sized* feature into implementation tasks (one file, one
concern) that all ship in one PR. `issue-decomposer` runs *before*
sizing clears, breaking a too-large issue into smaller business-outcome
issues, each with its own PR.

### Many small tickets in a window

If `ticket-sizer` returns `S` and the issue is the Nth small
bug or chore in a configured window, the orchestrator suggests
grouping under a super-issue before sizing completes. On approval the
super-issue becomes the shippable unit
(see [Two-phase design-to-build delivery](#two-phase-design-to-build-delivery)):
it runs through the full pipeline as a single unit, the grouped children pause
their own pipelines and attach, and one PR closes the super-issue and
all its children on merge.

### PR contains merge conflicts

After CI passes, a **`merge-conflict`** agent runs automatically before
pr-reviewer. It checks the PR's mergeability via the GitHub API. If the
branch is clean, the agent emits complete and the orchestrator auto-advances
the pipeline to pr-reviewer without any human action (clean PRs are
unaffected). If conflicts are found, the agent fetches both branches
locally, simulates the merge, and posts a prioritised list of resolution
recommendations on the PR — one entry per file, each naming the conflict
scope and the suggested resolution approach. The pipeline pauses at a
`merge-conflict:approved` gate (see [Human gates](#human-gates) above).
On approval, the coding agent is re-invoked with the approved resolution
plan as context; it applies the resolutions and pushes the updated branch.

### SQL changes

When the `coder` opens a PR that touches `**/*.sql`, a
`migration-validator` runs in addition to the standard reviewers.
Merge is blocked on naming, RLS, and type violations regardless
of the standard review path.

---

## End-to-end happy path

A typical feature/bug/enhancement/toil ticket flows like this. Agent
names, dependencies, and gates are as declared in
[`pipeline.json`](../../../pipeline/pipeline.json).

**Spike issues** (`classification: spike`) stop after `prd-writer:approved`.
`create-pr`, `prd-docs-updater`, and `coder` are excluded for spikes —
there is no code to ship, so no branch or PR is created.

| Time | Object | Actor | Event | Outcome label |
|---|---|---|---|---|
| T+0 | Issue | Stakeholder | Opens issue | — |
| T+2m | Issue | `01_product_docs/issue-classifier` | Validates required fields; classifies issue type | `issue-classifier:complete` |
| T+5m | Issue | `01_product_docs/prd-writer` | Drafts PRD; rewrites issue body in user-story + Gherkin format | `prd-writer:review` |
| T+1h | Issue | Stakeholder | Approves PRD | `prd-writer:approved` → `prd-writer:complete` |
| | | | **Design phase — approved design publishes to `main`** | |
| T+2m | Issue → PR | `01_product_docs/create-pr` (script) | Opens the draft **design** PR on `issue-{N}-docs` (no closing keyword); posts the link on the issue | `create-pr:complete` |
| T+5m | PR | `01_product_docs/prd-docs-updater` | Writes the `docs/product/` + `docs/features/{feature}.md` changes on `issue-{N}-docs` | `prd-docs-updater:review` |
| T+30m | PR | Stakeholder | Approves the design; the design PR merges to `main` | `prd-docs-updater:approved` → `prd-docs-updater:complete` → _design merged_ |
| | | | **Build phase — code builds on the now-current `main`** | |
| T+2m | Issue → PR | `01_product_docs/create-pr` (script) | Opens the draft **code** PR on `issue-{N}` (`Closes #{N}`), cut from the post-design-merge `main` | `create-pr:complete` |
| T+30m | Issue | `03_execute/coder` | Implements issue and sub-issues; orchestrator commits changes to `issue-{N}` | _(orchestrator commits + pushes)_ |
| T+10m | PR | `03_execute/pr-reviewer` | Reviews code PR diff against spec; posts structured review | `pr-reviewer:review` |
| T+30m | PR | Engineer | Approves review | `pr-reviewer:approved` → orchestrator marks PR ready |
| — | PR | Engineer | Reviews and merges the code PR | `pr.merged` → issue auto-closes |

The **Actor** column shows who performs each step — agent names
formatted as `{phase}/{short-name}` (see
[`PRODUCT.md`](PRODUCT.md#naming-carries-the-phase));
capitalised names (Stakeholder, Engineer) are human personas from
[`03-personas.md`](03-personas.md).

The **Outcome label** column shows the label applied at the end of
the step. `agent:complete` and `agent:review` are agent status labels
(see [PRODUCT.md](PRODUCT.md#the-state-machine)); the `*:approved`
labels are human gates (see [Human gates](#human-gates) above).
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
| Inputs | Audit log branch (see [`08-audit-log.md`](08-audit-log.md)); corpus of closed retrospectives | Approved PRDs (issue comments tagged with the PRD marker); product vision ([`PRODUCT.md`](PRODUCT.md#vision)) and product-layer standards; shipped codebase (code, tests, public API surface, UI flows); closed retrospectives (a noted "we cut scope X" seeds a gap-issue) | Codebase (module sizes, dependency graphs, test ratios, duplication, coupling, hot-spot files); ADRs (`adrs/adrs.json`), especially `status: accepted` whose context has changed; standards (`standards/*.json`); closed retrospectives ("we'll come back to this" seeds a debt-issue); audit log (repeated `:blocked` against one surface flags structural fragility) |
| Outputs | Proposals against the pipeline itself (`pipeline.json`, agent prompts, schedules): pipeline metrics, pipeline-graph proposals, prompt tuning, knowledge artefacts | New GitHub *gap-issues* proposing work to close a gap. They re-enter the pipeline at `issue-classifier` and run through Phases 1–4; provenance recorded via a `Gap-source: ai-agile/gap-assessor` trailer | New GitHub *debt-issues* proposing remediation. They re-enter the pipeline at `issue-classifier` and carry a `Debt-source: ai-agile/debt-finder` trailer |
| Agents | **`metrics-aggregator`** (daily) — reads the audit log; computes cycle time per phase, gate dwell time per gate, agent duration distributions, rejection rates, blocked/failed counts; writes a metrics report to `docs/product/orchestrator/generated/metrics/` (per [P-2](PRODUCT.md#as-1----one-file-tells-you-what-the-pipeline-does)). **`pipeline-tuner`** (monthly) — scans metrics for systemic patterns (agents that exceed timeout, dependencies that always halt, gates that are rubber-stamped, schedules that miss work); drafts PRs against `pipeline.json`. **`prompt-tuner`** (monthly) — per agent, examines rejection rates and the diff between first draft and human-approved version; drafts targeted prompt edits at `.claude/agents/{agent}.md` as PRs. **`knowledge-curator`** (weekly) — identifies tickets with reusable patterns (recurring incident shape, novel architecture choice, useful test pattern) and drafts knowledge artefacts (runbooks, templates, teaching examples) into `docs/learnings/`. **`process-reviewer`** (quarterly) — reads [`PRODUCT.md`](PRODUCT.md), the metrics from `metrics-aggregator`, and closed retrospectives; produces a holistic assessment (are we honoring our promises, serving our personas, where has practice drifted) and drafts *coordinated* change proposals spanning the pipeline graph, agent prompts, standards, and docs; may propose changes to `PRODUCT.md` itself (rare; requires an ADR). Distinct from `prompt-tuner`: tactical one-agent tuning vs. strategic multi-component review. | **`gap-assessor`** (weekly) — walks approved PRDs, cross-checks each acceptance criterion against the test suite, shipped code, and changelog; flags criteria with no matching test, no shipped behaviour, or behaviour that diverges from spec. **`vision-aligner`** (weekly) — reads the product vision and product-layer standards; checks the codebase for *missing* capabilities the vision implies but no ticket has captured; drafts gap-issues. **`gap-curator`** (weekly) — de-duplicates and clusters candidates from `gap-assessor` and `vision-aligner`, prioritises by severity (broken acceptance criterion > missing capability > divergent behaviour), posts one rolled-up gap report for human review. | **`debt-finder`** (weekly) — computes structural metrics (module size, cyclomatic complexity, coupling, test coverage on hot files, churn) and surfaces outliers; cross-references hot-spot files against open issues and recent retrospectives; drafts candidate debt-issues with evidence (file paths, metric snapshots, trend over the last N weeks). **`adr-revisitor`** (monthly) — walks accepted ADRs, evaluates whether the *context* of each decision still holds; drafts revisit-this-ADR issues for those whose tradeoff has materially shifted. **`debt-curator`** (weekly) — like `gap-curator`: de-duplicates and prioritises candidates from `debt-finder` and `adr-revisitor`, posts one rolled-up debt report for human review. |
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
