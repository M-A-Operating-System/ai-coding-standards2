# Spike findings — Codification assessment of the engineering taxonomy

**Related issues:** [#339](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/339) — taxonomy consumers ·
[#329](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/329) — the seed (closed)
**Author:** ad-hoc assessment (not a pipeline agent run)
**Date:** 2026-08-20
**Covers:** taxonomy v0.2.0 (as merged at `70dc4ab`), the v0.3.0 update, and the v0.3.1 merge in
[#351](https://github.com/M-A-Operating-System/ai-coding-standards2/pull/351)
**Source files reviewed:** all files under `taxonomy/`, the 11 documents under `docs/product/taxonomy/`,
`pipeline/validate_taxonomy.py`
**Visual versions:** [Taxonomy Schedule Review](https://claude.ai/code/artifact/14489c71-b5fb-49c1-b95c-9bd37fd37467) ·
[What the Field Settled](https://claude.ai/code/artifact/c8931354-d75c-4022-94fb-87fdbfeb310b)

---

## Rubric

The taxonomy is judged against four questions, in this order:

1. **Does the data support the capabilities the specification claims?** Measured by counting
   populated fields, not by reading prose.
2. **Is the model sound?** Judged against established practice in classification, architecture
   description, and vocabulary governance — see [Part 3](#part-3--prior-art).
3. **Is it usable today?** Measured by coverage: what fraction of the vocabulary a consumer could
   resolve to something.
4. **Does each update move these numbers?** Measured by re-running the same counts per version.

Every measurement is reproducible from the repository — see [Part 7](#part-7--how-to-verify).
Where a statement is inference rather than measurement it is marked as such.

---

## TL;DR

The taxonomy is **structurally sound and almost entirely unpopulated**. At v0.2.0 all 1,812
inheritance sections across all 453 records were empty and all 453 descriptions were the same
generated template string, so the tree supported exactly one operation: *is this a known
identifier?*

**v0.3.0 improved the descriptive layer without moving the structural findings.** 61 sections are
now populated (3.4%), 36 definitions are genuinely hand-written, and implementation records gained
useful metadata. But 417 of 453 definitions are still generated from a richer template, coverage
regressed slightly, and the update failed validation with 43 errors because it was authored from the
original bundle rather than from `main`. #351 merges the gains and drops the regressions.

**Almost every remaining problem has been solved elsewhere.** OpenTelemetry runs the attribute
registry and deprecation lifecycle this taxonomy needs. MITRE CWE answers the rigid-tree problem
with views over one entry set. ArchiMate draws the metamodel/model line the inheritance rule is
missing. The `concepts` domain reinvents ISO/IEC 25010 and disagrees with it on six of nine
characteristics.

Sixteen recommendations follow. **R-16 comes first** — separating immutable identity from mutable name
and path turns every other structural repair here from a breaking change into a routine one. R-1, R-3,
R-9 and R-11 are likewise cheap now and expensive after adoption, since they change the shape of
records while nothing consumes them. Variable-depth paths were considered and rejected; facets are
adopted as the orthogonal mechanism instead, and the padding is repaired by R-15.

---

## Part 1 — Measurements

### Size, unchanged across all three versions

| Domain | Families | Classes | Subclasses | Identifiers |
|---|---:|---:|---:|---:|
| architecture | 14 | 84 | 141 | 239 |
| patterns | 8 | 21 | 44 | 73 |
| code | 9 | 25 | 39 | 73 |
| concepts | 8 | 21 | 39 | 68 |
| **Total** | **39** | **151** | **263** | **453** |

### Fill rate and coverage, by version

| Measure | v0.2.0 | v0.3.0 | v0.3.1 |
|---|---:|---:|---:|
| `validate_taxonomy.py` | exit 0 | **exit 1, 43 errors** | exit 0 |
| Populated inheritance sections (of 1,812) | 0 | 61 | 61 |
| Generated descriptions (of 453) | 453 | 417 | 417 |
| Descriptions with an article error | 0 | 207 | 0 |
| Implementations registered | 13 | 12 | 13 |
| Runtime services registered | 25 | 23 | 25 |
| Cross-domain relationships | 6 | 5 | 6 |
| CALM node types mapped (of 9) | 4 | 5 | 5 |
| Schemas | 9 | 5 | 9 |
| Classes with exactly one subclass (of 151) | 72 | 72 | 72 |
| Architecture subclasses with an implementation (of 141) | 9 | 9 | 9 |
| Code subclasses a rule can assign (of 39) | 4 | 4 | 4 |

---

## Part 2 — Findings

### F-1 — The taxonomy is a naming skeleton, not yet a semantic model

```text
v0.2.0  inheritance sections populated ....... 0 of 1,812   (0.0%)
        descriptions matching the template ... 453 of 453   (100%)
v0.3.1  inheritance sections populated ....... 61 of 1,812  (3.4%)
        definitions matching a template ...... 417 of 453   (92.1%)
```

At v0.2.0 every `attributes`, `capabilities`, `relationships` and `constraints` block was
`{add:{}, override:{}, drop:[]}` — not sparse, empty — and every description was the same generated
sentence with the record name substituted.

v0.3.0 improved this materially but not structurally. The 61 populated sections are **4 distinct
attribute blocks repeated across 39 families**, one per domain, and 417 definitions are generated
from three new templates. The 36 hand-written definitions are the real gain and set the standard:
"Long-running service whose primary responsibility is exposing a machine-consumable API" is a
definition that discriminates.

The documented capabilities depend on content that is still largely absent. "Standards selection can
use taxonomy inheritance" requires constraints to inherit; `effective_definition(id)` still merges
mostly-empty objects.

**Severity:** blocks every stated capability.

### F-2 — The parent edge carries two different meanings

```text
architecture/data/database/relational-database
  data      -> database ................. grouping ("things about data")
  database  -> relational-database ...... specialisation (a kind of database)
```

Family-to-class is a thematic bucket; class-to-subclass is genuine subtyping. One `parent` field
expresses both. This is the ambiguity SKOS exists to avoid — W3C guidance is explicit that a taxonomy
link "can have at least two different meanings (sub-class or sub-part)", which is why SKOS offers the
deliberately loose `broader`/`narrower` rather than `rdfs:subClassOf`.

`03-model.md` specifies that inheritance "resolves parent-first" from family down, so a constraint
written on `data` would be inherited by every database, cache and queue beneath it as though
membership of a topic were a subtype relation.

**This became load-bearing in v0.3.0.** The 39 new family attribute blocks sit at exactly the level
that cannot soundly inherit. v0.3.0 also set every family's `parent` to `null`, which is the right
instinct expressed the wrong way: the fix is to name the relation, not to empty the field.

**Severity:** was latent; now active.

### F-3 — Half the classes do not discriminate

```text
classes with exactly one subclass ..... 72 of 151   (47.7%)
subclasses per class .................. 1:72  2:58  3:14  4:6  9:1

examples  architecture/data/lake/data-lake
          architecture/data/lakehouse/data-lakehouse
          architecture/compute/function/serverless-function
```

Nearly half the classes have a single child, and in many the class and subclass are the same concept
spelled twice. A level that never discriminates carries no information.

The 72 split into two distinct defects, which need different repairs:

```text
A. subclass merely restates the class ......... 46  (63.9%)
     messaging/queue/message-queue
     data/lake/data-lake
     code/domain/service/domain-service
     concepts/performance/latency/latency-budget

B. subclass genuinely narrows, class is thin ... 26  (36.1%)
     security/key-management/kms
     ai-ml/inference/model-endpoint
     code/persistence/transaction/unit-of-work
     networking/subnet/network-segment
```

**A is the real padding.** The class carries the concept and the subclass adds a word. The class
level is doing the work, and the subclass level is empty ceremony.

**B is thin but sound.** The class is a real category that happens to have one member written so
far. These need filling in, not restructuring. A secondary observation on B: many of its subclasses
are product-category names — `kms`, `siem`, `secrets-manager`, `alert-manager`, `model-registry` —
which sit closer to implementation than to canonical meaning, and may belong in the implementation
registry under TX-1 rather than in the semantic tree.

**Severity:** structural cost, no correctness impact.

### F-4 — The abstract flag is fully derivable and therefore noise

```text
family   abstract=true  ..... 39 / 39
class    abstract=true  ..... 151 / 151
subclass abstract=false ..... 263 / 263
```

`abstract` is a perfect function of `level` across all 453 records, in every version.

**Severity:** cheap to remove now, awkward later.

### F-5 — The coverage cliff makes the vocabulary unusable in practice

```text
implementations registered ....... 13 technologies
runtime services registered ...... 25
classification rules ............. 4  (three Python, one unscoped)
cross-domain relationships ....... 6  across 453 ids (1.3%)
```

A classifier meeting a Java Spring service, a Kafka topic, or a Terraform module has nothing to match
on. 93.6% of architecture subclasses name a kind of thing no registered technology claims to be.

v0.3.0 did not improve any of these and slightly regressed three; v0.3.1 restores them to the v0.2.0
level. The model is broad where it needed to be deep.

**Severity:** primary limit on present usefulness.

### F-6 — CALM alignment covers under half the node types, and every mapping is ambiguous

```text
CALM 1.0 node types ... actor, ecosystem, system, service, database,
                        network, ldap, webclient, data-asset
mapped (v0.3.1) ....... system, service, database, network, webclient   (5/9)
unmapped .............. actor, ecosystem, ldap, data-asset
candidates per mapped type ... service 3 · database 4 · network 2 · system 2
```

Every mapped CALM type resolves to multiple canonical candidates, and the resolution rule exists only
as prose — "additional CALM metadata resolves the choice" — with nothing in the data saying which
metadata or how. A deterministic pipeline cannot execute that sentence.

CALM does provide a hook: its node schema carries an open `metadata` object with
`additionalProperties`.

**Severity:** blocks the intended-versus-observed capability.

### F-7 — Identifiers are promised as contracts but have no lifecycle fields

```text
v0.2.0 fields ... id, name, level, parent, abstract, description,
                  attributes, capabilities, relationships, constraints
v0.3.1 adds ..... aliases  (present on all 453, non-empty on 0)
still absent .... status, deprecated, replaced_by, since
versioning ...... single global schema_version
```

`10-governance.md` commits to deprecating identifiers with a replacement and to consumers warning on
deprecated references. No record can express any of that.

The consequence appeared immediately: v0.3.0 renamed the record field `description` to `definition`
with no migration path. #351 declines to carry the rename for exactly this reason — a breaking rename
in a vocabulary with no deprecation mechanism is the defect the taxonomy exists to prevent.

**Severity:** free to fix now, expensive after adoption.

### F-8 — Technology identity is re-coined where standards already exist

```text
implementation id ..... postgresql
runtime id ............ aws/rds
established forms ..... pkg:generic/postgresql · CPE · AWS::RDS::DBInstance

leaf names reused across the tree ..... 8
  within one domain ... policy-engine, package-registry (architecture)
                        transactional-outbox (patterns)
```

Package URL is an existing standard for naming software across ecosystems, adopted by both major SBOM
formats precisely because bespoke naming defeats cross-tool joins. Minting `postgresql` and `aws/rds`
means the registry cannot be joined to an SBOM, a vulnerability feed, or infrastructure state without
a translation table nobody has written.

v0.3.0 enriched implementation records with `vendor`, `category`, `capabilities` and `related_code`
but added no external identifier.

**Severity:** interoperability debt.

---

<a name="part-3--prior-art"></a>

## Part 3 — Prior art

Fifteen frameworks were read against the design. Verdicts are relative to the taxonomy as it stands:
*confirms* means current practice already matches, *borrow* means there is a mechanism worth taking,
*contradicts* means the field settled on something different.

| Framework | What it settles | Verdict |
|---|---|---|
| OpenTelemetry SemConv | Central attribute registry, stability levels, never-remove deprecation, dual-emit migration | Borrow |
| MITRE CWE | One entry set with many views; four abstraction levels; stable IDs | Contradicts |
| ArchiMate 3.2 | Specialization lives in the metamodel, never in concrete models | Contradicts |
| ISO/IEC 25010:2023 | Nine standardised quality characteristics | Contradicts |
| ISO/IEC/IEEE 42010 | Concerns must be framed by viewpoints, held by stakeholders | Borrow |
| TOGAF content metamodel | Standards attach to metamodel entities; catalogue / matrix / diagram | Confirms |
| C4 and Structurizr | Four abstractions carry most architectural communication | Borrow |
| Backstage catalog | Small closed `kind`, open `type`, facets in labels | Confirms |
| SKOS | `broader`/`narrower` over `subClassOf`, to avoid the F-2 ambiguity | Contradicts |
| Faceted classification | Multidimensionality and persistence over fixed hierarchy | Contradicts |
| Reflexion models | Convergence, divergence, absence | Borrow |
| CALM 1.0 | Node types, relationships, open `metadata` extension point | Borrow |
| Code property graphs | AST, control flow and data dependence unified — the layer below this one | Confirms |
| Package URL | Standardised cross-ecosystem software identifiers | Borrow |
| ServiceNow CSDM | Observed-state modelling with owned, classed CIs | Confirms |

### Vocabulary governance

**OpenTelemetry Semantic Conventions** is the closest living analogue: a large, actively governed,
versioned vocabulary that thousands of independent implementations depend on. Attributes are
registered centrally *before* use in any convention; a convention may override an attribute's
properties but never its `id`, `type` or `stability`. Groups declare a stability level —
`development`, `alpha`, `beta`, `release_candidate`, `stable` — and the level is a contract.

Two mechanisms transplant directly. **Never remove, only deprecate**: a group of any stability level
must not be removed, because code generation and existing instrumentation depend on it, and a
deprecated stable convention survives until a major version. And **a real migration path**: when the
HTTP and database conventions were renamed, implementations honoured an opt-in that emitted both old
and new attribute names side by side, so dashboards kept working while queries were updated.

**MITRE CWE** faced this taxonomy's structural problem and answered it differently: one set of
entries, many *views* over them. The Research Concepts view (CWE-1000) organises by behaviour for
analysis; the Development Concepts view (CWE-699) organises the same entries by where they arise.
Neither is the tree; both are lenses. CWE's four abstraction levels — pillar, class, base, variant —
describe how specific an entry is, not how deep it must sit.

### Architecture modelling

**ArchiMate 3.2** holds the sharpest rule: *specialization is used only in the metamodel, not in
concrete models*. The generic metamodel defines the abstractions, each layer derives its elements
from them, and actual architectures instantiate those elements without adding inheritance. ArchiMate
also organises by layer, related by *realization*, so a concrete element realises a more abstract one
— the relation this taxonomy expresses only as a registry lookup.

**C4 and Structurizr** are the minimalist counter-argument: four abstractions — person, software
system, container, component — carry most architectural communication, expressed as a text DSL and
rendered into many diagrams. Set against 453 identifiers with little semantics, C4 puts the burden of
proof on every identifier beyond the fourth to show what it discriminates.

**TOGAF's content metamodel** is twenty years of prior art for the capability this taxonomy wants
most: standards in the Standards Information Base are categorised *by content-metamodel building
block*, and each entity can carry standards. TOGAF also splits content three ways — catalogues list
building blocks, matrices record relationships, diagrams present views. This taxonomy is almost
entirely catalogue; six relationships across 453 identifiers is a matrix that barely exists, and
relationships are where standards selection gets its leverage.

**ISO/IEC/IEEE 42010** supplies the vocabulary the comparison capability lacks. A *concern* is a
matter of importance to a stakeholder; a *viewpoint* is the conventions for constructing a view that
frames one or more concerns; every identified concern must be framed by at least one viewpoint and
associated with the stakeholders holding it. The `concepts` domain is a set of concerns with neither.

### The quality vocabulary already exists

ISO/IEC 25010:2023 defines nine product quality characteristics with sub-characteristics. The
`concepts` domain covers the same ground and was invented independently.

| Status | Families | n |
|---|---|---:|
| In both | `maintainability`, `reliability`, `security` | 3 |
| Theirs only | `consistency`, `data-management`, `observability`, `performance`, `scalability` | 5 |
| ISO only, absent | `functional suitability`, `performance efficiency`, `compatibility`, `usability`, `portability`, `safety` | 6 |

Two divergences are near-misses that will cause friction: `performance` is ISO's
`performance efficiency` under a shorter name, and `scalability` is a sub-characteristic of it rather
than a peer. Two are genuine additions worth keeping — `observability` and `data-management` matter
here and ISO handles them obliquely.

---

## Part 4 — The v0.3.0 update

### Scorecard against the findings

| Finding | v0.3.0 | Evidence |
|---|---|---|
| F-1 | Partial | 61/1812 sections populated; 417/453 definitions still generated |
| F-2 | Gestured at, not fixed | Still one `parent`; families set to `null` |
| F-3 | Not addressed | 72 single-child classes, unchanged |
| F-4 | Not addressed | `abstract` on all 453 |
| F-5 | Regressed | impl 13→12, runtime svcs 25→23, cross-domain 6→5 |
| F-6 | Marginal | 4→5 of 9 mapped; ambiguity mechanism unchanged |
| F-7 | Partial | `aliases` added, non-empty on 0; no `status`/`replaced_by`/`since` |
| F-8 | Not addressed | No purl/cpe; records gained `vendor`, `category`, `capabilities`, `related_code` |

### Why it could not be taken as-is

Against the validator on `main`, v0.3.0 fails with **43 errors**: 39 family records with
`parent: null`, plus 4 missing schemas. It was authored from the original bundle rather than from
`main`, so dropping it in would have reverted the schemas added in
[#332](https://github.com/M-A-Operating-System/ai-coding-standards2/pull/332).

Three further errors surfaced once those were fixed, all content the update had dropped and the
schemas caught: `calm-to-canonical.source`, and the `role` field on both external semantic sources.
Every v0.3.0 schema is also weaker than its counterpart — `domain-taxonomy.schema.json` went 549 to
230 bytes and lost its `properties` block entirely.

### What v0.3.1 merged

**Taken:** the 36 hand-written descriptions, the domain-level attribute vocabularies, the enriched
implementation records, the `aliases` field, and the CALM `webclient` mapping.

**Kept from `main`:** the four #332 schemas, the 39 family `parent` values, and the content v0.3.0
dropped — `kubernetes`, `aws/eventbridge`, `gcp/pubsub`, the `trace-context-propagation`
relationship, and the three required fields above.

**Corrected:** 207 generated descriptions carried an article error ("is **a architecture**
specialization", "a patterns", "a concepts"). The `description` → `definition` rename was not
carried, per F-7.

---

## Part 5 — Recommendations

Ordered by dependency. The first four change the shape of records and are cheapest while nothing
consumes them.

### R-1 — Split the parent edge into two named relations

*Serves F-2. Low effort.*

```text
now         parent: "architecture/data"
            parent: "architecture/data/database"

proposed    broader:     "architecture/data"
            specialises: "architecture/data/database"
```

Attributes and constraints inherit across `specialises` only; `broader` becomes navigational, which
is all a topic bucket can support. Do this before the attribute blocks fill further — afterwards it
is a data migration rather than a field rename.

### R-3 — Add lifecycle fields before anything depends on an identifier

*Serves F-7. Low effort.*

Four optional fields on every record: `status` (`active` | `deprecated`), `replaced_by`, `aliases`,
`since`. Extend `validate_taxonomy.py` to reject a `replaced_by` that does not resolve and to warn
when a mapping or rule cites a deprecated identifier.

### R-9 — Introduce an attribute registry

*Serves F-1. Medium effort.*

Declare every attribute once, centrally, with an id, a type and a stability level. Records reference
registry entries rather than redefining them; a record may constrain an attribute's use in context
but never redefine its identity or type. This replaces four attribute blocks copied across 39
families with one declaration and 39 references, and makes "which classes carry `criticality`?"
answerable.

### R-11 — Adopt stability levels and a deprecation contract

*Serves F-7. Low effort.*

Give every record a `stability`. Commit in writing to two rules borrowed intact from OpenTelemetry:
a stable identifier is never removed, only deprecated with a replacement named; and removal of a
deprecated stable identifier waits for a major version. For renames already in flight, define a
dual-emit window where consumers accept both names — which unblocks `description` → `definition`
properly rather than deferring it again.

### R-2 / R-10 — Make the family level a view, not a tree level

*Serves F-2. Medium effort. Revised — see the decision below.*

Follow CWE: keep one set of entries and define views over them. A `concern` view groups by `data`,
`compute`, `security`; a `lifecycle` view could group by build-time, deploy-time, run-time. An entry
appears in several views without duplication — which is what `policy-engine` and `package-registry`
need and cannot have today.

Views do not require variable depth, and facets are the mechanism that makes them possible. Both are
adopted; only the depth half of the original proposal is rejected.

> **Decision — variable-depth path is rejected; facets are adopted as an orthogonal mechanism.**
> Paths keep four parts, always. The reasoning is recorded in
> [`03-model.md`](../product/taxonomy/03-model.md): fixed arity lets a consumer parse a path without
> a lookup, validate it by position, and rely on every path carrying the same information. Variable
> depth moves that cost onto every consumer and leaves the CI positional checks nothing fixed to
> check against.
>
> Facets carry the dimensions that position cannot. A facet is a named dimension with a controlled
> value set, attached to a node's identifier; it never changes identity, never changes the path, and
> never participates in inheritance. A node may hold several values in one facet — `policy-engine` is
> both an identity and a security concern, a fact about the concept that no single position can
> express, and the reason it is currently duplicated in the tree.
>
> A view is then a query over facets rather than a second hierarchy. The padding criticism in F-3 is
> still accepted, and is repaired by R-15.

### R-16 — Separate immutable identity from mutable name and path

*Serves F-7, and de-risks F-3, R-12 and R-15. Medium effort, and the prerequisite for all of them.*

Today a node's `id` **is** its path, so identity is only as stable as every name in it. Renaming one
class rewrites the identifier of every descendant, and of every standard, decision, mapping, rule and
recorded classification that cited them.

```text
now       id      architecture/data/database/relational-database

proposed  id      SUB-000042                                       immutable, never reused
          path    architecture/data/database/relational-database   current location
          name    Relational Database                              freely improvable
```

Identifiers are opaque and sequential within a level, prefixed `FAM`, `CLS` or `SUB`, so a citation
is legible in a standard the way `CWE-79` is and a reader can tell a family reference from a subclass
reference without resolving it. The code records the level rather than the subject, so a node keeps
its identity when it moves between domains. Stored references — in standards, decisions,
rules, mappings, and classifications against real systems — use the identifier. The resolver accepts
either, and former paths are retained so a stale path resolves with a warning rather than failing.

This is recorded as [TX-5](../product/taxonomy/02-principles.md#tx-5--identity-is-immutable-names-and-paths-are-not).

**Why it is the prerequisite.** Three of the recommendations here are structural repairs: R-15 rewrites
46 padded classes, R-12 rebases the concepts families on ISO/IEC 25010, R-2/R-10 reorganises what the
family level means. Under path-as-identity every one of those is a breaking change to a published
contract. Under TX-5 they are all minor changes — the nodes keep their identity, their former paths
still resolve, and no consumer has to migrate. Doing R-16 first converts the rest of this list from
expensive to routine.

It also settles the rename that has already come up twice: `description` → `definition` at the field
level, and every name correction the 36 hand-written definitions imply at the record level.

### R-15 — Repair the padded classes by improving the classes

*Serves F-3. Supersedes the depth half of R-2/R-10. Medium effort, incremental.*

The 46 pattern-A classes are the work. For each, the class names a real concept and the subclass
level needs genuine discriminating members written beneath it. The test for a candidate subclass is
whether a standard, a classification rule, or an architecture comparison would ever treat it
differently from its siblings.

```text
now                              repaired
messaging/queue/message-queue    messaging/queue/fifo-queue
                                 messaging/queue/priority-queue
                                 messaging/queue/dead-letter-queue
                                 messaging/queue/delay-queue

data/lake/data-lake              data/lake/raw-zone-lake
                                 data/lake/curated-zone-lake

code/domain/service/            code/domain/service/domain-service
  domain-service                 code/domain/service/application-service
```

Those candidates are illustrative, not ratified — choosing them is domain judgement and belongs with
the vocabulary's owners. What is not a judgement call is the shape of the fix: add discriminating
siblings, or merge the class into a neighbour where no discrimination exists. Never delete the level.

Sequence it with R-4 rather than as a separate campaign: repair the classes inside the vertical slice
being populated, so each repair is tested against real classification work rather than argued in the
abstract. The 26 pattern-B classes are a fill-in backlog and need no restructuring; check first
whether their subclass belongs in the implementation registry instead.

### R-13 — Separate the metamodel from the model

*Serves F-2 and F-4. Medium effort.*

State explicitly which artefacts are metamodel — the levels, record kinds, relation types — and which
are model instances, then apply ArchiMate's rule that inheritance operates in the metamodel only.
This also disposes of `abstract` honestly: the field is trying to say "this is a metamodel node", a
statement about which model a record belongs to rather than a property to repeat 453 times.

### R-4 — Prove one vertical slice before widening any domain

*Serves F-1 and F-5. High effort.*

Pick the slice this repo can exercise on itself — Python services with a relational store — and
populate it completely: real descriptions, real attributes and constraints, implementations for every
subclass in the slice, and enough rules to classify this repository's own source.

State the target as a measurement: run the classifier over `pipeline/` and `tests/` and have it
assign a correct identifier to a stated share of modules. The corollary is a freeze — add no new
families until one branch is fully populated. Note that v0.3.0's 36 good definitions are spread
across 18 families, 1–5 each: a sample everywhere and a completed slice nowhere.

### R-5 — Carry canonical identifiers inside CALM rather than mapping to them

*Serves F-6. Medium effort.*

CALM nodes have an open `metadata` object. Write the canonical identifier there at authoring time and
the ambiguity disappears — a node states what it is instead of a lookup table guessing from a coarse
type. Keep `calm-to-canonical.json` as the fallback for documents predating the convention, but
complete it first: four of nine CALM node types still have no mapping.

### R-6 — Anchor technology and runtime identity to existing standards

*Serves F-8. Low effort.*

Keep the short local key for readability, but record the external identifier alongside it — a Package
URL and CPE for implementations, the provider's own resource type for runtimes. This is what makes an
SBOM, a vulnerability feed, or Terraform state joinable to the taxonomy without a hand-built
translation layer.

### R-12 — Rebase the concepts domain on ISO/IEC 25010

*Serves interoperability. Medium effort.*

Take the nine characteristics as the family set, keep `observability` and `data-management` as
declared local extensions, and fold `performance` and `scalability` into `performance efficiency`
where the standard puts them. Record the ISO characteristic each family maps to, the same way R-6
records a Package URL alongside a local key.

### R-7 — Adopt the reflexion vocabulary for comparison findings

*Serves a prior-art gap. Low effort.*

Restructure the ten finding types in `06-alignment.md` under the three established ones:
**convergence** (intent and reality agree), **divergence** (reality has what intent does not),
**absence** (intent has what reality does not). The current types become the refinement. This buys
three decades of shared understanding, and makes the absence of a *convergence* concept visible — the
present list can only report problems, never confirm a design was honoured.

### R-14 — Give concerns viewpoints and stakeholders

*Serves the comparison capability. Medium effort.*

Per ISO/IEC/IEEE 42010, a concern not framed by a viewpoint is incomplete. For each concepts entry,
record the viewpoint that frames it — how you would look at a system to see whether it holds — and
the stakeholder who holds it. This turns a drift finding from "classification-mismatch" into "the
reliability concern held by the on-call team is not satisfied by the running system", which is a form
a person can act on.

### R-8 — Retire the abstract field

*Serves F-4. Trivial effort.*

It is a function of `level` in all 453 records. Delete it and derive it if a consumer wants it. If it
is instead meant to mean "may not be assigned directly", say that with a differently named field and
let it vary — at which point it carries information.

---

## Part 6 — What not to change

- **The separation of meaning from technology and runtime (TX-1).** Three independent coordinates is
  the decision that lets a new vendor product be a registry entry rather than a model change.
  ArchiMate's realization across layers is the same instinct; Backstage's closed `kind` and open
  `type` is a third independent arrival at it.
- **The static-analysis boundary (TX-3).** Correctly drawn, and encoding it as data in
  `semantic-analysis-boundary.json` rather than prose is better practice than most schemes manage. No
  architecture framework surveyed attempts to model what a code property graph already models.
- **Determinism as the default (TX-4).** Rules that record their evidence are reviewable and
  re-runnable in a way repeated inference is not.
- **Positional identity enforced in CI.** Requiring each record's declared `id`, `parent` and `level`
  to match its position, and failing an unmapped file rather than skipping it, is stronger than most
  published vocabularies. It caught three regressions in v0.3.0 that inspection had missed.
- **Attaching governance to classified entities.** TOGAF has categorised its Standards Information
  Base by content-metamodel entity for two decades. The central bet is sound.
- **JSON, in git, reviewed by pull request.** Every living vocabulary surveyed — OpenTelemetry, CALM,
  Backstage, Structurizr — has converged on machine-readable definitions under version control.

---

<a name="part-7--how-to-verify"></a>

## Part 7 — How to verify

Every measurement is reproducible from the repository. The headline one:

```bash
python3 - <<'PY'
import json, pathlib, re
T = pathlib.Path('taxonomy')
empty = filled = boiler = total = 0
for d in ['architecture', 'patterns', 'code', 'concepts']:
    j = json.load(open(T / d / f'{d}.json'))
    def walk(n):
        global empty, filled, boiler, total
        total += 1
        if re.match(r'^Canonical \w+ (family|class|subclass) for ', n.get('description', '')):
            boiler += 1
        for sec in ('attributes', 'capabilities', 'relationships', 'constraints'):
            v = n.get(sec) or {}
            if v.get('add') or v.get('override') or v.get('drop'):
                filled += 1
            else:
                empty += 1
    for fam in j['families'].values():
        walk(fam)
        for cl in fam.get('classes', {}).values():
            walk(cl)
            for s in cl.get('subclasses', {}).values():
                walk(s)
print(f'sections: {filled} filled, {empty} empty')
print(f'descriptions: {boiler} templated of {total}')
PY
```

The rest are counted the same way: F-3 from the subclass-count distribution, F-4 from the
`abstract`/`level` correlation, F-5 by set-differencing cited identifiers against declared ones, F-6
against the CALM 1.0 node-type enum, F-7 by collecting the union of record field names, F-8 by
grouping leaf names. Version comparisons re-run the same counts against each tree.

---

## Out of scope

- **Whether the chosen families and classes are the right ones.** Whether `architecture` genuinely
  needs 14 families is a domain judgement that cannot be settled from the files; this assessment
  measures structure and coverage, not the aptness of the vocabulary.
- **Implementing any recommendation.** #351 merges v0.3.0's content but implements none of R-1 to
  R-16.
- **Distributing `taxonomy/` to consuming repos**, unresolved from #329.

### Limits of the prior-art survey

The ArchiMate, ISO/IEC 25010 and ISO/IEC/IEEE 42010 material was read through secondary sources; the
primary specifications are paywalled. One source on CWE's own taxonomic critique was unreachable from
this environment. Where a framework's precise element or entry counts were not verifiable, the
assessment describes the mechanism rather than quoting a number.

---

## Suggested follow-on issue titles

- `[TOIL] - taxonomy - split the parent edge into broader and specialises` (R-1)
- `[TOIL] - taxonomy - add status, replaced_by, aliases and since to every record` (R-3, R-11)
- `[FEATURE] - taxonomy - introduce a central attribute registry with stability levels` (R-9)
- `[FEATURE] - taxonomy - model families as views over one entry set` (R-2, R-10)
- `[ENHANCEMENT] - taxonomy - write discriminating subclasses for the 46 padded classes` (R-15)
- `[FEATURE] - taxonomy - separate immutable node identity from mutable name and path` (R-16)
- `[FEATURE] - taxonomy - add facets as an orthogonal dimension with a value registry` (R-2, R-10)
- `[SPIKE] - taxonomy - populate one vertical slice and measure classifier accuracy on this repo` (R-4)
- `[TOIL] - taxonomy - rebase the concepts domain on ISO/IEC 25010` (R-12)

---

## Sources

1. Usman et al., [Taxonomies in software engineering: a systematic mapping study and a revised
   taxonomy development method](https://www.sciencedirect.com/science/article/pii/S0950584917300472)
2. [Faceted classification](https://en.wikipedia.org/wiki/Faceted_classification)
3. W3C, [SKOS Primer](https://www.w3.org/TR/skos-primer/) and
   [SKOS Reference](https://www.w3.org/TR/skos-reference/)
4. OpenTelemetry, [Semantic convention groups](https://opentelemetry.io/docs/specs/semconv/general/semantic-convention-groups/)
   and [Attribute registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/)
5. MITRE, [CWE schema](https://cwe.mitre.org/data/xsd/cwe_schema_v6.5.xsd); Research (CWE-1000) and
   Development (CWE-699) views
6. The Open Group, [ArchiMate 3.2 Specification](https://pubs.opengroup.org/architecture/archimate3-doc/)
7. ISO, [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html)
8. [ISO/IEC/IEEE 42010](https://www.iso-architecture.org/ieee-1471/ads/)
9. The Open Group, [TOGAF Content Metamodel](https://pubs.opengroup.org/architecture/togaf9-doc/arch/chap30.html)
   and [Architecture Repository](https://pubs.opengroup.org/architecture/togaf9-doc/arch/chap37.html)
10. [C4 model](https://c4model.com/) and [Structurizr DSL](https://docs.structurizr.com/dsl/language)
11. Backstage, [Descriptor format](https://backstage.io/docs/features/software-catalog/descriptor-format/)
    and [Extending the model](https://backstage.io/docs/features/software-catalog/extending-the-model/)
12. Murphy, Notkin and Sullivan, [Software reflexion models](https://dl.acm.org/doi/10.1145/222124.222136)
    (FSE 1995)
13. FINOS, [CALM 1.0 core metamodel](https://github.com/finos/architecture-as-code/blob/main/calm/release/1.0/meta/core.json)
14. [Package URL specification](https://github.com/package-url/purl-spec)
15. ServiceNow, [Common Service Data Model](https://www.servicenow.com/content/dam/servicenow-assets/public/en-us/doc-type/resource-center/solution-brief/sbr-servicenow-common-service-data-model.pdf)
