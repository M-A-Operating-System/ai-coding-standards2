# Semantic domains

Four domains carry meaning. They are separate because they answer different
questions about the same system, and linkable because the answers relate.

| Domain | Answers |
|---|---|
| [Architecture](#architecture) | What kind of thing is this, structurally? |
| [Patterns](#patterns) | How is this recurring problem solved? |
| [Code](#code) | What role does this source structure play? |
| [Concepts](#concepts) | What engineering property is being achieved? |

---

## Architecture

The architecture domain classifies architectural objects in a
provider-neutral way. Its families cover the span of a system:

```text
system        compute       data          storage
messaging     networking    identity      security
integration   observability ai-ml         experience
platform      external
```

A worked branch:

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

Technology stays out of it. PostgreSQL maps to
`architecture/data/database/relational-database` and MongoDB to
`architecture/data/database/document-database` through the implementation
registry ([05-registries.md](05-registries.md)), not by appearing in the tree.

## Patterns

The patterns domain describes reusable engineering approaches — how a
recurring problem is solved.

```text
patterns/api/request-processing/idempotent-handler
patterns/persistence/data-access/repository
patterns/messaging/consumption/idempotent-consumer
patterns/resilience/retry/exponential-backoff
patterns/security/authorization/role-based-access-control
```

A pattern is an approach, not an artefact. The reusable component that
embodies a pattern is a separate thing, catalogued elsewhere and pointing
back at the pattern it implements ([08-consumption.md](08-consumption.md)).

## Code

The code domain describes meaningful structural roles in source code,
deliberately above primitive syntax
([TX-3](02-principles.md#tx-3--primitive-code-semantics-belong-to-static-analysis-systems)).

```text
code/api/handler/request-handler
code/api/middleware/request-middleware
code/domain/model/aggregate-root
code/persistence/repository/repository-implementation
code/messaging/consumer/message-consumer
code/testing/test/integration-test
```

The underlying observable facts — this is a class, it imports that module,
it is decorated so — come from static analysis. Rules carry those facts to
these identifiers ([07-code-classification.md](07-code-classification.md)).

## Concepts

The concepts domain represents technology-neutral engineering properties and
concerns.

```text
concepts/reliability/idempotency/request-idempotency
concepts/reliability/fault-tolerance/circuit-breaking
concepts/security/authorization/least-privilege
concepts/observability/correlation/request-correlation
concepts/maintainability/modularity/separation-of-concerns
```

Concepts are what patterns and code are *for*. They are the domain a standard
most often wants to talk about when it cares about a property rather than a
shape.

## Cross-domain relationships

The domains are separate but intentionally linkable, and the links are
declared rather than inferred:

```text
patterns/persistence/data-access/repository
    → typically-implemented-as
code/persistence/repository/repository-implementation

patterns/api/request-processing/idempotent-handler
    → supports-concept
concepts/reliability/idempotency/request-idempotency

code/api/handler/request-handler
    → typically-realizes
architecture/compute/service/api-service
```

These relationships live in `mappings/cross-domain.json` and are
machine-readable. A relationship that can be codified once is not inferred
repeatedly by agents
([TX-4](02-principles.md#tx-4--deterministic-classification-is-the-default)).
