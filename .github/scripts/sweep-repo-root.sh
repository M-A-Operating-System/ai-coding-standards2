#!/usr/bin/env bash
# sweep-repo-root.sh
#
# "After" half of the repo-root sweep (issue #376). Removes the files an agent
# wrote to the repository root instead of $AI_AGILE_SCRATCH, and says which.
#
# Declared in pipeline.json as defaults.agent_lifecycle.after -- the
# orchestrator neither performs this work nor names this script (AS-2,
# STD-ARCH-035). It was inline Python inside pipeline_orchestrator.py
# (_repo_root / _untracked_root_files / _sweep_agent_root_files) until issue
# #407 moved it here.
#
# NOT a pipeline step -- does not emit AI_AGILE_STATUS:.
#
# Runs for EVERY agent-type step, not only the ones that commit. prd-writer,
# pr-reviewer and issue-classifier declare no git_ops.commit_after, and all
# three were observed leaving files at the repo root (issue #376).
#
# Deliberately conservative: only files ABSENT from the baseline
# sweep-repo-root-snapshot.sh recorded are removed, so a file a human left in
# the tree is never touched. With no baseline it deletes nothing at all
# (STD-ARCH-014, fail closed) -- an unknown baseline would mean "every
# untracked root file is new", turning a failed probe into a delete-everything
# sweep.
#
# Related but NOT the same guard: commit-agent-work.sh refuses to COMMIT a new
# root-level file, working from the git index and leaving the file on disk. This
# script works from a before/after diff of untracked files and deletes. Both
# exist because they catch the leak at different moments and for different sets
# of steps; neither subsumes the other.
#
# Environment (set by the orchestrator):
#   AI_AGILE_SCRATCH -- absolute path to this run's scratch directory
#   AI_AGILE_ROOT    -- the repository checkout (optional; defaults to cwd)

set -euo pipefail

: "${AI_AGILE_SCRATCH:?AI_AGILE_SCRATCH must be set}"

SNAPSHOT="${AI_AGILE_SCRATCH%/}.root-snapshot"

if ! ROOT=$(cd "${AI_AGILE_ROOT:-.}" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null); then
    ROOT=""
fi
if [[ -z "$ROOT" ]]; then
    echo "sweep-repo-root: ERROR: could not resolve the repository root from '${AI_AGILE_ROOT:-.}'; skipping the sweep" >&2
    exit 1
fi

if [[ ! -f "$SNAPSHOT" ]]; then
    # Fail closed: skipping loses a cleanup, guessing risks deleting files the
    # agent never wrote. Skip, and say so loudly enough for the orchestrator to
    # log it.
    echo "sweep-repo-root: ERROR: no baseline at ${SNAPSHOT}; skipping the sweep rather than deleting on a guess" >&2
    exit 1
fi

if ! _listing=$(cd "$ROOT" && git ls-files --others --exclude-standard 2>/dev/null); then
    echo "sweep-repo-root: ERROR: git ls-files failed in ${ROOT}; skipping the sweep" >&2
    exit 1
fi

BEFORE=$(mktemp)
AFTER=$(mktemp)
LEAKED=$(mktemp)
# The snapshot is this run's baseline and is consumed here: removing it keeps a
# later run from sweeping against a baseline that predates it.
trap 'rm -f -- "$BEFORE" "$AFTER" "$LEAKED" "$SNAPSHOT"' EXIT

sort -- "$SNAPSHOT" > "$BEFORE"
printf '%s\n' "$_listing" | grep -v '/' | grep -v '^$' | sort > "$AFTER" || true
comm -13 "$BEFORE" "$AFTER" > "$LEAKED" || true

if [[ ! -s "$LEAKED" ]]; then
    exit 0
fi

# A silent sweep would hide the bug it exists to contain: name the files.
echo "sweep-repo-root: WARNING: ${AGENT_NAME:-the step} wrote $(wc -l < "$LEAKED" | tr -d ' ') file(s) to the repo root instead of \$AI_AGILE_SCRATCH; removing: $(tr '\n' ' ' < "$LEAKED")" >&2

_rc=0
while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    if ! rm -f -- "${ROOT}/${name}"; then
        echo "sweep-repo-root: WARNING: could not remove ${name}" >&2
        _rc=1
    fi
done < "$LEAKED"

exit "$_rc"
