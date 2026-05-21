# Unblock Agent

Remove a `:blocked` label from an issue so the pipeline re-runs the agent on
the next orchestrator tick.

Use this after you have resolved whatever caused the agent to block — for
example, adding missing acceptance criteria, clarifying scope, or fixing a
configuration problem the agent reported.

## Input

`$ARGUMENTS`: `[agent-name] <issue-number>`

The agent name is optional when only one agent is blocked on the issue.

Examples:
- `42` (only one agent is blocked)
- `01_product_docs/prd-writer 42`
- `#15`

## Instructions

1. Parse `$ARGUMENTS`:
   - If two tokens: first is agent name, second is issue number.
   - If one token: it is the issue number; discover the blocked agent below.

2. Detect the repo:
   ```bash
   REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
   ```

3. Fetch current labels:
   ```bash
   gh issue view $ISSUE_NUMBER --repo $REPO --json labels \
     --jq '[.labels[].name]'
   ```

4. Find all `:blocked` labels. If no agent name was provided:
   - If exactly one `:blocked` label: use that agent.
   - If multiple: list them and ask the user which to unblock. Stop.
   - If none: report "No blocked agents on issue #N." and stop.

5. Show the agent's block comment so the user can confirm the issue is resolved:
   ```bash
   gh issue view $ISSUE_NUMBER --repo $REPO --json comments \
     --jq '[.comments[] | select(.body | contains("set-blocked") or contains("blocked"))] | last | .body'
   ```

6. Remove the `:blocked` label:
   ```bash
   gh issue edit $ISSUE_NUMBER --repo $REPO \
     --remove-label "{agent}:blocked"
   ```

7. Confirm:
   ```
   ✅ Removed `{agent}:blocked` from issue #42.
   The orchestrator will re-run {agent} on the next tick.
   ```
