# Governance

Canonical identifiers are depended on by standards, decisions, architecture,
code indexes, and reusable assets. That makes them contracts, and contracts
need a change process proportionate to what breaks when they move.

---

## Identifiers are contracts

Identifiers are durable API contracts. Because identity is separate from name
and path ([TX-5](02-principles.md#tx-5--identity-is-immutable-names-and-paths-are-not)),
what counts as a breaking change is narrower than it would otherwise be:

| Change | Means |
|---|---|
| Patch | Corrections that do not change semantic meaning |
| Minor | Backward-compatible additions; renaming, moving, splitting or merging a node, since its identifier survives and its former path still resolves |
| Major | Removing a deprecated identifier, or changing what an existing identifier means |

The middle row is the point. Improving a name or a position used to be a
breaking change, because the name was the key. It is now routine, which is
what makes the vocabulary safe to correct as understanding improves.

## Deprecation

A superseded identifier is not deleted immediately. It is marked deprecated
with a replacement, consumers warn on deprecated references, and removal
waits for a major version.

The reason is asymmetry: an identifier that vanishes breaks every consumer
silently and at a distance, while one that lingers costs only a warning.

## What earns an entry

A new entry is justified when all four hold:

1. The concept has materially different engineering semantics.
2. That difference affects standards, architecture, implementation, review,
   reuse, or context selection.
3. Existing attributes or capabilities cannot represent the distinction
   cleanly.
4. The concept is expected to recur.

A new vendor product or cloud SKU is not by itself a reason to add one — that
is a registry entry ([05-registries.md](05-registries.md)). The failure mode
this guards against is a semantic model that grows a class per product until
inheritance means nothing.

## Change process

Taxonomy changes arrive as pull requests carrying:

- the reason for the change;
- the proposed path, and the identifier assigned to the node;
- its parent classification;
- its semantic definition;
- examples;
- implementation and runtime mappings, where relevant;
- affected standards and decisions;
- migration impact and compatibility assessment.

CI validates every change: JSON syntax, schema conformance against an
explicit file-to-schema map, three-level consistency with each record's
declared `path`, `parent`, and `level` matching its position, and referential
integrity for every identifier cited anywhere in the folder. Identity is
checked too: an `id` must be unique, must never be reused, and must not
disappear between versions -- a node leaves by deprecation, never by
deletion. A JSON
file added with no mapped schema fails validation rather than being skipped,
so coverage cannot erode silently as the folder grows.

## Ownership

The Taxonomy has named maintainers, enforced through CODEOWNERS or
equivalent repository controls, spanning architecture governance, platform
engineering, developer productivity, infrastructure, and engineering
practice.

## Definition is central, consumption is local

The authoritative vocabulary lives in one repository. Consuming repositories
take a pinned version or a generated projection; they do not fork or redefine
canonical semantics, because a forked vocabulary stops being a shared
contract the moment it diverges.

Application-specific data stays local: local architecture, local ADRs, source
mappings, analysis findings, observed resource instances, and issue-specific
context manifests.

A repository may hold a compact generated projection carrying only what it
uses:

```text
.ai-agile/index/
├── taxonomy.json
├── implementations.json
├── standards.json
└── adrs.json
```

A projection records the taxonomy version and source commit it was generated
from, the selected canonical identifiers, and the implementation and runtime
mappings those require — so a stale projection is detectable rather than
silently wrong.
