# Spike findings — Codification assessment of the engineering taxonomy v0.2.0

**Related issue:** [#339](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/339) — `[FEATURE] - taxonomy - specify and build the taxonomy consumers`
**Author:** ad-hoc assessment (not a pipeline agent run)
**Date:** 2026-08-20
**Measured at:** commit `70dc4ab`
**Source files reviewed:** all 23 files under `taxonomy/`, the 11 documents under
`docs/product/taxonomy/`, `pipeline/validate_taxonomy.py`.
**Visual version:** [Taxonomy Schedule Review](https://claude.ai/code/artifact/14489c71-b5fb-49c1-b95c-9bd37fd37467)

---

## Rubric

The taxonomy is judged against three questions, in this order:

1. **Does the data support the capabilities the specification claims?** Measured
   by counting populated fields, not by reading prose.
2. **Is the model sound?** Judged against established practice in classification
   and architecture reconstruction, cited in [Research anchors](#research-anchors).
3. **Is it usable today?** Measured by coverage — what fraction of the
   vocabulary a consumer could actually resolve to something.

Every finding below is measured from the files at `70dc4ab`. Where a statement
is inference rather than measurement it is marked as such.

---

## TL;DR

The taxonomy is **structurally sound and almost entirely unpopulated**. The tree
is well formed, positional identity is enforced in CI, and the boundary against
static-analysis tooling is drawn correctly. But **all 1,812 inheritance sections
across all 453 records are empty**, and **all 453 descriptions are the same
generated template string**. The tree currently supports exactly one operation:
*is this a known identifier?*

Two structural problems are cheap to fix now and expensive later: the `parent`
edge carries two different meanings (grouping and subtyping) while inheritance is
specified to follow both, and identifiers are promised as durable contracts with
no lifecycle fields to deprecate them.

Eight findings and eight recommendations follow. R-1, R-2 and R-3 change the
shape of the model and should land before anything consumes it.

---

## Measurements

| Domain | Families | Classes | Subclasses | Identifiers |
|---|---:|---:|---:|---:|
| architecture | 14 | 84 | 141 | 239 |
| patterns | 8 | 21 | 44 | 73 |
| code | 9 | 25 | 39 | 73 |
| concepts | 8 | 21 | 39 | 68 |
| **Total** | **39** | **151** | **263** | **453** |

Fill rate against what the specification promises:

| Measure | Value | |
|---|---:|---|
| Records with any attribute, capability, relationship or constraint | 0 / 1812 | 0.0% |
| Hand-written descriptions | 0 / 453 | 0.0% |
| Architecture subclasses with an implementation | 9 / 141 | 6.4% |
| Architecture subclasses with a runtime | 13 / 141 | 9.2% |
| Code subclasses a rule can assign | 4 / 39 | 10.3% |
| CALM node types mapped | 4 / 9 | 44.4% |
| Classes with exactly one subclass | 72 / 151 | 47.7% |
| Cross-domain relationships | 6 / 453 ids | 1.3% |

---

## Findings

### F-1 — The taxonomy is a naming skeleton, not yet a semantic model

```text
inheritance sections populated ................ 0 of 1,812   (0.0%)
descriptions matching the generated template .. 453 of 453   (100%)
sample ........................................ "Canonical architecture class for system."
```

Every `attributes`, `capabilities`, `relationships` and `constraints` block in
all four domains is `{add:{}, override:{}, drop:[]}`. Not sparse — empty. Every
description is the same generated sentence with the record name substituted.

This matters because the documented capabilities depend on content that is not
there. "Standards selection can use taxonomy inheritance" requires constraints to
inherit. `effective_definition(id)` returns the merge of four empty objects.

**Severity:** blocks every stated capability.

### F-2 — The parent edge carries two different meanings

```text
architecture/data/database/relational-database
  data      -> database ................. grouping ("things about data")
  database  -> relational-database ...... specialisation (a kind of database)
```

Family-to-class is a thematic bucket; class-to-subclass is genuine subtyping. One
`parent` field expresses both. This is the ambiguity SKOS exists to avoid — the
W3C guidance is explicit that a taxonomy link "can have at least two different
meanings (sub-class or sub-part)", which is why SKOS offers the deliberately
loose `broader`/`narrower` rather than `rdfs:subClassOf`.

The consequence is not cosmetic. `03-model.md` specifies that inheritance
"resolves parent-first" from family down, which means a constraint written on
`data` would be inherited by every database, cache and queue beneath it as though
membership of a topic were a subtype relation. Today that yields empty results;
once F-1 is fixed it yields wrong ones.

**Severity:** latent — becomes wrong answers once F-1 is filled.

### F-3 — Fixed three-level depth is padding the tree

```text
classes with exactly one subclass ..... 72 of 151   (47.7%)
subclasses per class .................. 1:72  2:58  3:14  4:6  9:1

examples  architecture/data/lake/data-lake
          architecture/data/lakehouse/data-lakehouse
          architecture/compute/function/serverless-function
```

Nearly half the classes have a single child, and in many the class and subclass
are the same concept spelled twice. A level that never discriminates carries no
information; it exists to satisfy the rule that there must be three. The
distribution indicates the natural depth of this material is uneven and the model
is forcing it flat.

**Severity:** structural cost, no correctness impact yet.

### F-4 — The abstract flag is fully derivable and therefore noise

```text
family   abstract=true  ..... 39 / 39
class    abstract=true  ..... 151 / 151
subclass abstract=false ..... 263 / 263
```

`abstract` is a perfect function of `level` across all 453 records. It adds a
field to every record and another thing to keep consistent, while telling a
consumer nothing `level` did not already say.

**Severity:** cheap to remove now, awkward later.

### F-5 — The coverage cliff makes the vocabulary unusable in practice

```text
implementations registered ....... 13 technologies
runtime services registered ...... 25
classification rules ............. 4  (three Python, one unscoped)
cross-domain relationships ....... 6  across 453 ids (1.3%)
```

A classifier meeting a Java Spring service, a Kafka topic, or a Terraform module
has nothing to match on. 93.6% of architecture subclasses name a kind of thing no
registered technology claims to be, so resolving from intent to an approved
implementation dead-ends in almost every case.

The model is broad where it needed to be deep. One fully-populated vertical would
be worth more than four thinly-populated domains.

**Severity:** primary limit on present usefulness.

### F-6 — CALM alignment covers under half the node types, and every mapping is ambiguous

```text
CALM 1.0 node types ... actor, ecosystem, system, service, database,
                        network, ldap, webclient, data-asset
mapped ................ system, service, database, network        (4/9)
unmapped .............. actor, ecosystem, ldap, webclient, data-asset
candidates per mapped type ... service 3 · database 4 · network 2 · system 2
```

Every mapped CALM type resolves to multiple canonical candidates, and the
resolution rule exists only as prose — "additional CALM metadata resolves the
choice" — with nothing in the data saying which metadata or how. A deterministic
pipeline cannot execute that sentence.

CALM does provide a hook: its node schema carries an open `metadata` object with
`additionalProperties`.

**Severity:** blocks the intended-versus-observed capability.

### F-7 — Identifiers are promised as contracts but have no lifecycle fields

```text
fields present on records ... id, name, level, parent, abstract, description,
                              attributes, capabilities, relationships, constraints
status ....... absent      deprecated ... absent
replaced_by .. absent      aliases ...... absent
versioning ... single global schema_version = 0.2.0
```

`10-governance.md` commits to deprecating identifiers with a replacement and to
consumers warning on deprecated references. No record can express any of that.

Adding these fields while nothing consumes the taxonomy is a no-op. Adding them
after consumers exist is a migration of a published contract.

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

Package URL is an existing standard for naming software across ecosystems,
adopted by both major SBOM formats precisely because bespoke naming defeats
cross-tool joins. Minting `postgresql` and `aws/rds` means the registry cannot be
joined to an SBOM, a vulnerability feed, or infrastructure state without a
translation table nobody has written.

Separately, three names are reused inside a single domain — the same concept
classified in two places, which will produce inconsistent classification.

**Severity:** interoperability debt.

---

## Research anchors

Four points from external practice bear on the design; two contradict current
choices.

**Rigid hierarchy is the known-weak option.** The systematic mapping of
taxonomies in software engineering finds hierarchy (53%) and faceted analysis
(39%) are the two dominant structures. Faceted classification abandons the
requirement that everything occupy one fixed position in one tree, which is the
property that keeps a scheme from deteriorating as it grows. F-3 is the classic
symptom of forcing facets into a hierarchy.

**A small closed kind set plus open facets is the working industrial pattern.**
Backstage's catalog splits exactly this way: `kind` is a small fixed set carrying
schema, `type` is an open string "expected to follow some taxonomy that makes
sense for yourself", and labels, annotations and relations carry the rest.

**Intended-versus-observed comparison has a settled vocabulary.** Reflexion
models (Murphy, Notkin and Sullivan, 1995; TSE 2001) established the terms three
decades ago: map implementation entities onto a high-level model, then compute
**convergence**, **divergence** and **absence**. The literature also warns that
the mapping from entities to components is the human-authored part, not the
derivable part — worth noting against TX-4's determinism assumption.

**The static-analysis boundary is drawn correctly.** Code property graphs unify
AST, control flow and data dependence into one queryable structure; Joern and
CodeQL are mature at exactly the layer the taxonomy declines to model. TX-3 is
well judged.

---

## Recommendations

### R-1 — Split the parent edge into two named relations

*Fixes F-2. Low effort.*

```text
now         parent: "architecture/data"
            parent: "architecture/data/database"

proposed    broader:     "architecture/data"
            specialises: "architecture/data/database"
```

Attributes and constraints inherit across `specialises` only. `broader` becomes
navigational, which is all a topic bucket can honestly support. Do this before
F-1 is filled — afterwards it is a data migration rather than a field rename.

### R-2 — Turn families into facets and let depth vary

*Fixes F-3. Medium effort.*

The family level already behaves as a facet — `data`, `compute`, `security` are
concerns, not supertypes. Model it as one. Drop the requirement of exactly three
levels, let a branch be as deep as it genuinely discriminates, and collapse the
72 single-child classes.

- `architecture/data/lake/data-lake` becomes `architecture/data-lake` with facet
  `concern: data`.
- A record can then carry more than one facet value, which the present tree
  cannot express — `policy-engine` is both identity and security, which is why it
  appears twice today (F-8).

Identifiers stay path-shaped and stay validated; what changes is that position no
longer has to encode every dimension at once.

### R-3 — Add lifecycle fields before anything depends on an identifier

*Fixes F-7. Low effort.*

Four optional fields on every record, defaulted and unenforced until needed:
`status` (`active` | `deprecated`), `replaced_by`, `aliases`, `since`. Extend
`validate_taxonomy.py` to reject a `replaced_by` that does not resolve, and to
warn when a mapping or rule cites a deprecated identifier.

The cheapest item on this list and the one whose cost grows fastest.

### R-4 — Prove one vertical slice before widening any domain

*Fixes F-1 and F-5. High effort.*

Pick the slice this repo can exercise on itself — Python services with a
relational store — and populate it completely: real descriptions, real attributes
and constraints, implementations for every subclass in the slice, and enough
rules to classify this repository's own source.

State the target as a measurement: run the classifier over `pipeline/` and
`tests/` and have it assign a correct identifier to a stated share of modules.
That number is the first honest evidence the vocabulary works, and it will teach
more about the shape of attributes and constraints than another 200 empty
identifiers.

The corollary is a freeze: add no new families until one existing branch is fully
populated.

### R-5 — Carry canonical identifiers inside CALM rather than mapping to them

*Fixes F-6. Medium effort.*

CALM nodes have an open `metadata` object. Write the canonical identifier there
at authoring time and the ambiguity disappears — a node states what it is instead
of a lookup table guessing from a coarse type.

```text
mapping (lossy)              carried (exact)
node-type: "database"        node-type: "database"
  -> 4 candidates            metadata:
  -> resolved by prose         canonical: "architecture/data/database/relational-database"
```

Keep `calm-to-canonical.json` as the fallback for documents predating the
convention, but complete it first — five of nine CALM node types have no mapping
at all.

### R-6 — Anchor technology and runtime identity to existing standards

*Fixes F-8. Low effort.*

Keep the short local key for readability, but record the external identifier
alongside it.

```text
now                          proposed
"postgresql": {              "postgresql": {
  name: "PostgreSQL",          name: "PostgreSQL",
  implements: [...]            purl_type: "pkg:generic/postgresql",
}                              cpe: "cpe:2.3:a:postgresql:...",
                               implements: [...]
                             }
```

Same for runtimes: record the provider's own resource type next to `aws/rds`.
This is what makes an SBOM, a vulnerability feed, or Terraform state joinable to
the taxonomy without a hand-built translation layer.

### R-7 — Adopt the reflexion vocabulary for comparison findings

*Fixes a prior-art gap. Low effort.*

Restructure the ten finding types in `06-alignment.md` under the three
established ones: **convergence** (intent and reality agree), **divergence**
(reality has what intent does not), **absence** (intent has what reality does
not). The current types become the refinement.

The gain is not naming tidiness. It buys three decades of literature and shared
understanding, and it makes the absence of a *convergence* concept visible — the
present list can only report problems, never confirm a design was honoured.

### R-8 — Retire the abstract field

*Fixes F-4. Trivial effort.*

It is a function of `level` in all 453 records. Delete it and derive it if a
consumer ever wants it. If it is instead meant to mean "may not be assigned
directly", say that with a differently named field and let it vary — at which
point it carries information.

---

## What not to change

- **The separation of meaning from technology and runtime (TX-1).** Three
  independent coordinates is the decision that lets a new vendor product be a
  registry entry rather than a model change. Every recommendation above assumes
  it.
- **The static-analysis boundary (TX-3).** Correctly drawn, and encoding it as
  data in `semantic-analysis-boundary.json` rather than prose is better practice
  than most schemes manage.
- **Determinism as the default (TX-4).** Rules that record their evidence are
  reviewable and re-runnable in a way repeated inference is not.
- **Positional identity enforced in CI.** Requiring each record's declared `id`,
  `parent` and `level` to match its position, and failing an unmapped file rather
  than skipping it, is stronger than most published vocabularies. Keep it through
  every change above.

---

## How to verify these findings

Every measurement above is reproducible from the repository:

```bash
# F-1  empty inheritance sections and templated descriptions
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

The remaining findings are counted the same way: F-3 from the subclass-count
distribution, F-4 from the `abstract`/`level` correlation, F-5 by set-differencing
cited identifiers against declared ones, F-6 against the CALM 1.0 node-type enum,
F-7 by collecting the union of record field names, F-8 by grouping leaf names.

---

## Out of scope for this spike

- **Whether the chosen families and classes are the right ones.** Whether
  `architecture` genuinely needs 14 families is a domain judgement that cannot be
  settled from the files; this assessment measures structure and coverage, not
  the aptness of the vocabulary.
- **Implementing any recommendation.** Nothing under `taxonomy/` is modified.
- **Distributing `taxonomy/` to consuming repos**, unresolved from
  [#329](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/329).

---

## Suggested follow-on issue titles

- `[TOIL] - taxonomy - split the parent edge into broader and specialises` (R-1)
- `[FEATURE] - taxonomy - model families as facets and collapse single-child classes` (R-2)
- `[TOIL] - taxonomy - add status, replaced_by, aliases and since to every record` (R-3)
- `[SPIKE] - taxonomy - populate one vertical slice and measure classifier accuracy on this repo` (R-4)

---

## Sources

1. Usman et al., [Taxonomies in software engineering: a systematic mapping study
   and a revised taxonomy development method](https://www.sciencedirect.com/science/article/pii/S0950584917300472)
2. [Faceted classification](https://en.wikipedia.org/wiki/Faceted_classification)
3. W3C, [SKOS Primer](https://www.w3.org/TR/skos-primer/) and
   [SKOS Reference](https://www.w3.org/TR/skos-reference/)
4. FINOS, [CALM 1.0 core metamodel](https://github.com/finos/architecture-as-code/blob/main/calm/release/1.0/meta/core.json)
5. Backstage, [Descriptor format](https://backstage.io/docs/features/software-catalog/descriptor-format/)
   and [Extending the model](https://backstage.io/docs/features/software-catalog/extending-the-model/)
6. Murphy, Notkin and Sullivan, [Software reflexion models](https://dl.acm.org/doi/10.1145/222124.222136)
   (FSE 1995)
7. [Package URL specification](https://github.com/package-url/purl-spec)
