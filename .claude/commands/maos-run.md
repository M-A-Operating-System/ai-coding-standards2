# maos-run

Drive a GitHub issue through the **full AI-Agile pipeline end-to-end in one
interactive session** by invoking the real orchestrator
(`pipeline/pipeline_orchestrator.py`) one step at a time -- same sequence, same
dependencies, same human gates, same label transitions -- pausing in the chat
session for you to approve or request changes at each gate.

This is a hand-authored **driver** command (like `/maos-merge`,
`/maos-new-branch-pr`, `/maos-rebaseline`). It is NOT a pipeline agent and
carries no generated marker, so `scripts/generate_slash_commands.py` preserves
it. Routing is read from `pipeline/pipeline.json` + `pipeline/statuses.json` at
run time -- the flow is never hardcoded here, so adding/removing/reordering a
pipeline step changes the run with no edit to this command (P-14, P-2).

**Core rule: the orchestrator runs every step -- this command never does.**
Each label transition, `:wip` mutex, announcement, `<!-- ai-agile/artefact -->`
comment, `post_steps`, and `git_ops` commit/push is performed by the
orchestrator's own code when you invoke it. Driving through the orchestrator is
the only thing that guarantees the labels, artefact placement, and updates match
a real run. This command MUST NOT hand-apply `:wip`/`:complete`/`:review`
labels, gate labels (`{agent}:approved`), post artefacts, or run agent prompts
by hand -- that hand-mirroring drifts state (misplaced artefacts, missing
downstream labels, orphaned branches), and for a gate label specifically it is
also a P-10/MI-7 violation the orchestrator's own self-approval guard rejects
in a bot-attributed session (issue #377) and silently mis-attributes in any
other (PRODUCT.md MI-7: "the driver never writes the gate label itself").
There is only one thing `/maos-run` does itself: mark a PR ready for review via
the GitHub MCP tool when the orchestrator cannot (step 4d) -- a restricted
interactive session blocks the GraphQL `markPullRequestReadyForReview` op
`gh pr ready` uses, and REST has no draft->ready endpoint, so that one op falls
to the driver's MCP tool. On the GitHub Actions runner (full API) even that
runs natively. A human gate (step 4c) is instead crossed by telling the
orchestrator you have the person's confirmation and letting it write the
label itself (`--confirm-gate`) -- see step 4c.

## Input

`$ARGUMENTS` -- the issue number to drive (e.g. `42`).

## Instructions

### 1. Confirm the orchestrator can run here

`/maos-run` advances state ONLY by invoking the orchestrator. Before starting,
confirm:

- **REPO** -- `owner/repo` (from the git remote or the GitHub MCP context).
- A checked-out **working tree at the repo root** containing
  `pipeline/pipeline_orchestrator.py` (standalone checkout) or
  `ai-coding-standards2/pipeline/pipeline_orchestrator.py` (submodule layout).
  If neither exists, stop and report the missing prerequisite per **Fallback**.
- **GitHub auth** the orchestrator can use (`GITHUB_TOKEN`/`GH_TOKEN`, or `gh`
  auth), the **`gh` CLI** on PATH (the scripts and agents call `gh api` REST --
  install it if missing), and the **Claude CLI** on PATH for agent steps.

The **core** pipeline's scripts and agents (`01_product_docs/*`, `03_execute/*`,
and the scripts they invoke) call GitHub via `gh api` REST (not GraphQL), so they
run in a restricted session as well as on the CI runner. Two things still need
the full API: marking a PR ready for review (see the core rule and step 4d), and
the `00_ondemand/*` agents (`sizer`, the cleanup agents) which are not yet
REST-converted -- so driving an epic (which invokes the sizer) or a cleanup step
in a restricted session will halt on those ticks until they are converted.

If the orchestrator cannot run in this session (missing token/CLI, offline),
**stop and tell the user** -- do NOT fall back to hand-driving the steps. See
**Fallback**.

### 2. Load the spec (read-only -- for narration and gate detection)

Read `pipeline/pipeline.json` (each step's `agent`, `phase`, `object`,
`trigger`, `dependencies`, `human_gate_after`/`human_gate_label`, `self_gates`,
`type`, `review_loop`, `git_ops`, `post_steps`) and `pipeline/statuses.json`
(the label/status model) so you can explain what runs next and recognise human
gates. Do **not** reimplement the decision loop or apply labels from it -- the
orchestrator reads the same files at run time and makes the authoritative
decision.

### 3. Read current state

Read the issue's labels via `mcp__github__issue_read` -- the labels ARE the
state machine (P-1/P-11). Use them only to report where things stand and to
detect gate/halt conditions between ticks, not to drive transitions yourself.

### 4. Drive loop -- run each step through the orchestrator

Repeat until Complete (step 5) or Halt (step 6):

**a. Run one orchestrator tick scoped to this issue.** From the repo root:

```bash
SCRIPT=pipeline/pipeline_orchestrator.py
[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/pipeline/pipeline_orchestrator.py
python3 "$SCRIPT" --repo "$REPO" --issue $ARGUMENTS
```

**`.pipeline-stop` does not block interactive runs.** If the scheduled pipeline
is stopped (an operator ran `ai_emergency_stop.yml` to halt unattended work),
`/maos-run` ticks still proceed -- the orchestrator logs the stop but continues
when invoked without `--headless`. You do not need to clear `.pipeline-stop`
before driving an issue interactively.

