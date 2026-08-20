# Taxonomy Product Design Document

## 1. Purpose

The Taxonomy is the canonical semantic classification system used across the AI-agile software delivery process.

It provides a stable, machine-readable vocabulary for describing:

- intended architecture;
- discovered infrastructure and runtime topology;
- reusable architecture and coding patterns;
- code-level implementation roles;
- engineering concepts;
- concrete technology implementations;
- cloud and on-prem runtime realizations;
- standards applicability;
- ADR applicability;
- reusable implementation assets.

The Taxonomy exists to reduce ambiguity between product intent, architecture, implementation, governance, and observed runtime state.

It also supports the primary operational objective of the AI-agile process:

> Reduce end-to-end LLM context consumption by replacing repeated rediscovery with deterministic classification and targeted context retrieval.

The Taxonomy is not intended to replace source code analysis, CALM, a CMDB, standards, ADRs, or reusable implementation repositories. It provides the shared semantic vocabulary that allows those systems to interoperate.

## 2. Product Goals

The Taxonomy MUST:

1. Provide stable canonical identifiers for engineering concepts.
2. Support deterministic classification without requiring AI for routine processing.
3. Support exactly three semantic inheritance levels within each primary taxonomy domain: family, class, and subclass.
4. Separate canonical semantic meaning from concrete technology products.
5. Separate semantic meaning from runtime/provider realization.
6. Allow CALM intended architecture and discovered CMDB objects to normalize to the same canonical classes.
7. Allow static-analysis facts from CodeQL, Joern/CPG, AST tooling, or similar systems to map into higher-level code, pattern, and concept classifications.
8. Allow standards and ADRs to target taxonomy identifiers deterministically.
9. Support reusable implementation assets that declare which canonical classes, patterns, and concepts they implement.
10. Be represented as JSON and validated using JSON Schema.
11. Be version-controlled and reviewed through normal pull-request governance.
12. Remain extensible without allowing uncontrolled taxonomy proliferation.

## 3. Non-Goals

The Taxonomy SHOULD NOT:

- duplicate AST, CST, CodeQL, CPG, LSP, or compiler-level semantic models;
- list every cloud resource as a canonical semantic class;
- encode every technology product as another level of taxonomy inheritance;
- replace CALM as the intended architecture specification;
- replace discovered CMDB data as the observed state of infrastructure;
- replace coding standards or ADRs;
- embed source-code implementations;
- become a generic enterprise ontology for every organizational concept;
- use AI classification as the normal path for assigning taxonomy identifiers.

## 4. Design Principles

### 4.1 Semantic meaning is separate from implementation

The Taxonomy describes what an engineering object **is**. Concrete technology describes what **implements** it. Runtime describes where or how it is **realized**.

Example:

```text
Canonical class:
architecture/data/database/relational-database

Implementation:
postgresql

Runtime:
aws/rds
```

MongoDB is therefore not a fourth taxonomy level under `database`. It is a concrete implementation of:

```text
architecture/data/database/document-database
```

### 4.2 Intended and observed architecture share canonical vocabulary

CALM describes intended architecture. The discovered CMDB describes observed architecture. Both project into the same canonical architecture taxonomy.

```text
CALM intended model
        ↓
canonical architecture classification
        ↑
discovered CMDB model
```

This allows deterministic semantic comparison.

### 4.3 Primitive code semantics belong to static-analysis systems

The Taxonomy does not redefine concepts already modeled well by tools such as CodeQL or Joern/CPG.

Examples of external primitive semantics include:

- module;
- class;
- function;
- method;
- parameter;
- import;
- call;
- control-flow edge;
- data-flow edge;
- API usage;
- type declaration.

The Taxonomy begins at the engineering-meaning layer.

### 4.4 Deterministic classification is the default

Taxonomy assignment SHOULD occur through deterministic rules whenever the required facts are observable.

Preferred evidence sources include:

- CALM metadata;
- discovered infrastructure metadata;
- CodeQL;
- Joern/CPG;
- language ASTs;
- framework decorators;
- imports;
- calls;
- file paths;
- naming conventions;
- explicit manifests;
- reusable asset metadata.

