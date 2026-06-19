# Enhancement: Inject Runtime Context Into Agent Prompt

## Problem

When the orchestrator invokes an agent via the Claude CLI, it passes runtime context
(`$REPO`, `$ISSUE_NUMBER`, `$SESSION_ID`, etc.) as environment variables on the subprocess.
Agent prompts tell agents these vars are available and to read them via shell.

In headless CI runs the `allowedTools` list passed to the Claude CLI is restrictive —
`Bash(printenv *)`, `Bash(echo *)`, and bare variable expansion (`$VAR`) are not in the
allowlist. This causes agents to burn 2–3 turns on permission errors at the very start of
every run before they recover and find another path forward.

Example failures observed in session `ais-v1-03-execute-coder-issue-155`:

```
Error: Contains expansion
Error: This Bash command contains multiple operations. The following part requires approval: printenv REPO ISSUE_NUMBER SESSION_ID AI_AGILE_ROOT
Error: This Bash command contains multiple operations. The following part requires approval: printenv
```

## Proposed Fix

Inject the resolved values directly into the agent prompt text rather than relying on
the agent to shell out and read them at runtime.

### Change in `pipeline_orchestrator.py` — `invoke_agent()`

Replace the current "Env vars" line in the prompt:

```python
# BEFORE
f"Env vars: $REPO ${num_var} $WORK_ITEM_KIND $AI_AGILE_ROOT $AI_AGILE_CONTEXT "
f"$SESSION_ID $SESSION_SCOPE\n\n"
```

With a pre-resolved block:

```python
# AFTER
f"## Runtime context\n\n"
f"REPO={repo}\n"
f"{num_var}={work_item.number}\n"
f"WORK_ITEM_KIND={work_item.kind}\n"
f"SESSION_ID={agent_session_id}\n"
f"SESSION_SCOPE={agent_def.session_scope}\n"
f"AI_AGILE_ROOT={os.environ.get('AI_AGILE_ROOT', str(SUBMODULE_ROOT))}\n"
f"AI_AGILE_CONTEXT={str(AI_AGILE_CONTEXT)}\n\n"
```

The env vars are still set on the subprocess (unchanged) so any bash snippets that
reference them continue to work when the tool is allowed. The prompt values serve as a
zero-cost fallback that the agent can read without any tool call.

## Acceptance Criteria

- An agent that begins a run on a fresh issue does not attempt `printenv`, `echo $REPO`,
  or similar env-reading commands as its first action.
- The values visible in the prompt match the values in the subprocess environment.
- Existing agents that use `gh issue view $ISSUE_NUMBER` or similar bash snippets
  continue to work — the env vars are still exported to the subprocess.
- No new `allowedTools` entries are required to cover this path.

## Impact

- **Low risk** — additive prompt change only; no orchestrator logic changes.
- **Low effort** — single-site edit in `invoke_agent()`.
- **Benefit** — eliminates wasted turns and the 9-second permission-error recovery loop
  at the start of every agent invocation in CI.
