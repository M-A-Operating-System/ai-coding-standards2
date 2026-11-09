# Implementation and Verification

Implementation turns a prioritized capability into verified software. Start
with the [product design and roadmap](02_product-led-design.md). Use the
capability ID to connect the GitHub issue, specifications, pull requests,
tests, and verification evidence.

## Specify and approve the change

An issue should link to the capability, explain the problem and desired
outcome, and identify scope, dependencies, and relevant architecture guidance.
An agent can draft the product requirements document (PRD) and express the
expected behavior as Gherkin scenarios. The stakeholder reviews the scope
and scenarios together before the design moves forward.

```gherkin
Feature: Search Public Trees

Scenario: Search for a published tree
  Given published decision trees exist
  When a user searches for "mortgage"
  Then matching decision trees are displayed
```

## Publish the design before building

In the standard delivery flow, a design pull request updates
`docs/product/` and records approved scenarios in
`docs/features/{feature}.md`. Once the design PR has been approved and
merged to its target branch, the code branch starts from the version that
already contains the design. This makes the approved behavior available to
the build and surfaces conflicting design changes before coding.

## Implement and verify

Derive tests from the approved scenarios and link the tests back to the
capability. The implementation should follow the applicable
[standards and technical guidance](../standards_taxonomy/README.md).
For substantial changes, make the affected areas, test strategy, risks,
assumptions, and decisions visible in the implementation plan.

The code pull request should show the capability and linked issue, the
behavior delivered, the scenarios and tests that cover it, and any known
technical debt or decisions a reviewer needs to make. Use structured
evidence where practical, including CI results, test reports, and any
security, performance, or deployment checks required by the change.

Automated checks and agent review provide evidence for the human reviewer.
Work that fails a required check returns for correction or escalates through
the workflow. People remain accountable for approval, risk acceptance, and
review decisions. The [generated pipeline reference](pipeline-reference.md)
shows the configured steps and gates.

## Feed evidence into the roadmap and release

Record the verification result against the capability so roadmap progress
can be calculated from evidence. Link any technical debt to the capability,
applicable standard, finding, and proposed remediation. Once the code is
reviewed and merged, the issue, pull request, and evidence are available to
[release management](06_release-management.md).
