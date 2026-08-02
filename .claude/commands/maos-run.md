# maos-run

Drive a GitHub issue through the **full AI-Agile pipeline end-to-end in one
interactive session**, behaving exactly as the deterministic orchestrator
(`pipeline/pipeline_orchestrator.py`) would -- same sequence, same
dependencies, same human gates, same label transitions -- but pausing in the
chat session for you to approve or request changes at each gate.

This is a hand-authored **driver** command (like `/maos-merge`,
`/maos-new-branch-pr`, `/maos-rebaseline`). It is NOT a pipeline agent and
carries no generated marker, so `scripts/generate_slash_commands.py` preserves
it. Routing is read from `pipeline/pipeline.json` + `pipeline/statuses.json` at
run time -- the flow is never hardcoded here, so adding/removing/reordering a
pipeline step changes the run with no edit to this command (P-14, P-2).

## Input

`$ARGUMENTS` -- the issue number to drive (e.g. `42`).

## Instructions

### 1. Load the spec (source of truth)

Read `pipeline/pipeline.json` (the agent graph: each step's `agent`, `phase`,
`object`, `trigger`, `dependencies`, `human_gate_after`/`human_gate_label`,
`self_gates`, `type` (`agent`|`script`) + `script`, `exclude_classifications`,
`exclude_labels`, `review_loop`, `git_ops`, `post_steps`) and
`pipeline/statuses.json` (the label/status model). Do not embed a copy of the
flow; mirror the orchestrator's decision loop against what these files declare.

### 2. Read current state

Read the issue's current labels (via `mcp__github__issue_read`) -- the labels
ARE the state machine (P-1/P-11). Determine which step ran last and what is
eligible next. Also read the issue's classification (the
`classification: {type}` label applied by `issue-classifier`) for exclusion
checks.

### 3. Decision loop -- pick and run the next eligible step

Repeat until no step is eligible or a halt condition is hit:

**a. Select the next step.** A step is eligible when, per `pipeline.json`:
- its `trigger` is satisfied by the current labels/state (e.g. the upstream
  agent's `:complete` label is present, or `issue.opened` for the first step);
  AND
- every entry in its `dependencies` is complete (upstream `:complete`, and any
  upstream `human_gate_label` present unless that upstream is `self_gates`); AND
- it is not skipped by `exclude_classifications` (e.g. skip `create-pr`/`coder`
  for a `spike`) or `exclude_labels` (e.g. skip `epic`/`blocked`).
If more than one is eligible, take them in pipeline order. If none is eligible,
go to step 5 (halt/report).

**b. Claim it.** Apply the `{agent}:wip` label (the mutex, P-4) before running,
and post the opening announcement, mirroring the orchestrator.

**c. Run it.**
- **Agent steps** (`type: agent`): run the agent by following its prompt in
  `.claude/agents/{agent}.md` (the same as `run-agent {agent} {N}`), using the
  GitHub MCP tools + git + the existing interactive commands in this
  environment (`gh` is unavailable here). Capture its `AI_AGILE_STATUS`
  outcome (`complete`|`review`|`blocked`).
- **Script steps** (`type: script`, e.g. `create-docs-pr`, `merge-docs-pr`,
  `create-pr`): perform the script's logic interactively -- reuse the matching
  hand-authored command where one exists (`/maos-new-branch-pr` for the code
  PR, `/maos-merge` for a merge) and the MCP tools + git otherwise. Never call
  the `.sh` directly (it depends on `gh`).

**d. Apply the outcome label** the orchestrator would: clear `:wip` and set
`:complete`, `:review`, or `:blocked` per the sentinel and `self_gates`
(when `self_gates: true`, trust the agent's own `review` vs `complete`; do not
force `:complete` to `:review`). Run any `post_steps` and honour `git_ops`
(the orchestrator normally owns commit/push -- do the equivalent here).

**e. Human gate** (`human_gate_after: true`, and the step emitted `:review`):
**pause and prompt the human in the chat session** with two choices -- do not
self-approve (P-10):
- **Approve** -> apply the step's `{agent}:approved` gate label and continue
  the loop. Apply this label ONLY on the human's explicit in-chat approval.
- **Request changes** (with feedback) -> post the human's feedback as a
  comment / `REQUEST_CHANGES` review on the issue or PR, and apply the
  change-loop labels the orchestrator uses (e.g. `review-cycle:N` /
  `human-review-pending`), so the coder is re-invoked per `review_loop`
  (up to `review_loop.max_cycles`). Then continue the loop.
The resulting GitHub state (labels + comments) must match a real orchestrated
run so the flow stays resumable.

**f. Review loop.** When `pr-reviewer` issues REQUEST CHANGES, re-invoke the
`review_loop.re_invoke` agent (the coder) up to `review_loop.max_cycles`,
mirroring the orchestrator, before requiring human sign-off.

### 4. Complete

Stop when the issue's code PR is marked ready for review (pr-reviewer APPROVE,
no unresolved human REQUEST_CHANGES) -- report the PR number and that it is
ready to merge. Do not self-merge (that is `/maos-merge` on explicit request).

### 5. Halt and report

Stop and surface state when a step emits `blocked`/`review`/`failed`, when a
human gate is awaiting your decision, or when no further step is eligible.
Report exactly where it stopped, why, and what must happen to resume (which
label to apply, which gate to approve). Never loop or guess past a halt.

## Fallback

If GitHub MCP tools are not connected, inform the user:
```
GitHub MCP tools are not connected. To drive the pipeline, ensure the GitHub MCP
server is configured in your Claude Code settings.
```
