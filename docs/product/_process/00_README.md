# Product-First AI Agile Process

This is one implementation of an AI-first Agile pipeline. We chose a
**Product-First** approach. Every delivery change starts from a well-defined
product design and roadmap. The design describes what the product should do
and the capabilities it needs. The roadmap connects those capabilities to
business outcomes and sets their delivery order.

A capability is the link between design, planning, and delivery. Its
specification defines the behavior to build, tests verify the implementation,
and the resulting evidence shows which capabilities have been delivered.
That evidence is used to measure roadmap progress.

The [orchestrator](../orchestrator/README.md) runs the workflow and can also run
other pipeline definitions. The process guides describe how we work. The
[generated pipeline reference](pipeline-reference.md) shows the flows, steps,
dependencies, and approvals declared in the shipped configuration.

## Read the process in order

| Guide | What it covers |
| --- | --- |
| [Product design and roadmap](02_product-led-design.md) | Define the desired product, identify its capabilities, and plan delivery around business outcomes. |
| [Implementation and verification](04_ai-agile-implementation.md) | Turn an approved capability into testable behavior, publish the design, and verify the implementation before merge. |
| [Release management](06_release-management.md) | Publish eligible merged changes and keep a record of what shipped. |

People set direction, approve scope and risk, and review results. Agents
help interpret product intent and generate artifacts. Scripted checks handle
work that can be expressed as a rule.

Keep the artifacts versioned, readable by people and tools, and linked by
stable identifiers. A reviewer should be able to trace a released change back
through its pull request, tests, and approved specification to the original
capability and product decision.

[Product documentation](../README.md)
