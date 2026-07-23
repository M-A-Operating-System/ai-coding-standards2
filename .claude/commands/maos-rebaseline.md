# maos-rebaseline

Reset this session's local repo checkout to match the current state of the
remote default branch (normally `main`), so subsequent work starts from a
known-clean, up-to-date baseline.

This is a plain `git` utility, not a pipeline agent step — it doesn't touch
GitHub issues, PRs, or labels.

## Input

None required. `$ARGUMENTS` may optionally name a different branch to
rebaseline against (e.g. `develop`); defaults to the repo's remote default
branch.

## Instructions

1. **Check for uncommitted work first.** Run `git status --short`. If
   anything is staged, unstaged, or untracked, **stop** — list exactly what's
   dirty and ask the user whether to commit it, stash it, or discard it. Never
   stash, discard, or commit on the user's behalf without being told to; this
   command must not silently lose work.

2. **Determine the target branch.** Use `$ARGUMENTS` if given. Otherwise
   resolve the remote's default branch:
   ```bash
   git symbolic-ref refs/remotes/origin/HEAD --short 2>/dev/null | sed 's#origin/##'
   ```
   Fall back to `main` if that's empty (e.g. the symbolic ref was never set
   locally) -- run `git fetch origin` first if needed to set it.

3. **Fetch and check for local-only commits before resetting.** Note if the
   session is currently on the target branch with commits not present on
   `origin/{target}` -- rebaseline is expected to discard these (that's the
   point), but say so explicitly rather than silently dropping them. They
   remain recoverable via `git reflog` afterward; mention this so the user
   isn't left wondering.
   ```bash
   git fetch origin {target}
   ```

4. **Switch to the target branch and hard-reset it to match origin exactly:**
   ```bash
   git checkout {target}
   git reset --hard origin/{target}
   git clean -fd  # only if there are untracked files the user has already agreed to discard in step 1
   ```
   Do not run `git clean -fd` unless step 1 found untracked files and the user
   explicitly agreed to discard them -- otherwise skip it entirely so no
   untracked file the user still wants is removed.

5. **Report the result:** the branch name, the commit it now points to
   (`git log -1 --oneline`), and whether any local-only commits were
   discarded in the process.

## Notes

- This intentionally uses `git reset --hard`, a destructive operation --
  that's the entire purpose of "rebaseline." The safety net is step 1 (refuse
  to run over uncommitted work) and step 3 (say what's being discarded before
  discarding it), not avoiding the reset itself.
- If the session is mid-way through unrelated work on a feature branch, don't
  rebaseline that branch -- this command's job is to reset the *default*
  branch checkout (or whatever `$ARGUMENTS` names), not whatever branch
  happens to be currently checked out for other reasons. If the current
  branch differs from the target and has its own uncommitted work, step 1
  still catches it.
