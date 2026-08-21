# Information model

What a node actually contains, where it lives, and how the two correspond.
[03-model.md](03-model.md) describes the concepts; this document describes
their realisation.

---

## Anatomy of a node

Every node in every semantic domain carries the same shape. The fields divide
into four groups by what they are for and how they change.

```text
identity      id           SUB000042               immutable, never reused
              path         architecture/data/database/relational-database
              former_paths [...]                    retained for resolution

naming        name         Relational Database      freely improvable
              aliases      [rdbms, sql-database]    accepted alternatives
              description  Database organised around relational tables,
                           keys, constraints and transactional semantics.

position      level        subclass
              parent       CLS000018               the class above

meaning       facets       concern: data
                           lifecycle: run-time
              attributes   { add, override, drop }
              capabilities { add, override, drop }
              relationships{ add, override, drop }
              constraints  { add, override, drop }

lifecycle     stability    stable
              status       active
              replaced_by  -
              since        0.4.0
```

**Identity** never changes. Everything that stores a reference stores the
`id`; `path` is where the node currently sits and may be rewritten whenever a
name improves
([TX-5](02-principles.md#tx-5--identity-is-immutable-names-and-paths-are-not)).

**Naming** is prose for humans and for search. None of it is load-bearing for
resolution, which is what makes it safe to correct.

**Position** places the node in the tree. `parent` refers to the node above by
identifier, not by path, so a rename above does not rewrite the node below. A
family sits at the top of the tree, so its `parent` is the identifier of the
domain record it belongs to (`DOM000001`) — a record type rather than a fourth
level, and one that carries no `level` field of its own.

**Meaning** is what the node asserts about members of the class. Facets are
orthogonal dimensions; the four inheritance sections carry the semantics that
resolve parent-first down the tree.

**Lifecycle** is the contract state. A node leaves the vocabulary by becoming
`deprecated` with a `replaced_by`, never by deletion
([10-governance.md](10-governance.md)).

## Where each part lives

The physical layout follows the conceptual one: one file per domain, one file
per registry, and separate files for the things that are neither.

```text
taxonomy/
  taxonomy.json              master registry -- names domains, registries,
                             mappings, rules, and where each lives
  domains/                   the four partitions -- identifier, description,
                             and the file carrying each one's tree
  architecture/              the four semantic domains, one file each,
  patterns/                  carrying the full family/class/subclass tree
  code/                      for that domain
  concepts/
  facets/                    facet definitions and their controlled values
  implementations/           concrete technologies, pointing at nodes
  runtimes/                  provider realisations, pointing at nodes
  mappings/                  CALM, cross-domain, analysis boundary
  rules/                     deterministic classification rules
  schemas/                   JSON Schema for every file above
  examples/                  worked classifications, illustrative only
```

A consumer begins at `taxonomy.json` and resolves outward; it never hard-codes
a path that the registry can supply.

The whole tree for one domain sits in one document rather than one file per
node. That keeps a domain reviewable as a unit in a pull request — the
reviewer sees the sibling context a new subclass is being added into, which is
the context needed to judge whether it discriminates.

## How the parts refer to each other

Everything points at identity. Nothing points at a path.

```text
implementations ──implements──▶ node id
runtimes ─────────supports────▶ node id
mappings ─────────maps to─────▶ node id
rules ────────────assigns─────▶ node id
families ─────────belong to───▶ domain id
standards ────────applies to──▶ node id
decisions ────────applies to──▶ node id
facets ◀──────────carried by───  node id
```

This is why identity has to be immutable and why the validator treats it as a
primary key. A dangling reference is a silently wrong classification
downstream, so every one of these arrows is checked in CI.

## What is deliberately not in a node

| Not stored | Where it lives instead |
|---|---|
| The technology that implements the class | `implementations/`, under TX-1 |
| The provider that runs it | `runtimes/` |
| Functions, calls, types, data flow | External analysis, under TX-3 |
| The source of a reusable component | A reusable-asset repository |
| A specific system's instances | The consuming repository's own records |
| Rendering, ordering or display hints | Nowhere; views derive from facets |

The test for admitting a field is whether a consumer would resolve
differently without it. Fields that only describe a node, rather than
constrain what it means, belong in prose.

## Correspondence to the concepts

| Concept in [03-model.md](03-model.md) | Realised as |
|---|---|
| Three semantic levels | Nesting in a domain file: `families` → `classes` → `subclasses` |
| Domain as a partition, not a level | A record in `domains/domains.json`, referenced as a family's `parent`; the schema forbids it a `level` |
| Four-part path | Composed from position at validation time, stored on the node |
| Immutable identity | `id`, assigned from a per-level counter that never rewinds |
| Inheritance | The four sections, resolved parent-first along `parent` |
| Facets | `facets/` definitions, referenced by value from each node |
| Views | Queries over facets, computed by the resolver, stored nowhere |

Views being computed rather than stored is the point of the facet mechanism:
a new way to organise the vocabulary is a query, not a migration.
