#!/usr/bin/env bash
# PreToolUse hook: real enforcement of /run-agent's tool-scope rule (issue #311).
#
# /run-agent writes .claude/.run-agent-scope.json at the start of a run,
# declaring the target agent's `tools:` frontmatter allowlist, and removes it
# when the run ends. While that file exists, this hook denies any tool call
# outside the declared list -- the same restriction the real orchestrator
# applies via --allowedTools when it spawns the agent as a subprocess.
#
# No scope file present -> nothing to enforce -> allow silently (exit 0, no
# output). This is the normal state outside of a /run-agent invocation.
set -euo pipefail

SCOPE_FILE=".claude/.run-agent-scope.json"

[ -f "$SCOPE_FILE" ] || exit 0

TOOL="$(jq -r '.tool_name // empty')"
[ -n "$TOOL" ] || exit 0

if jq -e --arg t "$TOOL" '.allowed | index($t) != null' "$SCOPE_FILE" >/dev/null 2>&1; then
  exit 0
fi

AGENT="$(jq -r '.agent // "unknown"' "$SCOPE_FILE")"
ALLOWED="$(jq -r '.allowed | join(", ")' "$SCOPE_FILE")"
REASON="Blocked by /run-agent tool-scope enforcement: $TOOL is not in $AGENT's declared tools allowlist [$ALLOWED]. The real orchestrator-spawned subprocess would not have this tool available. If you are not running /run-agent, remove $SCOPE_FILE."

jq -n --arg reason "$REASON" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
