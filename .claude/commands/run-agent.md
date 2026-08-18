# Run Agent

Invoke a pipeline agent interactively on an issue. This executes the agent's
prompt file in the current Claude Code session — you see each step live and can
intervene at any point.

Useful for: debugging an agent, running an agent before GitHub Actions is wired
up, or re-running an agent after editing its prompt.

## Input

`$ARGUMENTS`: `<agent-name> <issue-number>`

Examples:
- `01_product_docs/prd-writer 42`
- `01_product_docs/issue-classifier 15`

## Instructions

1. Parse `$ARGUMENTS`:
   - Agent name: everything up to the last space-separated token
   - Issue number: the last token (strip any leading `#`)

2. Detect the repo and resolve paths:
   ```bash
   REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
   ```

   Locate the agent file — try in order:
   - `.claude/agents/{agent-name}.md` (standalone)
   - `ai-coding-standards2/.claude/agents/{agent-name}.md` (submodule)

   Locate status.sh — try in order:
   - `.github/scripts/status.sh` (standalone)
   - `ai-coding-standards2/.github/scripts/status.sh` (submodule)

   If the agent file is not found, list available agents:
   ```bash
   find .claude/agents ai-coding-standards2/.claude/agents \
     -name "*.md" 2>/dev/null | sort
   ```
   Then stop.

3. Read the agent file. Note the `model:`, `max_turns:`, and `tools:` frontmatter
   values. `tools:` is the allowlist the real orchestrator passes as
   `--allowedTools` when it spawns this agent as a subprocess — the agent was
   written and tested against exactly that set.

   **Tool-scope rule (enforced, not advisory):** write the declared allowlist
   to a scope file before following any of the agent's own instructions:

   ```bash
   mkdir -p .claude
   jq -n --arg agent "$AGENT_NAME" --argjson allowed '["Bash","Read","Grep"]' \
     '{agent: $agent, allowed: $allowed}' > .claude/.run-agent-scope.json
   ```

   Replace the `--argjson allowed` value with the exact `tools:` list from the
   frontmatter you just read (as a JSON array), and `$AGENT_NAME` with the
   agent name parsed in step 1.

   A `PreToolUse` hook (`.claude/hooks/run-agent-scope.sh`, registered in
   `.claude/settings.json`) reads this file for the rest of the run and
   **denies** any tool call outside the declared list — the same restriction
   the real orchestrator applies via `--allowedTools`. This is a real block,
   not a warning: if a tool call is denied, do not retry it — find a
   declared-tool alternative or stop and tell the user the agent's allowlist
   doesn't cover what this run needs.

   `Glob` in particular is absent from most agents' allowlists and silently
   returns empty results through symlinked directories (`standards/`,
   `.claude/`) rather than an error — see `.claude/CLAUDE.md` Section 6.

4. Set the following variables for use in the agent's bash snippets:
   - `AGENT_NAME` = the agent name parsed in step 1
   - `ISSUE_NUMBER` = the parsed issue number
   - `REPO` = the detected repo
   - `STATUS_SH` = the resolved path to status.sh
   - `AI_AGILE_ROOT` = the directory that contains `ai-agile/` and `.github/`

5. Follow the agent's instructions exactly, substituting `$ISSUE_NUMBER`,
   `$REPO`, `$STATUS_SH`, and `$AI_AGILE_ROOT` wherever the agent references
   them.

   Run each bash snippet from the agent file using your Bash tool.

6. When you reach the agent's terminal step (set-complete, set-review, or
   set-blocked), confirm to the user:
   ```
   ✅ Agent 01_product_docs/prd-writer completed on issue #42.
   Final status: complete
   ```

7. Remove the scope file so it doesn't affect unrelated tool use later in this
   session:
   ```bash
   rm -f .claude/.run-agent-scope.json
   ```
   Do this even if the run halts early (error, `:blocked`, user interruption,
   a denied tool with no alternative) — remove the scope file before ending
   your turn either way.
