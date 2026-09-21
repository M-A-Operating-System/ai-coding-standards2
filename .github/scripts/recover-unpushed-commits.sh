#!/usr/bin/env bash
# recover-unpushed-commits.sh
#
# Pushes commits a previous run committed but never got to push, before the
# branch is reset for a fresh worktree (issue #495, STD-ARCH-035; was inline
# in pipeline_orchestrator.py's _recover_unpushed_commits).
#
# A step commits into its worktree as it goes, and those commits move the
# shared branch ref immediately -- but they only become durable when the ref
# moves on the remote, which the orchestrator does after the step returns. A
# step killed at its budget ceiling never returns, so its commits sit ahead
# of origin with nothing having pushed them. The next run for that branch is
# where they would otherwise be lost: worktree setup resets the local branch
# to the remote, discarding exactly the work this script protects.
#
# Runs from the orchestrator's own shared checkout (there is no isolated
# worktree for this branch yet -- that is what this recovery happens before).
# Best-effort by design: a branch that cannot be pushed (diverged, or the
# remote refuses) is reported and left alone -- the caller still needs to
# reset and continue, and failing the whole run over a previous run's
# leftovers would strand the branch rather than rescue it. Always exits 0;
# all diagnostic output goes to stderr.
#
# Usage: recover-unpushed-commits.sh <branch>

set -uo pipefail

BRANCH="${1:?usage: recover-unpushed-commits.sh <branch>}"

COUNT="$(git rev-list --count "origin/${BRANCH}..${BRANCH}" 2>/dev/null)"
if [[ -z "$COUNT" || ! "$COUNT" =~ ^[0-9]+$ || "$COUNT" == "0" ]]; then
    exit 0
fi

echo "recover-unpushed-commits: ${BRANCH} is ${COUNT} commit(s) ahead of its remote from an earlier run -- pushing before the branch is reset" >&2

if ! PUSH_OUT="$(git push origin "${BRANCH}:${BRANCH}" 2>&1)"; then
    echo "recover-unpushed-commits: could not recover ${COUNT} unpushed commit(s) on ${BRANCH}: ${PUSH_OUT}" >&2
    exit 0
fi

echo "recover-unpushed-commits: recovered ${COUNT} unpushed commit(s) on ${BRANCH}" >&2
