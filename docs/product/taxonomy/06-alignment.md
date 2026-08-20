# Architecture alignment

CALM describes what was designed. Discovery describes what is running. Both
normalise into the same canonical architecture classes, which is what makes
the difference between them computable
([TX-2](02-principles.md#tx-2--intended-and-observed-architecture-share-one-vocabulary)).

---

## CALM alignment

CALM remains the authoritative representation of intended architecture. The
Taxonomy supplements it with a finer classification vocabulary — CALM says
what the nodes are and how they connect; the Taxonomy says precisely what
kind of thing each node is.

```text
CALM node-type            database
canonical classification  architecture/data/database/relational-database
implementation            postgresql
runtime                   aws/rds
```

`mappings/calm-to-canonical.json` provides deterministic candidate mappings.
CALM node types are coarse by design, so one type commonly maps to several
canonical subclasses; where it does, additional CALM metadata resolves the
choice rather than the Taxonomy guessing.

The Taxonomy never silently alters CALM intent. Classification adds a reading
of the design; it does not amend the design.

## Discovered CMDB alignment

Discovery connectors emit provider-specific JSON. That raw output is
evidence, not canonical representation — it describes an AWS resource in
AWS's terms, which is exactly the vocabulary problem the Taxonomy exists to
solve.

Normalisation runs per provider:

```text
raw discovery JSON
        ↓
provider adapter
        ↓
canonical architecture classification
        ↓
observed CMDB JSON
```

The adapter is the only component that needs to understand a provider's
vocabulary. Everything downstream sees canonical classes.

## Comparing intent with reality

Because intent and observation land on the same identifiers, comparison
operates over normalised semantic fields rather than textual JSON diffs. A
textual diff reports noise wherever two systems phrase the same fact
differently, and stays silent where genuine divergence is phrased similarly.

Comparison yields typed findings:

| Finding | Means |
|---|---|
| `missing-node` | Designed, not running |
| `unexpected-node` | Running, not designed |
| `missing-relationship` | A designed connection is absent |
| `unexpected-relationship` | An undesigned connection exists |
| `classification-mismatch` | The running thing is a different kind of thing |
| `implementation-mismatch` | Different technology than intended |
| `runtime-mismatch` | Different provider or deployment than intended |
| `attribute-mismatch` | Same kind of thing, different properties |
| `interface-mismatch` | Exposed interface differs from the design |
| `control-mismatch` | A required control is absent or differs |

The three coordinates of [05-registries.md](05-registries.md) are why the
middle rows are separable. Moving a database between providers is a
`runtime-mismatch` and nothing more; discovering that the relational store in
the design is a document store in production is a
`classification-mismatch`, which is a different conversation entirely.
