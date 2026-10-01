#!/usr/bin/env bash
# rebaseline-branch.sh
#
# Resets a local checkout to match the remote's state of a branch, so
# subsequent work starts from a known-clean, up-to-date baseline.
# `/maos-rebaseline` names this script and passes its argument through (AS-3);
# the procedure lives here, where it can be tested, rather than as numbered
# steps in a command file nothing reads but a person.
#
# A plain git utility: it touches no issue, PR, or label, and needs no token.
#
# This intentionally uses `git reset --hard`, a destructive operation -- that
# is the entire purpose of "rebaseline". The safety net is refusing to run over
# uncommitted work, and saying what is being discarded before discarding it,
# not avoiding the reset itself.
#
# Usage: rebaseline-branch.sh [target-branch]
#        Defaults to the remote's default branch.

set -euo pipefail

TARGET="${1:-}"

# ---------------------------------------------------------------------------
# Refuse to run over uncommitted work. Anything staged, unstaged or untracked
# stops the script: what to do with it -- commit, stash, discard -- is the
# person's call, never this script's, and a rebaseline must not silently lose
# work.
# ---------------------------------------------------------------------------
DIRTY=$(git status --short)
if [[ -n "$DIRTY" ]]; then
    echo "rebaseline: ERROR: the working tree is not clean. Commit, stash or discard these first:" >&2
    printf '%s\n' "$DIRTY" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Resolve the target branch. `git symbolic-ref refs/remotes/origin/HEAD` is
# only set locally by a clone (or by an explicit `set-head`), so a fetch is
# tried before falling back to main.
# ---------------------------------------------------------------------------
if [[ -z "$TARGET" ]]; then
    TARGET=$(git symbolic-ref refs/remotes/origin/HEAD --short 2>/dev/null | sed 's#^origin/##' || true)
fi
if [[ -z "$TARGET" ]]; then
    git remote set-head origin --auto >/dev/null 2>&1 || true
    TARGET=$(git symbolic-ref refs/remotes/origin/HEAD --short 2>/dev/null | sed 's#^origin/##' || true)
fi
TARGET="${TARGET:-main}"

git fetch origin "$TARGET"

# ---------------------------------------------------------------------------
# Say what is about to be discarded. Commits on the local target branch that
# origin does not have are exactly what a rebaseline throws away -- that is the
# point, but it is said out loud rather than done quietly. They stay
# recoverable through `git reflog`.
# ---------------------------------------------------------------------------
LOCAL_ONLY=""
if git rev-parse --verify --quiet "refs/heads/${TARGET}" >/dev/null; then
    LOCAL_ONLY=$(git log --oneline "origin/${TARGET}..${TARGET}" 2>/dev/null || true)
fi
if [[ -n "$LOCAL_ONLY" ]]; then
    echo "rebaseline: discarding these local-only commits on ${TARGET} (recoverable via 'git reflog'):"
    printf '%s\n' "$LOCAL_ONLY"
fi

# ---------------------------------------------------------------------------
# Switch to the target and reset it to the remote exactly. `checkout -B` both
# creates the branch and points it at origin's tip, so a fresh checkout that
# never had it locally takes the same path as one that did.
#
# Do NOT add `git clean -fd` here. The dirty-tree check above already refuses
# to proceed while any untracked file is present, so there is nothing left to
# clean; if dirty state ever reaches this point, that is a bug in the check to
# fix, not a reason to start deleting files.
# ---------------------------------------------------------------------------
git checkout -B "$TARGET" "origin/${TARGET}"
git reset --hard "origin/${TARGET}"

echo "rebaseline: ${TARGET} is now at $(git log -1 --oneline)"
if [[ -n "$LOCAL_ONLY" ]]; then
    echo "rebaseline: $(printf '%s\n' "$LOCAL_ONLY" | wc -l | tr -d ' ') local-only commit(s) were discarded"
else
    echo "rebaseline: no local-only commits were discarded"
fi
