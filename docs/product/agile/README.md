# AI Agile — Product Documentation

This directory describes **AI Agile**: a product development lifecycle in
which specialised AI agents move every change from a single GitHub issue
through to shipped, tested, documented code — with humans approving at
well-defined gates.

These documents describe the target state. They are deliberately written
as "this is how it works" rather than "this is what we plan." We will
evolve them as the system matures.

---

## Reading order

| # | Document | What it tells you |
|---|---|---|
| 01 | [Vision](01-vision.md) | The problem, what success looks like |
| 02 | [Principles](02-principles.md) | The rules AI Agile is built on (P-1..P-15) |
| 03 | [Personas](03-personas.md) | Who uses AI Agile and what they need from it |
| 04 | [Lifecycle](04-lifecycle.md) | Seven per-ticket phases plus three continuous cross-ticket phases (Learn, Gap assessment, Tech debt) |
| 05 | [Pipeline configuration](05-pipeline-config.md) | The single JSON file that declares the agent graph |
| 06 | [Status model](06-status-model.md) | The label-driven state machine |
| 07 | [Human gates](07-human-gates.md) | Where humans approve, and what they are signing off |
| 08 | [Audit log](08-audit-log.md) | The immutable cross-session timeline branch |
| 09 | [Human interaction](09-human-interaction.md) | How agents and humans communicate; the Question Card protocol |
| 10 | [Roadmap](10-roadmap.md) | MVP scope, agent merges, and phased rollout |
| 11 | [Orchestrator](11-orchestrator.md) | Python orchestrator technical design, decision logic, and GitHub Actions workflows |
| 12 | [Agent specification](12-agent-spec.md) | Required shape of an agent prompt file: frontmatter, body sections, tool allowlist |
| 13 | [Todos](13-todos.md) | How tasks are stored in issue/PR bodies, with ISO 8601 timestamps |

## Generated views

Authoritative facts about the pipeline are declared once in
`pipeline/pipeline.json` and rendered for human reading at:

| File | Description |
|---|---|
| [`generated/agents.md`](generated/agents.md) | Catalogue of every agent, its role, dependencies, and gate |
| [`generated/phases.md`](generated/phases.md) | Agents grouped by phase, in dependency order |
| [`generated/gates.md`](generated/gates.md) | The full list of human gates |
| `generated/pipeline.mmd` | Full mermaid flowchart |
| `generated/pipeline-issue.mmd` | Issue subgraph |
| `generated/pipeline-pr.mmd` | PR subgraph |

These files are produced by `pipeline/generators/` and committed
in the same PR as any change to the source JSON. They are not
hand-edited. See [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated).

---

## One-paragraph summary

Every change starts as a GitHub issue. The pipeline orchestrator reads
status labels on that issue, identifies which agent is eligible to run
next based on the dependency graph in
[`pipeline/pipeline.json`](../../../pipeline/pipeline.json),
and invokes it. Each agent produces a single artefact — a PRD, a design,
a test spec, a PR, a retrospective — and either marks itself complete or
requests human review. Humans approve at gates by applying or removing
labels. Every transition is appended to an immutable audit log branch.
Code is held to standards declared in machine-readable JSON, and
recurring violations feed the next iteration of those standards. The
whole loop is designed to be transparent, resumable, and auditable on
GitHub alone — no sidecar database, no separate dashboard, no hidden
state.
