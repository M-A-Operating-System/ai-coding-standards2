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

   **Tool-scope rule:** follow only the agent's declared tool allowlist for the
   duration of this run. Before invoking any tool that is **not** in the
   agent's `tools:` list (e.g. `Glob` when the agent declares
   `tools: [Bash, Read, Grep]`), stop and explicitly warn:

   ```
   WARNING: agent declares tools: [...] -- <ToolName> is outside that allowlist.
   The real orchestrator would not have this tool available. Proceeding anyway
   only if there is no declared-tool alternative.
   ```

   This prevents silent capability drift between interactive runs and real
   orchestrator-spawned runs. `Glob` in particular silently returns empty results
   through symlinked directories (`standards/`, `.claude/`) -- see
   `.claude/CLAUDE.md` Section 6 -- so using it when the agent does not declare
   it both violates the allowlist and produces wrong results.

4. Set the following variables for use in the agent's bash snippets:
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
