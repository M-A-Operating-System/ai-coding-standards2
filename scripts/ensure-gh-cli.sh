#!/usr/bin/env bash
# ensure-gh-cli.sh
#
# Ensures `gh` is on PATH and can make authenticated REST calls, installing
# it via apt if missing. Runs once at orchestrator startup (issue #495 --
# STD-ARCH-035: this was inline in pipeline_orchestrator.py's _ensure_gh_cli).
#
# Script-type pipeline steps (scripts/*.sh) shell out to `gh api`
# REST calls, not gh's GraphQL-backed subcommands (some of which 403 in
# restricted sessions -- see #276/#284), so this only needs the binary plus
# GITHUB_TOKEN/GH_TOKEN in the environment. Verification below uses
# `gh api user` rather than `gh auth status`: the latter performs a
# GraphQL-backed validation call that can 403 in a restricted session even
# when `gh api` works fine, producing a false "not authenticated" reading.
#
# Never fails the run: gh being unavailable or unauthenticated is reported
# and left for the steps that actually need it to fail on their own.
#
# Usage: ensure-gh-cli.sh
# Environment: GITHUB_TOKEN / GH_TOKEN (read by `gh` itself, not by this script)
#
# Exit codes are informational only, not a pass/fail contract -- caller logs
# stdout/stderr and continues regardless:
#   0 -- gh is present and gh api user succeeded (message on stdout)
#   1 -- gh could not be installed, or is present but not authenticated
#        (message on stderr)

set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
    echo "ensure-gh-cli: gh CLI not found on PATH -- installing via apt (script-type steps call \`gh api\`)" >&2
    if ! apt_out="$(apt-get update -qq 2>&1 && apt-get install -y -qq gh 2>&1)"; then
        echo "ensure-gh-cli: could not install gh CLI automatically (script-type steps calling \`gh api\` will fail until it is installed manually): ${apt_out}" >&2
        exit 1
    fi
    if ! command -v gh >/dev/null 2>&1; then
        echo "ensure-gh-cli: apt install of gh exited cleanly but \`gh\` is still not on PATH" >&2
        exit 1
    fi
    echo "ensure-gh-cli: gh CLI installed" >&2
fi

if ! probe_out="$(gh api user --jq '.login' 2>&1)"; then
    echo "ensure-gh-cli: gh CLI present but \`gh api user\` failed -- script-type steps calling \`gh api\` may fail: ${probe_out}" >&2
    exit 1
fi

echo "ensure-gh-cli: gh CLI REST-authenticated as ${probe_out}"
