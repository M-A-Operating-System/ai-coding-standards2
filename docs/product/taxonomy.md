# Taxonomy

**The Taxonomy** is the canonical semantic vocabulary of the AI-agile
delivery process. It gives intended architecture, discovered infrastructure,
source code, standards, decisions, and reusable assets one shared set of
identifiers, so that a claim made in any of them resolves against the same
meaning. Its value is not in modelling every engineering detail; it is in
letting every other part of the system resolve only the context it needs.

The vocabulary lives in [`taxonomy/`](../../taxonomy/) as versioned JSON,
governed through pull requests and enforced in CI.

---

## Purpose

Product intent, architecture, implementation, governance, and observed
runtime state are each described in their own vocabulary. CALM says
`database`; a discovery connector says `AWS::RDS::DBInstance`; a standard
says "relational stores"; a repository contains a class named
`BookingRepository`. Nothing connects them, so every agent and every human
rediscovers the same relationships on each pass — expensively, and with a
different answer each time.

The Taxonomy is the single vocabulary those systems normalise into. A
canonical identifier means the same thing whether it was reached from an
architecture diagram, a cloud discovery scan, or a parsed source file, which
makes the relationships between them computable rather than re-derived.

This serves the operating objective of the wider process: reduce end-to-end
LLM context consumption by replacing repeated rediscovery with deterministic
classification and targeted retrieval. An agent that can resolve a canonical
class receives the standards, decisions, patterns, and code that bear on it —
not the repository.

---

## Scope

### In scope

The Taxonomy defines canonical vocabulary for:

| Dimension | What it classifies |
|---|---|
| Architecture | Architectural objects, provider-neutral |
| Patterns | Reusable design and implementation approaches |
| Code | Structural roles in source code, above primitive syntax |
| Concepts | Technology-neutral engineering properties and concerns |
| Implementations | Concrete technologies, mapped to canonical classes |
| Runtimes | Provider and deployment realisations |

It also defines the mappings that let external systems project into that
vocabulary — CALM node types, cross-domain relationships, and the boundary
against static-analysis ontologies — and the deterministic rules that carry
static-analysis facts into code classifications.

### Out of scope

The Taxonomy is deliberately not the following, and a change that moves it
toward any of them is a change to this specification:

| Not this | Because |
|---|---|
| An AST, CST, CodeQL, CPG, LSP, or compiler semantic model | Those own primitive code facts; the Taxonomy classifies above them |
| A catalogue of every cloud resource | Provider SKUs are runtime realisations, not semantic classes |
| A technology hierarchy | Products are implementations, not a fourth inheritance level |
| A replacement for CALM | CALM remains the intended-architecture standard |
| A replacement for discovered CMDB data | The CMDB remains observed state |
| A replacement for standards or ADRs | It supplies their applicability vocabulary, not their content |
| A source-code repository | It classifies assets; it does not contain them |
| A general enterprise ontology | It covers engineering semantics, not every organisational concept |
| An AI classification service | AI proposes vocabulary; it does not assign identifiers as the normal path |

---

## The canonical model

Four decisions fix the shape of the vocabulary. They are settled: a change
to any of them is an architectural decision and goes through an ADR
(STD-DOC-001).

### TX-1 — Semantic meaning is separate from implementation

**Statement.** A canonical class describes what something *is*, in
provider-neutral and product-neutral terms. The concrete technology that
realises it, and the provider that runs it, are separate registries.

`architecture/data/database/relational-database` is the meaning. PostgreSQL
is an implementation of it. `aws/rds` is a runtime realisation. Collapsing
these would make every new vendor product a change to the semantic model,
and the model would never stabilise.

An implementation may realise more than one canonical class; the usage
context decides which classification applies to a given instance.

### TX-2 — Intended and observed architecture share one vocabulary

**Statement.** CALM intent and discovered CMDB state both normalise into the
same architecture classes, so the difference between them is computable.

