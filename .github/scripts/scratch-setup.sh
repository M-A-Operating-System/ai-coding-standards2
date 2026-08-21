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
#   AI_AGILE_SCRATCH — absolute path to this run's scratch directory

set -euo pipefail

: "${AI_AGILE_SCRATCH:?AI_AGILE_SCRATCH must be set}"

# Refuse anything that is not an absolute path under a temp root. This script
# runs rm -rf; a relative path, or one pointing into the working tree, would
# delete real work.
case "$AI_AGILE_SCRATCH" in
    /tmp/?*|/var/tmp/?*) ;;
    *)
        echo "ERROR: AI_AGILE_SCRATCH must be an absolute path under /tmp or /var/tmp, got: ${AI_AGILE_SCRATCH}" >&2
        exit 1
        ;;
esac

rm -rf -- "$AI_AGILE_SCRATCH"
mkdir -p -- "$AI_AGILE_SCRATCH"

echo "scratch-setup: ${AI_AGILE_SCRATCH} ready"
