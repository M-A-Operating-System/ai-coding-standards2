# AI-First Product Engineering Process

This is one implementation of an AI-first Agile pipeline. We chose a
**Product-First** approach, where every change starts from a well-defined
[product design](02_product-led-design.md) and [roadmap](03_roadmap-specification.md).
The design defines what the product should do and the capabilities it needs.
The roadmap connects those capabilities to business outcomes and sets the
order in which we intend to deliver them.

Each change carries that product intent into its specifications, implementation,
and tests. We use the resulting evidence to see which capabilities have been
delivered and measure roadmap progress. The [orchestrator](../orchestrator/README.md)
runs this workflow and supports other pipeline definitions.

[Product documentation](../README.md)

**Version:** 1.0  
**Status:** Draft Process Standard  
**Folder:** `docs/product/_process`

---

## Purpose

These process standards show how product design and roadmap priorities become
work that people and agents can carry through delivery. People define product
intent, set priorities, and review the results. Agents and scripted steps help
turn approved work into specifications, code, tests, and evidence.

The process is built around one principle.

> Every artifact is codified, machine-readable, human-readable, linearly generated from the previous layer where possible, and traceable backward to its source.

This approach allows product documentation, roadmap planning, capability definition, BDD specifications, test specifications, code, and evidence to remain connected throughout the product lifecycle.

---

## AI-First Operating Model

Traditional software delivery processes were designed for human execution. They assume that humans interpret requirements, break work into tickets, write specifications, write code, create tests, update documentation, and report progress manually.

This repository is designed for a different model.

Humans remain responsible for:

- Product vision
- Business direction
- Product intent
- Prioritization
- Governance
- Review
- Risk judgment
- Approval

AI systems are expected to assist with or perform:

- Product analysis
- Capability decomposition
- Specification generation
- Test generation
- Implementation planning
- Code generation
- Documentation generation
- Traceability analysis
- Progress reporting
- Gap analysis
- Technical debt analysis

The human role shifts from manual production to direction, review, and control.

The AI role shifts from assistant-at-the-edge to active execution engine operating against codified product intent.

---

## Linear Product Knowledge Chain

The chain below follows a capability from product intent through release. The
roadmap groups capabilities by business outcome and delivery phase, and uses
the evidence from this chain to show progress.

```text
Product Intent
    ↓
Product Documentation
    ↓
Modules
    ↓
Components
    ↓
Capabilities
    ↓
BDD Specifications
    ↓
Test Specifications
    ↓
Implementation
    ↓
Evidence
    ↓
Release
```

This chain is intentionally linear.

The process should not require teams to reverse engineer product intent from source code, infer specifications from tests, or manually reconcile roadmap status from delivery tickets. Each artifact should be generated from, linked to, or traceable back to the artifact that preceded it.

The same chain can also be traversed backward.

```text
Release
    ↓
Evidence
    ↓
Test Specification
    ↓
BDD Specification
    ↓
Capability
    ↓
Component
    ↓
Module
    ↓
Product Documentation
    ↓
Product Intent
```

This backward traceability is what allows AI systems and human reviewers to answer questions such as:

- Why does this code exist?
- Which capability does this test verify?
- Which business outcome is impacted by this failure?
- Which roadmap phase is blocked by this missing capability?
- Which product document originally described this behavior?

---

## Machine Readable and Human Readable

Every important artifact should be usable by both humans and machines.

Human readability is required because product, engineering, architecture, security, and business stakeholders must be able to review and approve the work.

Machine readability is required because AI systems, validation tools, reporting pipelines, and automation workflows must be able to parse and reason over the work.

Recommended artifact forms include:

| Artifact | Recommended Form |
| --- | --- |
| Product Documentation | Markdown with stable headings and identifiers |
| Module Definitions | Markdown and/or YAML |
| Component Definitions | Markdown and/or YAML |
| Capability Definitions | YAML with companion Markdown where needed |
| Roadmaps | YAML, generated Markdown |
| BDD Specifications | Gherkin |
| Test Specifications | Code and structured test metadata |
| Evidence | JSON, test reports, CI artifacts |
| Generated Reports | Markdown, JSON, HTML |

Generated documents may be created for human consumption, but generated documents should not become the source of truth.

---

## Desired State, Current State, and Product Gap

Product documentation defines the desired state.

Code, tests, deployments, and evidence define the current state.

The roadmap represents the measured gap between the desired state and the current verified state.

```text
Roadmap Gap
=
Desired Product State
-
Current Verified State
```

Technical debt is related but distinct. Roadmap gap measures what has not been delivered. Technical debt measures what has been delivered but does not yet meet the required engineering, quality, security, reliability, or maintainability standard.

```text
Total Product Gap
=
Undelivered Capabilities
+
Technical Debt
```

This distinction is important because an organization can have a high percentage of delivered capabilities and still carry substantial technical debt.

---

## Repository as Product Knowledge Graph

The repository should function as a product knowledge graph.

Every major artifact should have a stable identifier and explicit links to adjacent artifacts.

Examples:

- A product document references modules.
- A module references components.
- A component references capabilities.
- A capability references BDD specifications.
- A BDD specification references test specifications.
- A test produces evidence.
- An outcome references capabilities.
- A roadmap phase references outcomes.

This creates a graph that can be traversed by humans, automation, and AI agents.

The graph is not separate from the repository. The graph is encoded in the repository through structured files, consistent naming, references, and generated indexes.

---

## Documents in this Folder

| File | Purpose |
| --- | --- |
| `01_ai-first-product-engineering.md` | Defines the foundational AI-first engineering operating model |
| `02_product-led-design.md` | Defines how product documentation describes the desired end state |
| `03_roadmap-specification.md` | Defines how roadmap progress is calculated from capability evidence |
| `04_ai-agile-implementation.md` | Defines the AI-first implementation loop |
| `05_product-architecture-and-technical-architecture.md` | Defines how product architecture and technical architecture operate in parallel |
| [`06_release-management.md`](06_release-management.md) | Defines how verified, merged changes become a versioned release |

These documents are complementary and should be read together.

---

## Summary

This process establishes a product engineering model designed for AI-first implementation.

The core principles are:

- Humans define intent.
- AI performs execution work.
- Product documentation defines the desired state.
- Code and evidence define the current state.
- Capabilities connect product design, roadmap planning, implementation, and verification.
- Every artifact is codified for both humans and machines.
- Every artifact is generated from, linked to, or traceable back to the previous layer.
- Roadmap progress is calculated, not manually maintained.
- Technical debt is measured separately from undelivered capability gap.

The result is a repository that can be read by humans, reasoned over by AI, validated by machines, and used as the system of record for product engineering.
