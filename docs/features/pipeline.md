# Feature: Pipeline

## Scenario: /maos-run works when ai-coding-standards2 is checked out as a nested submodule

**Given** a consuming repo with `ai-coding-standards2/` added as a git submodule and the whole-folder `.claude` symlink installed
**When** a human runs `/maos-run {N}` from the consuming repo's root
**Then** the driver locates and invokes `ai-coding-standards2/pipeline/pipeline_orchestrator.py`, not a nonexistent `pipeline/pipeline_orchestrator.py`

## Scenario: /maos-run continues to work in ai-coding-standards2's own repo

**Given** an interactive session working directly in ai-coding-standards2's own checkout (no nested submodule)
**When** a human runs `/maos-run {N}`
**Then** the driver locates and invokes `pipeline/pipeline_orchestrator.py` at the repo root, unchanged from current behaviour

## Scenario: Missing orchestrator script produces a clear stop, not a silent failure

**Given** neither `pipeline/pipeline_orchestrator.py` nor `ai-coding-standards2/pipeline/pipeline_orchestrator.py` exists relative to the working directory
**When** `/maos-run` is invoked
**Then** it stops and reports the missing prerequisite per the existing Fallback section, rather than attempting a tick against a path that doesn't exist

## Scenario: Worktree agent chooses --resume when a prior transcript exists

**Given** `invoke_agent()` is called with a `cwd` under a dot-prefixed directory (e.g. `.claude/worktrees/orchestrator/issue-N`)
**And** a session transcript file for the agent's UUID exists on disk under the CLI's actual project-directory encoding of that path
**When** the session-resume check runs
**Then** `--resume` is passed to the Claude CLI subprocess, not `--session-id`

## Scenario: New agent session is started when no prior transcript exists

**Given** `invoke_agent()` is called for any agent (worktree-based or not)
**And** no file matching `{agent_session_uuid}.jsonl` exists anywhere under any `.claude/projects/` directory reachable from `CLAUDE_CONFIG_DIR` or `HOME`
**When** the session-resume check runs
**Then** `--session-id` is passed to the Claude CLI subprocess, not `--resume`

## Scenario: Step 0 standalone gh api call is permitted under allowedTools

**Given** the orchestrator has spawned a coder subprocess with `--allowedTools` including `Bash(gh api repos/*/issues/*)`
**When** Step 0 issues a `gh api` call as a standalone Bash command with no leading variable assignment or `&&` chain on the same invocation
**Then** the call is permitted and returns the expected issue metadata without a permission denial

## Scenario: No multi-statement Bash blocks remain in documented Step 0 scripts

**Given** `coder.md` and `pr-reviewer.md` have been updated
**When** a reviewer reads the Step 0 section of each agent prompt file
**Then** every `gh api` call in those sections appears as a standalone Bash command, not embedded in a variable assignment, `&&` chain, or `if` conditional on the same invocation
