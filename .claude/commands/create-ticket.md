# Create GitHub Issue

Create a new GitHub issue in the current repository with an immutable issue key for deduplication.

## Input

The user provides: `$ARGUMENTS`

This may be a title, a title + description, or a general description of the issue. Parse it accordingly.

## Title Standard

The calling agent is responsible for constructing the title. It MUST match this format:

```
[<agent-name>] - <KEY> - <short description>
```

Where `<KEY>` follows the Issue Key Standard from `.claude/agent-todo-standard.md`:
- Format: `<AGENT>-<CATEGORY>-<HASH>`
- `<AGENT>`: uppercase short agent name (e.g., `REVDOC`, `FACTORY`, `USER`)
- `<CATEGORY>`: one of `DEAD`, `BUG`, `SEC`, `PERF`, `TYPE`, `STYLE`, `MISS`, `STALE`, `GEN`
- `<HASH>`: first 6 hex chars of a deterministic hash

Examples of valid titles:
```
[reverse-doc] - REVDOC-DEAD-a3f2c1 - Unused export in dag-parser.ts
[lint-agent] - LINT-BUG-7e9b04 - Missing null check in advance()
[user] - USER-GEN-d12f88 - Add dark mode support
```

## Instructions

1. **Validate the title.** The title provided in `$ARGUMENTS` MUST match the pattern:
   ```
   [<agent-name>] - <AGENT>-<CATEGORY>-<HASH> - <description>
   ```
   Specifically, verify:
   - Starts with `[` and contains `]` (agent name bracket)
   - Contains a key matching `<AGENT>-<CATEGORY>-<HASH>` where:
     - `<AGENT>` is uppercase alphanumeric
     - `<CATEGORY>` is one of: `DEAD`, `BUG`, `SEC`, `PERF`, `TYPE`, `STYLE`, `MISS`, `STALE`, `GEN`
     - `<HASH>` is exactly 6 hex characters (`[0-9a-f]{6}`)
   - Ends with a short description after the second ` - `

   **If validation fails**, reject the request and print:
   ```
   ERROR: Title does not match the required format.
   Expected: [<agent-name>] - <AGENT>-<CATEGORY>-<HASH> - <description>
   Received: <the invalid title>

   The calling agent is responsible for constructing a valid title.
   See .claude/agent-todo-standard.md for the Issue Key Standard.
   ```
   **Do NOT create the issue. Stop here.**

2. **Extract fields from the validated title:**
   - `<agent-name>` — from the bracket portion
   - `<KEY>` — the `<AGENT>-<CATEGORY>-<HASH>` portion
   - `<description>` — everything after the second ` - `

3. **Parse the body.** Extract or construct a descriptive body from the remainder of `$ARGUMENTS` (everything beyond the title). If only a title was given, ask the user for details or generate a reasonable body.

4. **Check for duplicates.** Search existing GitHub issues for the key using `mcp__github__search_issues`. If the key already exists:
   ```
   DUPLICATE: Issue with key <KEY> already exists: #<number>
   URL: <issue_url>
   ```
   **Do NOT create the issue. Stop here.**

5. **Create the issue** using `mcp__github__issue_write` with:
   - `owner`: extracted from the current repo (use `git remote get-url origin` to determine)
   - `repo`: extracted from the current repo
   - `title`: the validated title as-is
   - `labels`: `["<agent-name>: new"]`
   - `body`: the issue body in markdown format. Include:
     - `**Issue Key:** \`<KEY>\``
     - A clear description of the issue or request
     - Relevant file paths if applicable
     - Any code snippets or context that help explain the issue

6. **Add an audit comment** immediately after creation using `mcp__github__add_issue_comment`:
   ```
   **Agent:** <agent-name>
   **Action:** Created
   **Status:** new
   **Issue Key:** <KEY>
   **Timestamp:** YYYY-MM-DD HH:MM UTC
   ```

7. **Record in todo file.** If the agent has a todo file at `.claude/todos/<agent-name>.todo`, append the key under `## Issues Raised`.

8. **Print the result:**
   ```
   Issue created: #<number> — <title>
   Key: <KEY>
   URL: <issue_url>
   ```

## Fallback

If GitHub MCP tools are not available, inform the user:
```
GitHub MCP tools are not connected. To create issues, ensure the GitHub MCP server is configured in your Claude Code settings.
```
