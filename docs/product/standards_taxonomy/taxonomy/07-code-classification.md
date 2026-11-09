# Code classification

Source code is classified by rule over evidence, not by inference at each
encounter
([TX-4](02-principles.md#tx-4--deterministic-classification-is-the-default)).
The evidence comes from static-analysis tools that already do that job well
([TX-3](02-principles.md#tx-3--primitive-code-semantics-belong-to-static-analysis-systems)).

---

## The static-analysis boundary

The division of labour is recorded as data in
`mappings/semantic-analysis-boundary.json`, so it is checkable rather than
conventional.

**External sources own primitive facts.** CodeQL owns functions, methods,
classes, modules, calls, imports, control flow, data flow, and the API
graph. Joern/CPG owns the equivalent code-property-graph node kinds. Both are
described as deterministic fact sources.

**The Taxonomy owns meaning.** Architecture meaning, coding-role meaning,
design-pattern meaning, engineering-concept meaning, and the implementation
and runtime mappings.

The question a static-analysis tool answers well is "is this a class that
imports `fastapi` and carries a route decorator?" The question it does not
answer is "is this a request handler?" The Taxonomy answers the second, from
the first.

## The pipeline

```text
source code
    ↓
static analysis
    ↓
semantic facts
    ↓
classification rules
    ↓
taxonomy assignments
    ↓
code index
```

Preferred semantic sources are CodeQL, Joern/CPG, language ASTs, and
framework metadata.

## Rules

`rules/code-classification-rules.json` carries facts to identifiers. A rule
matches on observable evidence — language, imports, naming, decorators, call
prefixes — and assigns one or more canonical identifiers.

A classification preserves the rule and the evidence that produced it. This
is not bookkeeping: an assignment whose provenance is unrecorded cannot be
reviewed when it turns out to be wrong, and cannot be re-derived when a rule
changes.

Rules are expected to be refined against whichever fact shape is adopted.
They are the part of the vocabulary that grows with use, and the part where
AI proposals are most valuable.

## AI usage policy

AI does not classify routine source code where deterministic evidence is
available. That is the cost this system exists to remove.

AI is used to:

- identify recurring unclassified structures;
- propose new taxonomy entries;
- propose new classification rules;
- explain ambiguous mappings;
- propose consolidation of overlapping patterns.

Every AI-generated proposal becomes a reviewed, deterministic definition or
rule before it is treated as authoritative. The distinction is between using
AI to *extend the vocabulary*, which is judgement work, and using it to
*apply the vocabulary*, which is mechanical and belongs to rules.
