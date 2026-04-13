# Update GitHub Issue

Update an existing GitHub issue in the current repository.

## Input

The user provides: `$ARGUMENTS`

This should include an issue number and what to update. Examples:
- `42 status wip`
- `42 add label bug`
- `15 change title to "Fix parser edge case"`
- `7 add comment "This is resolved in PR #12"`

## Instructions

1. **Parse the input.** Extract:
   - The issue number (required — first number found in arguments)
   - The action: update status, update title, update body, add label, remove label, add comment, or assign
   - If the action is `status <value>`, the value must be one of: `new`, `wip`, `blocked`, `review`, `na`

2. **Determine the agent name.** If this command is being invoked by an agent, use that agent's name. If invoked directly by the user, use `"user"`.

3. **Fetch the current issue** using `mcp__github__issue_read` to understand its current state. Extract:
   - The **issue key** from the title (the `<KEY>` portion of `[agent] - <KEY> - description`). If no key exists, note as `N/A`.
   - The **current status label** — any label matching `<agent-name>: <status>`.

4. **Update the status label** (if the action involves a status change or if any update warrants a status transition):
   - Remove the old `<agent-name>: <old-status>` label (if present)
   - Add the new `<agent-name>: <new-status>` label
   - Valid statuses: `new`, `wip`, `blocked`, `review`, `na`

5. **Apply any other updates** using the appropriate tool:
   - **Title/body/labels/assignees/state:** Use `mcp__github__issue_write`
   - **Add a comment:** Use `mcp__github__add_issue_comment`

6. **Add an audit comment** after every update using `mcp__github__add_issue_comment`:
   ```
   **Agent:** <agent-name>
   **Action:** Updated — <brief description of what changed>
   **Status:** <new-status>
   **Issue Key:** <KEY>
   **Timestamp:** YYYY-MM-DD HH:MM UTC
   ```
   If the user's action was itself a comment, combine the user's comment and the audit trail into a single comment to avoid noise:
   ```
   <user's comment text>

   ---
   **Agent:** <agent-name> | **Action:** Comment added | **Status:** <status> | **Issue Key:** <KEY> | **Timestamp:** YYYY-MM-DD HH:MM UTC
   ```

7. **Print the result:**
   ```
   Issue #<number> updated: <what changed>
   Status: <agent-name>: <new-status>
   Key: <KEY>
   URL: <issue_url>
   ```

## Fallback

If GitHub MCP tools are not available, inform the user:
```
GitHub MCP tools are not connected. To update issues, ensure the GitHub MCP server is configured in your Claude Code settings.
```
