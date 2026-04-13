#!/usr/bin/env bash
# status.sh
#
# Commands for applying and removing agent status labels on GitHub issues
# and PRs. Labels follow the convention: {agent-name}:{status}
#
# Source this file to use the functions, or call it directly:
#
#   source .github/scripts/status.sh
#   status_set_review prd-writer 42
#
#   bash .github/scripts/status.sh set-review prd-writer 42
#
# Requires: gh CLI authenticated, GITHUB_REPOSITORY set or --repo passed.
#
# Status reference (canonical source: ai-agile/pipeline/statuses.json)
# ─────────────────────────────────────────────────────────────────────
#  wip       Yellow   Agent is actively running. Set by orchestrator.
#  complete  Green    Agent finished successfully. Set by orchestrator.
#  review    Purple   Agent requests formal human review. Set by agent.
#  blocked   Red-org  Agent cannot proceed without human help. Set by agent.
#  failed    Red      Agent exited with an error. Set by orchestrator.
#  skipped   L.Blue   Agent intentionally bypassed. Set by human.
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

# ---------------------------------------------------------------------------
# Config — override via environment or arguments
# ---------------------------------------------------------------------------

REPO="${GITHUB_REPOSITORY:-}"
STATUSES_JSON="${STATUSES_JSON:-$(dirname "$0")/../../ai-agile/pipeline/statuses.json}"

# Colour codes — kept in sync with statuses.json
declare -A STATUS_COLOURS=(
  [wip]="E4E669"
  [complete]="0E8A16"
  [review]="D4C5F9"
  [blocked]="E99695"
  [failed]="B60205"
  [skipped]="BFD4F2"
)

declare -A STATUS_DESCRIPTIONS=(
  [wip]="Agent is actively running"
  [complete]="Agent completed successfully"
  [review]="Awaiting formal human review and approval"
  [blocked]="Blocked — needs human intervention to proceed"
  [failed]="Agent exited with an error"
  [skipped]="Intentionally bypassed"
)

ALL_STATUSES=(wip complete review blocked failed skipped)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_repo() {
  if [ -n "${1:-}" ]; then echo "$1"
  elif [ -n "$REPO" ]; then echo "$REPO"
  else
    gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || {
      echo "ERROR: Cannot determine repository. Set GITHUB_REPOSITORY or pass --repo." >&2
      exit 1
    }
  fi
}

_label_name() {
  local agent="$1" status="$2"
  echo "${agent}:${status}"
}

_ensure_label() {
  local repo="$1" label="$2" colour="$3" description="$4"
  if ! gh label list --repo "$repo" --json name -q '.[].name' 2>/dev/null \
      | grep -qxF "$label"; then
    gh label create "$label" \
      --repo "$repo" \
      --color "$colour" \
      --description "$description" \
      2>/dev/null || true  # ignore 422 race condition
    echo "  created label: $label"
  fi
}

_remove_all_statuses() {
  local repo="$1" agent="$2" number="$3"
  for s in "${ALL_STATUSES[@]}"; do
    local lbl
    lbl=$(_label_name "$agent" "$s")
    gh label remove "$lbl" --repo "$repo" \
      "$(gh issue view "$number" --repo "$repo" --json id -q .id 2>/dev/null || true)" \
      2>/dev/null || true
    # Direct removal via issues API (more reliable)
    gh api \
      --method DELETE \
      "/repos/${repo}/issues/${number}/labels/$(python3 -c "import urllib.parse; print(urllib.parse.quote('${lbl}', safe=''))")" \
      2>/dev/null || true
  done
}

_set_status() {
  local agent="$1" status="$2" number="$3" repo="${4:-$(_repo)}"
  local label colour description

  label=$(_label_name "$agent" "$status")
  colour="${STATUS_COLOURS[$status]}"
  description="${STATUS_DESCRIPTIONS[$status]}"

  _ensure_label "$repo" "$label" "$colour" "$description"
  _remove_all_statuses "$repo" "$agent" "$number"
  gh issue edit "$number" --repo "$repo" --add-label "$label"
  echo "  $agent → $status  (#$number)"
}

# ---------------------------------------------------------------------------
# Public commands — one per status
# ---------------------------------------------------------------------------

# Mark an agent as actively running
status_set_wip() {
  # Usage: status_set_wip <agent> <issue-or-pr-number> [repo]
  _set_status "$1" "wip" "$2" "${3:-$(_repo)}"
}

