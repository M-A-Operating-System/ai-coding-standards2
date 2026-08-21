# Feature: Agents

## Scenario: AGENTS.md states a concrete scratch-file convention, not just the principle

**Given** `.claude/AGENTS.md` after this change
**When** an agent needs a working file mid-run
**Then** the document states the exact variable (`$AI_AGILE_SCRATCH`), how to resolve it when it is unset (`${AI_AGILE_SCRATCH:-...}`, for a human running a `/maos-*` command), and a worked example -- not just "don't leave state behind"

## Scenario: The worked example stages the body and posts it from the file

**Given** an agent posts a comment whose body contains JSON or a fenced block
**When** it follows the example in `.claude/AGENTS.md`
**Then** the example writes the body into `${AI_AGILE_SCRATCH:-/tmp}` and posts it with `gh api --method POST ... -F body=@<that file>`
**And** it does not use `gh pr comment --body-file`, which is GraphQL-only and 403s in a restricted session
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

## Scenario: A tick killed mid-run leaves no debris for the next one

**Given** the orchestrator is killed by an uncatchable signal, so no teardown runs
**When** the next run of that same agent on that same work item begins
**Then** `$AI_AGILE_SCRATCH` is empty -- setup clears the directory before creating it, so the lifecycle is self-healing and needs no signal handler

## Scenario: An interactively-run agent gets the same scratch directory as an orchestrated one

**Given** an agent is run by hand through `/run-agent` rather than by the orchestrator
**When** the invocation is resolved
**Then** `--print-prompt` returns `AI_AGILE_SCRATCH` in its env, and `/run-agent` creates that directory with `scratch-setup.sh` before the agent starts and removes it with `scratch-teardown.sh` at the end
**And** the agent therefore does not fall back to a shared `/tmp` where two concurrent runs would collide on the same filenames

## Scenario: Only steps that were given a scratch directory are torn down

**Given** a `script` step, which is never given `AI_AGILE_SCRATCH`
**When** the orchestrator finishes running it
**Then** no teardown runs for it -- teardown is paired with setup, never orphaned

## Scenario: A leaked root file never reaches a commit

**Given** an agent writes a working file at the repo root instead of into `$AI_AGILE_SCRATCH`
**When** `commit-agent-work.sh` stages the agent's work
**Then** the new root-level file is unstaged before the commit is written, and an error naming it is logged
**And** the file is left on disk rather than deleted, so nothing the agent produced is destroyed

## Scenario: The root-file guard does not cost the agent its real work

**Given** an agent modifies a tracked root file such as `README.md` and adds a new nested file
**When** `commit-agent-work.sh` stages the agent's work
**Then** both are committed -- only *new* files at depth 0 are refused

## Scenario: A run whose entire output is leaked root files produces no commit

**Given** an agent writes nothing but root-level working files
**When** `commit-agent-work.sh` runs
**Then** no commit is created at all, rather than an empty or leak-only one
