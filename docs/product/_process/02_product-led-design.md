# Product-Led Design Standard

**Version:** 1.0  
**Status:** Draft Process Standard  
**Folder:** `docs/_process`

---

## Purpose

This document defines how products are designed and documented in an AI-first product engineering repository.

Product-led design means that product documentation defines the desired future state of the product before implementation work is planned or executed.

The product definition is the source of truth for what should exist.

Implementation is evidence of how much of that desired state has been realized.

---

## Relationship to AI-First Product Engineering

This standard supports the AI-first engineering model by making product intent explicit, structured, and traceable.

AI systems can only implement effectively when they understand what product outcome they are trying to create.

Product-led design provides that intent.

```text
Product Documentation
    ↓
Modules
    ↓
Components
    ↓
Capabilities
    ↓
BDD Specifications
```

Each layer should be understandable to humans and usable by AI systems.

---

## Product Documentation Defines Desired State

Product documentation describes the final desired state of a product.

It should answer:

```text
What should the product become?
```

It should not primarily answer:

```text
How has the product currently been implemented?
```

The current implementation may be incomplete, transitional, or technically constrained. Product documentation should define the intended end state clearly enough that AI systems and human teams can work toward it.

---

## Desired State and Current State

The distinction between desired state and current state is central.

Desired state is defined by:

```text
Product Documentation
    ↓
Module
    ↓
Component
    ↓
Capability
```

Current state is evidenced by:

```text
Code
    ↓
Tests
    ↓
Verification Evidence
```

The roadmap is the measured gap between desired state and current verified state.

---

## Product Design Hierarchy

The v1 product design model uses three product architecture layers below the product itself.

```text
Product
    ↓
Module
    ↓
Component
    ↓
Capability
```

This hierarchy defines what the product should contain.

---

## Product

A Product is a complete business solution or product experience.

A repository may contain documentation for one product or multiple products.

Each product should have a clear product overview that describes:

- Product purpose
- Target users
- Business context
- Core outcomes
- Primary modules
- Major user journeys
- Design principles

The product overview should be written for both humans and AI systems.

---

## Module

A Module is a major product area.

Modules organize the product into stable business areas.

Examples:

- Public Repository
- Authoring
- Administration
- Analytics
- Identity Management

A module should describe a meaningful area of product functionality, not a technical subsystem.

A module document should include:

- Module purpose
- Business responsibilities
- Primary users
- Components
- Key workflows
- Related outcomes
- Ownership where applicable

---

## Component

A Component is a logical subsystem within a module.

Components group related capabilities.

Examples:

- Tree Viewer
- Search
- Download Services
- User Management
- Security Configuration

A component document should include:

- Component purpose
- Responsibilities
- Supported capabilities
- User interactions
- Business rules
- Dependencies on other components
- Relevant design notes

Components should describe product behavior and business responsibility rather than technical implementation.

---

## Capability

A Capability is a discrete business function delivered by the product.

Capabilities are the primary unit of AI-first implementation.

Examples:

- Search Public Trees
- View Public Tree
- Download Tree DSL
- Publish Decision Tree
- Configure SSO Provider

Capabilities should be named in business language.

Good capability names:

```text
Search Public Trees
Download Tree DSL
Publish Decision Tree
Approve User Registration
```

Poor capability names:

```text
Build Search API
Create React Component
Add Database Table
Implement Lambda Function
```

Capabilities should describe what the product enables, not how the implementation works.

---

## Capabilities as the Bridge to Implementation

Capabilities are where product design becomes executable.

Each capability should be traceable to:

- Product document
- Module
- Component
- Business outcome
- BDD specification
- Tests
- Evidence

The capability is the central link between product intent and implementation work.

```text
Product Design
    ↓
Capability
    ↓
BDD Specification
    ↓
Test
    ↓
Implementation
    ↓
Evidence
```

---

## Product Documentation for Humans and AI

Product documentation should be written in a style that supports both human review and AI consumption.

Recommended practices:

- Use stable headings.
- Use consistent terminology.
- Use explicit identifiers where practical.
- Avoid vague language.
- Avoid unexplained assumptions.
- Separate business behavior from implementation details.
- Link to related modules, components, capabilities, and outcomes.
- Use tables for structured lists.
- Use examples to clarify behavior.

AI systems should be able to read the product documentation and propose a capability model without needing hidden context.

---

## Product Documentation Should Avoid Implementation Detail

Product documentation should avoid over-specifying technology unless technology is itself part of the product behavior.

Avoid including:

- Framework choices
- Database table designs
- Internal service names
- Deployment topology
- Low-level code structure

Those belong in technical architecture or implementation documentation.

Product documentation defines the destination.

Technical architecture defines the preferred route.

Implementation defines the current location.

---

## Capability Derivation

Capabilities should be derived from product documentation.

A capability should exist because a product document describes a business behavior, user outcome, or product function that requires it.

The derivation should be traceable.

Example:

```text
Product Document:
Users can search public decision trees by keyword.

Derived Capability:
Search Public Trees

Generated BDD:
Feature: Search Public Trees
```

This makes the capability catalog an explicit representation of the product design.

---

## Recommended Repository Pattern

For a repository containing multiple product definitions, product documentation may be organized as:

```text
docs/
    product/
        product-a/
            overview.md
            modules/
            components/
            capabilities/
        product-b/
            overview.md
            modules/
            components/
            capabilities/
```

The process standards remain shared under:

```text
docs/_process/
```

The process folder defines how product documentation should work.

The product folder contains the actual product definitions.

---

## Product-Led Design Workflow

Recommended workflow:

```text
1. Human defines or updates product intent.
2. AI analyzes the product document.
3. AI proposes modules, components, and capabilities.
4. Human reviews and approves the structure.
5. AI generates capability definitions.
6. Human reviews and approves capability definitions.
7. AI generates BDD specifications from capabilities.
8. BDD specifications become the basis for test and implementation work.
```

This workflow keeps humans in control of intent and approval while using AI to perform analysis and generation.

---

## Product Design Completion

Product design completion is not the same as implementation completion.

Product design completion means:

- Product documentation exists.
- Modules are defined.
- Components are defined.
- Capabilities are identified.
- Capabilities are linked to product intent.
- Capabilities are ready for specification.

Implementation completion is measured separately through evidence.

---

## Summary

Product-led design defines the desired future state of the product.

The design hierarchy is:

```text
Product
    ↓
Module
    ↓
Component
    ↓
Capability
```

Capabilities are the bridge between product intent and AI-first implementation.

Product documentation should be written for both humans and AI systems. It should be structured, explicit, traceable, and focused on desired product behavior rather than current implementation details.

The output of product-led design is a codified product model that AI systems can use to generate specifications, tests, implementation plans, and code under human oversight.
