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

# Refuse anything that is not an absolute path under a temp root. This script
# runs rm -rf; a relative path, or one pointing into the working tree, would
# delete real work.
#
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

echo "scratch-teardown: ${AI_AGILE_SCRATCH} removed"
