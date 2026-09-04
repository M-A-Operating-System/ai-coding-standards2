#!/usr/bin/env bash
# CI gate: poll GitHub check-runs for the issue PR until all pass, any fail, or timeout.
# Emits AI_AGILE_STATUS: complete | review | blocked on stdout as the final line.
# All diagnostic output goes to stderr so it appears in the Actions log without
# polluting the sentinel line on stdout.
set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

# The branch whose PR this gate polls, resolved by the orchestrator from this
# step's flow naming (issue #406) -- never derived from the issue number here.
BRANCH="${AI_AGILE_BRANCH:?AI_AGILE_BRANCH is required -- the branch declared by this step flow naming}"
POLL_INTERVAL="${CI_GATE_POLL_INTERVAL:-30}"
TIMEOUT="${CI_GATE_TIMEOUT:-840}"                # 14 minutes — leaves 1 min headroom
NO_CHECKS_GRACE="${CI_GATE_NO_CHECKS_GRACE:-4}"  # polls before assuming no CI exists

log() { echo "[ci-gate $(date -u +%H:%M:%S)] $*" >&2; }

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

get_check_runs_raw() {
    # Fetches all check runs for a SHA and emits one JSON object per line.
    # Returns non-zero if the API call fails so the caller can detect errors.
    local sha="$1"
    local raw
    raw="$(gh api "/repos/${REPO}/commits/${sha}/check-runs" --paginate 2>&1)" || {
        log "  API error fetching check-runs: ${raw}"
        return 1
    }
    # Validate the response contains check_runs before processing
    if ! echo "$raw" | jq -e '.check_runs' >/dev/null 2>&1; then
        log "  unexpected API response (no check_runs field): $(echo "$raw" | head -c 200)"
        return 1
    fi
    echo "$raw" | jq -r \
        '.check_runs[] | {name: .name, status: .status, conclusion: .conclusion, suite_id: (.check_suite.id // 0)}'
}

post_comment() {
    local pr_number="$1" body="$2"
    # gh pr comment is GraphQL-backed and 403s when this script runs as a direct
    # subprocess (not inside a nested `claude` agent invocation); the issues
    # comments REST endpoint serves PR comments identically.
    gh api --method POST "repos/${REPO}/issues/${pr_number}/comments" -f body="$body" >/dev/null
}

# ── build exclusion filter for orchestrator check runs ───────────────────────
#
# Any check run whose name matches an orchestrator job is excluded from the
# poll — this covers the current run, any queued run waiting behind it, and
# any run that completed between the push and now.  Exclusion is by job name
# because names are stable across all runs of the same workflow.

declare -A seen_names=()
EXCLUDE_NAMES='[]'  # JSON array of job names to exclude — passed via --argjson to jq

_add_excluded_name() {
    local name="$1"
    [[ -z "$name" || -v "seen_names[$name]" ]] && return
    seen_names["$name"]=1
    # Build the JSON array incrementally via jq — names are args, never interpolated
    # into jq source code, so crafted job names cannot inject jq expressions.
    EXCLUDE_NAMES="$(jq -n --argjson arr "$EXCLUDE_NAMES" --arg name "$name" '$arr + [$name]')"
}

# 1. Explicit list from workflow env (most reliable — no API call required)
if [[ -n "${CI_GATE_EXCLUDE_JOB_NAMES:-}" ]]; then
    while IFS= read -r name; do
        _add_excluded_name "$name"
    done <<<"$CI_GATE_EXCLUDE_JOB_NAMES"
fi

# 2. Live query — picks up any jobs not yet listed in CI_GATE_EXCLUDE_JOB_NAMES
if [[ -n "${GITHUB_RUN_ID:-}" ]]; then
    while IFS= read -r name; do
        _add_excluded_name "$name"
    done < <(gh api "/repos/${REPO}/actions/runs/${GITHUB_RUN_ID}/jobs" \
        --jq '.jobs[].name' 2>/dev/null || true)
fi

