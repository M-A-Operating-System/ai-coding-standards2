#!/usr/bin/env bash
# scratch-setup.sh
#
# Creates the per-run scratch directory empty, immediately before the
# orchestrator spawns an agent. Agents write working files here -- staged
# comment bodies, snapshots, intermediate output -- so nothing lands in the
# repo root where the commit sweep would pick it up (issue #321).
#
# NOT a pipeline step -- does not emit AI_AGILE_STATUS:.
#
# Removing first is what makes the whole lifecycle self-healing: a run killed
# mid-flight leaves its directory behind, and the next run on the same
# SESSION_ID clears it before the agent starts. That is why teardown is
# hygiene rather than a correctness requirement, and why no signal handler
# needs to clean up.
#
# Environment (set by orchestrator):
#   AI_AGILE_SCRATCH -- absolute path to this run's scratch directory

set -euo pipefail

: "${AI_AGILE_SCRATCH:?AI_AGILE_SCRATCH must be set}"

# Refuse anything that is not an absolute path under a temp root. This script
# runs rm -rf; a relative path, or one pointing into the working tree, would
# delete real work.
#
# Reject a relative path on the string, BEFORE resolving. readlink -m resolves
# a relative path against the caller's cwd, so "relative/path" passes the
# resolved test whenever cwd is itself under a temp root -- which is the normal
# case here, because the orchestrator gives each committing step a worktree
# under /tmp. rm -rf then runs inside that worktree. Found on PR #462.
case "$AI_AGILE_SCRATCH" in
    /*) ;;
    *)
        echo "ERROR: AI_AGILE_SCRATCH must be an absolute path; got ${AI_AGILE_SCRATCH}" >&2
        exit 1
        ;;
esac

# Check the RESOLVED path, not the string. A literal prefix test passes
# "/tmp/../etc/foo" -- ? consumes the dot, * takes the rest -- and rm -rf then
# runs outside /tmp. readlink -m resolves without requiring the path to exist.
_RESOLVED=$(readlink -m -- "$AI_AGILE_SCRATCH")
case "$_RESOLVED" in
    /tmp/?*|/var/tmp/?*) ;;
    *)
        echo "ERROR: AI_AGILE_SCRATCH must resolve to a path under /tmp or /var/tmp; got ${AI_AGILE_SCRATCH} (resolves to ${_RESOLVED})" >&2
        exit 1
        ;;
esac

rm -rf -- "$_RESOLVED"
mkdir -p -- "$_RESOLVED"

echo "scratch-setup: ${AI_AGILE_SCRATCH} ready"
