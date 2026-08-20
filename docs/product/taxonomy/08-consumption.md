# Consumption

Everything downstream of the vocabulary uses it the same way: state what you
apply to by identifier, then let inheritance do the selection. This is what
turns "read everything and decide" into "resolve and retrieve".

---

## Standards

A standard states its applicability by taxonomy identifier, and applicability
follows inheritance. A standard targeting `architecture/data/database`
applies to relational, document, key-value, and every other database
subclass, without listing them.

Technology-specific standards target implementation identifiers; provider
standards target runtime identifiers. Effective selection for a given
component therefore combines several axes:

```text
canonical inheritance
+ implementation
+ runtime
+ concepts
+ linked decisions
```

The alternative — an agent reading every standard and judging relevance — is
the rediscovery cost this system removes.

## Decisions

Architecture decision records reference taxonomy, implementation, and runtime
identifiers the same way. This allows deterministic ADR selection without an
agent rereading the full decision log.

Decisions remain authoritative on their own terms. The Taxonomy supplies a
stable applicability vocabulary; it does not encode the decision.

## Reusable assets

A reusable implementation asset declares what it is in canonical terms:

- which architecture classes it implements;
- which patterns it embodies;
- which engineering concepts it supports;
- which technology it uses.

That declaration is what makes an approved component findable from intent
rather than from memory:

```text
issue
    ↓
CALM intended node
    ↓
canonical architecture class
    ↓
approved technology
    ↓
approved reusable asset
```

A reusable-asset repository consumes the Taxonomy as an external contract. It
does not grow a parallel vocabulary; changes it needs are proposed upstream
([10-governance.md](10-governance.md)).

## Context retrieval

The Taxonomy is a primary index for deterministic context reduction. An agent
receives the projection bearing on its work, not the whole vocabulary and not
the whole repository.

Having resolved an architecture class, a planner retrieves only the relevant
architecture nodes, implementations, reusable patterns, coding roles,
standards, decisions, and code symbols.

This is the operating objective the vocabulary serves: replace repeated
rediscovery with classification once and targeted retrieval thereafter.

## The resolver

Consumers interact through a resolver rather than traversing files
themselves, so traversal logic exists once and behaves identically for
everyone.

```text
resolve(id)                  the record for an identifier
ancestors(id)                walk up to class and family
descendants(id)              everything inheriting from it
implementations_for(id)      technologies realising it
runtimes_for(id)             provider realisations
related_patterns(id)         linked patterns
related_concepts(id)         linked concepts
effective_definition(id)     parent-first inheritance resolved
validate_reference(id)       does this identifier exist
```

The resolver is deterministic and side-effect free. The same identifier
returns the same answer for the same taxonomy version, which is what allows
callers to cache and to reason about their own behaviour.
