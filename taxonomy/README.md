# Taxonomy

Version 0.2.0 of the master engineering taxonomy.

## Purpose

Provide a stable JSON-native vocabulary shared across CALM intended architecture, discovered CMDB topology, deterministic code classification, reusable patterns, engineering concepts, concrete implementations, runtimes, and standards/ADR applicability.

## Structure

- `taxonomy.json` — master registry
- `architecture/architecture.json` — canonical architecture classes
- `patterns/patterns.json` — reusable design and implementation patterns
- `code/code.json` — governance-oriented coding roles and structures
- `concepts/concepts.json` — technology-neutral engineering concepts
- `implementations/implementations.json` — concrete technologies mapped to canonical classes
- `runtimes/runtimes.json` — cloud/on-prem realizations
- `mappings/` — CALM, cross-domain, and static-analysis-boundary mappings
- `rules/` — starter deterministic code-classification rules
- `schemas/` — initial JSON Schemas
- `examples/` — example classified architecture and code objects

## Three-level semantic hierarchy

`<domain>/<family>/<class>/<subclass>`

Examples:

- `architecture/data/database/document-database`
- `patterns/persistence/data-access/repository`
- `code/api/handler/request-handler`
- `concepts/reliability/idempotency/request-idempotency`

Concrete technologies are implementations rather than a fourth semantic level. Provider/runtime realization is separate.

## CALM alignment

CALM remains the intended architecture standard. The canonical taxonomy provides finer semantic classification that both CALM intent and discovered CMDB objects can project into for deterministic comparison.

## Code semantics boundary

The taxonomy does not replace primitive static-analysis ontologies. CodeQL or Joern/CPG should own functions, methods, classes/types, calls, imports, control flow, data flow, and API usage. Deterministic rules map those facts into higher-level taxonomy IDs.

## Inheritance

Family, class, and subclass records include `attributes`, `capabilities`, `relationships`, and `constraints`, each supporting `add`, `override`, and `drop`. Effective definitions resolve parent-first.