Raw discovery output is evidence, not canonical representation. A provider
adapter normalises it into canonical classifications, producing observed
CMDB state in the same terms CALM intent was expressed in. Comparison then
operates over normalised semantic fields rather than textual JSON diffs, and
yields typed findings — a missing node, an unexpected relationship, a
classification, implementation, or runtime mismatch.

The Taxonomy never silently alters CALM intent. Where a CALM node type maps
to several canonical subclasses, additional CALM metadata resolves the
choice.

### TX-3 — Primitive code semantics belong to static-analysis systems

**Statement.** Functions, methods, types, calls, imports, control flow, and
data flow are owned by CodeQL, Joern/CPG, or equivalent. The Taxonomy
classifies the roles those facts add up to.

`mappings/semantic-analysis-boundary.json` records this division explicitly,
naming what each external source owns and what the Taxonomy owns. Duplicating
a compiler-grade model would be expensive to build, impossible to keep
current, and would compete with tools that already do it well.

### TX-4 — Deterministic classification is the default

**Statement.** Taxonomy identifiers are assigned by rules over observable
evidence, not by inference at each encounter. A classification records the
rule and the evidence that produced it.

AI has a defined role in the loop, and it is upstream of assignment: finding
recurring unclassified structures, proposing new entries or rules,
explaining ambiguous mappings, and proposing consolidation of overlapping
patterns. Every AI-generated proposal becomes a reviewed, deterministic
definition before it carries authority. Re-deriving a settled classification
on each pass is the cost this specification exists to remove.

### The three-level hierarchy

Each semantic domain has exactly three levels, and identifiers compose from
position:

```text
<domain>/<family>/<class>/<subclass>

architecture/data/database/relational-database
patterns/persistence/data-access/repository
code/api/handler/request-handler
concepts/reliability/idempotency/request-idempotency
```

Technology, provider, runtime, capability, concern, ownership, and
provenance are orthogonal metadata. None becomes a further inheritance level
merely because it adds specificity.

Each level may define attributes, capabilities, relationships, and
constraints, each supporting `add`, `override`, and `drop`. Inheritance
resolves parent-first. A `drop` that removes an inherited governance
requirement is an exception and carries an ADR.

`taxonomy.json` is the master registry: it names the available domains,
registries, mappings, and rule collections rather than containing them.
Consumers begin resolution there rather than hard-coding paths.

---

## Capabilities

The Taxonomy exists to enable the following business outcomes. Each is named
in business language and carries a stable kebab-case id; the capability is
the unit referenced from the roadmap and from delivery (STD-PROC-013).

| id | Capability | Outcome |
|---|---|---|
| `classify-intended-architecture` | Classify Intended Architecture | An architecture expressed in CALM carries canonical classifications, so its meaning is comparable across systems and teams |
| `classify-observed-infrastructure` | Classify Observed Infrastructure | Discovered runtime topology is normalised into the same canonical classes as intent, whatever provider it came from |
| `compare-intent-with-reality` | Compare Intent With Reality | The difference between designed and running architecture is reported as typed semantic findings rather than a textual diff |
| `classify-source-code` | Classify Source Code | Common source structures receive their engineering role deterministically from static-analysis evidence, without AI in the loop |
| `target-governance-by-classification` | Target Governance By Classification | A standard or decision states what it applies to by classification, and applicability follows inheritance rather than document search |
| `find-approved-building-blocks` | Find Approved Building Blocks | An approved reusable asset is discoverable from architectural intent, so teams build from sanctioned components |
| `deliver-targeted-context` | Deliver Targeted Context | An agent receives the projection bearing on its work — relevant nodes, implementations, patterns, standards, decisions, and symbols — instead of a repository |
| `govern-vocabulary-change` | Govern Vocabulary Change | The vocabulary evolves under review, staying stable enough to be depended on as a contract |

