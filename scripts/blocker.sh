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

# The identity every headless system action on GitHub uses (MI-7): the
# dedicated bot when the repository configures one, otherwise exactly the token
# this script used before. Resolved in one place, never here.
# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

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

BLOCKEDBY_LABELS=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}" --jq \
    '.labels[].name | select(startswith("blockedby:"))')

if [[ -z "${BLOCKEDBY_LABELS}" ]]; then
    log "no blockedby: label found on #${ISSUE_NUMBER} -- nothing to reciprocate"
    echo "AI_AGILE_STATUS: blocked \"apply blockedby:{N} to #${ISSUE_NUMBER} first, then re-request blocker\""
    exit 0
fi

# An issue can carry more than one blockedby: label at once (the orchestrator
# side gates on all of them) -- reciprocate every one, not just the first.
RECIPROCATED=0
while IFS= read -r blockedby_label; do
    target="${blockedby_label#blockedby:}"
    if ! [[ "${target}" =~ ^[0-9]+$ ]]; then
        log "malformed label '${blockedby_label}' on #${ISSUE_NUMBER} -- skipping"
        continue
    fi
    log "reciprocating: applying blocks:${ISSUE_NUMBER} to issue #${target}"
    ensure_label "${REPO}" "blocks:${ISSUE_NUMBER}"
    gh api --method POST "repos/${REPO}/issues/${target}/labels" \
        -f "labels[]=blocks:${ISSUE_NUMBER}" >/dev/null
    RECIPROCATED=$((RECIPROCATED + 1))
done <<< "${BLOCKEDBY_LABELS}"

if [[ "${RECIPROCATED}" -eq 0 ]]; then
    log "every blockedby: label on #${ISSUE_NUMBER} was malformed -- nothing reciprocated"
    echo "AI_AGILE_STATUS: blocked \"no valid blockedby:{N} label on #${ISSUE_NUMBER}\""
    exit 0
fi

log "done (${RECIPROCATED} reciprocated)"
echo "AI_AGILE_STATUS: complete"
