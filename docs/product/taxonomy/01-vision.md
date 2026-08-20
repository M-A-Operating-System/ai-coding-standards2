# Vision

## Problem

Every part of the delivery system describes the same things in a different
vocabulary. An architecture diagram says `database`. A cloud discovery scan
says `AWS::RDS::DBInstance`. A standard says "relational stores". A
repository contains a class called `BookingRepository`. A reusable component
is described in a README that nobody indexes.

Nothing connects these. So each time an agent or a person needs to know
whether a standard applies, whether the running system matches its design,
or whether an approved component already exists, they rediscover the
relationships from raw material — reading files, inferring intent, and
reaching a slightly different answer than last time.

The result is a familiar pattern:

- The same classification is re-derived on every pass, at full cost.
- Two agents reading the same code reach different conclusions about what it
  is.
- Standards are applied by searching documents rather than by knowing what
  the code is.
- Drift between designed and running architecture is found by reading, not
  by computing.
- Reusable components are rebuilt because nobody could find them.

For an AI-driven process this is not merely untidy. Rediscovery is the
dominant consumer of context, and context is the scarce resource.

## Vision

The Taxonomy is one vocabulary that every other system normalises into. A
canonical identifier means the same thing whether it was reached from an
architecture diagram, a cloud discovery scan, or a parsed source file — which
makes the relationships between them computable rather than re-derived.

Four semantic domains classify meaning: **architecture**, **patterns**,
**code**, and **concepts**. Each is three levels deep and addressed by
position. Concrete technologies and cloud services stay outside that model,
in separate registries that point at canonical classes, so the semantic
model does not churn every time a vendor ships a product.

The intent is not to model engineering exhaustively. It is to establish
enough shared vocabulary that every other part of the system can resolve
only the context it needs.

## Principles

The rules the model is built on are documented as a numbered, referenced
list in [`02-principles.md`](02-principles.md). Every principle has a stable
ID (`TX-1`, `TX-2`, …) referenced from the other documents here.

In summary: semantic meaning is separate from the technology that implements
it; intended and observed architecture share one vocabulary; primitive code
semantics belong to static-analysis systems; and classification is
deterministic by default, with AI proposing vocabulary rather than assigning
identifiers.

## What success looks like

- Designed and running architecture are compared deterministically, and a
  drift finding names a semantic difference rather than a text change.
- Common source structures are classified without AI, and each assignment
  carries the rule and the evidence that produced it.
- Standards and decisions are selected by inheritance from a classification,
  not by searching documents.
- An approved reusable component is reachable from architectural intent.
- Agents receive compact projections rather than whole repositories, and the
  context consumed per unit of work falls.
- A new technology is absorbed by adding a registry entry, with no change to
  the semantic model.
- Canonical identifiers survive across versions well enough to be depended on
  as internal APIs.

## What this is not

- Not a compiler or static-analysis model. Functions, calls, types, and data
  flow belong to CodeQL, Joern/CPG, and their peers; the Taxonomy classifies
  the roles those facts add up to ([TX-3](02-principles.md#tx-3--primitive-code-semantics-belong-to-static-analysis-systems)).
- Not a catalogue of cloud resources. Provider services are runtime
  realisations, not semantic classes.
- Not a technology hierarchy. Products are implementations, never a fourth
  inheritance level ([TX-1](02-principles.md#tx-1--semantic-meaning-is-separate-from-implementation)).
- Not a replacement for CALM, which remains the intended-architecture
  standard, or for discovered CMDB data, which remains observed state.
- Not a replacement for standards or decisions. It supplies their
  applicability vocabulary, not their content.
- Not a source-code repository. It classifies assets; it does not contain
  them.
- Not a general enterprise ontology. It covers engineering semantics, not
  every organisational concept.
- Not an AI classification service. AI proposes vocabulary; it does not
  assign identifiers as the normal path
  ([TX-4](02-principles.md#tx-4--deterministic-classification-is-the-default)).
