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

## Scenario: stateless step re-checks PR state after commit change

**Given** `merge-conflict` has previously been invoked for issue N and produced outcome "complete" for commit C1
**When** the orchestrator invokes `merge-conflict` again for issue N with a new head commit C2
**Then** the agent calls the GitHub API to check the current `mergeable_state` and writes `result.json` based on that fresh check, not the prior session's conclusion

## Scenario: retry after stale-session failure reaches an unused session

**Given** `merge-conflict` has failed because a resumed session replied without any fresh API calls
**When** the orchestrator re-drives the step for the same issue in a subsequent run
**Then** the step uses a session that has not previously concluded for this issue-step combination, giving it a genuine chance to produce a fresh result

## Scenario: interrupted run recovers idempotently on next run

**Given** a step's worktree directory exists from a previous interrupted run
**When** the orchestrator starts that step on the next pipeline run
**Then** `_create_run_worktree` detects the stale worktree, removes it, and creates a fresh one -- with no signal handler and no in-flight globals to read (issue #495: `_CURRENT_WIP`/`_CURRENT_WORKTREE` and the SIGTERM/SIGINT handler that used to read them were removed; a stranded `:wip` self-heals separately via `_reclaim_stale_wip`'s lease expiry)

## Scenario: filesystem/process logic runs as extracted scripts where genuinely separable, and stays inline where load-bearing

**Given** a step completes and its result file is present in the scratch directory
**When** the orchestrator processes the step's result
**Then** logic with no orchestrator-internal coupling and a safe degrade path -- the `gh` CLI bootstrap (`ensure-gh-cli.sh`), unpushed-commit recovery (`recover-unpushed-commits.sh`), and todos-block patching (`pipeline/todos_patch.py`) -- runs as a standalone script or module (issue #495), while the git push and worktree teardown that make a step's commit durable (`_push_step_branch`, `_create_run_worktree`, `_remove_run_worktree`) and the metrics/announcement builders that share orchestrator-internal types stay inline in `pipeline_orchestrator.py` as a cited STD-ARCH-035 exception (`adrs/adrs.json` ADR-002) -- routing a load-bearing push through the same script-resolution fallback used for best-effort operations would reintroduce issue #196's regression class (see `test_pushing_a_step_s_commits_needs_no_script_on_the_branch`)
