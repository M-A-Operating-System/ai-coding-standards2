# Feature: Pipeline Epic-Completion Flow

## Scenario: All children of an epic closed triggers pr-reviewer on the accumulated issue PR

**Given** all child issues of epic #42 are closed
**When** the trigger.children: all_closed condition fires for issue #42
**Then** issue #42's 03_execute/pr-reviewer step runs against the issue-42 PR using the same review_loop, outcome_policy, and human-gate configuration as any other code PR

## Scenario: Epic closes only after its accumulated issue PR is reviewed and merged

**Given** epic #42's pr-reviewer step has completed and the human gate has been approved
**When** the issue-42 PR merges to its parent integration branch or main
**Then** issue #42 is closed as the production release and no separate incremental child-merge events are treated as the production release

## Scenario: Non-epic issues are unaffected by epic-completion flow changes

**Given** an open issue with no parent-issue or epic label exists in the pipeline
**When** the epic-completion flow executes for an unrelated epic
**Then** the non-epic issue's pipeline flow proceeds exactly as before the epic-completion flow change

## Scenario: Nested epics trigger pr-reviewer recursively as their children close

**Given** a sub-issue that is itself an epic and all of its child issues are closed
**When** the trigger.children: all_closed condition fires for the nested epic
**Then** the nested epic runs its own pr-reviewer against its issue-{N} -> issue-{parent_N} PR and closes only after that PR merges, which in turn enables the parent epic's trigger.children: all_closed to fire
