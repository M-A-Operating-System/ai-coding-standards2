# maos-run

Drive a GitHub issue through the AI-Agile pipeline in one interactive session
by invoking the real orchestrator repeatedly -- same sequence, same
dependencies, same human gates, same label transitions -- stopping whenever a
person has to decide something. This is a **deterministic script**, not an
agent: the drive loop is mechanical. It runs
`.github/scripts/drive-item.sh`, which ticks the orchestrator
(`pipeline/pipeline_orchestrator.py`) against the issue, reads the resulting
labels, and stops at a halt.

**The orchestrator runs every step -- this command never does.** Each label
transition, `:wip` mutex, announcement, artefact comment, `post_steps` and
`git_ops` commit is performed by the orchestrator's own code. Never hand-apply
`:wip`/`:complete`/`:review` labels, gate labels, artefacts, or agent prompts:
that drifts state, and for a gate label it is also a P-10/MI-7 violation.

## Input

`$ARGUMENTS` -- the issue number to drive (e.g. `42`).

## Instructions

Run the script directly -- do not interpret, second-guess, or reimplement its
logic. Locate it (standalone repo first, then the submodule) and execute it
with the repo and the issue number, from the repo root:

```bash
REPO=$(git remote get-url origin | sed -E 's#.*[:/]([^/]+/[^/]+?)(\.git)?$#\1#')
SCRIPT=.github/scripts/drive-item.sh
[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/.github/scripts/drive-item.sh
REPO="$REPO" bash "$SCRIPT" $ARGUMENTS
```

Report the script's output verbatim. Exit 0 means nothing is left for a tick to
advance; exit 2 means it halted for a person; exit 1 means it could not run --
surface the missing prerequisite rather than substituting for it.

## When the script halts for a person (exit 2)

The script names the halting labels and stops. Deciding is the person's, and
crossing a gate is never something a script may do on its own (MI-7), so relay
the decision -- never write the label yourself:

- **A gate reached** (a step is `:review`, or a `human_gate_after` step is
  waiting for its `{agent}:approved` label) -- ask the user to approve or
  request changes.
  - **Approved**: tell the orchestrator you have the person's confirmation and
    let it write the gate label, then re-run the command:
    ```bash
    ORCH=pipeline/pipeline_orchestrator.py
    [ -f "$ORCH" ] || ORCH=ai-coding-standards2/pipeline/pipeline_orchestrator.py
    python3 "$ORCH" --repo "$REPO" --agent {step} --issue $ARGUMENTS --confirm-gate
    ```
  - **Changes requested**: post the feedback as an issue/PR comment or a
    `REQUEST_CHANGES` review, then re-run the command. The orchestrator applies
    the review-loop labels and re-invokes the coder itself.
- **`:blocked` or `:failed`** -- report where it stopped and why. It is cleared
  by fixing the cause and removing the label; never hand-advance the state
  machine to get past it.

**Mark-ready assist.** A restricted session blocks the GraphQL op `gh pr ready`
uses, so a `mark-pr-ready` / `merge-docs-pr` step can leave the PR in draft. If
the PR is still draft when a step expected it ready, mark it ready via
`mcp__github__update_pull_request(pullNumber, draft:false)`. This is the only
GitHub write this command makes directly; on the CI runner the step does it
itself.

## Requirements

`drive-item.sh` needs the `gh` CLI on PATH and authenticated, GitHub auth the
orchestrator can use (`GITHUB_TOKEN`/`GH_TOKEN`, or `gh` auth), and the Claude
CLI on PATH for agent steps. If any is missing the script says so and exits 1 --
**stop and tell the user**. Do NOT substitute by running agent prompts and
applying labels by hand; the only supported ways to advance state are running
the orchestrator and letting the scheduled runner pick the issue up.

`.pipeline-stop` does not block interactive runs: the orchestrator logs the
stop and proceeds when invoked without `--headless`.

## See also

- **Headless and interactive**: [`docs/product/orchestrator/PRODUCT.md`](../../docs/product/orchestrator/PRODUCT.md#headless-and-interactive)
- **Quick Start**: [`docs/product/orchestrator/quick-start.md`](../../docs/product/orchestrator/quick-start.md)
