# Product Architecture and Technical Architecture

**Version:** 1.0  
**Status:** Draft Process Standard  
**Folder:** `docs/_process`

---

## Purpose

This document defines the relationship between product architecture and technical architecture in an AI-first product engineering repository.

Product architecture and technical architecture are complementary but distinct concerns.

Product architecture defines what should exist.

Technical architecture defines how it should be implemented.

Both are required for AI-first implementation.

---

## Core Separation

Product architecture represents product intent and business functionality.

Technical architecture represents implementation guidance and engineering constraints.

They should not be collapsed into one structure.

```text
Product Architecture
    What should the product do?

Technical Architecture
    How should the product be implemented?
```

The intersection point is the capability.

---

## Product Architecture

Product architecture uses the product-led design hierarchy.

```text
Product
    ↓
Module
    ↓
Component
    ↓
Capability
```

This hierarchy describes the desired product state.

It should be written in business and product language.

Example:

```text
Product: Decision Tree Repository
Module: Public Repository
Component: Tree Viewer
Capability: View Public Tree
```

This says what the product should enable.

It does not say which framework, service, database, or deployment model should be used.

---

## Technical Architecture

Technical architecture defines the engineering approach used to implement capabilities.

It may include:

- Architecture principles
- Reference architectures
- Application patterns
- API standards
- Data standards
- Security standards
- Observability standards
- Testing standards
- Deployment standards
- Operational standards
- AI coding standards

Technical architecture answers:

```text
What is the preferred way to implement this capability safely, consistently, and maintainably?
```

---

## Parallel Value Streams

The product process and technical architecture process run in parallel.

```text
Product Value Stream

Product Documentation
    ↓
Module
    ↓
Component
    ↓
Capability
    ↓
BDD Specification
```

```text
Technical Value Stream

Architecture Principles
    ↓
Reference Patterns
    ↓
Engineering Standards
    ↓
Implementation Guidance
    ↓
Code
```

They meet at implementation.

```text
Capability
    +
Technical Guidance
    ↓
Implementation
```

---

## Why They Should Remain Separate

Combining product architecture and technical architecture creates confusion.

Product stakeholders need to understand what the product does.

Engineering teams need to understand how to implement it.

AI systems need both, but for different purposes.

If product documentation contains too much technical implementation detail, it becomes difficult to reuse when technology changes.

If technical architecture contains product intent, implementation guidance becomes too specific and less reusable.

Separation allows the same product capability to be implemented differently over time while preserving product intent.

---

## Capability as the Bridge

Capabilities connect product and technical architecture.

A capability has product meaning and implementation implications.

Example:

```text
Capability:
Search Public Trees
```

Product view:

```text
Users can search public decision trees by keyword and receive relevant results.
```

Technical view:

```text
Use approved search pattern.
Apply public read API standard.
Apply caching guidance.
Apply observability standard.
Meet response time target.
```

The capability becomes the handoff point between product intent and technical implementation.

---

## Technical Guidance Attached to Capabilities

Capabilities may reference technical guidance without embedding all technical detail.

Example:

```yaml
id: search-public-trees
name: Search Public Trees
module: public-repository
component: search
bdd:
  - bdd/public-repository/search-public-trees.feature
technical_guidance:
  architecture_patterns:
    - public-search-service
    - read-optimized-query
  security_patterns:
    - public-read-access
  quality_requirements:
    response_time_ms: 500
    availability: 99.9
```

The detailed standards should live in architecture documentation.

The capability should reference them.

---

## Architecture Documentation Structure

Recommended architecture documentation structure:

```text
docs/
    _architecture/
        00_README.md
        architecture-principles.md
        reference-architectures.md
        engineering-standards.md
        security-standards.md
        testing-standards.md
        observability-standards.md
        ai-coding-standards.md
```

The process standards live in:

```text
docs/_process/
```

Product documentation lives in:

```text
docs/product/
```

This keeps governance, product definition, and technical guidance distinct.

---

## AI-First Implementation Context

AI agents need both product context and technical context.

Product context tells AI what to build.

Technical context tells AI how to build it.

Example AI implementation context:

```text
Product Context:
Capability: Search Public Trees
BDD: bdd/public-repository/search-public-trees.feature

Technical Context:
Use the public search service pattern.
Use the approved API standard.
Use the logging and observability standard.
Use the repository testing standard.
```

Without product context, AI may generate technically correct but product-wrong solutions.

Without technical context, AI may generate product-correct but architecturally inconsistent solutions.

Both are required.

---

## Technical Debt

Technical architecture also defines how technical debt is identified.

A capability may be functionally delivered but still fail to meet technical expectations.

Examples:

- Capability works but lacks required observability.
- Capability works but fails performance targets.
- Capability works but has insufficient test coverage.
- Capability works but does not follow approved security patterns.
- Capability works but creates excessive coupling.

This is technical debt.

Technical debt should be linked to:

- Capability
- Component
- Module
- Technical standard
- Evidence
- Remediation recommendation

---

## Product Gap and Technical Debt Gap

The total product gap has two parts.

```text
Total Product Gap
=
Undelivered Capability Gap
+
Technical Debt Gap
```

Product architecture helps identify the undelivered capability gap.

Technical architecture helps identify the technical debt gap.

Both are required to understand the true state of the product.

---

## Architecture Review in AI-First Delivery

Architecture review should focus on whether AI-generated implementation follows approved guidance.

Review questions include:

- Does the implementation satisfy the capability?
- Does it follow approved architecture patterns?
- Does it meet security standards?
- Does it meet test standards?
- Does it meet observability standards?
- Does it introduce technical debt?
- Is any technical debt explicitly captured and accepted?

AI can assist with architecture review, but human architects or designated reviewers remain accountable for approval where required.

---

## Summary

Product architecture and technical architecture sit in parallel.

Product architecture defines the desired product behavior.

```text
Product
    ↓
Module
    ↓
Component
    ↓
Capability
```

Technical architecture defines implementation best practices.

```text
Principles
    ↓
Patterns
    ↓
Standards
    ↓
Implementation Guidance
```

Capabilities connect the two.

This separation is essential for AI-first implementation because AI systems need both clear product intent and clear technical constraints to generate useful, safe, consistent, and maintainable software.
