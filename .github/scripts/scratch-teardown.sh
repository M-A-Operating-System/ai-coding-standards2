#!/usr/bin/env bash
# scratch-teardown.sh
#
# Removes the per-run scratch directory after an agent finishes, on any
# outcome (complete, review, blocked, failed, retries exhausted). Issue #321.
#
# NOT a pipeline step -- does not emit AI_AGILE_STATUS:.
#
# This is hygiene, not correctness: scratch-setup.sh clears the directory
# before every run, so a tick that dies before reaching teardown is cleaned up
# by the next one. Never fail a run because cleanup did not happen.
#
# Environment (set by orchestrator):
#   AI_AGILE_SCRATCH — absolute path to this run's scratch directory

set -euo pipefail

: "${AI_AGILE_SCRATCH:?AI_AGILE_SCRATCH must be set}"

# Same guard as scratch-setup.sh: this script runs rm -rf.
case "$AI_AGILE_SCRATCH" in
    /tmp/?*|/var/tmp/?*) ;;
    *)
        echo "ERROR: AI_AGILE_SCRATCH must be an absolute path under /tmp or /var/tmp, got: ${AI_AGILE_SCRATCH}" >&2
        exit 1
        ;;
esac

rm -rf -- "$AI_AGILE_SCRATCH"

echo "scratch-teardown: ${AI_AGILE_SCRATCH} removed"
