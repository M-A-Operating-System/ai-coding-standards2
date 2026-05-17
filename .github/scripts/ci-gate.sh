#!/usr/bin/env bash
# CI gate: poll GitHub check-runs for the issue PR until all pass, any fail, or timeout.
# Emits AI_AGILE_STATUS: complete | review | blocked on stdout as the final line.
set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

BRANCH="issue-${ISSUE_NUMBER}"
POLL_INTERVAL="${CI_GATE_POLL_INTERVAL:-30}"
TIMEOUT="${CI_GATE_TIMEOUT:-840}"          # 14 minutes — leaves 1 min headroom
NO_CHECKS_GRACE="${CI_GATE_NO_CHECKS_GRACE:-4}"  # polls before assuming no CI exists

# ── helpers ──────────────────────────────────────────────────────────────────

find_pr() {
    local owner
    owner="$(cut -d/ -f1 <<<"$REPO")"
    gh api "/repos/${REPO}/pulls" \
        --method GET \
        -f "head=${owner}:${BRANCH}" \
        -f "state=open" \
        -f "per_page=1" \
        --jq '.[0].number // empty'
}

get_check_runs() {
    # Returns check run objects after removing any orchestrator-owned runs.
    # $1 = commit SHA   $2 = jq boolean expression that selects runs to KEEP
    local sha="$1" keep_filter="$2"
    gh api "/repos/${REPO}/commits/${sha}/check-runs" \
        --paginate \
        --jq ".check_runs[] | select(${keep_filter}) | {name: .name, status: .status, conclusion: .conclusion}"
}

post_comment() {
    local pr_number="$1" body="$2"
    gh pr comment "$pr_number" --repo "$REPO" --body "$body"
}

# ── build exclusion filter for orchestrator check runs ───────────────────────
#
# Any check run whose name matches an orchestrator job is excluded from the
# poll — this covers the current run, any queued run waiting behind it, and
# any run that completed between the push and now.  Exclusion is by job name
# because names are stable across all runs of the same workflow.
#
# Primary source: CI_GATE_EXCLUDE_JOB_NAMES (newline-separated list set in
# the workflow env — explicit and reliable).  Supplemented by a live query of
# the current run's job names so the filter stays correct even if the workflow
# gains new jobs without updating the env var.

declare -A seen_names=()
KEEP_FILTER=""

# 1. Explicit list from workflow env (most reliable — no API call required)
if [[ -n "${CI_GATE_EXCLUDE_JOB_NAMES:-}" ]]; then
    while IFS= read -r name; do
        [[ -z "$name" || -v "seen_names[$name]" ]] && continue
        seen_names["$name"]=1
        escaped="$(printf '%s' "$name" | jq -Rs .)"
        KEEP_FILTER="${KEEP_FILTER:+${KEEP_FILTER} and }.name != ${escaped}"
    done <<<"$CI_GATE_EXCLUDE_JOB_NAMES"
fi

# 2. Live query — picks up any jobs not yet listed in CI_GATE_EXCLUDE_JOB_NAMES
if [[ -n "${GITHUB_RUN_ID:-}" ]]; then
    while IFS= read -r name; do
        [[ -z "$name" || -v "seen_names[$name]" ]] && continue
        seen_names["$name"]=1
        escaped="$(printf '%s' "$name" | jq -Rs .)"
        KEEP_FILTER="${KEEP_FILTER:+${KEEP_FILTER} and }.name != ${escaped}"
    done < <(gh api "/repos/${REPO}/actions/runs/${GITHUB_RUN_ID}/jobs" \
        --jq '.jobs[].name' 2>/dev/null || true)
fi

# If neither source produced any names, keep all (fail-open — better than deadlock)
[[ -z "$KEEP_FILTER" ]] && KEEP_FILTER='true'

# ── locate PR ────────────────────────────────────────────────────────────────

PR_NUMBER="$(find_pr)"
if [[ -z "$PR_NUMBER" ]]; then
    echo "ci-gate: no open PR found for branch ${BRANCH} — skipping." >&2
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