# Mark an agent as successfully complete
status_set_complete() {
  # Usage: status_set_complete <agent> <issue-or-pr-number> [repo]
  _set_status "$1" "complete" "$2" "${3:-$(_repo)}"
}

# Mark an agent as requesting formal human review
# The agent must have already posted its artefact or findings as a comment.
status_set_review() {
  # Usage: status_set_review <agent> <issue-or-pr-number> [message] [repo]
  local agent="$1" number="$2" message="${3:-}" repo="${4:-$(_repo)}"
  _set_status "$agent" "review" "$number" "$repo"

  if [ -n "$message" ]; then
    local body
    body=$(printf "**%s** has completed its work and is requesting formal review.\n\n%s\n\n" \
      "$agent" "$message")
    body+=$(printf "> **Action required:** Review the artefact above and remove the \`%s:review\` label to approve and advance the pipeline. If changes are needed, add a comment with your feedback before removing the label." "$agent")
    gh issue comment "$number" --repo "$repo" --body "$body"
  fi
}

# Mark an agent as blocked pending human intervention
# A reason explaining the blocker is required.
status_set_blocked() {
  # Usage: status_set_blocked <agent> <issue-or-pr-number> <reason> [repo]
  if [ $# -lt 3 ]; then
    echo "ERROR: status_set_blocked requires a reason. Usage: status_set_blocked <agent> <number> <reason>" >&2
    exit 1
  fi
  local agent="$1" number="$2" reason="$3" repo="${4:-$(_repo)}"
  _set_status "$agent" "blocked" "$number" "$repo"

  local body
  body=$(printf "**%s** is blocked and cannot proceed without human intervention.\n\n**Reason:**\n%s\n\n" \
    "$agent" "$reason")
  body+=$(printf "> **Action required:** Resolve the issue described above, then remove the \`%s:blocked\` label. The agent will re-run automatically." "$agent")
  gh issue comment "$number" --repo "$repo" --body "$body"
}

# Mark an agent as failed (technical error, not a decision)
status_set_failed() {
  # Usage: status_set_failed <agent> <issue-or-pr-number> [error-detail] [repo]
  local agent="$1" number="$2" detail="${3:-See agent logs for error detail.}" repo="${4:-$(_repo)}"
  _set_status "$agent" "failed" "$number" "$repo"

  local body
  body=$(printf "**%s** exited with an error.\n\n**Detail:**\n%s\n\n" \
    "$agent" "$detail")
  body+=$(printf "> **Action required:** Review the agent logs, fix the underlying error, then remove the \`%s:failed\` label to retry. Apply \`%s:skipped\` to bypass this agent entirely." \
    "$agent" "$agent")
  gh issue comment "$number" --repo "$repo" --body "$body"
}

# Mark an agent as intentionally skipped
status_set_skipped() {
  # Usage: status_set_skipped <agent> <issue-or-pr-number> [reason] [repo]
  local agent="$1" number="$2" reason="${3:-}" repo="${4:-$(_repo)}"
  _set_status "$agent" "skipped" "$number" "$repo"

  if [ -n "$reason" ]; then
    gh issue comment "$number" --repo "$repo" \
      --body "$(printf "**%s** was skipped.\n\n%s" "$agent" "$reason")"
  fi
}

# ---------------------------------------------------------------------------
# Utility commands
# ---------------------------------------------------------------------------

# Print the current status of all agents on an issue or PR
status_show() {
  # Usage: status_show <issue-or-pr-number> [repo]
  local number="$1" repo="${2:-$(_repo)}"
  local labels
  labels=$(gh issue view "$number" --repo "$repo" --json labels -q '.labels[].name' 2>/dev/null)

  echo "Status of #$number in $repo:"
  echo ""

  local found=false
  for status in "${ALL_STATUSES[@]}"; do
    while IFS= read -r label; do
      if [[ "$label" == *":$status" ]]; then
        local agent="${label%:*}"
        printf "  %-42s %s\n" "$label" "${STATUS_DESCRIPTIONS[$status]}"
        found=true
      fi
    done <<< "$labels"
  done

  if [ "$found" = false ]; then
    echo "  No agent status labels found."
  fi
}

# Bootstrap: create all status label variants for a given agent
status_bootstrap_agent() {
  # Usage: status_bootstrap_agent <agent> [repo]
  local agent="$1" repo="${2:-$(_repo)}"
  echo "Bootstrapping labels for agent: $agent in $repo"
  for status in "${ALL_STATUSES[@]}"; do
    local label colour description
    label=$(_label_name "$agent" "$status")
    colour="${STATUS_COLOURS[$status]}"
    description="${STATUS_DESCRIPTIONS[$status]}"
    _ensure_label "$repo" "$label" "$colour" "$description"
  done
  echo "Done."
}

# Bootstrap: create all status label variants for every agent in pipeline.json
status_bootstrap_all() {
  # Usage: status_bootstrap_all [pipeline.json path] [repo]
  local pipeline="${1:-$(dirname "$0")/../../ai-agile/pipeline/pipeline.json}"
  local repo="${2:-$(_repo)}"

  if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 required for status_bootstrap_all" >&2
    exit 1
  fi

  local agents
  agents=$(python3 -c "
import json, sys
with open('$pipeline') as f:
    data = json.load(f)
for a in data['pipeline']:
    print(a['agent'])
")

  echo "Bootstrapping labels for all pipeline agents in $repo"
  while IFS= read -r agent; do
    status_bootstrap_agent "$agent" "$repo"
  done <<< "$agents"
  echo "All agents bootstrapped."
}

# ---------------------------------------------------------------------------
# Direct CLI dispatch (when called as a script, not sourced)
# ---------------------------------------------------------------------------

_usage() {
  cat << 'USAGE'
status.sh — Apply and manage agent status labels on GitHub issues and PRs

Usage:
  status.sh <command> <agent> <number> [args...]

Commands:
  set-wip      <agent> <number>                   Mark agent as running
  set-complete <agent> <number>                   Mark agent as complete
  set-review   <agent> <number> [message]         Request formal human review
  set-blocked  <agent> <number> <reason>          Mark as blocked (reason required)
  set-failed   <agent> <number> [error-detail]    Mark as failed
  set-skipped  <agent> <number> [reason]          Mark as skipped

  show         <number>                           Show all agent statuses on an item
  bootstrap    <agent>                            Create all status labels for one agent
  bootstrap-all [pipeline.json]                   Create all labels for all pipeline agents

Options:
  --repo OWNER/REPO    GitHub repository (default: $GITHUB_REPOSITORY or gh default)

Status colour reference:
  wip       #E4E669  yellow      — agent running
  complete  #0E8A16  green       — finished successfully
  review    #D4C5F9  purple      — awaiting human approval
  blocked   #E99695  red-orange  — needs human intervention
  failed    #B60205  red         — technical error
  skipped   #BFD4F2  light-blue  — bypassed by human

Examples:
  status.sh set-wip      prd-writer 42
  status.sh set-review   prd-writer 42 "PRD draft posted above for review"
  status.sh set-blocked  architect  42 "The data model in the PRD conflicts with STD000000003 — need clarification on whether the legacy_integrations table is in scope"
  status.sh set-complete coder      42
  status.sh set-failed   test-runner 42 "pytest exited with code 1 — see Actions run #1234"
  status.sh set-skipped  adr-proposer 42 "No ADR-worthy decisions identified"
  status.sh show         42
  status.sh bootstrap-all
USAGE
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  REPO_OVERRIDE=""
  # Extract --repo flag if present
  args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo) REPO_OVERRIDE="$2"; shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  set -- "${args[@]:-}"
  [ -n "$REPO_OVERRIDE" ] && REPO="$REPO_OVERRIDE"

  cmd="${1:-help}"
  case "$cmd" in
    set-wip)      status_set_wip      "${2:?agent required}" "${3:?number required}" ;;
    set-complete) status_set_complete "${2:?agent required}" "${3:?number required}" ;;
    set-review)   status_set_review   "${2:?agent required}" "${3:?number required}" "${4:-}" ;;
    set-blocked)  status_set_blocked  "${2:?agent required}" "${3:?number required}" "${4:?reason required}" ;;
    set-failed)   status_set_failed   "${2:?agent required}" "${3:?number required}" "${4:-}" ;;
    set-skipped)  status_set_skipped  "${2:?agent required}" "${3:?number required}" "${4:-}" ;;
    show)         status_show         "${2:?number required}" ;;
    bootstrap)    status_bootstrap_agent "${2:?agent required}" ;;
    bootstrap-all) status_bootstrap_all "${2:-}" ;;
    help|--help|-h) _usage ;;
    *) echo "Unknown command: $cmd"; echo ""; _usage; exit 1 ;;
  esac
fi
