# AI-Agile Implementation Approach

**Version:** 1.0  
**Status:** Draft Process Standard  
**Folder:** `docs/_process`

---

## Purpose

This document defines the implementation approach used to convert product intent into verified software in an AI-first product engineering repository.

The approach combines:

- Product-led design
- Capability-driven roadmaps
- Behavior Driven Development
- AI-assisted implementation
- Evidence-based verification

This is not traditional Agile with AI assistance. It is an AI-first implementation process where humans provide direction and oversight while AI systems perform much of the delivery work.

---

## Core Philosophy

The purpose of delivery is not to complete tickets.

The purpose of delivery is to realize product intent.

The product intent is codified in product documentation, modules, components, capabilities, outcomes, and BDD specifications.

AI systems operate against that codified intent to generate implementation plans, tests, code, documentation, and evidence.

Humans remain responsible for review, governance, and approval.

---

## Implementation Chain

The implementation process follows a linear chain.

```text
Product Documentation
    ↓
Capability
    ↓
BDD Specification
    ↓
Test Specification
    ↓
Implementation Plan
    ↓
Code
    ↓
Evidence
```

Each artifact should be generated from or traceable to the prior artifact.

This linear chain allows AI systems to perform work without losing product context.

---

## Human Role

Humans provide direction and oversight.

Human responsibilities include:

- Define product intent
- Approve product design
- Approve capability definitions
- Approve BDD specifications
- Approve architecture patterns
- Review AI-generated plans
- Review AI-generated code where required
- Review test evidence
- Approve releases
- Make trade-off decisions
- Accept or reject technical debt

Humans do not need to manually perform every translation step.

---

## AI Role

AI systems perform execution work.

AI responsibilities may include:

- Analyze product documentation
- Generate capability definitions
- Identify missing capabilities
- Generate BDD scenarios
- Generate test specifications
- Generate implementation plans
- Generate code
- Modify existing code
- Generate documentation
- Run tests
- Interpret failures
- Propose fixes
- Generate progress reports
- Generate traceability reports
- Identify technical debt

AI works best when each step has a clear upstream input and a clear downstream output.

---

## AI-First Delivery Loop

The recommended loop is:

```text
1. Human defines or updates product intent.
2. AI derives or updates capabilities.
3. Human reviews and approves capabilities.
4. AI generates BDD specifications.
5. Human reviews and approves BDD.
6. AI generates tests and implementation plans.
7. AI implements code changes.
8. AI executes verification.
9. Human reviews evidence.
10. Roadmap and traceability reports are generated.
```

This loop preserves human control while allowing AI to do the work.

---

## Capability Intake

Work should enter the implementation process as capabilities, not vague tasks.

A capability entering implementation should have:

- Stable identifier
- Product source
- Module
- Component
- Business description
- Linked outcome
- Acceptance expectations
- BDD specification status
- Dependencies
- Relevant architecture guidance

If a capability lacks these elements, AI should flag the gap before implementation begins.

---

## BDD as the Implementation Contract

BDD specifications translate capability intent into executable behavior.

BDD is the contract between product design and implementation.

Example:

```gherkin
Feature: Search Public Trees

Scenario: Search for a published tree
  Given published decision trees exist
  When a user searches for "mortgage"
  Then matching decision trees are displayed
```

AI can use BDD specifications to:

- Generate tests
- Generate implementation plans
- Identify missing edge cases
- Validate expected behavior
- Explain failures

BDD should remain understandable by product, engineering, QA, and AI systems.

---

## Test Specification Generation

Test specifications should be generated from BDD scenarios.

Each test should be traceable to:

- BDD feature
- BDD scenario
- Capability
- Component
- Module
- Outcome where applicable

Tests should produce structured evidence that can be consumed by reports and AI systems.

---

## Implementation Planning

AI-generated implementation plans should include:

- Capability being implemented
- Linked BDD scenarios
- Files likely to change
- Architecture patterns to follow
- Technical standards to apply
- Test strategy
- Risks
- Assumptions
- Required human decisions

Implementation plans should be reviewed before major changes are made.

---

## Code Generation and Modification

AI may generate or modify code, but code should remain subordinate to product intent and technical standards.

Code should be traceable to capabilities.

Where practical, commits and pull requests should reference capability identifiers.

Implementation should follow approved technical architecture, engineering standards, security standards, and testing standards.

---

## Evidence Generation

Evidence proves what has been delivered.

Evidence may include:

- Passing BDD tests
- Unit test results
- Integration test results
- End-to-end test results
- Deployment validation
- Security scans
- Performance results
- Operational telemetry
- Manual approval records where required

Evidence should be structured and machine-readable where possible.

Evidence updates roadmap progress.

---

## Progress Reporting

Progress should be generated from evidence.

Manual status reporting should be avoided.

Reports should answer:

- Which capabilities are verified?
- Which capabilities are in progress?
- Which capabilities have failing tests?
- Which capabilities lack BDD?
- Which outcomes are blocked?
- Which roadmap phase is closest to completion?
- Which delivered capabilities carry technical debt?

Progress should be calculated, not declared.

---

## Technical Debt Handling

AI-first implementation must distinguish between undelivered capability and technical debt.

Undelivered capability means the product behavior does not yet exist or is not yet verified.

Technical debt means the behavior exists but the implementation does not meet required standards.

AI systems should identify technical debt during implementation and verification.

Technical debt should be linked to:

- Capability
- Component
- Module
- Technical standard
- Evidence or finding
- Recommended remediation

---

## Pull Request Expectations

Pull requests should be generated or structured around capabilities.

A pull request should ideally include:

- Capability identifier
- Linked BDD specifications
- Summary of behavior delivered
- Tests added or updated
- Evidence generated
- Architecture guidance followed
- Known technical debt
- Human review areas

This makes pull requests easier for humans to review and easier for AI systems to analyze.

---

## AI Review and Human Approval

AI can perform first-level review.

AI review may check:

- Traceability
- Test coverage
- Architecture compliance
- Security standards
- Documentation updates
- Roadmap impact
- Technical debt

Human approval remains required for important changes, release decisions, and risk acceptance.

---

## Summary

The AI-Agile Implementation Approach is a delivery model where:

```text
Humans define intent and approve outcomes.
AI generates and implements work.
Evidence proves delivery.
```

The process is linear, codified, and traceable.

It turns product documentation into capabilities, capabilities into BDD, BDD into tests, tests into implementation, and implementation into evidence.

This creates an implementation process suitable for AI-first product engineering while preserving human governance and accountability.
