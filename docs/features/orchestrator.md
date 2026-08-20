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

## Scenario: /run-agent obtains its tool allowlist from the orchestrator instead of hand-parsing frontmatter

**Given** `/run-agent <agent-name> <issue-number>` is invoked
**When** it resolves the target agent's invocation parameters
**Then** it does so via the orchestrator's resolve-only mode, and the resulting `.claude/.run-agent-scope.json` allowlist matches exactly what `pipeline_orchestrator.py` would pass as `--allowedTools` for a real subprocess spawn of that same agent

## Scenario: Resolve-only mode mutates no GitHub state

**Given** the orchestrator is invoked in resolve-only mode for a specific agent
**When** it prints the resolved prompt/tools/env
**Then** no labels are changed, no `:wip` is applied, and no GitHub API write calls are made
