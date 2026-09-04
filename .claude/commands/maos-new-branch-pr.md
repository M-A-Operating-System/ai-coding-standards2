# maos-new-branch-pr

Create the shared issue branch and open its draft PR, linked via `Closes #N`.
This is a **deterministic script**, not an agent -- there is no LLM judgement
in opening a branch and a PR. It runs `.github/scripts/new-branch-pr.sh`, which
resolves the branch name from the flow's `naming` in `pipeline.json` and hands
off to `.github/scripts/create-pr.sh` -- the same script the
`01_product_docs/create-pr` pipeline step runs, so an interactive run and a
headless one produce the identical branch, PR, label and announcement.

Idempotent: an existing branch and PR are reported, never recreated.

## Input

`$ARGUMENTS` -- the issue number (e.g. `42`).

## Instructions

Run the script directly -- do not interpret, second-guess, or reimplement its
logic. Locate it (standalone repo first, then the submodule) and execute it
with the repo and the issue number:

```bash
REPO=$(git remote get-url origin | sed -E 's#.*[:/]([^/]+/[^/]+?)(\.git)?$#\1#')
SCRIPT=.github/scripts/new-branch-pr.sh
[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/.github/scripts/new-branch-pr.sh
REPO="$REPO" bash "$SCRIPT" $ARGUMENTS
```

Report the script's output verbatim -- PR number, URL and branch name. If it
exits non-zero, surface the error; do not open the branch or the PR by any
other means.

## Requirements

`new-branch-pr.sh` uses `git` and the `gh` CLI (like the other pipeline
scripts). It runs in CI and on a developer machine with `gh` installed and
authenticated. In an environment without `gh` (e.g. Claude Code on the web),
tell the user the command requires the `gh` CLI and cannot run there.
