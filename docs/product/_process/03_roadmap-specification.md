# Roadmap Specification

**Version:** 1.0  
**Status:** Draft Process Standard  
**Folder:** `docs/_process`

---

## Purpose

This document defines how roadmaps are represented, measured, and generated in an AI-first product engineering repository.

The roadmap is not treated as a manually maintained planning artifact.

The roadmap is a calculated representation of the gap between the desired product state and the current verified state.

```text
Roadmap
=
Desired Product State
-
Current Verified State
```

Roadmap progress is derived from capability evidence.

---

## Relationship to AI-First Product Engineering

AI-first implementation requires the roadmap to be machine-readable, traceable, and generated from product and evidence artifacts.

AI systems need to know:

- What capabilities exist in the desired state
- Which outcomes those capabilities support
- Which phase those outcomes belong to
- Which capabilities are verified
- Which capabilities are missing, blocked, or incomplete
- Which technical debt items affect delivered capabilities

A codified roadmap allows AI systems to generate status and recommendations without relying on manual updates.

---

## Relationship to Product-Led Design

Product-led design defines the desired state.

The roadmap measures progress toward that desired state.

Product-led design uses:

```text
Product
    ↓
Module
    ↓
Component
    ↓
Capability
```

The roadmap uses:

```text
Phase
    ↓
Outcome
    ↓
Capability
```

Capabilities connect both structures.

---

## Core Roadmap Principle

The roadmap should be capability-driven.

Capabilities are the unit of roadmap progress because they are:

- Derived from product documentation
- Linked to modules and components
- Linked to outcomes
- Linked to BDD specifications
- Verified by tests and evidence

A roadmap item is complete only when the required capabilities are verified.

---

## Business Roadmap Model

The v1 roadmap model uses the following structure:

```text
Phase
    ↓
Outcome
    ↓
Capability
```

This separates business planning from product architecture.

Product architecture defines what is built.

Roadmap planning defines why and when capabilities are delivered.

---

## Phase

A Phase represents a delivery period, planning horizon, or major increment of product maturity.

Examples:

- Foundation
- Public Launch
- Enterprise Readiness
- Scale
- Optimization

A phase contains outcomes.

A phase should not directly contain implementation tasks.

A phase should not directly contain modules or components.

A phase exists to organize business outcomes over time.

---

## Outcome

An Outcome is a measurable business result the product should achieve.

Examples:

- Increase Public Tree Usage
- Enable AI Consumption
- Improve Search Adoption
- Reduce User Onboarding Time
- Improve Enterprise Readiness

Outcomes are achieved through one or more capabilities.

An outcome may require capabilities from multiple modules or components.

Outcomes explain why capabilities are being delivered.

---

## Capability

A Capability is the shared unit between product design, roadmap planning, and implementation.

In the roadmap, capabilities represent the work required to achieve an outcome.

In the product architecture, capabilities represent functions provided by components.

In verification, capabilities represent behavior proven by BDD and test evidence.

This makes capabilities the canonical roadmap object.

---

## Codified Roadmap

The roadmap should be stored in a structured, machine-readable form.

Recommended source of truth:

```text
roadmap.yaml
```

Human-readable roadmap documents may be generated from the YAML source.

Generated roadmap documents should not be manually maintained.

---

## Example Roadmap Structure

```yaml
version: 1

phases:
  foundation:
    name: Foundation
    outcomes:
      - increase-public-tree-usage
      - enable-ai-consumption

outcomes:
  increase-public-tree-usage:
    name: Increase Public Tree Usage
    description: Increase public engagement with published decision trees.
    capabilities:
      - search-public-trees
      - view-public-tree

  enable-ai-consumption:
    name: Enable AI Consumption
    description: Allow AI systems to consume decision tree definitions.
    capabilities:
      - download-tree-dsl
      - download-tree-json
```

This structure keeps the roadmap simple.

The roadmap does not redefine modules or components.

The roadmap references capabilities.

---

## Capability Links

Each capability should define or reference:

- Capability identifier
- Name
- Description
- Owning component
- Owning module
- Related outcomes
- BDD specifications
- Dependencies
- Verification evidence

