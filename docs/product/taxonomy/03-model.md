# Canonical model

The Taxonomy separates what a node *is* from where it *sits*. Identity is an
opaque, immutable code; location is a path composed from the domain and the
three levels beneath it. Both are enforced in CI, and confusing the two is the
mistake this model exists to prevent.

---

## The three-level hierarchy

Each semantic domain has exactly three levels:

```text
family
  ↓
class
  ↓
subclass
```

Paths compose from position:

```text
<domain>/<family>/<class>/<subclass>
```

```text
architecture/data/database/relational-database
patterns/persistence/data-access/repository
code/api/handler/request-handler
concepts/reliability/idempotency/request-idempotency
```

Three levels is a deliberate ceiling, not a starting point. Technology,
provider, runtime, capability, concern, ownership, and provenance all add
specificity, and none of them becomes a further level
([TX-1](02-principles.md#tx-1--semantic-meaning-is-separate-from-implementation)).
Specificity that matters is expressed as attributes on a record or as an
entry in a registry, so the depth of the tree stays fixed while the detail it
carries can grow.

The arity is fixed as well as capped: every canonical identifier has four
parts, always. A consumer can therefore parse one without a lookup, validate
it by position, and rely on every identifier carrying the same amount of
information. Variable depth would move that cost onto every consumer — each
would have to handle two-, three- and four-part identifiers — and the
positional checks CI performs today would have nothing fixed to check
against. This is settled: a proposal to vary depth by branch was considered
and rejected.

A class with a single subclass is a defect in the class, not evidence for
variable depth. It means one of two things. Either the subclass restates the
class and no discriminating subclass has been written yet — `data/lake` with
only `data-lake` beneath it — or the class was drawn too narrowly and belongs
merged with a sibling. Both are repaired by improving the class. Neither is
repaired by removing the level.

Every record declares the `path`, `parent`, and `level` that its position
implies. A record whose declaration disagrees with its position is
unreachable by the composed lookup every consumer uses, so the disagreement
fails validation rather than sitting latent.

## Identity and location are different things

The path says where a node sits. It does not say what the node is, because a
path is made of names and names improve
([TX-5](02-principles.md#tx-5--identity-is-immutable-names-and-paths-are-not)).

Every node therefore carries two keys:

| Field | Mutable | Purpose |
|---|---|---|
| `id` | Never | Identity. Opaque, sequential within a level, never reused |
| `path` | Yes | Location. The composed four-part path, unique at any moment |

```text
id      SUB000042
path    architecture/data/database/relational-database
name    Relational Database
```

The three-letter code records the **level** — `FAM` for a family, `CLS` for a
class, `SUB` for a subclass — followed immediately by six padded digits, with
no separator. It says nothing about the domain or the subject, deliberately:
an identifier that encoded
content would embed the very thing most likely to be corrected, and a node
moving between domains would need a new key. Coding by level keeps the
identifier stable through every structural repair the vocabulary needs.

What the code does buy is a reader who can tell at a glance whether a citation
names a broad family or a specific subclass, without resolving it. Counters run
per level across the whole taxonomy, never rewind, and a retired identifier is
deprecated rather than freed for reuse.

Everything that cites a node cites its `id`: standards, decisions,
classification rules, mappings, cross-domain relationships, and the
classifications recorded against real systems. A consumer may resolve by path
for convenience, and the resolver accepts both, but a stored reference is
always an identifier.

Former paths are retained on the node. A lookup by a superseded path resolves
to the same node and warns, so a rename never silently breaks a caller — and
never forces a coordinated migration either.

The practical gain is that the vocabulary becomes safe to improve. Renaming a
class, splitting it, merging it into a neighbour, or moving it to a better
parent changes paths and leaves identity untouched, so the structural repairs
this taxonomy needs cost its consumers nothing.

## Facets

Levels answer one question — what kind of thing is this? Facets answer the
others, and they are orthogonal to the tree: a facet never changes a node's
identity, never changes its path, and never participates in inheritance.

```text
id        SUB000071
path      architecture/security/policy/policy-engine
facets    concern:    [identity, security]
          layer:      platform
          lifecycle:  run-time
```

A facet is a named dimension with a controlled set of values, declared once in
a registry and referenced by nodes. A node may carry several values in one
facet where the concept genuinely spans them — `policy-engine` is both an
identity concern and a security concern, which is a fact about the concept
that no single position in a tree can express.

Facets are what make more than one organisation of the same nodes possible. A
**view** is a query over facets: group every node by its `concern` value and
the result reads as one taxonomy; group by `lifecycle` and the same nodes read
as another. Neither view is the tree, and adding a view costs no
restructuring, because the nodes have not moved.

This is the mechanism that removes the pressure to encode every dimension in
position. Technology, provider, runtime, capability, concern, ownership and
provenance were already excluded from the levels; facets give the ones worth
querying a first-class home instead of leaving them as prose.

## Master registry

`taxonomy.json` is the master registry. It does not contain the taxonomy — it
names the available domains, registries, mappings, and rule collections, and
where each lives.

Consumers begin resolution there rather than hard-coding paths. A registry
entry that names a file which does not exist fails validation, so the
registry cannot drift from the folder it describes.

## Inheritance

Each level may define four kinds of content:

| Section | What it carries |
|---|---|
| `attributes` | Properties a member of this class has |
| `capabilities` | What a member of this class can do |
| `relationships` | How it connects to other classified things |
| `constraints` | What must hold for a member of this class |

Each supports three operations:

```text
add       introduce something the parent did not define
override  replace the parent's definition
drop      remove an inherited definition
```

Inheritance resolves parent-first: a subclass's effective definition is its
family's, amended by its class's, amended by its own.

`drop` is used sparingly. Removing an inherited constraint is not a
modelling convenience — where the dropped requirement represents a governance
rule, the removal is an exception and carries an ADR, the same as any other
authorised deviation from a standard.

## What the model guarantees

Because identity is immutable and position is enforced, three things hold for
every consumer without further checking:

- An identifier that resolves today resolves to the same meaning tomorrow,
  unless a major version says otherwise.
- Every identifier cited anywhere in the folder — by an implementation, a
  runtime, a mapping, a rule, or an example — names a record that exists.
- Walking up from any record reaches its class and family; walking down
  reaches everything that inherits from it.