Do **not** wrap this in a short shell `timeout`. Agent-heavy steps (`prd-writer`,
`coder`, `pr-reviewer`) legitimately take a few minutes, and the orchestrator
already enforces its own per-agent timeout. A short cap that kills the tick is
caught by the SIGTERM handler (which clears the in-flight `:wip` so nothing is
stranded), but the step will not finish -- let the tick run to completion.

Add `--verbose` for live agent output, or `--dry-run` first to preview what the
tick would trigger without modifying labels. The orchestrator selects the next
eligible step from `pipeline.json` (honouring `trigger`, `dependencies`,
`exclude_classifications`, `exclude_labels`), claims it (`:wip`), runs the agent
or script, posts the announcement and artefact **to the correct object**,
applies the outcome label (`:complete`/`:review`/`:blocked`, honouring
`self_gates`), and runs `post_steps` + `git_ops`. This is the orchestrator's own
code -- correct by construction. A single tick advances the next eligible
step(s) and stops; it does not cross a human gate.

**b. Re-read the issue (and any PR) labels and decide what happened:**

- **Advanced, more is eligible** (no gate reached) -> loop to (a) for the next
  tick.
- **Reached a human gate** (a step emitted `:review`, or a `human_gate_after`
  step completed and its `{agent}:approved` label is unset) -> go to (c).
- **`:blocked` / `:failed`, or the tick advanced nothing** (no eligible step)
  -> go to **Halt and report** (step 6).

**c. Human gate -- pause and prompt the human** with two choices; never
self-approve (P-10):

- **Approve** -> tell the orchestrator you have the person's confirmation and
  let it write the gate label itself (PRODUCT.md MI-7 -- the driver never
  writes a gate label directly):
  ```bash
  python3 "$SCRIPT" --repo "$REPO" --agent {agent} --issue $ARGUMENTS --confirm-gate
  ```
  where `{agent}` is the gated step's name (e.g. `01_product_docs/prd-writer`)
  from the labels you read in step 3. Because this runs inside your own
  session, the label's recorded GitHub actor is your account -- the same
  self-approval guard that would reject a bot-attributed application accepts
  it exactly the way a headless human-applied label is accepted (one
  mechanism, not two). If it refuses because the gate label is already
  present from an earlier, non-human application, it names the exact
  `gh issue edit --remove-label` command to run first, then re-run
  `--confirm-gate`. Then loop to (a); the next tick advances past the gate.
- **Request changes** (with feedback) -> post the feedback as an issue/PR
  comment or a `REQUEST_CHANGES` review, then run the next tick (a). The
  orchestrator applies the review-loop labels (`review-cycle:N` /
  `human-review-pending`) and re-invokes the coder per `review_loop`.

**d. Mark-ready assist (restricted sessions only).** When a tick's
`mark-pr-ready` / `merge-docs-pr` step needs a PR flipped from draft to ready
and the session blocks `gh pr ready` (GraphQL 403), the orchestrator logs the
failure and the PR stays draft. Detect this (the PR is still `draft` when the
step expected it ready) and mark it ready via
`mcp__github__update_pull_request(pullNumber, draft:false)` -- the only
in-session path that un-drafts. This is the only action the driver takes
directly (step 4c's `--confirm-gate` hands the gate label's own write to the
orchestrator). On the CI runner the step does it itself; no assist needed.

**e. Review loop.** `pr-reviewer` REQUEST CHANGES and the coder re-invoke are
handled by the orchestrator via `review_loop` (up to `review_loop.max_cycles`).
`/maos-run` only relays the human decision and runs the next tick.

### 5. Complete

Stop when the issue's code PR is marked ready for review (pr-reviewer APPROVE,
no unresolved human REQUEST_CHANGES). Report the PR number and that it is ready
to merge. Do not self-merge (that is `/maos-merge` on explicit request).

### 6. Halt and report

Stop and surface state when a tick emits `:blocked`/`:failed`, when a human gate
is awaiting your decision, or when a tick advances nothing. Report exactly where
it stopped, why, and what must happen to resume (which gate to approve, which
`:failed` label to clear so the next tick retries). Never hand-advance the state
machine to get past a halt.

## Fallback

- **GitHub MCP tools not connected** (needed to read state and prompt at gates):
  ```
  GitHub MCP tools are not connected. To drive the pipeline, ensure the GitHub MCP
  server is configured in your Claude Code settings.
  ```
- **Orchestrator cannot run in this session** (missing `GITHUB_TOKEN`/`gh` auth,
  no Claude CLI, or no network): STOP and tell the user which prerequisite is
  missing. Do NOT substitute by running agent prompts and applying labels by
  hand -- that produces the label/artefact drift this command exists to prevent.
  The only supported ways to advance state are running the orchestrator (here,
  once per step) or letting the scheduled GitHub Actions orchestrator pick the
  issue up.

## See also

- **Headless and interactive** (concept and comparison for scheduled vs.
  in-session): [`docs/product/orchestrator/PRODUCT.md`](../../docs/product/orchestrator/PRODUCT.md#headless-and-interactive)
- **Quick Start** (shortest path to a first run in either mode, prerequisites
  listed): [`docs/product/orchestrator/quick-start.md`](../../docs/product/orchestrator/quick-start.md)
