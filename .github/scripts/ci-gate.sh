#!/usr/bin/env bash
# CI gate: poll GitHub check-runs for the issue PR until all pass, any fail, or timeout.
# Emits AI_AGILE_STATUS: complete | review | blocked on stdout as the final line.
set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

BRANCH="issue-${ISSUE_NUMBER}"
POLL_INTERVAL="${CI_GATE_POLL_INTERVAL:-30}"
TIMEOUT="${CI_GATE_TIMEOUT:-840}"   # 14 minutes — leaves 1 min headroom in a 15-min job

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
    local sha="$1" own_suite="$2"
    # Exclude the orchestrator's own check suite so ci-gate does not watch itself.
    # The API returns check_suite as a nested object; the id lives at .check_suite.id
    local suite_filter='true'
    [[ -n "$own_suite" ]] && suite_filter="(.check_suite.id // 0) != ${own_suite}"
    gh api "/repos/${REPO}/commits/${sha}/check-runs" \
        --paginate \
        --jq ".check_runs[] | select(${suite_filter}) | {name: .name, status: .status, conclusion: .conclusion}"
}

post_comment() {
    local pr_number="$1" body="$2"
    gh pr comment "$pr_number" --repo "$REPO" --body "$body"
}

# ── resolve orchestrator's own check suite (GitHub Actions only) ─────────────

OWN_SUITE_ID=""
if [[ -n "${GITHUB_RUN_ID:-}" ]]; then
    OWN_SUITE_ID="$(gh api "/repos/${REPO}/actions/runs/${GITHUB_RUN_ID}" \
        --jq '.check_suite_id // empty' 2>/dev/null || true)"
fi

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
# Grace periods: how many consecutive empty polls before we conclude no
# external CI is configured for this repo. Default: 4 × 30s = 2 minutes.
NO_CHECKS_GRACE="${CI_GATE_NO_CHECKS_GRACE:-4}"
empty_polls=0

while true; do
    NOW=$(date +%s)
    if (( NOW >= DEADLINE )); then
        STILL_RUNNING_JSON="$(get_check_runs "$HEAD_SHA" "$OWN_SUITE_ID" 2>/dev/null \
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

    # Fetch current check-run state (excluding the orchestrator's own suite)
    CHECK_JSON="$(get_check_runs "$HEAD_SHA" "$OWN_SUITE_ID" 2>/dev/null || true)"

    if [[ -z "$CHECK_JSON" ]]; then
        (( empty_polls++ )) || true
        if (( empty_polls >= NO_CHECKS_GRACE )); then
            # No external checks have registered after the grace period —
            # this repo has no CI configured for this branch; pass through.
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

    # Reset counter once checks appear
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
