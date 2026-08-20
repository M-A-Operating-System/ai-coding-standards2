#!/usr/bin/env bash
# PreToolUse hook: real enforcement of /run-agent's tool-scope rule (issue #311).
#
# /run-agent writes .claude/.run-agent-scope.json at the start of a run,
# declaring the allowlist the orchestrator would pass as --allowedTools when it
# spawns the target agent as a subprocess, and removes it when the run ends.
# While that file exists, this hook denies any tool call outside that allowlist.
#
# Entries come in two forms, and both must be honoured (issue #335):
#   "Read", "Grep"        -- a bare tool name grants that whole tool.
#   "Bash(gh pr diff *)"  -- a fine-grained pattern grants only matching commands.
# BASE_AGENT_TOOLS uses the second form exclusively for Bash, so checking
# tool-name membership alone denies every Bash call an agent makes.
#
# No scope file present -> nothing to enforce -> allow silently (exit 0, no
# output). This is the normal state outside of a /run-agent invocation.
set -euo pipefail

SCOPE_FILE=".claude/.run-agent-scope.json"

[ -f "$SCOPE_FILE" ] || exit 0

PAYLOAD="$(cat)"

TOOL="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // empty')"
[ -n "$TOOL" ] || exit 0

# A bare tool-name entry grants the tool outright, arguments unchecked.
if jq -e --arg t "$TOOL" '.allowed | index($t) != null' "$SCOPE_FILE" >/dev/null 2>&1; then
  exit 0
fi

# Otherwise a fine-grained "Bash(pattern)" entry may still grant this command.
# Matching mirrors Claude Code's Bash permission semantics: the pattern is
# matched against the literal command text, with `*` spanning any sequence of
# characters including spaces (issue #326).
COMMAND=""
if [ "$TOOL" = "Bash" ]; then
  COMMAND="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // empty')"
fi

if [ -n "$COMMAND" ]; then
  while IFS= read -r PATTERN; do
    [ -n "$PATTERN" ] || continue
    # Unquoted on purpose: $PATTERN is the glob, not a literal string.
    case "$COMMAND" in
      $PATTERN) exit 0 ;;
    esac
  done < <(jq -r '.allowed[]? | select(startswith("Bash(")) | ltrimstr("Bash(") | rtrimstr(")")' "$SCOPE_FILE")
fi

AGENT="$(jq -r '.agent // "unknown"' "$SCOPE_FILE")"
ALLOWED="$(jq -r '.allowed | join(", ")' "$SCOPE_FILE")"
if [ -n "$COMMAND" ]; then
  SUBJECT="the command \`$COMMAND\` matches no entry in"
else
  SUBJECT="$TOOL is not in"
fi
REASON="Blocked by /run-agent tool-scope enforcement: $SUBJECT $AGENT's declared tools allowlist [$ALLOWED]. The real orchestrator-spawned subprocess would not be permitted this call. If you are not running /run-agent, remove $SCOPE_FILE."

jq -n --arg reason "$REASON" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