AI MAY propose new rules when recurring unclassified patterns are found, but those rules SHOULD be reviewed and converted into deterministic logic before becoming authoritative.

## 5. Repository Structure

The master folder is:

```text
taxonomy/
```

The recommended structure is:

```text
taxonomy/
├── taxonomy.json
├── README.md
├── architecture/
│   └── architecture.json
├── patterns/
│   └── patterns.json
├── code/
│   └── code.json
├── concepts/
│   └── concepts.json
├── implementations/
│   └── implementations.json
├── runtimes/
│   └── runtimes.json
├── mappings/
│   ├── calm-to-canonical.json
│   ├── cross-domain.json
│   └── semantic-analysis-boundary.json
├── rules/
│   └── code-classification-rules.json
├── schemas/
│   ├── taxonomy.schema.json
│   ├── domain-taxonomy.schema.json
│   ├── implementations.schema.json
│   ├── runtimes.schema.json
│   ├── calm-mapping.schema.json
│   ├── cross-domain.schema.json
│   ├── semantic-analysis-boundary.schema.json
│   ├── classification-rule.schema.json
│   └── classification-rules-file.schema.json
└── examples/
    ├── observed-booking-db.json
    └── classified-code-symbol.json
```

The one-level directory structure is intentional. Each semantic domain is independently maintainable, while the complete three-level hierarchy for that domain remains in one JSON document.

## 6. Master Registry

`taxonomy.json` is the master registry. It does not contain the complete taxonomy. It identifies the available domains, registries, mappings, and rule collections.

Consumers SHOULD begin resolution from `taxonomy.json`. They SHOULD NOT hard-code file paths where the registry can resolve them.

## 7. Canonical Three-Level Model

Each semantic taxonomy domain uses exactly three canonical levels:

```text
family
  ↓
class
  ↓
subclass
```

Canonical identifiers follow:

```text
<domain>/<family>/<class>/<subclass>
```

Examples:

```text
architecture/data/database/relational-database
patterns/persistence/data-access/repository
code/api/handler/request-handler
concepts/reliability/idempotency/request-idempotency
```

The three-level model is intended to remain stable. Technology, provider, runtime, capability, concern, ownership, and provenance are orthogonal metadata and MUST NOT become additional semantic inheritance levels merely because they add specificity.

## 8. Architecture Domain

The architecture taxonomy classifies architectural objects in a provider-neutral way.

Initial families include:

```text
system
compute
data
storage
messaging
networking
identity
security
integration
observability
ai-ml
experience
platform
external
```

Example hierarchy:

```text
architecture
└── data
    └── database
        ├── relational-database
        ├── document-database
        ├── key-value-database
        ├── wide-column-database
        ├── graph-database
        ├── time-series-database
        ├── vector-database
        ├── search-database
        └── embedded-database
```

Technology mappings are separate. For example, PostgreSQL maps to `architecture/data/database/relational-database`, while MongoDB maps to `architecture/data/database/document-database`.

## 9. Patterns Domain

The patterns taxonomy describes reusable engineering and implementation approaches.

Examples include:

```text
patterns/api/request-processing/idempotent-handler
patterns/persistence/data-access/repository
patterns/messaging/consumption/idempotent-consumer
patterns/resilience/retry/exponential-backoff
patterns/security/authorization/role-based-access-control
```

Patterns describe **how a recurring engineering problem is solved**. Patterns SHOULD NOT be confused with concrete reusable source-code assets.

## 10. Code Domain

The code taxonomy describes meaningful structural roles in source code. It is intentionally above primitive syntax semantics.

Examples:

```text
code/api/handler/request-handler
code/api/middleware/request-middleware
code/domain/model/aggregate-root
code/persistence/repository/repository-implementation
code/messaging/consumer/message-consumer
code/testing/test/integration-test
```

CodeQL, Joern/CPG, AST analysis, or equivalent tools SHOULD provide the underlying observable facts. The taxonomy classifier SHOULD assign code taxonomy identifiers based on deterministic rules.

## 11. Concepts Domain

Concepts represent technology-neutral engineering properties and concerns.

Examples:

