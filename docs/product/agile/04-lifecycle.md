# Lifecycle

Every change passes through seven phases. Each phase has clearly defined
inputs, outputs, agents, and (where applicable) a human gate.

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

## The seven phases

| # | Phase | Purpose | Primary artefact |
|---|---|---|---|
| 1 | Product docs | Establish what is being built and whether it fits | PRD + sized ticket + dependency map |
| 2 | Technical docs | Establish how it will be built | Technical design + ADR drafts |
| 3 | Testing spec | Establish what "done" means | Numbered Gherkin scenarios |
| 4 | Build plan | Establish the order of work | Ordered child task list |
| 5 | Execute | Build it | One PR per task |
| 6 | Test | Verify it | Tests, coverage report |
| 7 | Evaluate | Record and learn | Changelog, retrospective, standards proposals |

Each phase produces an artefact that is the input to the next. Skipping
a phase is not supported — the orchestrator will not invoke a downstream
agent until its declared dependencies are satisfied.

---

## How the pipeline advances

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
