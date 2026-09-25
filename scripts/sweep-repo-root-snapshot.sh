#!/usr/bin/env bash
# sweep-repo-root-snapshot.sh
#
# "Before" half of the repo-root sweep (issue #376). Records which untracked
# files already sit at the repository root, immediately before the orchestrator
# spawns an agent, so sweep-repo-root.sh can afterwards tell what the agent
# itself added from what was already there.
#
# Declared in pipeline.json as defaults.agent_lifecycle.before -- the
# orchestrator neither performs this work nor names this script (AS-2,
# STD-ARCH-035). It was inline Python inside pipeline_orchestrator.py until
# issue #407 moved it here.
#
# NOT a pipeline step -- does not emit AI_AGILE_STATUS:.
#
# The snapshot lives NEXT TO the scratch directory, not inside it:
# scratch-setup.sh empties the scratch directory before every retry attempt,
# and the baseline has to survive all of a step's attempts. Taking a fresh
# baseline per attempt would hide a file leaked by attempt 1 from the sweep
# that runs after attempt 2. So an existing, still-fresh snapshot is kept
# rather than overwritten; only a stale one (left by a run that was killed
# before its sweep) is replaced.
#
# Environment (set by the orchestrator):
#   AI_AGILE_SCRATCH -- absolute path to this run's scratch directory
#   AI_AGILE_ROOT    -- the repository checkout (optional; defaults to cwd)
#   AI_AGILE_ROOT_SNAPSHOT_MAX_AGE -- seconds a snapshot stays usable (default 21600)

set -euo pipefail

: "${AI_AGILE_SCRATCH:?AI_AGILE_SCRATCH must be set}"

SNAPSHOT="${AI_AGILE_SCRATCH%/}.root-snapshot"
MAX_AGE="${AI_AGILE_ROOT_SNAPSHOT_MAX_AGE:-21600}"

# Resolve the repository root by asking git rather than trusting a path.
# AI_AGILE_ROOT is often "." (it is a consuming-repo-relative convention), so
# reading it directly would leave this cwd-relative: a tick started from a
# subdirectory would snapshot and later delete files there instead of at the
# repo root. `git rev-parse --show-toplevel` is absolute and correct from
# anywhere inside the tree.
if ! ROOT=$(cd "${AI_AGILE_ROOT:-.}" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null); then
    ROOT=""
fi
if [[ -z "$ROOT" ]]; then
    # Fail closed (STD-ARCH-014): with no root there is no baseline, and a
    # stale one from an earlier run must not be left behind for the sweep to
    # delete files against. Remove it and say so; the sweep then skips.
    rm -f -- "$SNAPSHOT"
    echo "sweep-repo-root-snapshot: ERROR: could not resolve the repository root from '${AI_AGILE_ROOT:-.}'; no baseline recorded, the sweep will skip" >&2
    exit 1
fi

# An existing snapshot from an earlier attempt of THIS run is the baseline to
# keep. Past MAX_AGE it belongs to a run that died before sweeping, and is
# replaced rather than trusted -- never delete files against ancient evidence.
if [[ -f "$SNAPSHOT" ]]; then
    _now=$(date +%s)
    _mtime=$(date -r "$SNAPSHOT" +%s 2>/dev/null || echo 0)
    if (( _mtime > 0 && _now - _mtime < MAX_AGE )); then
        echo "sweep-repo-root-snapshot: reusing the baseline already recorded at ${SNAPSHOT}"
        exit 0
    fi
    echo "sweep-repo-root-snapshot: replacing a stale baseline at ${SNAPSHOT}" >&2
    rm -f -- "$SNAPSHOT"
fi

# Untracked files at depth 0 only. The scratch contract says agents write
# working files under $AI_AGILE_SCRATCH and never into the repo; when an agent
# writes to a relative path instead, the file lands here. Subdirectories are
# real work and are never listed.
if ! _listing=$(cd "$ROOT" && git ls-files --others --exclude-standard 2>/dev/null); then
    rm -f -- "$SNAPSHOT"
    echo "sweep-repo-root-snapshot: ERROR: git ls-files failed in ${ROOT}; no baseline recorded, the sweep will skip" >&2
    exit 1
fi

# Write via a temp file so a snapshot is never half-written: a truncated
# baseline would read as "these files are new" and delete them.
printf '%s\n' "$_listing" | grep -v '/' | grep -v '^$' > "${SNAPSHOT}.tmp" || true
mv -- "${SNAPSHOT}.tmp" "$SNAPSHOT"

echo "sweep-repo-root-snapshot: baseline of $(wc -l < "$SNAPSHOT" | tr -d ' ') root file(s) recorded at ${SNAPSHOT}"