```text
concepts/reliability/idempotency/request-idempotency
concepts/reliability/fault-tolerance/circuit-breaking
concepts/security/authorization/least-privilege
concepts/observability/correlation/request-correlation
concepts/maintainability/modularity/separation-of-concerns
```

Concepts answer the question: **What engineering property or principle is being achieved?**

## 12. Implementation Registry

`implementations/implementations.json` maps concrete technologies to semantic classes.

An implementation MAY implement more than one semantic class. The actual usage context determines which classification applies to a specific instance.

## 13. Runtime Registry

`runtimes/runtimes.json` describes provider or deployment realizations.

Examples:

```text
aws/rds
aws/lambda
aws/eks
azure/functions
azure/aks
gcp/cloud-sql
gcp/gke
on-prem/bare-metal
on-prem/kubernetes
```

Runtime identifiers MUST remain distinct from implementation identifiers.

## 14. CALM Alignment

CALM is the authoritative representation of intended architecture. The Taxonomy supplements CALM with a finer classification vocabulary.

Example:

```text
CALM node-type:
database

canonical classification:
architecture/data/database/relational-database

implementation:
postgresql

runtime:
aws/rds
```

`mappings/calm-to-canonical.json` provides deterministic candidate mappings. Where a CALM node type maps to multiple canonical subclasses, additional CALM metadata SHOULD identify the final classification.

The Taxonomy MUST NOT silently alter CALM intent.

## 15. Discovered CMDB Alignment

Discovery connectors may emit provider-specific JSON. Raw discovery files are evidence, not the canonical CMDB representation.

The normalization process is:

```text
raw discovery JSON
        ↓
provider adapter
        ↓
canonical architecture classification
        ↓
observed CMDB JSON
```

Because intended CALM and observed CMDB state use the same canonical taxonomy, the system can perform semantic architecture diffs.

## 16. Intended-versus-Observed Comparison

Architecture comparison SHOULD operate over normalized semantic fields rather than raw JSON textual diffs.

Recommended finding types include:

```text
missing-node
unexpected-node
missing-relationship
unexpected-relationship
classification-mismatch
implementation-mismatch
runtime-mismatch
attribute-mismatch
interface-mismatch
control-mismatch
```

## 17. Code Classification Pipeline

The deterministic code-classification pipeline is:

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

Preferred semantic sources include CodeQL, Joern/CPG, language ASTs, and framework metadata.

Classification results SHOULD preserve the rule and evidence used to assign the taxonomy ID.

## 18. AI Usage Policy

AI SHOULD NOT classify routine source code directly when deterministic evidence is available.

AI MAY be used to:

- identify recurring unclassified structures;
- propose new taxonomy entries;
- propose new classification rules;
- explain ambiguous mappings;
- propose consolidation of overlapping patterns.

AI-generated proposals MUST become reviewed, deterministic definitions or rules before being treated as authoritative.

## 19. Inheritance Model

Each semantic level may eventually define:

- attributes;
- capabilities;
- relationships;
- constraints.

Each section supports:

```text
add
override
drop
```

Inheritance resolves parent-first:

```text
family
    ↓
class
    ↓
subclass
```

`drop` SHOULD be used sparingly. Where a dropped inherited requirement represents a governance exception, the exception SHOULD require an ADR or equivalent explicit authorization.

## 20. Cross-Domain Relationships

The domains are separate but intentionally linkable.

Examples:

```text
patterns/persistence/data-access/repository
    → typically-implemented-as
code/persistence/repository/repository-implementation
```

```text
patterns/api/request-processing/idempotent-handler
    → supports-concept
concepts/reliability/idempotency/request-idempotency
```

```text
code/api/handler/request-handler
    → typically-realizes
architecture/compute/service/api-service
```

These relationships SHOULD be explicit and machine-readable. They SHOULD NOT be inferred repeatedly by agents if they can be codified once.

## 21. Standards Consumption

Standards SHOULD reference taxonomy identifiers in their applicability metadata.

A standard targeting `architecture/data/database` automatically applies to descendants such as relational and document databases.

Technology-specific standards may target implementation identifiers. Provider standards may target runtime identifiers.

Effective standards selection may therefore combine:

```text
canonical inheritance
+
implementation
+
runtime
+
concepts
+
linked ADRs
```

