# Lifecycle

This document lists the pipeline's phases, its agents, and the flows a
ticket moves through. What each label means as a product concept —
`type:`, `size:`, `priority:`, blocking — is defined in
[`PRODUCT.md`](PRODUCT.md) and only referenced here. The authoritative
list of agents per phase, their dependencies, triggers, and gates lives
in [`pipeline/pipeline.json`](../../../pipeline/pipeline.json), and
per-phase mermaid charts are rendered at
[`generated/phases/`](generated/phases/). If anything below disagrees
with `pipeline.json`, `pipeline.json` is correct
(see [P-2](PRODUCT.md#as-1----one-file-tells-you-what-the-pipeline-does)).

---

## Phases

| # | Phase | Directory | Cadence | Purpose | Primary artefact |
|---|---|---|---|---|---|
| 0 | On-demand | `00_ondemand` | Human-triggered | Ad-hoc analysis and setup tools | Varies per agent |
| 1 | Product docs | `01_product_docs` | Per ticket | Establish what is being built and whether it fits | PRD + sized ticket + dependency map |
| 2 | Design | `02_design` | Per ticket | Establish how it will be built, what "done" means, and (at `size: L`) the order children are created in | Technical design + ADR drafts + numbered Gherkin scenarios, when warranted; a child-issue plan at `L` |
| 3 | Execute | `03_execute` | Per ticket | Build it and verify it | One PR including tests and coverage |
| 4 | Evaluate | `04_evaluate` | Per ticket | Record what shipped and reflect on this ticket | Changelog, per-ticket retrospective, targeted standards proposals |
| 5 | Continuous | `05_continuous` | Continuous | Improve the pipeline, the product, and the implementation from accumulated evidence | Pipeline metrics and tuning proposals, gap-issue proposals, tech-debt issue proposals |

Each per-ticket phase produces an artefact that is the input to the
next. Skipping a phase is not supported — the orchestrator will not
invoke a downstream agent until its declared dependencies are
satisfied. Phase 5 does not block any per-ticket flow.

---

## Agents

| Agent | Phase | Kind | Purpose |
|---|---|---|---|
| `00_ondemand/codebase-reviewer` | 0 | agent | Three-persona codebase review; files a Technical Review issue |
| `00_ondemand/new-agent` | 0 | agent | Scaffolds a new pipeline agent from an issue description |
| `00_ondemand/standards-migrator` | 0 | agent | Converts a consuming repo's existing knowledge files into `standards/*.json` |
| `00_ondemand/branch-cleanup` | 0 | agent | Recommends, then (on approval) deletes, stale remote branches |
| `00_ondemand/issue-cleanup` | 0 | agent | Recommends, then (on approval) closes, complete or duplicate issues |
| `00_ondemand/blocker` | 0 | script | Reciprocates `blocks:{this}` onto issue N given an existing `blockedby:{N}`, on request |
| `01_product_docs/issue-classifier` | 1 | agent | Classifies the issue; validates required fields are present |
| `01_product_docs/issue-sizer` | 1 | agent | Sizes the ticket (`S`/`M`/`L`) |
| `01_product_docs/prd-writer` | 1 | agent | Drafts the PRD; rewrites the issue body into user-story + Gherkin format |
| `01_product_docs/create-docs-pr` | 1 | script | Opens the design PR (`issue-{N}-docs`), non-closing |
| `01_product_docs/prd-docs-updater` | 1 | agent | Writes the scoped `docs/product/` + `docs/features/` change; copies approved Gherkin |
| `01_product_docs/merge-docs-pr` | 1 | script | Merges the design PR to `main` ahead of the build phase |
| `01_product_docs/create-pr` | 1 | script | Opens the code PR (`issue-{N}`), cut from the post-design `main` |
| `02_design/architect` | 2 | agent | Technical design — data model, API contracts, boundaries, NFRs |
| `02_design/test-spec-writer` | 2 | agent | Derives a numbered Gherkin scenario list from the approved PRD |
| `02_design/test-coverage-auditor` | 2 | agent | Confirms every PRD acceptance criterion maps to at least one scenario |
| `02_design/dependency-planner` | 2 | agent | Produces the build plan — child creation order and critical path |
| `02_design/large-decomposer` | 2 | agent | Drafts the child-issue roadmap for an `L` ticket |
| `02_design/create-integration-pr` | 2 | script | Opens `feature-{parent_N}` and its non-closing integration PR into `main` |
| `03_execute/coder` | 3 | agent | Implements the issue; the orchestrator commits on completion |
| `03_execute/ci-gate` | 3 | script | Polls CI checks |
| `03_execute/merge-conflict` | 3 | agent | Auto-advances a clean PR; posts a resolution plan otherwise |
| `03_execute/pr-reviewer` | 3 | agent | Structured code review; `REQUEST_CHANGES`/`APPROVE` |
| `03_execute/impact-assessor` | 3 | agent | Flags sensitive surfaces touched (auth, RLS, IAM, secrets, PII) |
| `03_execute/migration-validator` | 3 | agent | Confirms forward-only, idempotent, RLS-compliant migrations |
| `03_execute/coverage-enforcer` | 3 | agent | Confirms tests pass and coverage hasn't regressed |
| `03_execute/large-reviewer` | 3 | agent | Reviews an `L` ticket's aggregate diff once every child merges |
| `04_evaluate/standards-evolver` | 4 | agent | Proposes a new or changed standard from repeated findings |
| `05_continuous/metrics-aggregator` | 5 | agent | Daily: cycle time, gate dwell time, agent duration, rejection rate |
| `05_continuous/pipeline-tuner` | 5 | agent | Monthly: drafts PRs against `pipeline.json` from systemic metric patterns |
| `05_continuous/prompt-tuner` | 5 | agent | Monthly: drafts targeted agent-prompt edits from rejection-rate evidence |
| `05_continuous/knowledge-curator` | 5 | agent | Weekly: drafts knowledge artefacts from tickets with reusable patterns |
| `05_continuous/process-reviewer` | 5 | agent | Quarterly: holistic assessment against `PRODUCT.md` |
| `05_continuous/gap-assessor` | 5 | agent | Weekly: cross-checks PRD acceptance criteria against tests and shipped code |
| `05_continuous/vision-aligner` | 5 | agent | Weekly: checks the codebase for capabilities the vision implies but no ticket captured |
| `05_continuous/gap-curator` | 5 | agent | Weekly: de-duplicates and prioritises gap candidates into one report |
| `05_continuous/debt-finder` | 5 | agent | Weekly: surfaces structural outliers — size, complexity, coupling, coverage, churn |
| `05_continuous/adr-revisitor` | 5 | agent | Monthly: flags accepted ADRs whose context has materially shifted |
| `05_continuous/debt-curator` | 5 | agent | Weekly: de-duplicates and prioritises debt candidates into one report |

Clearing a satisfied `blockedby:`/`blocks:` pair once the blocking issue
closes is not a separate scheduled agent -- the pipeline runs no scheduled
jobs beyond the emergency-stop check and the main orchestrator tick, so this
is orchestrator-internal behaviour that runs as part of every ordinary tick
instead (`pipeline_orchestrator.py`'s `_clear_satisfied_blocks`), the same
way gate promotion already does.

---

## Flows

`type:` and `size:` ([PRODUCT.md](PRODUCT.md#type-ranks-five-reasons-an-issue-exists),
[PRODUCT.md](PRODUCT.md#size-measures-how-much-work-there-is)) decide
which flow below a ticket takes. Each flow's table names the gate and
its approver inline, where one applies.

### Issue classification taxonomy

Every issue enters at `01_product_docs/issue-classifier`, which assigns
`type:` and starts whichever flow below matches.

### Two-phase design-to-build delivery

Every shippable unit (any `size: M` issue, or a super-issue) is
delivered as two sequenced phases, each its own branch and PR, so the
approved design reaches its target branch before any code is written:

| Phase | Branch | PR | Closes issue? | Merges at |
|---|---|---|---|---|
| **Design** | `issue-{N}-docs` | design PR (`docs/product/` + `docs/features/{feature}.md`) | No | `prd-docs-updater:approved` (Stakeholder) |
| **Build** | `issue-{N}` | code PR (tests + implementation) | Yes (`Closes #{N}`) | end of code review |

The code branch is cut from the post-design-merge target branch —
`main` normally, `feature-{parent_N}` for a decomposition child (see
[The ticket is too big](#the-ticket-is-too-big)) — so the build always
starts from a tree that already contains the latest approved design.
`prd-docs-updater`'s edit is scoped to what the PRD changed, never a
full-file rewrite.

### PRD format and the `prd-writer` gate

The artefact for `prd-writer:approved` is the rewritten issue body: six
sections (Problem, Goal, User stories, Acceptance criteria, Out of
scope, Success metrics) in user-story and Gherkin format, approved by
the Stakeholder who opened the issue. `prd-writer` refuses to draft an
oversized PRD — an issue describing multiple distinct user outcomes or
spanning multiple bounded contexts gets a decomposition recommendation
instead. Each Gherkin scenario in an approved PRD is what
`test-spec-writer` derives its scenarios from at `size: L`. The
stakeholder's original title and body are kept as an immutable snapshot
comment, under the [MI-7](PRODUCT.md#mi-7----only-a-person-approves)
carve-out that lets `prd-writer` edit issue title and body.

### End-to-end happy path

A typical `size: M` security/bug/enhancement/tech-debt ticket, walked
end to end, with no fork. **Spike issues** (`type: spike`) stop after
`prd-writer:approved` — `create-pr`, `prd-docs-updater`, and `coder`
are excluded, since there is no code to ship.

| # | Actor | Event | Outcome label | Gate (Approver) |
|---|---|---|---|---|
| 1 | Stakeholder | Opens issue | — | — |
| 2 | `issue-classifier` | Validates required fields; classifies issue type | `issue-classifier:complete` | — |
| 3 | `prd-writer` | Drafts PRD; rewrites issue body | `prd-writer:review` | — |
| 4 | Stakeholder | Approves PRD | `prd-writer:approved` | **`prd-writer:approved`** — Stakeholder |
| 5 | `issue-sizer` | Sizes the ticket; returns `size: M` | `issue-sizer:review` | — |
| 6 | Reviewer | Approves the size | `size:approved` | **`size:approved`** — Reviewer |
| 7 | `create-pr` (script) | Opens the draft **design** PR on `issue-{N}-docs` | `create-pr:complete` | — |
| 8 | `prd-docs-updater` | Writes the `docs/product/` + `docs/features/` changes | `prd-docs-updater:review` | — |
| 9 | Stakeholder | Approves the design; design PR merges to `main` | `prd-docs-updater:approved` | **`prd-docs-updater:approved`** — Stakeholder |
| 10 | `create-pr` (script) | Opens the draft **code** PR on `issue-{N}` (`Closes #{N}`) | `create-pr:complete` | — |
| 11 | `coder` | Implements the issue; orchestrator commits and pushes | — | — |
| 12 | `pr-reviewer` | Reviews code PR diff against spec | `pr-reviewer:review` | — |
| 13 | Reviewer | Approves review | `pr-reviewer:approved` | **`pr:approved`** — Reviewer |
| 14 | Reviewer | Reviews and merges the code PR | `pr.merged` → issue auto-closes | — |

Notes: `REQUEST_CHANGES` from `pr-reviewer` re-invokes `coder`, up to
three cycles before requiring human sign-off; `pr-reviewer` cannot
`APPROVE` while any human `REQUEST_CHANGES` review is unresolved,
regardless of its own findings. Merged branches (`issue-{N}` and
`issue-{N}-docs`) are auto-deleted by the orchestrator.

Two gates not shown above apply conditionally, regardless of type/size:
`coverage:approved` (Engineer, from `coverage-enforcer`) always at
`size: M`; `security-review:approved` (Security owner, from
`impact-assessor`) only when a PR is flagged; `data-migration:approved`
(Data owner, from `migration-validator`) only when a PR touches
`**/*.sql`.

### The ticket is too big

At `size: L`, design and planning happen before decomposition, not after —
`architect` settles the boundaries `large-decomposer` splits along, and
`dependency-planner`'s child order depends on the same design.

| Step | Actor | What happens | Gate (Approver) |
|---|---|---|---|
| Design | `architect` | Settles component boundaries, API contracts, data model | **`design:approved`** — Reviewer |
| Test spec | `test-spec-writer` / `test-coverage-auditor` | Scenario set + coverage check against the PRD | **`test-spec:approved`** — Reviewer |
| Plan | `dependency-planner` | Build plan: child creation order and critical path | **`plan:approved`** — Engineer |
| Decompose | `large-decomposer` | Drafts the child-issue roadmap | **`decomposition:approved`** — Engineer |
| Open integration branch | `create-integration-pr` (script) | Opens `feature-{parent_N}` and its non-closing integration PR into `main` | — |
| Build the parts | Children (recursive) | Each child re-enters at `issue-classifier`, sized on its own merits, building on `feature-{parent_N}` instead of `main`, until it resolves to `M` | — |
| Review the whole | `large-reviewer` | Reviews `feature-{parent_N}`'s accumulated diff against the parent's PRD, design, and plan | **`large-review:approved`** — Reviewer |
| Close it | Reviewer merges the integration PR | Brings the aggregate into `main`; closes the parent | — |

`REQUEST_CHANGES` on `large-review:approved` files a new child under
the same parent, rather than reopening one that already merged.
Declaring "wait for the parts" needs a trigger that can say "every
child of this item is closed" — a condition about other work items;
see [`PRODUCT.md`](PRODUCT.md#coordinating-work-needs-a-trigger-that-can-look-outward).

### Many small tickets in a window

At `size: S`:

| Step | Actor | What happens | Gate (Approver) |
|---|---|---|---|
| Group | Orchestrator (combiner) | Suggests grouping with other `S` issues in the window | **`super-issue:approved`** — Reviewer |
| Re-enter | Super-issue | Becomes the shippable unit, sized on its own merits (typically `M`); grouped children pause their own pipelines and attach | follows [End-to-end happy path](#end-to-end-happy-path) |
| Close | One PR | Closes the super-issue and every grouped child on merge | — |

### PR contains merge conflicts

| Step | Actor | What happens | Gate (Approver) |
|---|---|---|---|
| Check | `merge-conflict` | Runs after CI passes, before `pr-reviewer`; checks mergeability via the GitHub API | — |
| Clean | Orchestrator | Auto-advances to `pr-reviewer`, no human action | — |
| Conflicted | `merge-conflict` | Simulates the merge; posts a prioritised per-file resolution plan | **`merge-conflict:approved`** — Engineer |
| Resolve | `coder` | Re-invoked with the approved plan; applies resolutions and pushes | — |

### SQL changes

When `coder` opens a PR touching `**/*.sql`, `migration-validator` runs
in addition to the standard reviewers and gates
**`data-migration:approved`** (Data owner) on the migration file(s) and
its report. Merge is blocked on naming, RLS, and type violations
regardless of the standard review path.

### Continuous loops (Phase 5)

Three loops run on independent cadences and never touch code directly.
Each files a work item rather than doing work itself: for two of the
three, that means a new issue that re-enters at `issue-classifier`
(Gap-assessment issues land as `enhancement`; Tech-debt issues carry a
`Debt-source:` trailer and are a primary source of the `tech-debt`
type — see [Issue classification taxonomy](#issue-classification-taxonomy)).
The Learn loop's output is a gated PR against the pipeline's own
configuration instead, since there is no product ticket to classify.

| | Learn loop | Gap-assessment loop | Tech-debt loop |
|---|---|---|---|
| Agents (cadence) | `metrics-aggregator` (daily); `pipeline-tuner` (monthly); `prompt-tuner` (monthly); `knowledge-curator` (weekly); `process-reviewer` (quarterly) | `gap-assessor` (weekly); `vision-aligner` (weekly); `gap-curator` (weekly) | `debt-finder` (weekly); `adr-revisitor` (monthly); `debt-curator` (weekly) |
| Output | Proposals against `pipeline.json`, agent prompts, schedules | Gap-issues, re-entering at `issue-classifier` | Debt-issues, re-entering at `issue-classifier` |
| Gate (Approver) | `pipeline-change:approved` (Standards owner); `prompt-change:approved` (agent owner); `process-review:approved` (Standards owner + a principal stakeholder) | `gap-report:approved` (Stakeholder + Standards owner) | `debt-report:approved` (Engineer/tech lead + Standards owner) |

`gap-curator` and `debt-curator` de-duplicate and prioritise candidates
into one rolled-up report each, rather than a firehose, so the human
gates above are the only queue throttle.
