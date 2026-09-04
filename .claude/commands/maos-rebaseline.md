# maos-rebaseline

Reset this session's local repo checkout to match the current state of the
remote default branch (normally `main`), so subsequent work starts from a
known-clean, up-to-date baseline. This is a **deterministic script**, not an
agent -- there is no LLM judgement in a rebaseline. It runs
`.github/scripts/rebaseline-branch.sh`, which refuses to run over uncommitted
work, resolves the target branch, says which local-only commits it is about to
discard, and hard-resets to the remote.

This is a plain `git` utility, not a pipeline agent step -- it doesn't touch
GitHub issues, PRs, or labels.

## Input

`$ARGUMENTS` -- optionally the branch to rebaseline against (e.g. `develop`).
Defaults to the repo's remote default branch.

## Instructions

Run the script directly -- do not interpret, second-guess, or reimplement its
logic. Locate it (standalone repo first, then the submodule) and execute it
with the argument:

```bash
SCRIPT=.github/scripts/rebaseline-branch.sh
[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/.github/scripts/rebaseline-branch.sh
bash "$SCRIPT" $ARGUMENTS
```

Report the script's output verbatim. If it exits non-zero, surface the error --
in particular, it stops rather than touching a dirty working tree, and what to
do with that work (commit it, stash it, discard it) is the user's decision to
make, not yours.
