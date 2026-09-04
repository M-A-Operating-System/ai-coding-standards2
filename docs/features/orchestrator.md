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

## Scenario: A bot-applied gate label does not satisfy the gate

**Given** an agent's `human_gate_label` is present on a work item, applied by a bot actor (`actor.type == "Bot"` or a `[bot]`-suffixed login)
**When** `_gate_label_human_applied` verifies it
**Then** it returns False -- the gate is not treated as satisfied, and `promote_gated_agents` leaves the step in `:review`

## Scenario: An inconclusive gate check refuses, it does not admit

**Given** any of: the issue-events API call raises, returns an unexpected (non-list) payload, has no `labeled` event for the gate label, or that event's actor cannot be determined as `type == "User"`
**When** `_gate_label_human_applied` evaluates the gate
**Then** it returns False and logs a fail-closed warning naming the reason -- a transient API error or ambiguous actor never admits an unverified approval (MI-7, STD-ARCH-014)

## Scenario: A genuinely human-applied gate label satisfies the gate even on an issue with many prior label events

**Given** an issue whose gate label's `labeled` event falls beyond the GitHub events API's first page
**When** `_gate_label_human_applied` verifies it
**Then** it paginates through the issue's events until it finds the gate label's most recent `labeled` event, rather than treating a first-page miss as "no matching event"

## Scenario: Headless gate-crossing accepts only a label a person applied from their own account

**Given** a headless (scheduled) tick evaluating a work item whose gated step is in `:review`
**When** the human-gate label is present
**Then** promotion to `:complete` happens only if `_gate_label_human_applied` verifies a human account applied it -- the pipeline itself never crosses the gate, because no human is present during a headless tick

## Scenario: Interactive gate-crossing is the orchestrator recording a relayed confirmation, never the driver writing the label itself

**Given** a person confirms a gate approval to the chat-AI driving `/maos-run` or `/approve-prd`
**When** the driver runs `pipeline_orchestrator.py --repo R --agent {agent} --issue N --confirm-gate`
**Then** the orchestrator itself calls `gh.add_label` for the gate label -- the driver never calls `gh issue edit --add-label` or an equivalent MCP write itself -- and the label's GitHub-recorded actor is the person's own account, satisfying the same `_gate_label_human_applied` check a headless human-applied label would (one mechanism, not two)

## Scenario: --confirm-gate refuses when the named agent has no gate to confirm

**Given** `--agent` names a step whose `human_gate_label` is unset (e.g. `03_execute/coder`)
**When** `--confirm-gate` is invoked
**Then** it refuses with an error naming the agent, rather than silently doing nothing

## Scenario: --confirm-gate refuses to paper over an already-present non-human label

**Given** the gate label is already present on the work item but was not verifiably applied by a human (e.g. a stale bot-applied label from before this mechanism existed)
**When** `--confirm-gate` is invoked
**Then** it refuses rather than re-adding the label -- `gh.add_label` on an already-present label is a GitHub no-op that generates no new `labeled` event, so silently proceeding would leave the prior bot-authored event as the most recent one -- and it names the exact `gh issue edit --remove-label` command to run first

## Scenario: --confirm-gate is a genuine no-op when the label is already present and was human-applied

**Given** the gate label is already present and `_gate_label_human_applied` verifies it as human-applied
**When** `--confirm-gate` is invoked again
**Then** it reports the gate as already confirmed and does not call `gh.add_label` a second time

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
**Then** it fetches `issue-{N}` and checks it out into its own isolated git worktree before the invocation, so the pin does not strand the agent on the wrong branch

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

## Scenario: An untagged item claims everything

**Given** an issue carries no `component:` label
**When** the orchestrator evaluates whether it can claim the item's components before starting it
**Then** it claims everything -- no other item, tagged or untagged, may claim anything while it runs, exactly as sequential as the pipeline was before component claims existed

## Scenario: Two items with disjoint components run at once

**Given** issue A carries only `component:frontend` and issue B carries only `component:backend`, and neither is currently claimed
**When** the orchestrator evaluates both in the same tick
**Then** it claims `component:frontend` for A and `component:backend` for B and starts both, since neither claim overlaps the other

## Scenario: An item waits when it cannot claim every component it names at once

**Given** issue A carries `component:frontend` and `component:backend`, and another in-flight item already holds `component:backend`
**When** the orchestrator evaluates issue A
**Then** it does not start A, and does not partially claim `component:frontend` while waiting for `component:backend` -- an item only ever claims all of what it names or none of it

## Scenario: Headless answers from its own settled state

**Given** a headless tick already fetched all work items and their labels at tick start
**When** it evaluates whether a later item in the same tick can claim its components
**Then** it decides from that in-memory snapshot, updated as this tick launches agents, without a further GitHub call

## Scenario: Interactive reads component claims fresh, not from a stale snapshot

