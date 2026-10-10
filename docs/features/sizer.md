# Feature: Sizer

## Scenario: confirm-gate advances the pipeline past sizer
**Given** the sizer step has completed and the issue carries `sizer:review`
**When** the operator invokes `--confirm-gate` for the sizer step
**Then** the issue advances past the gate and the pipeline continues to the next step

## Scenario: gate prompt names a label not already present on the issue
**Given** the sizer step has completed and `sizer:review` is on the issue
**When** the orchestrator posts the human gate prompt for the sizer step
**Then** the prompt instructs the human to apply a label that is not currently on the issue

## Scenario: Resumed sizer session routes to re-run-after-review path when prior decomposition exists
**Given** the sizer agent is invoked in a resumed `per_issue` session and sub-issues already exist for the issue (prior decomposition was completed in an earlier run)
**When** the agent executes Step 0's bash check against the issue's comment history
**Then** the agent proceeds to Step 5 (re-run-after-review) and writes `outcome: "complete"` to result.json, and the summary field states that Step 0 found a prior decomposition via the bash check

## Scenario: Fresh sizer invocation proceeds through normal decomposition when no prior decomposition exists
**Given** the sizer agent is invoked for an issue with no existing sub-issues and no prior decomposition in the comment history
**When** the agent executes Step 0's bash check against the issue's comment history
**Then** the agent proceeds through the normal sizing flow (Steps 1 and beyond) and the result.json summary field states that Step 0 found no prior decomposition
