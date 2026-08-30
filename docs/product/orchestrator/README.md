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
2. **[PRODUCT.md](PRODUCT.md#vision)** — the problem this solves and what
   the orchestrator promises (the *why* and the *what*).
3. **[04-lifecycle.md](04-lifecycle.md)** — the five phases, then its
   [End-to-end happy path](04-lifecycle.md#end-to-end-happy-path) section,
   which walks one ticket from issue to merged PR (the *how*).
4. **[glossary.md](glossary.md)** — keep it open; the other docs assume the
   terms it defines (gate, sentinel, work item, `:wip`, session, …).

Want to skip straight to running something? See **[quick-start.md](quick-start.md)**
for the shortest path to a first pipeline run.

Then read **[PRODUCT.md](PRODUCT.md#personas)** to find your own role, and
dip into the reference docs below as you need them. You do **not** need to
read all of them in order to get started.

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
| — | [Vision](PRODUCT.md#vision) | The problem, and what the orchestrator promises |
| — | [The promises](PRODUCT.md#the-promises) | The architectural-separation guarantees (AS-1 to AS-3) and mode invariants (MI-1 to MI-8) the system is built on, cited by ID everywhere else |
| — | [Personas](PRODUCT.md#personas) | Who uses AI Agile; the enforced vocabulary lives in [`standards/personas.json`](../../../standards/personas.json) |
| 04 | [Lifecycle](04-lifecycle.md) | The five phases (four per-ticket + one continuous) plus on-demand agents, with an end-to-end walkthrough |

### How the machine works — reference

| # | Document | What it tells you |
|---|---|---|
| — | [Audit log](PRODUCT.md#mi-6----you-can-believe-what-the-system-tells-you) | The immutable JSONL event timeline: where it lives, and the shape of one record |

### Building & operating

| # | Document | What it tells you |
|---|---|---|
| 16 | [Onboarding](16-onboarding.md) | How `get_started.py` wires this repo into a consuming repo |
| — | [Quick Start](quick-start.md) | Shortest path to a first pipeline run, in either operating mode |
| — | [Standards](../standards/14-standards.md) | The two-tier standards system, taxonomy, and ADR scoping -- lives in its own `docs/product/standards/` area, not this one; standards enforcement is agent behaviour, not orchestrator mechanism |

### Planning & status

| # | Document | What it tells you |
|---|---|---|
| 15 | [Backlog](15-backlog.md) | Point-in-time snapshot of open issues (GitHub is authoritative) |
| — | [Glossary](glossary.md) | Plain-language definitions of every term used above |
| — | [Retirement log](retirement-log.md) | Where each retired legacy document's content ended up -- history of the consolidation, not part of the design |

---

## Generated views

Authoritative facts about the pipeline are declared once in
`pipeline/pipeline.json` and rendered for human reading by
`pipeline/generators/generate_phase_mermaid.py`. These files are never
hand-edited and are committed in the same PR as any change to the source
JSON (see [P-2](PRODUCT.md#as-1----one-file-tells-you-what-the-pipeline-does)).
The generated views are listed in
[`generated/README.md`](generated/README.md); whole-pipeline catalogues
(agents, gates) are tracked in [`backlog.md`](15-backlog.md).
