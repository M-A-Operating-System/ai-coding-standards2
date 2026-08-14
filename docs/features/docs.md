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

## Scenario: Why gh CLI/REST is used instead of GitHub MCP tools is explained

**Given** the in-session mode's current limitations
**When** a consumer asks why pipeline scripts and agents call `gh api` instead of GitHub MCP tools
**Then** the docs explain that `pipeline_orchestrator.py`, `.github/scripts/*.sh`, and the scheduled GitHub Actions runner have no MCP access (bare subprocess / headless / no interactive session), so token-based gh/REST is the mechanism that works uniformly across both operating modes

## Scenario: Checking gh availability correctly is documented

**Given** the in-session mode's current limitations
**When** a consumer or session checks whether gh is usable
**Then** the docs state that `gh auth status` can report failure via a blocked GraphQL validation call even when `gh api` REST calls succeed, and that `gh api user` (or an equivalent REST call) is the correct check

## Scenario: A session's own "no gh CLI" instruction is correctly framed

**Given** a session's system prompt stating it has no gh CLI access
**When** a consumer reads the docs
**Then** the docs clarify this is a policy instruction to that interactive assistant (use MCP for its own actions), not evidence that the gh binary or its token are unavailable to scripts/agents it invokes via Bash

## Scenario: Docs stay in sync with the command implementation

**Given** `.claude/commands/maos-run.md` and the new consumer docs
**When** either changes
**Then** they cross-reference each other so a reader lands on the authoritative source for mechanism (`maos-run.md`) vs. concept/onboarding (product docs)