**Given** two people each run `/maos-{agent}` in their own chat session at roughly the same time, against different issues
**When** either instance evaluates whether it can claim its issue's components
**Then** it reads every other in-flight item's `component:` labels from GitHub directly, rather than trusting only the single work item it fetched for itself, since the other instance is a genuinely separate, unserialised process it cannot otherwise see

## Scenario: A fresh component-claim check fails closed on a GitHub error

**Given** interactive mode cannot fetch the current in-flight items because the GitHub API call fails
**When** the orchestrator evaluates whether an item can claim its components
**Then** it refuses the claim (treats everything as claimed) rather than proceeding as if nothing were in flight, and logs a warning

## Scenario: Each cleared item runs in its own git worktree

**Given** two commit_after runs are cleared to start at once, on different issues with non-overlapping components
**When** each is dispatched
**Then** each checks out its own issue branch into its own git worktree, so neither run's checkout can move the other's `HEAD`

## Scenario: A failed worktree checkout fails the run loudly

**Given** `git worktree add` (or the preceding fetch) fails for a commit_after run
**When** the orchestrator would otherwise invoke the agent
**Then** it does not fall back to running on whatever branch the orchestrator's own working directory happens to be on -- it fails the run, applying `:failed` with the failure reason, exactly as a crashed subprocess would

## Scenario: A killed run does not strand its worktree

**Given** a commit_after run's worktree is checked out and the orchestrator process receives SIGTERM or SIGINT before the run finishes
**When** the signal handler runs
**Then** it removes the in-flight worktree, alongside clearing the in-flight `:wip` label, so the next run does not collide with debris

## Scenario: AI_AGILE_ROOT matches the worktree an agent actually runs in

**Given** a commit_after agent is spawned with its `cwd` set to an isolated worktree
**When** the agent's prompt and environment are resolved
**Then** both the prompt's `AI_AGILE_ROOT=` line and the `$AI_AGILE_ROOT` env var point at that same worktree, not the orchestrator's own shared checkout
**And** the documented `cd $AI_AGILE_ROOT && <command>` idiom therefore stays inside the isolated worktree instead of escaping back onto the shared tree

## Scenario: Applying an interactive result still never touches the worktree mechanism

**Given** `--interactive-result` is applying a person-produced result.json for a commit_after step
**When** `_run_agent` runs
**Then** it does not create a worktree or check out the issue branch at all, exactly as it already skips the pre-agent checkout under `--interactive-result`

## Scenario: An untouched issue blocked by an open issue is not eligible to start

**Given** an issue carries `blockedby:12`, issue #12 is still open, and no step has yet run on the blocked issue
**When** the orchestrator evaluates the issue
**Then** no agent is dispatched -- not even the entry step -- and no labels are changed

## Scenario: blockedby: never gates a step mid-flow

**Given** an issue carries `blockedby:12` (issue #12 still open) but already has at least one agent status label from an earlier tick
**When** the orchestrator evaluates the issue
**Then** the block has no effect on this item -- whichever step is next in the flow is dispatched normally

## Scenario: Both labels come off automatically once the blocking issue closes

**Given** an issue carries `blockedby:12` and issue #12 carries `blocks:{this}`, and issue #12 is now closed
**When** the orchestrator evaluates the issue on its next tick
**Then** it removes `blockedby:12` from this issue and `blocks:{this}` from issue #12, and the issue becomes eligible to start

## Scenario: A human can clear a block directly, in either mode

**Given** an issue carries `blockedby:12` while #12 is still open
**When** a human removes the `blockedby:12` label directly, headless or interactive
**Then** the issue is eligible to start on the very next evaluation -- clearing never depends on who or what removed the label

## Scenario: A malformed blockedby: label is ignored, not treated as blocking

**Given** an issue carries a label like `blockedby:abc` (a non-numeric suffix)
**When** the orchestrator evaluates the issue
**Then** it logs a warning and does not treat the issue as blocked by it -- a bad label must not silently wedge an item forever

## Scenario: An indeterminate blocking-issue lookup fails closed

**Given** the orchestrator cannot determine whether a blocking issue is open or closed because the GitHub API call failed
**When** it evaluates an untouched issue carrying that blockedby: label
**Then** it treats the issue as still blocked -- an unverifiable block is never silently lifted

## Scenario: Blocking is issue-to-issue ordering, not a PR gate

**Given** a PR carries a `blockedby:` label
**When** the orchestrator evaluates the PR
**Then** the label has no effect -- blocking eligibility only applies to issues

## Scenario: 00_ondemand/blocker reciprocates an existing blockedby: label

**Given** a human has applied `blockedby:12` directly to issue #7 and then requests `blocker` (`blocker:requested`)
**When** the step runs
**Then** it applies `blocks:7` to issue #12, creating the label first if the repository doesn't have it yet

## Scenario: blocker reports blocked, not a silent no-op, when there is nothing to reciprocate
**Given** a human requests `blocker` on an issue that carries no `blockedby:` label
**When** the step runs
**Then** it writes no label and signals `blocked`, so the mistaken request stays visible rather than being silently swallowed

