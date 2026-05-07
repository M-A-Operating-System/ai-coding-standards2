# Retry Agent

Remove a `:failed` label from an issue so the pipeline re-runs the agent on
the next orchestrator tick. Optionally skip the agent instead.

Use this after investigating a failed agent run and either fixing the root
cause (bad config, missing secret, prompt bug) or deciding to skip the agent
entirely for this issue.

## Input

`$ARGUMENTS`: `[agent-name] <issue-number> [--skip]`

- Agent name is optional when only one agent has failed on the issue.
- `--skip` replaces the `:failed` label with `:skipped` instead of removing it.

Examples:
- `42`
- `01_product_docs/prd-writer 42`
- `01_product_docs/prd-writer 42 --skip`

## Instructions

1. Parse `$ARGUMENTS`:
   - Detect `--skip` flag if present; remove it from further parsing.
   - If two remaining tokens: first is agent name, second is issue number.
   - If one remaining token: it is the issue number; discover the failed agent below.

2. Detect the repo:
   ```bash
   REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
   ```

3. Fetch current labels:
   ```bash
   gh issue view $ISSUE_NUMBER --repo $REPO --json labels \
     --jq '[.labels[].name]'
   ```

4. Find all `:failed` labels. If no agent name was provided:
   - If exactly one `:failed` label: use that agent.
   - If multiple: list them and ask the user which to retry. Stop.
   - If none: report "No failed agents on issue #N." and stop.

5. Show the failure comment so the user can confirm the cause is understood:
   ```bash
   gh issue view $ISSUE_NUMBER --repo $REPO --json comments \
     --jq '[.comments[] | select(.body | contains("exited with an error"))] | last | .body'
   ```

6. Apply the action:

   **Retry** (default — removes `:failed` so the agent reruns):
   ```bash
   gh issue edit $ISSUE_NUMBER --repo $REPO \
     --remove-label "{agent}:failed"
   ```

   **Skip** (`--skip` flag — marks as skipped so the pipeline advances past it):
   ```bash
   gh issue edit $ISSUE_NUMBER --repo $REPO \
     --remove-label "{agent}:failed" \
     --add-label "{agent}:skipped"
   ```

7. Confirm:

   Retry:
   ```
   ✅ Removed `{agent}:failed` from issue #42.
   The orchestrator will re-run {agent} on the next tick.
   ```

   Skip:
   ```
   ⏭️ Marked `{agent}` as skipped on issue #42.
   The pipeline will treat this agent as complete and advance.
   ```
