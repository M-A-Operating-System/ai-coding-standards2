# Principles

These are the rules the Taxonomy is built on. They are referenced by ID
(`TX-1`, `TX-2`, …) from the other documents here. A change to any principle
is a significant architectural decision and goes through an ADR.

> **New here?** This is the canonical rulebook the rest of these documents
> cite by ID. TX-1 (meaning is separate from implementation) and TX-4
> (deterministic classification) are the load-bearing two; come back for the
> others when a document points you here.

IDs are stable. A retired principle keeps its ID and is marked
`status: retired`.

---

## TX-1 — Semantic meaning is separate from implementation

**Statement.** A canonical class describes what something *is*, in
provider-neutral and product-neutral terms. The concrete technology that
realises it, and the provider that runs it, live in separate registries.

**Why.** `architecture/data/database/relational-database` is the meaning.
PostgreSQL is an implementation of it. `aws/rds` is a runtime realisation of
that implementation. Collapsing these would make every new vendor product a
change to the semantic model, and the model would never stabilise. Keeping
them apart means a new technology is absorbed by adding a registry entry.

**Consequence.** An implementation may realise more than one canonical class;
the usage context decides which classification applies to a given instance.
Technology, provider, capability, concern, ownership, and provenance are
orthogonal metadata, never further inheritance levels.

## TX-2 — Intended and observed architecture share one vocabulary

**Statement.** CALM intent and discovered CMDB state both normalise into the
same architecture classes, so the difference between them is computable.

**Why.** Comparing a design to a running system by diffing JSON compares
representations, not meanings — it reports noise where the two systems merely
phrase the same fact differently, and misses genuine divergence expressed in
similar words. Normalising both sides first makes the comparison semantic.

**Consequence.** Raw discovery output is evidence, not canonical
representation; a provider adapter normalises it. Comparison operates over
normalised semantic fields and yields typed findings. The Taxonomy never
silently alters CALM intent — where a CALM node type maps to several
canonical subclasses, additional CALM metadata resolves the choice.

## TX-3 — Primitive code semantics belong to static-analysis systems

**Statement.** Functions, methods, types, calls, imports, control flow, and
data flow are owned by CodeQL, Joern/CPG, or equivalent. The Taxonomy
classifies the roles those facts add up to.

**Why.** Duplicating a compiler-grade model would be expensive to build,
impossible to keep current across languages, and would compete with tools
that already do it well. The useful question is not "is this a method?" but
"is this a request handler?"

**Consequence.** The division is recorded explicitly in
`mappings/semantic-analysis-boundary.json`, naming what each external source
owns and what the Taxonomy owns, so the boundary is data rather than
convention.

## TX-4 — Deterministic classification is the default

**Statement.** Taxonomy identifiers are assigned by rules over observable
evidence, not by inference at each encounter. A classification records the
rule and the evidence that produced it.

**Why.** Re-deriving a settled classification on every pass is the cost this
system exists to remove. A rule is also reviewable, testable, and stable
across runs in a way that repeated inference is not.

**Consequence.** AI has a defined role, and it is upstream of assignment:
finding recurring unclassified structures, proposing new entries or rules,
explaining ambiguous mappings, and proposing consolidation of overlapping
patterns. Every AI-generated proposal becomes a reviewed, deterministic
definition before it carries authority.

## TX-5 — Identity is immutable; names and paths are not

**Statement.** Every node carries a stable unique identifier that never
changes and is never reused. Its name and its path are separate, mutable
properties. Everything that refers to a node refers to it by identifier; the
path resolves to the same node but is a statement of where the node currently
sits, not of what it is.

**Why.** A path-shaped identifier is only stable while every name in it is
stable. Renaming one class rewrites the identifier of every descendant, and
every standard, decision, mapping, rule and classification that cited them.
The taxonomy is meant to be depended on as a contract, and a contract whose
keys change when a word is improved is not one.

Separating the two also makes the vocabulary safe to improve. A class can be
renamed, split, merged, or moved to a better parent, and the nodes keep their
identity through it — so the structural repairs the taxonomy needs cost
nothing to the consumers already citing it.

**Consequence.** Identifiers are opaque and sequential within a domain
(`ARCH-0042`), assigned once and retired only by deprecation. Paths remain
unique at any point in time and remain positionally validated, so
`<domain>/<family>/<class>/<subclass>` keeps every property that made it
worth fixing at four parts. A node's former paths are retained so a stale
reference resolves with a warning rather than failing. Facets attach to the
identifier, never to the path.
