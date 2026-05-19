# Pipeline Status

Show the current AI Agile pipeline state for an issue — which agents have run,
which are pending, and what action (if any) is needed from a human.

## Input

`$ARGUMENTS`: an issue number.

Examples:
- `42`
- `#15`

## Instructions

1. Parse the issue number from `$ARGUMENTS` (strip any leading `#`).

2. Detect the repo:
   ```bash
   REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
   ```

3. Fetch the issue's current labels:
   ```bash
   gh issue view $ISSUE_NUMBER --repo $REPO --json labels,title,state \
     --jq '{title: .title, state: .state, labels: [.labels[].name]}'
   ```

4. Locate `pipeline.json`. Try in order:
   - `pipeline/pipeline.json` (standalone)
   - `ai-coding-standards2/pipeline/pipeline.json` (submodule)

   Read it and extract the ordered list of agents with their phase, dependencies,
   and `human_gate_label` (if any).

5. For each agent in pipeline order, determine its status from the label set:
   - `{agent}:complete` → complete
   - `{agent}:wip`      → wip (running)
   - `{agent}:review`   → review
   - `{agent}:blocked`  → blocked
   - `{agent}:failed`   → failed
   - `{agent}:skipped`  → skipped
   - none of the above  → pending

6. Print a summary table:

   ```
   Pipeline status for ISSUE #{number}: {title}

   Phase             Agent                                  Status     Action needed
   ─────────────────────────────────────────────────────────────────────────────────
   01_product_docs   01_product_docs/issue-classifier       ✅ done
   01_product_docs   01_product_docs/prd-writer             🔍 review  Apply `01_product_docs/prd-writer:approved` to advance
   01_product_docs   01_product_docs/prd-docs-updater       ⏳ pending
   ```

   Status icons:
   - ✅ `complete`
   - 🔄 `wip` — agent is currently running
   - 🔍 `review` — waiting for human gate label
   - 🚫 `blocked` — agent needs human intervention; remove `:blocked` label to retry
   - ❌ `failed` — agent crashed; remove `:failed` label to retry
   - ⏭️ `skipped`
   - ⏳ `pending` — not yet started

7. After the table, if any agent is in `review`, list the exact label to apply:
   ```
   To advance: apply label `01_product_docs/prd-writer:approved` on issue #42
   ```

8. If any agent is `blocked` or `failed`, give the recovery command:
   ```bash
   gh issue edit 42 --repo OWNER/REPO --remove-label "01_product_docs/prd-writer:failed"
   ```
