# Feature: Sizer

## Scenario: confirm-gate advances the pipeline past sizer
**Given** the sizer step has completed and the issue carries `sizer:review`
**When** the operator invokes `--confirm-gate` for the sizer step
**Then** the issue advances past the gate and the pipeline continues to the next step

## Scenario: gate prompt names a label not already present on the issue
**Given** the sizer step has completed and `sizer:review` is on the issue
**When** the orchestrator posts the human gate prompt for the sizer step
**Then** the prompt instructs the human to apply a label that is not currently on the issue
