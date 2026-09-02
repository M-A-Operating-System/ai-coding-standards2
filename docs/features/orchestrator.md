# Feature: Orchestrator

## Scenario: A post_step failure after a genuinely successful agent run does not discard that success

**Given** an agent completes its own work correctly (e.g. `pr-reviewer` posts APPROVE and the PR is confirmed ready)
**When** a subsequent `post_steps` script for that same pipeline entry fails
**Then** the issue does not end up labeled `{agent}:failed` in a way that misrepresents the agent's actual, successful outcome

## Scenario: mark-pr-ready.sh does not fail when the PR is already ready

**Given** a PR that is already `draft: false` (marked ready by another path -- the driver's MCP assist, or the agent's own action)
**When** `mark-pr-ready.sh` runs as a post_step
**Then** it detects the PR is already ready and exits 0 without attempting the blocked `gh pr ready` call

## Scenario: Retrying after this specific failure converges instead of looping

**Given** `pr-reviewer:failed` was applied solely because of this post_step failure, in a session where `gh pr ready` is structurally blocked
**When** a human clears the label and the orchestrator retries
**Then** the retry does not deterministically hit the identical failure again -- it either succeeds or fails for a genuinely new reason

## Scenario: A scheduled tick's audit trail correctly identifies itself as unattended

**Given** `ai_orchestrator.yml` invokes the orchestrator with `--headless`
**When** a `system.tick` audit event is emitted
**Then** `actor.id` is `"github-actions"` and `actor.human` is `null`, as today

## Scenario: A human-triggered tick's audit trail correctly identifies a human trigger

**Given** a human runs `pipeline_orchestrator.py` without `--headless` (e.g. via `/maos-run`)
**When** a `system.tick` audit event is emitted
**Then** `actor.human` reflects that a human triggered the run, not the current hardcoded `null`

## Scenario: A human-triggered tick still performs real work

**Given** `/maos-run` invokes the orchestrator without `--headless`
**When** an eligible step exists
**Then** the orchestrator spawns the real agent subprocess and mutates labels exactly as it does today -- `--headless`'s absence must not switch the orchestrator into resolve-only/no-op behaviour

## Scenario: An orchestrator-spawned agent subprocess is always axis-B-headless, regardless of trigger

**Given** an agent is invoked via `_build_agent_env()` (spawned by the orchestrator), whether the tick was triggered by cron or by `/maos-run`
**When** the subprocess's environment is inspected
**Then** `AI_AGILE_EXECUTION_MODE` is `headless` in both cases -- it must not vary with `--headless`

## Scenario: .pipeline-stop halts the scheduled/headless path

**Given** `.pipeline-stop` exists and `ai_orchestrator.yml` invokes the orchestrator with `--headless`
**When** `main()` runs
**Then** it logs the stop and exits without invoking any agent, exactly as today

## Scenario: .pipeline-stop does not block an interactive tick

**Given** `.pipeline-stop` exists and a human runs the orchestrator without `--headless` (e.g. via `/maos-run`)
**When** `main()` runs
**Then** it logs that the pipeline is stopped but proceeds to evaluate and advance eligible work exactly as if the marker were absent

## Scenario: /maos-{agent}-i obtains its tool allowlist from the orchestrator instead of hand-parsing frontmatter

**Given** `/maos-{agent}-i <issue-number>` is invoked
**When** it resolves the target agent's invocation parameters
**Then** it does so via the orchestrator's resolve-only mode (`--print-prompt`), which returns exactly what `pipeline_orchestrator.py` would pass as `--allowedTools` for a real subprocess spawn of that same agent (issue #402 -- nothing enforces this list interactively any more; it is the person's preview of what the real headless run is allowed to do)

## Scenario: Resolve-only mode mutates no GitHub state

**Given** the orchestrator is invoked in resolve-only mode for a specific agent
**When** it prints the resolved prompt/tools/env
**Then** no labels are changed, no `:wip` is applied, and no GitHub API write calls are made

## Scenario: Each call site builds env from a named variable list

**Given** the five call sites in `pipeline/pipeline_orchestrator.py`
**When** the work is complete
**Then** each builds its env from an explicit named collection of variable names, never by spreading `os.environ`, and each site has its own distinct list

## Scenario: An ADR exception requires demonstrated necessity

**Given** a call site where investigation shows broad inheritance is genuinely required
**When** an ADR is filed in `adrs/adrs.json` citing STD-SEC-022
**Then** the ADR includes the specific demonstration of why narrowing is not possible, and the call site is annotated with a reference to the ADR

## Scenario: A narrowed script still works

**Given** a call site narrowed to a named variable set
**When** its script runs in a real orchestrator tick
**Then** it succeeds, and no variable it needs is missing

## Scenario: pr-reviewer stops flagging the excused sites

**Given** an ADR covers a call site that keeps broad inheritance
**When** `pr-reviewer` checks a diff touching that line against STD-SEC-022
**Then** it treats the standard as overridden rather than violated

## Scenario: The agent path is untouched

**Given** this work
**When** `_build_agent_env` is inspected
**Then** it is unchanged -- it already allowlists, and is not in scope here

## Scenario: Resolve-only returns the same allowlist as a real spawn

**Given** an agent with `extra_allowedTools` entries in `pipeline.json`
**When** its invocation is resolved via `--print-prompt`
**Then** the returned `allowed_tools` equals what `invoke_agent` would pass as `--allowedTools` for the same agent and work item

## Scenario: The defaults are included

**Given** `pipeline.json` sets `defaults.extra_allowedTools` to `["Write", "Edit"]`
**When** any agent's invocation is resolved via `--print-prompt`
**Then** `Write` and `Edit` appear in the returned `allowed_tools`

