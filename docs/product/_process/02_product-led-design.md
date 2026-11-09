# Product Design and Roadmap

Product design describes the desired state. The roadmap identifies the
business outcomes we intend to achieve and the order in which we intend to
deliver the capabilities that support them. The same capability identifiers
connect both views.

## Define the desired product

| Level | What to document |
| --- | --- |
| Product | Purpose, users, business context, outcomes, main journeys, and modules. |
| Module | A major area of business functionality, with its users, responsibilities, workflows, and components. |
| Component | A group of related capabilities, with its business rules, interactions, and dependencies. |
| Capability | A discrete behavior the product enables, with a stable ID, owning component, source product document, linked outcomes, and acceptance expectations. |

Write capabilities in terms of observable behavior. For example, **Search
Public Trees** means users can search published decision trees by keyword
and see matching results. Its capability record can point to dependencies,
approved scenarios, tests, and verification evidence as they become available.

Keep product intent in versioned documents under `docs/product/`. Use stable
headings, consistent terminology, and explicit links so people and agents
can find the same source. Agents can propose modules, components, and
capabilities from the design. People review the proposed structure and
confirm that it reflects the intended product.

## Product architecture and technical architecture

Product architecture defines the desired business behavior. Technical
architecture defines the engineering patterns and constraints for
implementing it. For **Search Public Trees**, the product design describes
what a search returns. The technical guidance can reference approved API,
security, observability, or performance requirements.

Keep the detailed rules in the architecture guidance and [standards
catalogue](../standards_taxonomy/README.md). Link the applicable guidance
from the capability so the implementation can be reviewed against both the
expected behavior and the relevant engineering rules.

## Plan delivery through the roadmap

A **phase** groups outcomes into a delivery horizon. An **outcome** describes
a measurable business result. Each outcome references the **capabilities**
required to achieve it, including capabilities from different components or
modules. Store the plan in a structured file such as `roadmap.yaml` and
reference capability IDs from the product design.

```yaml
version: 1
phases:
  foundation:
    name: Foundation
    outcomes:
      - increase-public-tree-usage
outcomes:
  increase-public-tree-usage:
    name: Increase Public Tree Usage
    description: Increase engagement with published decision trees.
    capabilities:
      - search-public-trees
      - view-public-tree
```

## Measure progress from evidence

A capability is verified when all required evidence passes. It may be
undefined, defined, specified, in progress, failed, or blocked before that
point. Generate status from the linked specifications, tests, and evidence.

- **Outcome progress** is verified required capabilities divided by total
  required capabilities.
- **Phase progress** rolls up outcome progress. Record any weighting used.
- **Roadmap gap** is the set of required capabilities that are still unverified.
- **Technical debt** is tracked separately against the delivered capability,
  applicable standard, supporting evidence, and proposed remediation.

Capability verification measures delivery progress. Measure achievement of
the business outcome separately using its defined measure.

When a capability is ready to enter delivery, use the [implementation and
verification guide](04_ai-agile-implementation.md) to turn it into approved,
testable work.