Capability Specifications and their BDD scenarios are tracked in
[#339](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/339).

### How the capabilities compose

The vocabulary is the spine of the delivery lifecycle: product intent
becomes CALM intended architecture, which classifies canonically, which
drives implementation planning and reusable-asset selection, which produces
code, which static analysis classifies canonically in turn — while discovery
classifies what actually runs, and review compares the two. Standards and
decisions are selected through the same identifiers at every step.

Consumption is through a resolver rather than ad hoc traversal. The resolver
is deterministic and side-effect free, and answers: resolve an id, walk its
ancestors or descendants, list implementations or runtimes for it, find
related patterns or concepts, compute an effective definition, and validate a
reference.

---

## Governance

**Identifiers are contracts.** Canonical IDs are treated as durable API
contracts and versioned on semantic-versioning principles: a patch corrects
without changing meaning, a minor adds compatibly, a major breaks
identifiers or restructures semantics. A superseded identifier is deprecated
with a replacement rather than deleted; consumers warn on deprecated
references, and removal waits for a major version.

**Additions are earned.** A new entry is justified when the concept has
materially different engineering semantics, that difference affects
standards, architecture, implementation, review, reuse, or context
selection, existing attributes cannot represent it cleanly, and it is
expected to recur. A new vendor product or cloud SKU is not by itself a
reason to add one.

**Change is reviewed.** Taxonomy changes arrive as pull requests carrying the
reason, the proposed identifier, its parent, its semantic definition,
examples, any implementation and runtime mappings, the standards and
decisions affected, and the migration and compatibility impact. CI validates
every change: JSON syntax, schema conformance against an explicit
file-to-schema map, three-level consistency with each node's declared `id`,
`parent`, and `level` matching its position, and referential integrity for
every canonical identifier cited anywhere in the folder. A JSON file added
with no mapped schema fails validation rather than being skipped, so
coverage cannot erode silently.

**Ownership is explicit.** The Taxonomy has named maintainers, enforced
through CODEOWNERS or equivalent, spanning architecture governance, platform
engineering, developer productivity, infrastructure, and engineering
practice.

**Definition is central; consumption is local.** The authoritative vocabulary
lives in one repository. Consuming repositories take a pinned version or a
generated projection and do not fork or redefine canonical semantics.
Application-specific data — local architecture, local ADRs, source mappings,
analysis findings, observed instances — stays local. A reusable-pattern
repository consumes the Taxonomy as an external contract and proposes
changes upstream rather than growing a parallel vocabulary.

---

## Roadmap Alignment

The vocabulary and its enforcement are in place: `taxonomy/` holds the
canonical domains, registries, mappings, rules, schemas, and examples, and
`validate-taxonomy` gates every change to them.

The capabilities above are the outcomes that vocabulary was built to serve,
and each depends on a consumer that reads it. Those consumers — the
resolver, deterministic code classification, CALM and CMDB alignment,
governance integration, and context projection — are tracked as a single
decomposable gap in
[#339](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/339),
which is the roadmap entry for this product area.

Whether the Taxonomy is distributed to consuming repositories the way
`standards/` is remains an open decision, recorded in
[#329](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/329).

---

## Success Measures

The Taxonomy is succeeding when:

- Designed and running architecture are compared deterministically, and a
  drift finding names a semantic difference rather than a text change.
- Common source structures are classified without AI, and each assignment
  carries the rule and evidence that produced it.
- Standards and decisions are selected through inheritance from a
  classification, not by searching documents.
- An approved reusable asset is reachable from architectural intent.
- Agents receive compact projections rather than whole repositories, and
  context consumed per unit of work falls.
- A new technology is absorbed by adding an implementation or runtime entry,
  with no change to the semantic model.
- Canonical identifiers survive across versions well enough to be depended
  on as internal APIs.

---

## Related

- [`taxonomy/README.md`](../../taxonomy/README.md) — structure and authoring
  conventions for the JSON itself.
- [`14-standards.md`](orchestrator/14-standards.md) — the two-tier standards
  system whose applicability this vocabulary is designed to target.
- [`05_product-architecture-and-technical-architecture.md`](_process/05_product-architecture-and-technical-architecture.md)
  — the architecture narrative this specification sits within.
