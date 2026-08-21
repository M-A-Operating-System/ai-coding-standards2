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
# A Bash command is split into its sub-commands first and EVERY sub-command must
# match a granted pattern (issue #362). Globbing a pattern against the whole
# command string was wrong in both directions: `Bash(export *)` granted
# `export FOO=1 && curl evil.com` because the trailing `*` spanned the `&&`,
# while `Bash(sed *)` refused `cd /repo && sed -n 1p f` because the string
# started with `cd`. split-command.py owns the decomposition and refuses
# anything it cannot decompose honestly; a refusal is a denial.
#
# No scope file present -> nothing to enforce -> allow silently (exit 0, no
# output). This is the normal state outside of a /run-agent invocation.
set -euo pipefail

SCOPE_FILE=".claude/.run-agent-scope.json"
SPLITTER="$(dirname -- "${BASH_SOURCE[0]}")/split-command.py"

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
# matched against the literal sub-command text, with `*` spanning any sequence
# of characters including spaces (issue #326).
COMMAND=""
if [ "$TOOL" = "Bash" ]; then
  COMMAND="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // empty')"
fi

# The escape hatch, always permitted: run-agent.md step 7 removes this file to
# end enforcement, and it must work for every agent, not only the ones whose
# allowlist happens to grant `rm`. Without it a pr-reviewer run leaves the
# session permanently scoped with no in-session route back -- the #335 lockout
# (issue #356). Matched exactly, so it grants nothing beyond removing the file.
case "$COMMAND" in
  "rm $SCOPE_FILE"|"rm -f $SCOPE_FILE"|"rm -f -- $SCOPE_FILE") exit 0 ;;
esac

DETAIL=""
if [ -n "$COMMAND" ]; then
  PATTERNS="$(jq -r '.allowed[]? | select(startswith("Bash(")) | ltrimstr("Bash(") | rtrimstr(")")' "$SCOPE_FILE")"

  if SEGMENTS="$(printf '%s' "$COMMAND" | python3 "$SPLITTER")"; then
    UNMATCHED=""
    while IFS= read -r SEGMENT; do
      [ -n "$SEGMENT" ] || continue
      MATCHED=""
      while IFS= read -r PATTERN; do
        [ -n "$PATTERN" ] || continue
        # Unquoted on purpose: $PATTERN is the glob, not a literal string.
        case "$SEGMENT" in
          $PATTERN) MATCHED="yes"; break ;;
        esac
      done <<< "$PATTERNS"
      if [ -z "$MATCHED" ]; then
        UNMATCHED="$SEGMENT"
        break
      fi
    done <<< "$SEGMENTS"

    if [ -z "$UNMATCHED" ]; then
      exit 0
    fi
    DETAIL="the sub-command \`$UNMATCHED\` matches no entry in"
  else
    # split-command.py refuses on stdout as `REFUSED: <reason>` and exits 2.
    # Anything else (no python3, missing splitter) fails closed with a reason
    # that says so, rather than an empty parenthesis.
    case "$SEGMENTS" in
      "REFUSED: "*) WHY="${SEGMENTS#REFUSED: }" ;;
      *)            WHY="$SPLITTER could not be run" ;;
    esac
    DETAIL="the command \`$COMMAND\` cannot be scope-checked ($WHY) and so is not granted by"
  fi
fi

AGENT="$(jq -r '.agent // "unknown"' "$SCOPE_FILE")"
ALLOWED="$(jq -r '.allowed | join(", ")' "$SCOPE_FILE")"
if [ -z "$DETAIL" ]; then
  DETAIL="$TOOL is not in"
fi
REASON="Blocked by /run-agent tool-scope enforcement: $DETAIL $AGENT's declared tools allowlist [$ALLOWED]. The real orchestrator-spawned subprocess would not be permitted this call. If you are not running /run-agent, remove $SCOPE_FILE."

jq -n --arg reason "$REASON" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
