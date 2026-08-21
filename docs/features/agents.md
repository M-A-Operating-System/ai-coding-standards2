# Feature: Agents

## Scenario: AGENTS.md states a concrete scratch-file convention, not just the principle

**Given** `.claude/AGENTS.md` after this change
**When** an agent needs a working file mid-run
**Then** the document states the exact variable (`$AI_AGILE_SCRATCH`), how to resolve it when it is unset (`${AI_AGILE_SCRATCH:-...}`, for a human running a `/maos-*` command), and a worked example -- not just "don't leave state behind"

## Scenario: The worked example stages the body and posts it with --body-file

**Given** an agent posts a comment whose body contains JSON or a fenced block
**When** it follows the example in `.claude/AGENTS.md`
**Then** the example writes the body into `$SCRATCH` and posts it with `gh pr comment --body-file`
**And** the example never inlines a body via `--body "$(cat <<EOF ...)"`, which needs backticks and `$` shielded from the shell twice over and is the form agents were observed routing around

## Scenario: Orchestrator creates an empty scratch directory before each agent run

**Given** `pr-reviewer` (which has no cleanup step of its own) is about to run on a work item
**When** the orchestrator invokes the agent
**Then** `$AI_AGILE_SCRATCH` exists and is empty -- even if a prior invocation left files there

## Scenario: Working tree is unchanged by an agent run that uses scratch files

**Given** an agent writes files under `$AI_AGILE_SCRATCH` during its run
**When** the run completes (in any outcome: complete, review, or blocked)
**Then** `git status` at the repo root shows no new untracked or modified files

## Scenario: Orchestrator removes the scratch directory on the failure path

**Given** an agent exits non-zero without emitting a sentinel
**When** the orchestrator applies `:failed` and posts the failure announcement
**Then** `$AI_AGILE_SCRATCH` no longer exists -- the same cleanup runs as on the success path

## Scenario: A retry receives an empty scratch directory

**Given** an agent run fails and the orchestrator retries it on the same work item
**When** the retry begins (same `SESSION_ID`, same `$AI_AGILE_SCRATCH` path)
**Then** `$AI_AGILE_SCRATCH` is empty -- the retry cannot read the previous attempt's files
