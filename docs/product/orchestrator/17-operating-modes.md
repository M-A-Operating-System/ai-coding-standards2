# Operating Modes

AI Agile has two operating modes. Both use the same orchestrator
(`pipeline/pipeline_orchestrator.py`), the same pipeline graph
(`pipeline/pipeline.json`), the same agent prompts, and the same
label-driven state machine. The difference is who triggers each step and
how gates are approved.

For the mechanism that drives in-session runs step by step, see
[`.claude/commands/maos-run.md`](../../../.claude/commands/maos-run.md).
This document covers the concept, comparison, and tradeoffs. To get a first
run working in either mode, see the dedicated
**[Quick Start](quick-start.md)**.

---

## Comparison

| Aspect | Scheduled (background) | In-session (live) |
|---|---|---|
| Trigger | GitHub Actions on `issues.*` / `pull_request.*` events, or cron | `/maos-run {N}` slash command in a Claude Code session |
| Auth — agents | `ANTHROPIC_API_KEY` repo secret | Session's own Claude subscription/OAuth login (or `ANTHROPIC_API_KEY` in the local environment) |
| Auth — GitHub | `AI_AGILE_BOT_TOKEN` repo secret | `gh` CLI auth (`GITHUB_TOKEN`, `GH_TOKEN`, or `gh auth login`) |
| Human present? | No — pipeline runs unattended; gates wait for a label applied whenever a human next looks | Yes — Claude pauses at each gate and waits for your decision in the same session |
| Gate approval | Apply `{agent}:approved` label on GitHub (web UI or `gh label add`) | Claude prompts you in the session; apply the label or ask Claude to apply it |
| What you see | GitHub issue/PR activity: labels, comments, branch creation | Live agent output in the Claude Code session plus the same GitHub activity |
| On-demand agents | All `00_ondemand/*` agents run (full REST + GraphQL access) | Limited — see current limitations below |

Both modes read and write the same GitHub labels, so they can be used on the same repo simultaneously. A common pattern: the scheduled runner handles the queue normally; a human drops into `/maos-run` to push a specific issue forward while they are at the keyboard.

---

## Current limitations of in-session mode

**`00_ondemand/*` agents not yet REST-converted.** The `sizer`,
epic-decomposer, and cleanup agents in `00_ondemand/` use GitHub operations
not yet ported to the REST-only call pattern. Running `/maos-run` on an epic
(which invokes the sizer) or a cleanup step in a restricted session will halt
when those ticks are reached. The scheduled runner handles them without
restriction.

**Marking a PR ready for review.** The `gh pr ready` command uses a GraphQL
mutation that a restricted interactive session blocks with a 403. The
`/maos-run` driver detects this and falls back to the GitHub MCP tool
(`update_pull_request(draft: false)`) as the only in-session path that
un-drafts a PR. The GitHub Actions runner does not need this fallback.

**Why gh CLI/REST, not GitHub MCP tools.** This is a separate decision from
the GraphQL->REST conversion above: that was `gh`'s *own* GraphQL vs REST
split (a restricted session blocks GraphQL); this is gh/REST *vs* GitHub MCP
tools. `pipeline_orchestrator.py` is a bare Python process with no Claude
tool-calling context, so it has no GitHub MCP access at all -- only a token
(`GITHUB_TOKEN` / `GH_TOKEN` / `AI_AGILE_BOT_TOKEN`) and the `gh` CLI reach
GitHub, for the orchestrator itself, its `.github/scripts/*.sh` subprocesses,
and `.claude/agents/*.md` (run headless via `claude -p`). The **scheduled
GitHub Actions runner** -- the pipeline's primary mode -- has no interactive
session and no guaranteed MCP server at all, so token-based gh/REST is the
one mechanism that works identically whether a step is triggered by cron or
by `/maos-run` in a live session. GitHub MCP tools are only reachable from
the top-level interactive session itself, which is why `/maos-run` reaches
for MCP for exactly one thing -- the mark-ready assist above, which has no
REST equivalent -- and nothing else.

**A session's own "no gh CLI" instruction is a policy, not a provisioning
fact.** Some interactive sessions carry a system-prompt line stating they
have no `gh` CLI access and must use GitHub MCP tools instead. That is an
instruction to *that assistant* about which tool to reach for -- it does not
mean the `gh` binary or its token are absent from the underlying environment,
and scripts/agents that assistant invokes via Bash may use `gh` successfully
regardless. Verify rather than infer this from the wording alone.

**Checking gh availability correctly.** `gh auth status` performs a
GraphQL-backed validation call, so it can report failure under the same
restriction as `gh pr ready` even when `gh api` REST calls work fine --
producing a false "not authenticated" reading. The correct orchestrator
startup probe therefore uses `gh api user` rather than `gh auth status`.

---

## See also

- **Quick Start** (shortest path to a first run in either mode): [quick-start.md](quick-start.md)
- **Mechanism** (how `/maos-run` drives the orchestrator step by step, fallback
  conditions, and gate handling): [`.claude/commands/maos-run.md`](../../../.claude/commands/maos-run.md)
- **Scheduled mode setup** (secrets, bootstrap, platform behaviour):
  [16-onboarding.md](16-onboarding.md) and [README.md](../../../README.md)
- **Human gates** (what each gate means and who approves): [07-human-gates.md](07-human-gates.md)
- **Status model** (label state machine): [06-status-model.md](06-status-model.md)
