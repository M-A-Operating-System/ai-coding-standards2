# AI Agile — Product Documentation

This directory describes **AI Agile**: a product development lifecycle in which
specialised AI agents move every change from a single GitHub issue through to
shipped, tested, documented code — with humans approving at well-defined gates.

These documents describe the target state. They are deliberately written as
"this is how it works" rather than "this is what we plan." We will evolve them
as the system matures.

---

## Read these first

| Document | What it tells you |
|---|---|
| [vision.md](vision.md) | The problem, our principles, what success looks like |
| [personas.md](personas.md) | Who uses AI Agile and what they need from it |
| [lifecycle.md](lifecycle.md) | The seven phases an issue passes through |
| [glossary.md](glossary.md) | Terms used across the system |

## Then go deeper

| Document | What it tells you |
|---|---|
| [agents.md](agents.md) | The agent catalogue and what each one owns |
| [human-gates.md](human-gates.md) | Where humans approve, and what they are signing off |
| [status-model.md](status-model.md) | The label-driven state machine that drives the pipeline |
| [standards.md](standards.md) | How standards are written, applied, and evolved |

## Phase deep dives

Each phase has its own document describing inputs, outputs, agents, and gates:

| Phase | Document | Outcome |
|---|---|---|
| 1 | [Product docs](phases/01-product-docs.md) | A reviewed PRD, sized ticket, no unresolved external dependencies |
| 2 | [Technical docs](phases/02-technical-docs.md) | An approved technical design, ADRs drafted where warranted |
| 3 | [Testing spec](phases/03-testing-spec.md) | Numbered Gherkin scenarios covering every acceptance criterion |
| 4 | [Build plan](phases/04-build-plan.md) | An ordered list of child tasks with a dependency-aware build order |
| 5 | [Execute](phases/05-execute.md) | One PR per task, standards-compliant, reviewed |
| 6 | [Test](phases/06-test.md) | Tests written from the spec, green suite, coverage gates met |
| 7 | [Evaluate](phases/07-evaluate.md) | Changelog, retrospective, and proposed evolutions to the standards |

---

## One-paragraph summary

Every change starts as a GitHub issue. The pipeline orchestrator reads status
labels on that issue, identifies which agent is eligible to run next based on a
declared dependency graph, and invokes it. Each agent produces a single
artefact — a PRD, a design, a test spec, a PR, a retrospective — and either
marks itself complete or requests human review. Humans approve at gates by
applying or removing labels. Code is held to standards declared in
machine-readable JSON, and recurring violations feed the next iteration of
those standards. The whole loop is designed to be transparent, resumable, and
auditable on GitHub.
