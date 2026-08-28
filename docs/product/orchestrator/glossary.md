# Glossary

Plain-language definitions of the terms used across these docs. Each entry
points to the document that defines the concept in full. If you are new,
skim this once — most of the docs assume these terms.

## Core concepts

**AI Agile** — The product-development lifecycle described by these docs:
specialised AI agents move every change from a GitHub issue to shipped,
tested, documented code, with humans approving at gates.
See [`PRODUCT.md`](PRODUCT.md#vision).

**Agent** — A single-purpose AI worker with one job (write a PRD, review a
PR, resolve a merge conflict). An agent is a prompt file plus a tool
allowlist; it never calls other agents. See [`PRODUCT.md`](PRODUCT.md#the-agent-prompt-file).

**Orchestrator** — The deterministic Python program that decides which agent
runs next. It reads labels, checks the dependency graph, invokes the one
eligible agent, and records the result. All routing is plain Python (no LLM),
so it is testable and predictable. See [`PRODUCT.md`](PRODUCT.md#how-it-uses-agents).

**Pipeline** — The ordered graph of agents, declared once in
`pipeline/pipeline.json`. This single file is the source of truth for which
agents exist, what triggers them, and what they depend on.
See [`PRODUCT.md`](PRODUCT.md#as-1----one-file-tells-you-what-the-pipeline-does).

**Phase** — A stage of the lifecycle. Phases 1–4 run per ticket (Product
docs → Design → Execute → Evaluate); Phase 5 runs continuously across all
tickets; `00_ondemand` holds human-triggered tools.
See [`04-lifecycle.md`](04-lifecycle.md).

**Work item / object** — The thing an agent acts on: a GitHub **issue** or a
**pull request**. "Object kind" is `issue` or `pr`.

**Shippable unit** — An issue that owns a deliverable (a feature, a chore, or
a super-issue). Each shippable unit is delivered as up to two sequenced
phase-PRs — a design PR then a code PR, each on its own branch — and only the
code PR closes it. Child issues are tracking units, not shippable units. See
[`04-lifecycle.md`](04-lifecycle.md#two-phase-design-to-build-delivery).

**Super-issue** — A parent issue that groups several small related items into
one shippable unit. See [`04-lifecycle.md`](04-lifecycle.md#many-small-tickets-in-a-window).

## How work advances

**Status label** — A GitHub label that encodes pipeline state, of the form
`{agent}:{status}` (e.g. `prd-writer:complete`). Labels are the entire state
machine — there is no separate database. See [`PRODUCT.md`](PRODUCT.md#the-state-machine).

**Status suffixes** — `:wip` (running), `:complete` (done), `:review`
(awaiting a human), `:blocked` (stuck, needs a human), `:failed` (errored),
`:approved` (a human applied a gate label). The orchestrator owns every
transition; humans only apply gate labels. See [`PRODUCT.md`](PRODUCT.md#the-state-machine).

**`:wip` (mutex)** — The `{agent}:wip` label doubles as the lock that stops
two orchestrator runs from working the same `(object, agent)` at once.
See [`PRODUCT.md`](PRODUCT.md#the-state-machine).

**Human gate** — A point where work cannot advance until a named human
approves by applying a gate label (e.g. `prd-writer:approved`). Agents draft;
humans decide. See [MI-7](PRODUCT.md#mi-7----only-a-person-approves).

**Sentinel** — The single line an agent prints to report its outcome:
`AI_AGILE_STATUS: complete|review|blocked`. The orchestrator reads it and
applies the matching label -- the current mechanism; PRODUCT.md's target
design replaces it with a written result (see
[`#what-a-step-must-return`](PRODUCT.md#what-a-step-must-return)). See
[`.claude/AGENTS.md`](../../../.claude/AGENTS.md) for today's exact syntax.

**Session** — The lifecycle of one agent's interactions with one object,
identified by a deterministic ID (e.g.
`ais-v1-01-product-docs-prd-writer-issue-42`). Re-runs resume the same
session. See [`schema/pipeline.schema.json`](schema/pipeline.schema.json), the
`session` field.

## Records and rules

**Audit log** — The immutable, append-only timeline of every pipeline event,
one JSON record per completed step, appended to the protected `ai-agile/log`
orphan branch. See [MI-6](PRODUCT.md#mi-6----you-can-believe-what-the-system-tells-you).

**Standards** — Machine-readable rules (`standards/*.json`) the coder and
reviewer enforce, in two tiers: organisation-wide and project-specific.
See [`14-standards.md`](../standards/14-standards.md).

**ADR** — Architecture Decision Record: a logged, dated decision with its
context, rationale, and consequences. An ADR may waive a specific standard
for a project (exception ADR) or document an architectural decision that
overrides no standard (decision-only ADR). Both forms live in `adrs/adrs.json`.
See [`14-standards.md`](../standards/14-standards.md).

**Promise (AS-x / MI-x)** — One of the architectural-separation guarantees
(AS-1 to AS-3) or mode invariants (MI-1 to MI-8) `PRODUCT.md` states, each
with a stated test, cited by ID from code and docs (e.g. MI-7 is the
human-approval rule). See [`PRODUCT.md`](PRODUCT.md#the-promises).

**Toil** — Necessary technical or process work that is not product work
(e.g. a refactor, a pipeline fix). Handled by the System actor persona, not
treated as a user-facing feature. See [`PRODUCT.md`](PRODUCT.md#personas) and
[`04-lifecycle.md`](04-lifecycle.md).

## Artefacts and communication

**PRD** — Product Requirements Document: the issue body, rewritten by
`prd-writer` into a canonical format (problem, goal, user stories, Gherkin
acceptance criteria, scope, metrics). The approved PRD is the source of truth
for everything downstream. See [`04-lifecycle.md`](04-lifecycle.md#prd-format-and-the-prd-writer-gate).

**Snapshot marker** — An immutable comment (`<!-- ai-agile/snapshot/v1 -->`)
preserving an artefact's original state for the audit trail, e.g. the
stakeholder's issue body before `prd-writer` rewrote it.
See [`PRODUCT.md`](PRODUCT.md#what-lands-on-the-issue).

**Todos block** — The marker-delimited task list stored in an issue or PR
body (not in comments or a separate file), with ISO 8601 timestamps.
See [`13-todos.md`](13-todos.md).

**Retrospective** — The per-ticket reflection produced in the Evaluate phase;
recurring findings feed standards proposals. See [`04-lifecycle.md`](04-lifecycle.md).

## Continuous phase

**Continuous loops** — The three cross-ticket loops in Phase 5: the **Learn
loop** (improve the pipeline), the **Gap-assessment loop** (find missing
product work), and the **Tech-debt loop** (find remediation work). The latter
two file ordinary issues that re-enter the pipeline.
See [`04-lifecycle.md`](04-lifecycle.md).

**Gap-issue / debt-issue** — A new issue proposed by a continuous loop, tagged
with its provenance, that runs through the normal per-ticket pipeline.
See [`04-lifecycle.md`](04-lifecycle.md).

## Setup

**`get_started.py`** — The script that wires this repo into a consuming repo
as a submodule (Linux symlink vs Windows copy) and installs the sync
workflow. See [`16-onboarding.md`](16-onboarding.md).
