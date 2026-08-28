# Taxonomy — Product Documentation

**The Taxonomy** is the canonical semantic vocabulary of the AI-agile
delivery process. It gives intended architecture, discovered infrastructure,
source code, standards, decisions, and reusable assets one shared set of
identifiers, so a claim made in any of them resolves against the same
meaning. Its value is not in modelling every engineering detail; it is in
letting every other part of the system resolve only the context it needs.
The vocabulary itself lives in [`taxonomy/`](../../../taxonomy/) as
versioned JSON, governed through pull requests and enforced in CI.

---

## New here? Start here

Read these three, in this order, and you will understand the system:

1. **[The 60-second summary](#the-60-second-summary)** below — what the
   vocabulary does, in one paragraph.
2. **[01-vision.md](01-vision.md)** — the problem it solves, the seven goals,
   and what success looks like (the *why*).
3. **[03-model.md](03-model.md)** — levels, identity, and facets (the *how*).

Then read **[02-principles.md](02-principles.md)**; the other documents cite
it by ID (`TX-1`…`TX-4`) rather than restating it.

---

## The 60-second summary

Product intent, architecture, code, governance, and observed runtime state
are each described in their own vocabulary — CALM says `database`, a
discovery scan says `AWS::RDS::DBInstance`, a repository contains
`BookingRepository`. Nothing connects them, so every agent rediscovers the
same relationships on each pass, expensively and inconsistently. The
Taxonomy is the single vocabulary they all normalise into: four semantic
domains (**architecture**, **patterns**, **code**, **concepts**), each three
levels deep. Every node has an **immutable identifier** and a **path** that
says where it currently sits — `SUB000042` and
`architecture/data/database/relational-database` — so names and positions can
improve without breaking anything that cited them. The three-letter code records
the level, not the subject, so a node keeps its identity even when it moves.
Dimensions that are not a
kind of thing, such as concern or lifecycle stage, attach as **facets** rather
than levels, which is what lets the same nodes be organised more than one way.
Concrete technologies and cloud services are separate **implementation** and
**runtime** registries pointing at nodes. Because CALM intent and discovered state land on the same
identifiers, the difference between designed and running architecture
becomes computable. Because static-analysis facts map into code classes by
deterministic rule, source structures are classified without AI. And because
standards and decisions target identifiers, an agent can be handed the
context bearing on its work instead of a repository.

---

## Document map

The documents fall into four groups. Start with **Core concepts**; treat the
rest as reference you consult when a question comes up.

### Core concepts — read to understand the system

| # | Document | What it tells you |
|---|---|---|
| 01 | [Vision](01-vision.md) | The problem, what success looks like, and what this is not |
| 02 | [Principles](02-principles.md) | The four rules the model is built on (TX-1…TX-4), cited by ID everywhere else |
| 03 | [Canonical model](03-model.md) | Levels, immutable identity versus mutable path, facets, master registry, inheritance |

### The vocabulary — reference

| # | Document | What it tells you |
|---|---|---|
| 04 | [Semantic domains](04-domains.md) | Architecture, patterns, code, and concepts — what each classifies |
| 05 | [Registries](05-registries.md) | Implementations and runtimes: concrete technology, kept out of the semantic model |
| 11 | [Information model](11-information-model.md) | What a node contains, where each part lives, and what is deliberately excluded |

### Interoperation

| # | Document | What it tells you |
|---|---|---|
| 06 | [Architecture alignment](06-alignment.md) | CALM intent, discovered CMDB state, and comparing the two |
| 07 | [Code classification](07-code-classification.md) | The static-analysis boundary, the classification pipeline, and the AI usage policy |
| 08 | [Consumption](08-consumption.md) | How standards, decisions, reusable assets, and context retrieval use the vocabulary |

### Planning & governance

| # | Document | What it tells you |
|---|---|---|
| 09 | [Capabilities](09-capabilities.md) | The business outcomes the vocabulary exists to enable, and their roadmap alignment |
| 10 | [Governance](10-governance.md) | Versioning, deprecation, what earns an entry, change process, and ownership |

---

## Related

- [`taxonomy/README.md`](../../../taxonomy/README.md) — structure and
  authoring conventions for the JSON itself.
- [`14-standards.md`](../standards/14-standards.md) — the two-tier
  standards system whose applicability this vocabulary is designed to target.
- [`05_product-architecture-and-technical-architecture.md`](../_process/05_product-architecture-and-technical-architecture.md)
  — the architecture narrative this documentation sits within.