Example:

```yaml
id: search-public-trees
name: Search Public Trees
module: public-repository
component: search
bdd:
  - bdd/public-repository/search-public-trees.feature
```

The roadmap references this capability rather than duplicating the capability details.

---

## Status is Derived

Roadmap status must not be manually maintained.

Manual status creates drift.

Instead, status should be derived from evidence.

```text
Capability Status
    ↓
Outcome Status
    ↓
Phase Status
```

A phase is only as complete as its outcomes.

An outcome is only as complete as its required capabilities.

A capability is only as complete as its verification evidence.

---

## Capability Status

Capability status is calculated from linked specifications, tests, and evidence.

Recommended states:

| Status | Meaning |
| --- | --- |
| Not Defined | Capability is referenced but not defined |
| Defined | Capability exists but has no BDD coverage |
| Specified | Capability has BDD coverage but no passing test evidence |
| In Progress | Some evidence exists but capability is not fully verified |
| Verified | All required evidence passes |
| Failed | Required evidence exists but is failing |
| Blocked | Capability cannot progress due to dependency or decision |

A capability should only be considered verified when all required evidence passes.

---

## Outcome Status

Outcome progress is calculated from required capability status.

```text
Outcome Progress
=
Verified Required Capabilities
/
Total Required Capabilities
```

Example:

```text
Outcome: Enable AI Consumption

Required Capabilities:
- Download Tree DSL: Verified
- Download Tree JSON: In Progress
- Publish Machine-Readable Metadata: Not Started

Progress: 1 / 3 = 33%
```

---

## Phase Status

Phase progress is calculated from outcome progress.

```text
Phase Progress
=
Average or Weighted Outcome Progress
```

The weighting model should be explicit if outcomes are not equally weighted.

---

## Roadmap Gap

The roadmap gap is the set of capabilities required by roadmap outcomes that are not yet verified.

```text
Roadmap Gap
=
Required Capabilities
-
Verified Capabilities
```

This gap can be reported by:

- Phase
- Outcome
- Module
- Component
- Capability owner
- BDD coverage
- Dependency
- Risk level

---

## Technical Debt and Roadmap Progress

Technical debt should be tracked separately from undelivered capability progress.

Roadmap progress asks:

```text
Which desired capabilities have not yet been verified?
```

Technical debt asks:

```text
Which delivered capabilities do not meet required technical standards?
```

Both matter.

A capability can be functionally verified while still carrying technical debt.

Examples of technical debt include:

- Missing non-functional tests
- Poor performance
- Weak observability
- Security findings
- Excessive complexity
- Fragile implementation
- Incomplete documentation
- Manual operational procedures

The total product gap is:

```text
Total Product Gap
=
Undelivered Capability Gap
+
Technical Debt Gap
```

---

## Generated Roadmap Reports

The following reports should be generated from roadmap, capability, BDD, and evidence files:

- Roadmap Status Report
- Phase Progress Report
- Outcome Progress Report
- Capability Coverage Report
- BDD Coverage Report
- Test Evidence Report
- Technical Debt Report
- Dependency Report
- Release Readiness Report
- Traceability Report

These reports are outputs.

They should not become systems of record.

---

## AI Use Cases

A codified roadmap allows AI systems to answer:

- Which capabilities are required for Phase 1?
- Which outcomes are blocked?
- Which capabilities lack BDD coverage?
- Which capabilities are verified?
- Which components have the largest roadmap gap?
- Which modules contribute to the most outcomes?
- Which roadmap items are blocked by technical debt?
- What implementation plan would close the next roadmap gap?
- What is the minimum set of capabilities required for the next release?

These answers should be generated from repository artifacts, not manual status comments.

---

## Summary

The roadmap is a generated view of product progress.

It is not a manually maintained list of projects.

The roadmap model is:

```text
Phase
    ↓
Outcome
    ↓
Capability
```

Capabilities connect roadmap planning to product design and implementation evidence.

Status is derived from verification evidence.

The roadmap gap is the difference between the desired product state and the current verified state.

This model makes roadmap reporting machine-readable, human-readable, traceable, and suitable for AI-first implementation.
