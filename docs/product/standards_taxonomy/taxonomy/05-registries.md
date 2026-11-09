# Registries

Concrete technology is kept out of the semantic model
([TX-1](02-principles.md#tx-1--semantic-meaning-is-separate-from-implementation)).
Two registries hold it, each pointing at canonical classes rather than
extending them.

---

## Implementations

`implementations/implementations.json` maps concrete technologies to the
semantic classes they realise.

An implementation may realise more than one canonical class. PostgreSQL is a
relational database; used as a job queue it is also something else. The
registry records what a technology *can* be; the usage context decides which
classification applies to a particular instance, and the classification
recorded against that instance is the specific one.

This is why a new vendor product is cheap. It is a registry entry naming
existing classes — not a new class, and not a change to the tree.

## Runtimes

`runtimes/runtimes.json` describes provider and deployment realisations.

```text
aws/rds            azure/functions      gcp/cloud-sql
aws/lambda         azure/aks            gcp/gke
aws/eks                                 on-prem/bare-metal
                                        on-prem/kubernetes
```

Runtime identifiers are distinct from implementation identifiers, and the
distinction is load-bearing: `postgresql` is what the thing is,
`aws/rds` is where it runs. The same implementation runs on several
runtimes, and the same runtime hosts several implementations.

## The three coordinates

Together with a canonical class, the registries give any classified object
three independent coordinates:

```text
canonical classification   SUB000042  architecture/data/database/relational-database
implementation             postgresql
runtime                    aws/rds
```

The classification coordinate is stored as the identifier; the path is shown
alongside for readability and is not what gets written down
([TX-5](02-principles.md#tx-5--identity-is-immutable-names-and-paths-are-not)).

Each can change without the others. Migrating from RDS to self-hosted
PostgreSQL changes the runtime alone. Swapping PostgreSQL for MySQL changes
the implementation alone. Only a genuine change in what the component *is*
touches the classification — and that is the change worth noticing in an
architecture comparison ([06-alignment.md](06-alignment.md)).
