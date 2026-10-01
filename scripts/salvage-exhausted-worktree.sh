#!/usr/bin/env bash
# salvage-exhausted-worktree.sh
#
# Best-effort push of whatever a budget-exhausted run left in its worktree
# (issue #445). Exhaustion never writes a result, so the normal commit_after
# path (_apply_result -> _push_step_branch) never runs, and the orchestrator
# discards the worktree -- committed or not -- unconditionally right after
# calling this script. This is the last chance to keep what's there.
#
# Commits whatever is left uncommitted under a `wip(exhausted):` message (a
# step killed mid-edit may not have reached its own next commit point yet),
# then pushes whatever ends up ahead of origin/<branch>. Mirrors
# _push_step_branch's stray-repo-root-file check in pipeline_orchestrator.py.
#
# This is git/filesystem process logic and runs as a standalone script per
# STD-ARCH-035, not inline in the orchestrator -- ADR-001 (adrs/adrs.json) is
# a plain decision record, not a waiver, and pr-reviewer flagged the inline
# version on PR #493 (finding SC-001) on exactly that basis.
#
# Complements _recover_unpushed_commits (pipeline_orchestrator.py), the
# deferred, next-retry path for the same already-committed case, by
# surfacing the recovery immediately rather than waiting for a possible
# future retry.
#
# Credential: invoked with no env= override, so this process inherits the
# orchestrator's own environment -- the same GIT_CONFIG_* header main() sets
# up once for its own `git push` calls (pipeline_orchestrator.py's _git_in).
# It never reads GH_TOKEN/GITHUB_TOKEN or builds its own auth header, so it
# does not source lib/github-identity.sh (that resolves the identity `gh`
# CLI calls and self-built auth preambles use; this script is neither).
#
# Usage: salvage-exhausted-worktree.sh <worktree-path> <branch> <agent-label>
#
# On a successful push, prints one JSON line to stdout:
#   {"sha": "<head-after-push>", "commits": <n>, "stray": [...]}
# and exits 0. When there is nothing ahead of origin/<branch> to push, exits
# 0 with no stdout. When a push is attempted and fails, exits 1 with no
# stdout -- the caller treats this the same as "nothing to push": this
# script is best-effort by design and never the reason a tick aborts.
# Diagnostic detail always goes to stderr.

set -uo pipefail

WORKTREE="${1:?usage: salvage-exhausted-worktree.sh <worktree-path> <branch> <agent-label>}"
BRANCH="${2:?usage: salvage-exhausted-worktree.sh <worktree-path> <branch> <agent-label>}"
AGENT_LABEL="${3:?usage: salvage-exhausted-worktree.sh <worktree-path> <branch> <agent-label>}"

cd "$WORKTREE" || { echo "salvage-exhausted-worktree: cannot cd to ${WORKTREE}" >&2; exit 1; }

if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    git add -A
    if ! git commit -m "wip(exhausted): uncommitted changes from a budget-exhausted ${AGENT_LABEL} run" >/dev/null 2>&1; then
        echo "salvage-exhausted-worktree: could not commit ${WORKTREE}'s uncommitted changes" >&2
    fi
fi

BASE="origin/${BRANCH}"
COUNT="$(git rev-list --count "${BASE}..HEAD" 2>/dev/null)"
if [[ -z "$COUNT" || ! "$COUNT" =~ ^[0-9]+$ || "$COUNT" == "0" ]]; then
    exit 0
fi

# Working files belong under $AI_AGILE_SCRATCH; a bare filename a step wrote
# resolves against the repo root because that is the working directory
# (issue #321). Reported, not repaired -- discarding a commit to punish a
# stray file would throw away the work this script exists to protect.
STRAY_FILES="$(git diff --name-only --diff-filter=A "${BASE}..HEAD" 2>/dev/null | grep -v '/' || true)"

if ! PUSH_OUT="$(git push origin "HEAD:${BRANCH}" 2>&1)"; then
    echo "salvage-exhausted-worktree: could not push ${COUNT} commit(s) for ${AGENT_LABEL}: ${PUSH_OUT}" >&2
    exit 1
fi

SHA="$(git rev-parse HEAD 2>/dev/null || true)"

if [[ -n "$STRAY_FILES" ]]; then
    echo "salvage-exhausted-worktree: ${AGENT_LABEL} committed file(s) at the repo root: $(tr '\n' ' ' <<<"$STRAY_FILES")" >&2
fi

SHA="$SHA" COUNT="$COUNT" STRAY_FILES="$STRAY_FILES" python3 - <<'PYEOF'
import json
import os

print(json.dumps({
    "sha": os.environ.get("SHA", ""),
    "commits": int(os.environ["COUNT"]),
    "stray": [f for f in os.environ.get("STRAY_FILES", "").splitlines() if f],
}))
PYEOF
