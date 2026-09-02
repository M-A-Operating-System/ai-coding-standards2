# Approve PRD

Apply the `01_product_docs/prd-writer:approved` gate label to an issue, advancing the pipeline from
`01_product_docs/prd-writer:review` to `01_product_docs/prd-writer:complete`.

Run this after reviewing the PRD in the issue body and deciding it is
ready to move to the next phase.

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

3. Confirm the issue is in the right state — check that
   `01_product_docs/prd-writer:review` is present:
   ```bash
   gh issue view $ISSUE_NUMBER --repo $REPO --json labels \
     --jq '[.labels[].name] | map(select(startswith("01_product_docs/prd-writer")))'
   ```

   If the label is not `01_product_docs/prd-writer:review`, report the
   current prd-writer status and stop — the gate should only be applied
   when the agent is actually awaiting review.

4. Tell the orchestrator you have the person's confirmation and let it write
   the gate label itself (PRODUCT.md MI-7 -- this command never writes a gate
   label directly; re-applying an already-present bot-authored label would be
   a silent no-op, per issue #377):
   ```bash
   SCRIPT=pipeline/pipeline_orchestrator.py
   [ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/pipeline/pipeline_orchestrator.py
   python3 "$SCRIPT" --repo "$REPO" --agent 01_product_docs/prd-writer --issue $ISSUE_NUMBER --confirm-gate
   ```
   If it refuses because the label is already present from a non-human
   application, it names the exact `gh issue edit --remove-label` command to
   run first, then re-run this step.

5. Confirm:
   ```
   ✅ Applied `01_product_docs/prd-writer:approved` to issue #42.
   The orchestrator will promote prd-writer to :complete on the next tick
   and trigger the next pipeline phase.
   ```