log "GITHUB_RUN_ID=${GITHUB_RUN_ID:-<not set>}"
log "exclude list: ${EXCLUDE_NAMES}"
if [[ ${#seen_names[@]} -eq 0 ]]; then
    log "excluded job names: <none>"
else
    log "excluded job names: ${!seen_names[*]}"
fi

# ── locate PR ────────────────────────────────────────────────────────────────

PR_NUMBER="$(find_pr)"
if [[ -z "$PR_NUMBER" ]]; then
    log "no open PR found for branch ${BRANCH} — skipping"
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi
log "PR #${PR_NUMBER}  branch=${BRANCH}"

# ── get HEAD SHA ─────────────────────────────────────────────────────────────

HEAD_SHA="$(gh api "repos/${REPO}/pulls/${PR_NUMBER}" --jq '.head.sha')"
if [[ -z "$HEAD_SHA" ]]; then
    log "could not resolve HEAD SHA for PR #${PR_NUMBER} — blocking"
    echo "AI_AGILE_STATUS: blocked \"Could not resolve HEAD SHA for PR #${PR_NUMBER}.\""
    exit 0
fi
log "HEAD SHA=${HEAD_SHA}"

# ── poll loop ────────────────────────────────────────────────────────────────

DEADLINE=$(( $(date +%s) + TIMEOUT ))
empty_polls=0
cycle=0

while true; do
    NOW=$(date +%s)
    REMAINING=$(( DEADLINE - NOW ))
    cycle=$(( cycle + 1 ))

    if (( NOW >= DEADLINE )); then
        log "TIMEOUT after ${TIMEOUT}s"
        STILL_RUNNING_JSON="$(get_check_runs_raw "$HEAD_SHA" 2>/dev/null \
            | jq -rs '[.[] | select(.status != "completed") | {name: .name, status: .status}]' \
            || echo '[]')"

        post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 03_execute/ci-gate -->
\`\`\`json
{
  "agent": "03_execute/ci-gate",
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

    # ── fetch raw check runs and log everything seen ──────────────────────────
    log "--- cycle ${cycle} (${REMAINING}s remaining) ---"

    if ! RAW_JSON="$(get_check_runs_raw "$HEAD_SHA")"; then
        log "  API call failed — skipping cycle"
        sleep "$POLL_INTERVAL"
        continue
    fi

    if [[ -z "$RAW_JSON" ]]; then
        log "  raw check runs: (none)"
    else
        while IFS= read -r line; do
            log "  raw: $line"
        done < <(jq -r '"\(.name) | status=\(.status) | conclusion=\(.conclusion // "-") | suite=\(.suite_id)"' \
            <<<"$RAW_JSON" 2>/dev/null || echo "$RAW_JSON")
    fi

    # ── apply exclusion filter ────────────────────────────────────────────────
    # Pass the exclusion list via --argjson so job names are never interpolated
    # into jq source code (prevents crafted names from injecting jq expressions).
    CHECK_JSON="$(jq -rs --argjson excl "$EXCLUDE_NAMES" \
        '[.[] | select(.name as $n | ($excl | index($n)) == null)][]' \
        <<<"${RAW_JSON:-[]}" 2>/dev/null || true)"

    raw_count=0
    [[ -n "$RAW_JSON" ]] && raw_count="$(jq -rs 'length' <<<"$RAW_JSON" 2>/dev/null || echo 0)"
    kept_count=0
    [[ -n "$CHECK_JSON" ]] && kept_count="$(jq -s 'length' <<<"$CHECK_JSON" 2>/dev/null || echo 0)"

    if [[ -z "$CHECK_JSON" && -n "$RAW_JSON" ]]; then
        log "  → all ${raw_count} raw run(s) excluded by filter (orchestrator-only)"
    fi

    if [[ -z "$CHECK_JSON" ]]; then
        empty_polls=$(( empty_polls + 1 ))
        log "  → no external checks visible (empty poll ${empty_polls}/${NO_CHECKS_GRACE})"
        if (( empty_polls >= NO_CHECKS_GRACE )); then
            log "  → grace period exhausted — no CI configured, passing through"
            post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 03_execute/ci-gate -->
\`\`\`json
{
  "agent": "03_execute/ci-gate",
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
        log "  sleeping ${POLL_INTERVAL}s"
        sleep "$POLL_INTERVAL"
        continue
    fi

    empty_polls=0
    TOTAL=$(  jq -s 'length'                                           <<<"$CHECK_JSON")
    PENDING=$(jq -s '[.[] | select(.status != "completed")] | length'  <<<"$CHECK_JSON")
    FAILED=$( jq -s '[.[] | select(.status == "completed" and
                (.conclusion == "failure" or
                 .conclusion == "timed_out" or
                 .conclusion == "cancelled" or
                 .conclusion == "action_required"))] | length'         <<<"$CHECK_JSON")

    log "  → external checks: total=${TOTAL} pending=${PENDING} failed=${FAILED}"
    while IFS= read -r line; do
        log "    $line"
    done < <(jq -r '"\(.name) | \(.status) | \(.conclusion // "-")"' <<<"$CHECK_JSON" 2>/dev/null || true)

    if (( PENDING > 0 )); then
        log "  sleeping ${POLL_INTERVAL}s"
        sleep "$POLL_INTERVAL"
        continue
    fi

    # All checks completed
    CHECKS_JSON="$(jq -rs '[.[] | {name: .name, conclusion: .conclusion}]' <<<"$CHECK_JSON")"

    if (( FAILED > 0 )); then
        log "RESULT: ${FAILED} check(s) failed"
        post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 03_execute/ci-gate -->
\`\`\`json
{
  "agent": "03_execute/ci-gate",
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
        log "RESULT: all ${TOTAL} check(s) passed"
        post_comment "$PR_NUMBER" "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 03_execute/ci-gate -->
\`\`\`json
{
  "agent": "03_execute/ci-gate",
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