# ── get HEAD SHA ─────────────────────────────────────────────────────────────

HEAD_SHA="$(gh pr view "$PR_NUMBER" --repo "$REPO" --json headRefOid --jq '.headRefOid')"

# ── poll loop ────────────────────────────────────────────────────────────────

DEADLINE=$(( $(date +%s) + TIMEOUT ))
empty_polls=0

while true; do
    NOW=$(date +%s)
    if (( NOW >= DEADLINE )); then
        STILL_RUNNING_JSON="$(get_check_runs "$HEAD_SHA" "$KEEP_FILTER" 2>/dev/null \
            | jq -rs '[.[] | select(.status != "completed") | {name: .name, status: .status}]' \
            || echo '[]')"

        post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 05_execute/ci-gate -->
\`\`\`json
{
  "agent": "05_execute/ci-gate",
  "outcome": "blocked",
  "pr": ${PR_NUMBER},
  "sha": "${HEAD_SHA}",
  "reason": "timeout",
  "timeout_seconds": ${TIMEOUT},
  "still_running": ${STILL_RUNNING_JSON}
}
\`\`\`
EOF
)"
        echo "AI_AGILE_STATUS: blocked \"CI checks did not complete within ${TIMEOUT}s.\""
        exit 0
    fi

    # Fetch current check-run state (orchestrator jobs excluded)
    CHECK_JSON="$(get_check_runs "$HEAD_SHA" "$KEEP_FILTER" 2>/dev/null || true)"

    if [[ -z "$CHECK_JSON" ]]; then
        (( empty_polls++ )) || true
        if (( empty_polls >= NO_CHECKS_GRACE )); then
            # No external checks registered after the grace period —
            # no CI is configured for this branch; pass through.
            post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 05_execute/ci-gate -->
\`\`\`json
{
  "agent": "05_execute/ci-gate",
  "outcome": "complete",
  "pr": ${PR_NUMBER},
  "sha": "${HEAD_SHA}",
  "checks_total": 0,
  "checks_failed": 0,
  "note": "No external CI checks found after ${NO_CHECKS_GRACE} polls — passing through."
}
\`\`\`
EOF
)"
            echo "AI_AGILE_STATUS: complete"
            exit 0
        fi
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Checks have appeared — reset the no-checks counter
    empty_polls=0

    TOTAL=$(  jq -s 'length'                                           <<<"$CHECK_JSON")
    PENDING=$(jq -s '[.[] | select(.status != "completed")] | length'  <<<"$CHECK_JSON")
    FAILED=$( jq -s '[.[] | select(.status == "completed" and
                (.conclusion == "failure" or
                 .conclusion == "timed_out" or
                 .conclusion == "cancelled" or
                 .conclusion == "action_required"))] | length'         <<<"$CHECK_JSON")

    if (( PENDING > 0 )); then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # All checks completed — build JSON summary array
    CHECKS_JSON="$(jq -rs '[.[] | {name: .name, conclusion: .conclusion}]' <<<"$CHECK_JSON")"

    if (( FAILED > 0 )); then
        post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 05_execute/ci-gate -->
\`\`\`json
{
  "agent": "05_execute/ci-gate",
  "outcome": "review",
  "pr": ${PR_NUMBER},
  "sha": "${HEAD_SHA}",
  "checks_total": ${TOTAL},
  "checks_failed": ${FAILED},
  "checks": ${CHECKS_JSON}
}
\`\`\`
EOF
)"
        echo "AI_AGILE_STATUS: review \"${FAILED} CI check(s) failed on PR #${PR_NUMBER}.\""
    else
        post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 05_execute/ci-gate -->
\`\`\`json
{
  "agent": "05_execute/ci-gate",
  "outcome": "complete",
  "pr": ${PR_NUMBER},
  "sha": "${HEAD_SHA}",
  "checks_total": ${TOTAL},
  "checks_failed": 0,
  "checks": ${CHECKS_JSON}
}
\`\`\`
EOF
)"
        echo "AI_AGILE_STATUS: complete"
    fi
    exit 0
done
