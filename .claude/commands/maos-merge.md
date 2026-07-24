# maos-merge

Merge a pull request and delete its branch. This is a **deterministic script**,
not an agent -- there is no LLM judgement in the merge decision. It runs
`.github/scripts/merge-pr.sh`, which finds the right PR, verifies it is open and
not conflicting, merges it, and deletes the head branch.

## Input

`$ARGUMENTS` -- a PR number, or an issue number whose `issue-{N}` branch has an
open PR. Resolved PR-number-first, then by the `issue-{N}` branch. An optional
second argument sets the merge method (`--merge` default, or `--squash` /
`--rebase`).

## Instructions

Run the script directly -- do not interpret, second-guess, or reimplement its
logic. Locate it (standalone repo first, then the submodule) and execute it with
the repo and the argument(s):

```bash
REPO=$(git remote get-url origin | sed -E 's#.*[:/]([^/]+/[^/]+?)(\.git)?$#\1#')
SCRIPT=.github/scripts/merge-pr.sh
[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/.github/scripts/merge-pr.sh
REPO="$REPO" bash "$SCRIPT" $ARGUMENTS
```

Report the script's output verbatim. If it exits non-zero, surface the error --
do not attempt to merge by any other means.

## Requirements

`merge-pr.sh` uses the `gh` CLI (like the other pipeline scripts, e.g.
`create-pr.sh`). It runs in CI and on a developer machine with `gh` installed
and authenticated. In an environment without `gh` (e.g. Claude Code on the web),
tell the user the command requires the `gh` CLI and cannot run there.