## 22. ADR Consumption

ADRs SHOULD be able to reference taxonomy identifiers, implementation identifiers, and runtime identifiers.

This allows deterministic ADR selection without requiring agents to reread all ADRs. ADRs remain authoritative decisions; the Taxonomy only provides a stable applicability vocabulary.

## 23. Reusable Asset Consumption

Reusable implementation assets SHOULD reference taxonomy identifiers.

A reusable asset can declare:

- which architecture classes it implements;
- which patterns it embodies;
- which engineering concepts it supports;
- which technology it uses.

This enables an implementation planner to resolve:

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

## 24. Context Retrieval

The Taxonomy is intended to be a primary index for deterministic context reduction.

Agents SHOULD receive only the relevant projection, not the full taxonomy.

A planner may resolve an architecture class and retrieve only:

- relevant CALM nodes;
- relevant implementations;
- relevant reusable patterns;
- relevant coding roles;
- relevant standards;
- relevant ADRs;
- relevant code symbols.

## 25. Taxonomy Consumption API

Consumers SHOULD interact with the Taxonomy through a resolver rather than implementing ad hoc traversal.

Recommended logical operations include:

```text
resolve(id)
ancestors(id)
descendants(id)
implementations_for(id)
runtimes_for(id)
related_patterns(id)
related_concepts(id)
effective_definition(id)
validate_reference(id)
```

The resolver SHOULD be deterministic and side-effect free.

## 26. Versioning

The Taxonomy MUST be versioned. Semantic-versioning principles SHOULD be used.

- Patch: corrections that do not change semantic meaning.
- Minor: backward-compatible taxonomy additions.
- Major: breaking identifier changes, semantic restructuring, or removals.

Canonical IDs SHOULD be treated as durable API contracts.

## 27. Deprecation

Canonical IDs SHOULD NOT be deleted immediately when superseded.

Definitions SHOULD eventually support a deprecated status and replacement identifier. Consumers SHOULD warn on deprecated references. A later major version MAY remove deprecated identifiers.

## 28. Addition Criteria

A new taxonomy entry SHOULD be added only when:

1. the concept has materially different engineering semantics;
2. the difference affects standards, architecture, implementation, review, reuse, or context selection;
3. existing attributes or capabilities cannot represent the distinction cleanly;
4. the concept is expected to recur.

A new canonical entry SHOULD NOT be added merely because a new vendor product or cloud SKU exists.

## 29. Taxonomy Change Process

All taxonomy changes SHOULD occur through pull requests.

A taxonomy PR SHOULD include:

- reason for the change;
- proposed canonical ID;
- parent classification;
- semantic definition;
- examples;
- implementation mappings if relevant;
- runtime mappings if relevant;
- affected standards;
- affected ADRs;
- migration impact;
- compatibility assessment.

CI validates the Taxonomy on every pull request touching `taxonomy/` and on every push to the default branch. `pipeline/validate_taxonomy.py`, run by the `validate-taxonomy` workflow, checks JSON syntax, JSON Schema conformance against an explicit file-to-schema map, exactly three semantic levels with each node's declared `id`, `parent`, and `level` matching the position it occupies, and referential integrity for every canonical ID cited by implementations, runtimes, mappings, rules, and examples. A JSON file added under `taxonomy/` with no mapped schema fails validation rather than being skipped, so coverage cannot silently erode.

CI SHOULD additionally validate the attribute, capability, relationship, and constraint semantics described in Section 19 once those are formally specified.

## 30. Ownership

The Taxonomy SHOULD have explicit maintainers. Ownership SHOULD be enforced through CODEOWNERS or equivalent repository controls.

Recommended ownership domains include architecture governance, platform engineering, developer productivity, cloud/platform infrastructure, and engineering practice owners.

## 31. Centralization

The authoritative Taxonomy SHOULD exist in a centralized Git repository.

Repositories SHOULD consume a pinned version or generated projection. Individual application repositories SHOULD NOT independently fork or redefine canonical taxonomy semantics.

Application-specific data remains local, including CALM system architecture, local ADRs, source mappings, CodeQL/CPG findings, observed resource instances, and issue-specific context manifests.

## 32. Repo-Local Projection

