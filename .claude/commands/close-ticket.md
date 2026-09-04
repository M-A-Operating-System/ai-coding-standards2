# Close GitHub Issue

Close an existing GitHub issue in the current repository.

## Input

The user provides: `$ARGUMENTS`

This should include an issue number and optionally a closing reason/comment. Examples:
- `42`
- `15 resolved in PR #20`
- `7 duplicate of #3`

## Instructions

1. **Parse the input.** Extract:
   - The issue number (required — first number found in arguments)
   - An optional closing reason (everything after the issue number)

2. **Determine the agent name.** If this command is being invoked by an agent, use that agent's name. If invoked directly by the user, use `"user"`.

3. **Fetch the current issue** using `mcp__github__issue_read`. Extract:
   - The **issue key** from the title (the `<KEY>` portion of `[agent] - <KEY> - description`). If no key exists, note as `N/A`.
   - The **current status label** — any label matching `<agent-name>: <status>`.

4. **Update the status label to `na`:**
   - Remove the old `<agent-name>: <old-status>` label (if present)
   - Add `<agent-name>: na`

5. **Add a closing audit comment** using `mcp__github__add_issue_comment`:
   ```
   **Agent:** <agent-name>
   **Action:** Closed — <closing reason if provided, otherwise "No reason given">
   **Status:** na
   **Issue Key:** <KEY>
   **Timestamp:** YYYY-MM-DD HH:MM UTC
   ```

6. **Close the issue** using `mcp__github__issue_write` with `state: "closed"`.

7. **Print the result:**
   ```
   Issue #<number> closed.
   Status: <agent-name>: na
   Key: <KEY>
   Reason: <closing reason if any>
   URL: <issue_url>
   ```

## Fallback

If GitHub MCP tools are not available, inform the user:
```
GitHub MCP tools are not connected. To close issues, ensure the GitHub MCP server is configured in your Claude Code settings.
```
