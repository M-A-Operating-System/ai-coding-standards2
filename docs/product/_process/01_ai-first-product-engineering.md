# AI-First Product Engineering Standard

**Version:** 1.0  
**Status:** Draft Process Standard  
**Folder:** `docs/_process`

---

## Purpose

This document defines the foundational operating model for AI-first product engineering.

The purpose of this standard is to make product engineering work executable by AI systems while remaining understandable, governable, and auditable by humans.

This is not a traditional engineering process with AI added as a productivity tool. It is a process designed specifically for an environment where humans provide product direction and oversight, while AI performs much of the decomposition, generation, implementation, verification, and reporting work.

---

## Foundational Statement

This repository is an AI-first product engineering system.

Every artifact should be:

- Codified
- Machine-readable
- Human-readable
- Version controlled
- Linearly derived from the previous layer where possible
- Traceable backward to its source

The goal is to create a continuous chain from product intent to executable evidence.

```text
Intent
  ↓
Design
  ↓
Capability
  ↓
Specification
  ↓
Test
  ↓
Code
  ↓
Evidence
```

Humans define the intent.

AI executes the work.

Evidence proves what has been delivered.

---

## Why AI-First Requires a Different Process

Most delivery processes were designed around human interpretation.

They rely on artifacts such as:

- Roadmap decks
- Confluence pages
- Jira tickets
- Informal requirements
- Technical notes
- Manual status updates
- Human memory

These artifacts can work when humans are doing the translation work. They are less effective when AI systems need to perform implementation work because they are often ambiguous, incomplete, duplicated, stale, or disconnected from each other.

AI-first engineering requires a more explicit operating model.

AI systems need product knowledge to be:

- Structured
- Linked
- Versioned
- Testable
- Traceable
- Machine-readable
- Semantically clear

This standard exists to make that possible.

---

## Human Responsibilities

Humans remain accountable for product and engineering outcomes.

Humans are responsible for:

- Product vision
- Business strategy
- Outcome definition
- Product direction
- Prioritization
- Governance
- Risk judgment
- Architecture approval
- Security approval
- User experience approval
- Release approval

Humans do not disappear from the process. They move higher in the control model.

The human role becomes direction, judgment, review, and approval.

---

## AI Responsibilities

AI systems are expected to assist with or perform a large portion of the execution work.

AI systems may be used to:

- Analyze product documentation
- Identify missing capabilities
- Generate capability definitions
- Generate BDD specifications
- Generate test specifications
- Generate implementation plans
- Generate code
- Refactor code
- Generate documentation
- Produce traceability reports
- Produce roadmap progress reports
- Identify technical debt
- Identify missing test coverage
- Explain delivery gaps

AI should operate against codified product intent and engineering standards rather than isolated prompts or disconnected tickets.

---

## The Codification Principle

Every important artifact should be codified.

Codified does not mean unreadable. It means the artifact has enough structure to be interpreted consistently by humans, tools, and AI systems.

Examples:

| Artifact | Codified Form |
| --- | --- |
| Product Overview | Markdown with stable sections |
| Product Module | Markdown or YAML |
| Product Component | Markdown or YAML |
| Capability | YAML with optional Markdown narrative |
| Roadmap | YAML |
| BDD Specification | Gherkin |
| Test Specification | Code and structured metadata |
| Evidence | JSON, CI output, test reports |
| Generated Reports | Markdown, HTML, JSON |

The objective is not to replace human-readable documentation with machine data. The objective is to make the same product knowledge usable by both humans and machines.

---

## Linear Generation Principle

Artifacts should be created in a linear sequence.

```text
Product Documentation
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
```

Each layer should be generated from, informed by, or linked to the prior layer.

A capability should not appear without a product design source.

A BDD specification should not appear without a linked capability.

A test should not appear without a linked specification.

A piece of implementation should be traceable to the capability it delivers.

Evidence should be traceable to the tests and capabilities it proves.

This does not mean every artifact must be generated automatically. It means every artifact must have a clear upstream source.

---

## Backward Traceability Principle

Every downstream artifact must be traceable backward.

Examples:

```text
Test Failure
    ↓
Test Specification
    ↓
BDD Scenario
    ↓
Capability
    ↓
Component
    ↓
Module
    ↓
Product Document
```

```text
Production Defect
    ↓
Capability
    ↓
Outcome
    ↓
Roadmap Phase
```

```text
Code Change
    ↓
Capability
    ↓
BDD Specification
    ↓
Product Intent
```

This traceability allows both humans and AI systems to reason about impact.

---

## Product Knowledge Graph

The repository should be treated as a product knowledge graph.

The graph is formed by relationships between artifacts.

Core nodes include:

- Product
- Module
- Component
- Capability
- Outcome
- Phase
- BDD Feature
- BDD Scenario
- Test
- Code
- Evidence
- Technical Standard
- Architecture Pattern
- Technical Debt Item

Core relationships include:

- Product contains Module
- Module contains Component
- Component contains Capability
- Outcome requires Capability
- Phase contains Outcome
- Capability is verified by BDD Specification
- BDD Specification is implemented by Test
- Test produces Evidence
- Capability follows Technical Standard
- Implementation creates or resolves Technical Debt

The repository does not require a separate graph database to begin using this model. Stable identifiers, structured files, and consistent references are sufficient.

---

## Desired State and Current State

The desired state is the product that should exist.

It is defined through product documentation, modules, components, capabilities, and outcomes.

The current state is what actually exists.

It is evidenced through code, tests, deployments, telemetry, and verification evidence.

The roadmap is the gap between the two.

```text
Desired State
    -
Current Verified State
    =
Roadmap Gap
```

Technical debt is the gap between delivered behavior and required engineering quality.

```text
Delivered Capability
    -
Required Technical Standard
    =
Technical Debt
```

The total product gap is:

```text
Undelivered Capability Gap
+
Technical Debt Gap
```

---

## AI-First Delivery Loop

The intended delivery loop is:

```text
Human defines or updates product intent (docs/product/{capability}.md)
    ↓
AI drafts an issue: user story + Gherkin scenarios
    ↓
Human reviews and approves the issue -- the single approval gate
    ↓
AI copies the approved scenarios into docs/features/{feature}.md
(create the file, append a new scenario, or replace a revised scenario by slug)
    ↓
AI generates tests that realize the scenarios in docs/features/{feature}.md
    ↓
AI generates or modifies code
    ↓
AI runs verification
    ↓
Human reviews evidence
    ↓
Roadmap status is generated
```

Capability scope and Gherkin scenarios are approved together, in the same issue review. There is
no separate capability-approval step: the issue carries both, and human approval of the issue is
the single gate that lets scenarios become a durable, versioned spec. Copying the approved
scenarios into `docs/features/{feature}.md` is a mechanical step, not a second approval -- it
preserves what was already approved.

This loop makes human approval explicit while allowing AI to perform execution work.

---

## Governance

AI-first does not mean unguided automation.

Governance should apply at key control points:

- Product intent approval
- Issue/PRD approval (covers capability scope and Gherkin scenarios in one gate)
- Architecture pattern approval
- Security review
- Test evidence review
- Release approval

The process should make those control points visible and traceable.

---

## Summary

AI-first product engineering requires more than AI coding tools.

It requires a codified product engineering system where every artifact is structured, linked, traceable, and usable by humans and AI.

The key operating model is:

```text
Humans define intent.
AI executes work.
Evidence proves completion.
```

This document defines the foundation. The remaining process documents explain how this foundation applies to product design, roadmaps, implementation, and architecture.
