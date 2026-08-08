# Feature: Docs

## Scenario: A new consumer can identify which mode to use

**Given** a consumer reading the updated docs
**When** they want to run the pipeline for the first time
**Then** they can find a Quick Start that gets a first run working in either mode within a few minutes, with prerequisites listed

## Scenario: Both modes are documented with their real requirements

**Given** the docs
**When** a consumer compares scheduled vs. in-session
**Then** each mode's auth model (API key secret vs. session/OAuth), trigger mechanism, and gate-approval flow are described accurately and match current behaviour (`ai_orchestrator.yml`, `maos-run.md`)

## Scenario: Current limitations are disclosed, not discovered by trial and error

**Given** the in-session mode
**When** a consumer reads about it
**Then** the docs state that `00_ondemand/*` agents are not yet REST-converted (so epics/sizer/cleanup steps won't run in-session) and that a restricted session cannot mark a PR ready via `gh pr ready` (handled by the driver's MCP fallback)

## Scenario: Docs stay in sync with the command implementation

**Given** `.claude/commands/maos-run.md` and the new consumer docs
**When** either changes
**Then** they cross-reference each other so a reader lands on the authoritative source for mechanism (`maos-run.md`) vs. concept/onboarding (product docs)
