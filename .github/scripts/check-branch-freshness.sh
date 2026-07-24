#!/usr/bin/env bash
# check-branch-freshness.sh -- flags an issue branch that has fallen too far
# behind origin/main, or that shares no merge base with it.
#
# Issue #197: a branch cut from an old main (or never refreshed) drifts,
# causing missing pipeline infrastructure, distant/absent merge bases, and
# permanently CONFLICTING PRs. This check surfaces that state as a hard signal
# (non-zero exit) so CI can gate on it or an operator can inspect it, instead
# of letting agents thrash on a stale branch.
#
# Usage:
#   check-branch-freshness.sh <branch> [max_behind]
#
#   <branch>      issue branch to check (e.g. issue-143)
#   [max_behind]  max commits the branch may be behind origin/main before it is
#                 flagged. Defaults to $BRANCH_FRESHNESS_MAX_BEHIND, else 200.
#
# Exit codes:
#   0  FRESH -- within threshold and shares a merge base with origin/main
#   1  STALE -- behind by more than max_behind, or no merge base at all
#   2  usage / environment error (bad args, branch not found, fetch failed)

set -euo pipefail

BRANCH="${1:?usage: check-branch-freshness.sh <branch> [max_behind]}"
MAX_BEHIND="${2:-${BRANCH_FRESHNESS_MAX_BEHIND:-200}}"

if ! [[ "${MAX_BEHIND}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: max_behind must be a non-negative integer, got: ${MAX_BEHIND}" >&2
    exit 2
fi

# Refresh remote-tracking refs so the check reflects true remote state,
# independent of whatever branch is locally checked out.
if ! git fetch --quiet origin main 2>/dev/null; then
    echo "ERROR: could not fetch origin/main" >&2
    exit 2
fi
if ! git fetch --quiet origin "${BRANCH}" 2>/dev/null; then
    echo "ERROR: could not fetch origin/${BRANCH}" >&2
    exit 2
fi

MAIN_REF="origin/main"
BRANCH_REF="origin/${BRANCH}"

if ! git rev-parse --verify --quiet "${BRANCH_REF}" >/dev/null; then
    echo "ERROR: branch ${BRANCH_REF} not found on origin" >&2
    exit 2
fi

# No merge base at all -> unrelated/old histories -> definitively broken.
if ! git merge-base "${MAIN_REF}" "${BRANCH_REF}" >/dev/null 2>&1; then
    echo "STALE: ${BRANCH} shares no merge base with ${MAIN_REF}" >&2
    exit 1
fi

# Commits on main that the branch does not contain == how far behind it is.
BEHIND=$(git rev-list --count "${BRANCH_REF}..${MAIN_REF}")

if (( BEHIND > MAX_BEHIND )); then
    echo "STALE: ${BRANCH} is ${BEHIND} commit(s) behind ${MAIN_REF} (threshold ${MAX_BEHIND})" >&2
    exit 1
fi

echo "FRESH: ${BRANCH} is ${BEHIND} commit(s) behind ${MAIN_REF} (threshold ${MAX_BEHIND})"
exit 0
