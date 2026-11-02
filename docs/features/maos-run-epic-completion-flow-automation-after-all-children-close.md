# Feature: Maos-Run Epic-Completion Flow Automation After All Children Close

## Scenario: Epic-completion flow triggers after all children close

**Given** `/maos-run` has been invoked on a decomposed epic and all child issues are now closed
**When** the epic-driving loop finishes processing the last child issue
**Then** `/maos-run` continues by driving the epic issue itself through the `epic-completion` flow (`create-pr` -> `epic-pr-reviewer` -> merge) rather than stopping

## Scenario: Human gate from epic-completion flow is relayed without auto-approval

**Given** all child issues of an epic are closed and `/maos-run` is driving the epic issue through the `epic-completion` flow
**When** the `epic-completion` flow raises a human gate
**Then** the gate is relayed to the operator in the same way child gates are relayed and is not silently skipped or auto-approved

## Scenario: Epic-completion flow does not trigger while a child issue remains open

**Given** a decomposed epic where at least one child issue is still open
**When** `/maos-run`'s epic-driving loop reaches the end of the child list
**Then** the `epic-completion` flow is not triggered and `/maos-run` exits without driving the epic issue through `epic-completion`

## Scenario: Non-epic single-issue invocations remain unaffected

**Given** a `/maos-run` invocation on a single non-epic issue
**When** the issue's pipeline flow completes
**Then** `/maos-run` produces the same result as before this change with no epic-completion logic applied
