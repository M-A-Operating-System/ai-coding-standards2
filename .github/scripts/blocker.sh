#!/usr/bin/env bash
# blocker: reciprocates a blockedby:/blocks: pair (issue #405).
#
# A human declares an ordering dependency by applying blockedby:{N} directly
# to the dependent issue (PRODUCT.md, "Blocking declares an ordering
# dependency between issues") -- that label alone is already sufficient to
# gate eligibility. Requesting this step (blocker:requested) is the
# convenience half: it reciprocates the symmetric blocks:{this} label onto
# issue N, so the relationship reads off either issue's own label list
# without the human having to edit both issues by hand.
#
# Emits AI_AGILE_STATUS: complete | blocked on stdout as the final line.
# All diagnostic output goes to stderr so it appears in the Actions log
# without polluting the sentinel line on stdout.
set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

log() { echo "[blocker] $*" >&2; }

ensure_label() {
    local repo="$1" label="$2"
    if ! gh label list --repo "${repo}" --json name -q '.[].name' 2>/dev/null \
            | grep -qxF "${label}"; then
        gh label create "${label}" \
            --repo "${repo}" \
            --color "EDEDED" \
            --description "Orchestrator: ${label}" \
            2>/dev/null || true  # ignore 422 race condition
        log "created label: ${label}"
    fi
}

BLOCKEDBY_LABEL=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}" --jq \
    '.labels[].name | select(startswith("blockedby:"))' | head -n1)

if [[ -z "${BLOCKEDBY_LABEL}" ]]; then
    log "no blockedby: label found on #${ISSUE_NUMBER} -- nothing to reciprocate"
    echo "AI_AGILE_STATUS: blocked \"apply blockedby:{N} to #${ISSUE_NUMBER} first, then re-request blocker\""
    exit 0
fi

TARGET="${BLOCKEDBY_LABEL#blockedby:}"
if ! [[ "${TARGET}" =~ ^[0-9]+$ ]]; then
    log "malformed label '${BLOCKEDBY_LABEL}' on #${ISSUE_NUMBER} -- not a numeric issue reference"
    echo "AI_AGILE_STATUS: blocked \"'${BLOCKEDBY_LABEL}' is not a valid blockedby:{N} label\""
    exit 0
fi

log "reciprocating: applying blocks:${ISSUE_NUMBER} to issue #${TARGET}"
ensure_label "${REPO}" "blocks:${ISSUE_NUMBER}"
gh api --method POST "repos/${REPO}/issues/${TARGET}/labels" \
    -f "labels[]=blocks:${ISSUE_NUMBER}" >/dev/null

log "done"
echo "AI_AGILE_STATUS: complete"
