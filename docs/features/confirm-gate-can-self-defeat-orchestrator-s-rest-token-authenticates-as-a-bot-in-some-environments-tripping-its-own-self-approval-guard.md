# Feature: --confirm-gate can self-defeat: orchestrator's REST token authenticates as a bot in some environments, tripping its own self-approval guard

## Scenario: confirm-gate detects bot-attributed label and fails with actionable error

**Given** the orchestrator's resolved REST token authenticates as a bot actor on GitHub
**When** a pipeline operator runs the orchestrator with `--confirm-gate` on an issue at a gate step
**Then** the command exits with a non-zero status and prints an error message that names the bot-attribution cause and describes a remediation path

## Scenario: confirm-gate succeeds when token is human-attributed

**Given** the orchestrator's resolved REST token authenticates as a human user on GitHub
**When** a pipeline operator runs the orchestrator with `--confirm-gate` on an issue at a gate step
**Then** the gate label is applied, the labeled event records the human actor, and the command reports success
