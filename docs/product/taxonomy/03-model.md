# Canonical model

The Taxonomy is addressed by position. An identifier is not a label attached
to a record — it is the path to that record, composed from the domain and the
three levels beneath it. This is what makes resolution deterministic and
what CI enforces.

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

Identifiers compose from position:

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

Every record declares the `id`, `parent`, and `level` that its position
implies. A record whose declaration disagrees with its position is
unreachable by the composed lookup every consumer uses, so the disagreement
fails validation rather than sitting latent.

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

Because identity is positional and enforced, three things hold for every
consumer without further checking:

- An identifier that resolves today resolves to the same meaning tomorrow,
  unless a major version says otherwise.
- Every identifier cited anywhere in the folder — by an implementation, a
  runtime, a mapping, a rule, or an example — names a record that exists.
- Walking up from any record reaches its class and family; walking down
  reaches everything that inherits from it.
