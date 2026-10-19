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

## Scenario: Orchestrator-owned scripts do not appear under .github/scripts

**Given** the script reorganization has been applied to the repository
**When** a developer lists all files under `.github/scripts/`
**Then** no pipeline-runtime-owned scripts are present there (worktree lifecycle, status operations, recovery, scratch, and branch/PR operations all reside only under `scripts/`)

## Scenario: Script resolution works when installed as a submodule

**Given** this repository is installed as a git submodule inside a consuming project
**When** the pipeline orchestrator starts and resolves a runtime script path
**Then** the resolved path points into the ai-coding-standards2 submodule's `scripts/` directory, not the consuming project's `.github/scripts/`

## Scenario: Conformance test rejects a new orchestrator script placed under .github/scripts

**Given** the ownership conformance tests have been added to the test suite
**When** a new pipeline-runtime script is placed under `.github/scripts/` rather than `scripts/`
**Then** the conformance test suite fails with a path-ownership violation message

## Scenario: build-affecting steps blocked while sizer is pending or in progress

**Given** an issue has been classified (a `classification: *` label is present) and sizer has not yet reached a terminal outcome
**When** the pipeline orchestrator evaluates which standard-delivery steps are eligible to run
**Then** all build-affecting standard-delivery steps from prd-writer onward are ineligible to run

## Scenario: issue flows through standard-delivery after sizer pass-through

**Given** an issue has been classified and sizer has determined it fits one development cycle (sizer reached a terminal outcome without applying the `epic` label)
**When** the pipeline orchestrator evaluates which standard-delivery steps are eligible next
**Then** prd-writer becomes eligible and the issue proceeds through standard-delivery without added waiting

## Scenario: Manual result apply succeeds with the override flag

**Given** a staged `result.json` for `00_ondemand/codebase-reviewer` associated with a valid issue number, and no override flag was previously used for this invocation
**When** the orchestrator is invoked with `--agent 00_ondemand/codebase-reviewer --issue N --interactive-result` and the manual-override flag
**Then** at least one agent is reported as triggered and the result is applied to the issue

## Scenario: Invocation without the override flag does not apply the result

**Given** the same staged `result.json` and issue number as above
**When** the orchestrator is invoked with `--agent 00_ondemand/codebase-reviewer --issue N --interactive-result` and no override flag
**Then** zero agents are reported as triggered and no result is applied

## Scenario: Slash command generator emits the override flag for schedule-triggered steps

**Given** the updated `scripts/generate_slash_commands.py` and the `00_ondemand/codebase-reviewer` step definition in `pipeline.json`
**When** the generator runs and regenerates `.claude/commands/maos-codebase-reviewer.md` and `.claude/commands/maos-codebase-reviewer-i.md`
**Then** neither generated command file references `codebase-reviewer:requested`, and both include the manual-override flag in their invocation instructions

## Scenario: Schedule fires at correct Eastern wall-clock time during winter (EST)

**Given** `pipeline.json` has `defaults.schedule_timezone` set to `"America/New_York"` and a flow declares `trigger.cron` of `"0 2 * * 1"` with no per-flow timezone override
**When** the orchestrator evaluates whether the schedule is due at 07:00 UTC on a Monday in January (EST, UTC-5)
**Then** the schedule is evaluated as due

## Scenario: Schedule fires at correct Eastern wall-clock time during summer (EDT)

**Given** `pipeline.json` has `defaults.schedule_timezone` set to `"America/New_York"` and a flow declares `trigger.cron` of `"0 2 * * 1"` with no per-flow timezone override
**When** the orchestrator evaluates whether the schedule is due at 06:00 UTC on a Monday in July (EDT, UTC-4)
**Then** the schedule is evaluated as due

## Scenario: Pipeline without defaults.schedule_timezone falls back to UTC

**Given** a `pipeline.json` with no `defaults.schedule_timezone` key
**When** the orchestrator evaluates `trigger.cron` of `"0 2 * * 1"` at Monday 02:00 UTC
**Then** the schedule is evaluated as due

## Scenario: Per-flow timezone override takes precedence over pipeline default

**Given** `pipeline.json` has `defaults.schedule_timezone` set to `"America/New_York"` and a flow declares `trigger.timezone` of `"UTC"` with `trigger.cron` of `"0 2 * * *"`
**When** the orchestrator evaluates the schedule at 02:00 UTC on any day
**Then** the schedule is evaluated as due
