#!/usr/bin/env bash
# aggregate-metrics-daily.sh -- daily metrics aggregation scheduled pipeline step.
#
# Thin wrapper around aggregate-metrics.sh that passes --period day (issue #547).
# Accepts --dry-run, which is forwarded to aggregate-metrics.sh unchanged.
#
# Required env (injected by the orchestrator):
#   AI_AGILE_ROOT  -- repo root, used to locate metrics_aggregator.py

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/aggregate-metrics.sh" --period day "$@"
