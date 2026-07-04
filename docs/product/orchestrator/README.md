# AI Agile — Product Documentation

**AI Agile** is a complete, self-contained agentic framework for a
product-led software development lifecycle, delivered as a single git
submodule. Specialised AI agents move every change from a single GitHub
issue through to shipped, tested, documented code — with humans approving at
well-defined gates. Everything runs on GitHub: issues, labels, comments,
branches, and PRs. There is no sidecar database, no separate dashboard, and
no hidden state. A consuming repo drops the submodule in and inherits the
whole lifecycle; this repo stays the sole definition of every agent,
pipeline stage, gate, and standard. The only thing a project owns locally is
its ADRs — the exceptions it records against the centrally-defined standards.

---

## New here? Start here

Read these four, in this order, and you will understand the system:

1. **[The 60-second summary](#the-60-second-summary)** below — the whole
   loop in one paragraph.
2. **[01-vision.md](01-vision.md)** — the problem this solves and what
   success looks like (the *why*).
3. **[04-lifecycle.md](04-lifecycle.md)** — the five phases, then its
   [End-to-end happy path](04-lifecycle.md#end-to-end-happy-path) section,
   which walks one ticket from issue to merged PR (the *how*).
4. **[glossary.md](glossary.md)** — keep it open; the other docs assume the
   terms it defines (gate, sentinel, work item, `:wip`, session, …).

Then read **[03-personas.md](03-personas.md)** to find your own role, and
dip into the reference docs below as you need them. You do **not** need to
read all 16 documents in order to get started.

---

## The 60-second summary

Every change starts as a GitHub issue. The **orchestrator** — a
deterministic Python program — reads the status **labels** on that issue,
identifies which **agent** is eligible to run next based on the dependency
graph in [`pipeline/pipeline.json`](../../../pipeline/pipeline.json), and
invokes it. Each agent does one job and produces a single artefact — a PRD,
a design, a PR, a retrospective — then either marks itself complete or
requests human review. Humans approve at **gates** by applying a label;
they never edit the agent's work to push it through. Every transition is
appended to an immutable **audit log**. Code is held to **standards**
declared in machine-readable JSON, and recurring violations feed the next
iteration of those standards. The whole loop is transparent, resumable, and
auditable on GitHub alone.

---

## Document map

The docs fall into four groups. Start with **Core concepts**; treat the
rest as reference you consult when a question comes up.

### Core concepts — read to understand the system

| # | Document | What it tells you |
|---|---|---|
| 01 | [Vision](01-vision.md) | The problem, and what success looks like |
| 02 | [Principles](02-principles.md) | The 16 rules the system is built on (P-1…P-16), cited by ID everywhere else |
| 03 | [Personas](03-personas.md) | Who uses AI Agile and what each needs from it |
| 04 | [Lifecycle](04-lifecycle.md) | The five phases (four per-ticket + one continuous) plus on-demand agents, with an end-to-end walkthrough |

### How the machine works — reference

| # | Document | What it tells you |
|---|---|---|
| 05 | [Pipeline configuration](05-pipeline-config.md) | `pipeline.json`: the single file that declares the agent graph |
| 06 | [Status model](06-status-model.md) | The label-driven state machine and who may change what |
| 07 | [Human gates](07-human-gates.md) | Every gate: who approves and what they are signing off |
| 08 | [Audit log](08-audit-log.md) | The immutable JSONL event timeline |
| 09 | [Human interaction](09-human-interaction.md) | How agents and humans communicate; the Question Card protocol |

### Building & operating

| # | Document | What it tells you |
|---|---|---|
| 11 | [Orchestrator](11-orchestrator.md) | The Python orchestrator's internal design and GitHub Actions workflows |
| 12 | [Agent specification](12-agent-spec.md) | How to write an agent prompt file: frontmatter, body, tool allowlist |
| 13 | [Todos](13-todos.md) | How task lists are stored in issue/PR bodies |
| 14 | [Standards](14-standards.md) | The two-tier standards system, taxonomy, and ADR scoping |
| 16 | [Onboarding](16-onboarding.md) | How `get_started.py` wires this repo into a consuming repo |

### Planning & status

| # | Document | What it tells you |
|---|---|---|
| 10 | [Roadmap](10-roadmap.md) | What ships now versus later; MVP scope and rollout phases |
| 15 | [Backlog](15-backlog.md) | Point-in-time snapshot of open issues (GitHub is authoritative) |
| — | [Glossary](glossary.md) | Plain-language definitions of every term used above |

---

## Generated views

Authoritative facts about the pipeline are declared once in
`pipeline/pipeline.json` and rendered for human reading by
`pipeline/generators/generate_phase_mermaid.py`. These files are never
hand-edited and are committed in the same PR as any change to the source
JSON (see [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated)).
The generated views are listed in
[`generated/README.md`](generated/README.md); whole-pipeline catalogues
(agents, gates) are tracked in [`backlog.md`](15-backlog.md).