## Scenario: A PR number resolves as a PR

**Given** `--print-prompt` is given a number that refers to a pull request and no explicit `--kind`
**When** the invocation is resolved
**Then** the probed kind is `pr`, and the printed env carries `WORK_ITEM_KIND=pr` and `PR_NUMBER`

## Scenario: An explicit --kind is an override, not a hint

**Given** `--print-prompt --kind issue` is given a number that refers to a pull request
**When** the invocation is resolved
**Then** the printed env carries `WORK_ITEM_KIND=issue` -- probing does not overrule the operator

## Scenario: Resolving an agent against an object kind it does not handle is reported

**Given** `03_execute/coder` lists `object: ["issue"]` in `pipeline.json`
**When** `--print-prompt` resolves it against a PR
**Then** the orchestrator logs a WARNING naming the agent and the kind, and resolves it anyway

## Scenario: The drift is caught by a test, not by inspection

**Given** the two resolution paths
**When** the test suite runs
**Then** a test compares the two resolved allowlists directly and fails if they differ

## Scenario: /maos-{agent} spawns a real subprocess with no new orchestrator code path

**Given** `/maos-{agent} <issue-number>` applies `{agent}:requested` to the work item
**When** the orchestrator runs a normal tick (`--repo R --issue N`, no `--print-prompt`, no `--interactive-result`)
**Then** it dispatches `{agent}` exactly as the headless GitHub Actions path does, via the same `_should_run`/`_run_agent` loop, native `--allowedTools` and all -- `:requested` bypasses only the trigger-label check, so unmet dependencies still block it

## Scenario: --interactive-result applies a person-produced result under the same eligibility check

**Given** a person and the chat-AI have written `$AI_AGILE_SCRATCH/result.json` for `{agent}` on issue N via `--print-prompt`'s resolve-only mode
**When** `pipeline_orchestrator.py --repo R --issue N --agent {agent} --interactive-result` runs
**Then** it applies exactly the eligibility check, `:wip`/announcement/artefact/label/body-write/post_steps handling a real subprocess run would -- reading the file instead of spawning a subprocess, but never bypassing `_should_run`

## Scenario: A missing or invalid interactive result fails loud, not silently

**Given** `--interactive-result` is invoked but `$AI_AGILE_SCRATCH/result.json` is missing or fails `_read_step_result`'s validation
**When** the orchestrator applies the result
**Then** it resolves exactly like a crashed subprocess -- `{agent}:failed` is applied, not a silent no-op

## Scenario: The audit trail distinguishes a person's activity from a spawned agent's

**Given** the same step completes once via `/maos-{agent}` and once via `--interactive-result`
**When** each run's terminal `agent.*` audit event is emitted
**Then** the `--interactive-result` run's event records `performed_by=human` and the subprocess run's records `performed_by=agent` -- everything else about how the result is applied is identical (MI-3)

## Scenario: Applying an interactive result never re-checks out the issue branch from origin

**Given** a `commit_after` agent (e.g. `coder`) whose person-driven session has already made uncommitted edits on the issue branch
**When** `--interactive-result` applies the written result
**Then** the orchestrator does not fetch and hard-reset onto `origin/issue-{N}` before committing -- that checkout exists to stage a fresh subprocess onto the right branch, and running it here would discard the person's own edits

## Scenario: A dropped permissions grant is surfaced, not swallowed

**Given** `.claude/settings.json` declares `permissions.allow` entries and the workspace is not marked trusted in the Claude CLI's config
**When** the orchestrator invokes any agent
**Then** it logs at WARNING which entries will be dropped and how to remedy it
**And** the run's `agent.invoked` audit event records `grants_dropped=<count>`

## Scenario: The orchestrator always runs its own code from main

**Given** a `pull_request` event fires the orchestrator workflow
**When** the checkout step runs
**Then** it checks out `main`, not `refs/pull/N/merge`
**And** a PR that edits an agent prompt, an orchestration script or the orchestrator itself cannot alter the run that reviews it

## Scenario: Pinning to main does not stop the PR's own content being reviewed

**Given** the orchestrator is running from `main` on a `pull_request` event
**When** `pr-reviewer` reviews the PR
**Then** it still sees the proposed changes, because it reads the unified diff and the files at the PR head over the GitHub API rather than from the local working tree
**And** the PR's own tests still run, because `test.yml` is a separate workflow triggered on the PR head

## Scenario: A commit_after agent still reaches its issue branch

**Given** the workspace is checked out at `main`
**When** the orchestrator invokes an agent whose step declares `git_ops.commit_after`
**Then** it fetches and checks out `issue-{N}` explicitly before the invocation, so the pin does not strand the agent on the wrong branch

## Scenario: An agent's working files go to the scratch directory, not the repo

**Given** an agent is given `$AI_AGILE_SCRATCH` as an absolute path in its runtime context
**When** it stages a comment body before posting it
**Then** it creates the file with the `Write` tool at that absolute path
**And** it needs no `cat`, `mkdir` or `rm` grant to do so

## Scenario: A file written to the repo root is removed after the agent runs

**Given** an agent writes a working file to a relative path, so it lands at the repository root
**When** the agent's invocation finishes, whatever its outcome
**Then** the orchestrator removes the file and logs which agent wrote it
**And** this happens for every agent, not only those with `git_ops.commit_after`

## Scenario: A file that was already at the root is left alone

**Given** an untracked file exists at the repository root before an agent is invoked
**When** the agent finishes without touching it
**Then** the orchestrator leaves it in place, because it compares against a snapshot taken before the run