Repositories MAY maintain a compact generated taxonomy projection containing only references relevant to that repository.

Example:

```text
.ai-agile/index/
├── taxonomy.json
├── implementations.json
├── standards.json
└── adrs.json
```

The projection SHOULD include taxonomy version, source commit, selected canonical IDs, and required implementation/runtime mappings.

## 33. Relationship to the Reusable Pattern Repository

The reusable pattern repository SHOULD consume this Taxonomy as an external semantic contract.

The reusable repository SHOULD NOT create its own parallel semantic taxonomy. Changes needed by reusable patterns SHOULD be proposed upstream to the Taxonomy repository.

## 34. Product Lifecycle Integration

The target lifecycle is:

```text
Product intent
    ↓
CALM intended architecture
    ↓
canonical taxonomy classification
    ↓
implementation planner
    ↓
reusable asset selection
    ↓
coder
    ↓
static analysis / CodeQL / CPG
    ↓
deterministic code classification
    ↓
discovered CMDB
    ↓
canonical observed classification
    ↓
reviewer
    ↓
intended-versus-observed comparison
```

Standards and ADRs are selected through the same semantic IDs throughout this lifecycle.

## 35. Success Criteria

The Taxonomy is successful when:

- architecture intent and observed runtime state can be compared deterministically;
- common source-code structures can be classified without AI;
- standards selection can use taxonomy inheritance rather than document-wide search;
- ADR applicability can be resolved deterministically;
- reusable implementation assets can be found from canonical architecture intent;
- agents receive compact context projections instead of entire repositories;
- new technologies can be introduced without redesigning the canonical taxonomy;
- taxonomy IDs remain stable enough to behave like internal APIs.

## 36. Initial Product Decisions

The following decisions are part of the current design baseline:

1. The master folder is named `taxonomy`.
2. JSON is the authoritative representation.
3. Each semantic domain has one directory and one primary JSON file.
4. The primary semantic domains are architecture, patterns, code, and concepts.
5. Implementations and runtimes are separate registries rather than semantic inheritance domains.
6. Each semantic domain uses a three-level hierarchy: family, class, subclass.
7. Concrete technology products do not become a fourth canonical level.
8. CALM remains the intended architecture standard.
9. Discovered CMDB data represents observed architecture.
10. CALM and CMDB objects normalize into the same architecture taxonomy.
11. Primitive source-code semantics are delegated to static-analysis systems such as CodeQL or Joern/CPG.
12. Taxonomy classification SHOULD be deterministic wherever possible.
13. AI is used to propose taxonomy/rule improvements, not to repeatedly rediscover established classifications.
14. Taxonomy definitions will progressively gain allowable attributes, capabilities, relationships, and constraints.
15. Taxonomy IDs are intended to become shared contracts across standards, ADRs, reusable patterns, architecture, source code, and CMDB data.

## 37. Future Work

Expected future work includes:

- full JSON Schema definitions for family, class, and subclass records;
- formal attribute inheritance and override semantics;
- explicit relationship-type registry;
- capability definitions;
- governance and exception semantics;
- taxonomy resolver CLI/library;
- deterministic CodeQL classification integration;
- optional Joern/CPG integration;
- CALM schema extensions carrying canonical taxonomy IDs;
- discovered-CMDB normalization adapters;
- standards applicability integration;
- ADR applicability integration;
- reusable asset lookup;
- taxonomy migration tooling;
- deprecation and alias support;
- generated documentation and diagrams;
- token-budget-aware context projection.

## 38. Summary

The Taxonomy is the semantic backbone connecting product intent, CALM architecture, reusable patterns, code analysis, discovered infrastructure, standards, ADRs, and reusable implementation assets.

Its central design is intentionally simple:

```text
Canonical semantic meaning
    family / class / subclass

Concrete implementation
    technology product

Runtime realization
    provider / service

Observed code semantics
    CodeQL / CPG facts

Governance
    standards / ADRs

Reuse
    approved implementation assets
```

The Taxonomy should remain small, stable, deterministic, and centrally governed.

Its value comes not from modeling every possible engineering detail, but from creating a shared vocabulary that allows every other part of the delivery system to resolve only the context it needs.
