#!/usr/bin/env bash
# run-release-flow.sh -- weekly release flow stub (issue #604 sub-issue 1/3).
#
# Fires on the weekly Wednesday cadence and supports manual dispatch. Checks
# for merged PRs or closed issues since the last GitHub Release and exits with
# a structured no-change outcome when none exist. This stub establishes the
# scheduling and dispatch infrastructure; no GitHub Release is created until
# sub-issue 2/3 merges.
#
# Outcomes:
#   no-change:  no merged PRs or closed issues since the last release --
#               emits a structured JSON record to stderr, AI_AGILE_STATUS: complete
#   stub:       changes exist but this is the sub-issue 1/3 stub --
#               emits a structured JSON record to stderr, AI_AGILE_STATUS: complete
#               (no GitHub Release is created)
#
# Idempotent: makes no writes to any branch or release; safe to re-trigger
# after a prior failed run without leaving residual state.
#
# Required env (injected by the orchestrator):
#   REPO              -- owner/name of the repository
#   GH_TOKEN or GITHUB_TOKEN

set -euo pipefail

# The identity every headless system action on GitHub uses (MI-7): the
# dedicated bot when the repository configures one, otherwise exactly the token
# this script used before. Resolved in one place, never here.
# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

REPO="${REPO:?run-release-flow.sh requires REPO}"

if [[ -z "${GH_TOKEN:-}" ]]; then
    echo "run-release-flow: ERROR: no GitHub credential available (GH_TOKEN unset after identity resolution)" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

# ---------------------------------------------------------------------------
# Find the last published GitHub Release.
# ---------------------------------------------------------------------------

LAST_RELEASE_DATE="1970-01-01T00:00:00Z"

if LATEST_JSON="$(gh api "repos/$REPO/releases/latest" 2>/dev/null)"; then
    _DATE="$(printf '%s' "$LATEST_JSON" \
        | python3 -I -c 'import json,sys; print(json.load(sys.stdin).get("published_at",""))')"
    if [[ -n "$_DATE" ]]; then
        LAST_RELEASE_DATE="$_DATE"
    fi
fi

echo "run-release-flow: last release date: $LAST_RELEASE_DATE" >&2

# ---------------------------------------------------------------------------
# Count merged PRs since the last release.
# ---------------------------------------------------------------------------

MERGED_PRS=0
if PULLS_JSON="$(gh api "repos/$REPO/pulls?state=closed&per_page=100" 2>/dev/null)"; then
    MERGED_PRS="$(printf '%s' "$PULLS_JSON" \
        | python3 -I -c "
import json, sys
last = sys.argv[1]
pulls = json.load(sys.stdin)
count = sum(1 for p in pulls if p.get('merged_at') and p['merged_at'] > last)
print(count)
" "$LAST_RELEASE_DATE")"
fi

# ---------------------------------------------------------------------------
# Count closed issues since the last release (excluding pull requests).
# ---------------------------------------------------------------------------

CLOSED_ISSUES=0
if ISSUES_JSON="$(gh api "repos/$REPO/issues?state=closed&since=${LAST_RELEASE_DATE}&per_page=100" 2>/dev/null)"; then
    CLOSED_ISSUES="$(printf '%s' "$ISSUES_JSON" \
        | python3 -I -c "
import json, sys
last = sys.argv[1]
issues = json.load(sys.stdin)
count = sum(
    1 for i in issues
    if i.get('pull_request') is None
    and i.get('closed_at', '') > last
)
print(count)
" "$LAST_RELEASE_DATE")"
fi

echo "run-release-flow: merged PRs since last release: $MERGED_PRS" >&2
echo "run-release-flow: closed issues since last release: $CLOSED_ISSUES" >&2

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------------------
# No-change path.
# ---------------------------------------------------------------------------

if [[ "$MERGED_PRS" -eq 0 && "$CLOSED_ISSUES" -eq 0 ]]; then
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'no-change',
    'reason': 'no merged PRs or closed issues since last release',
    'last_release_date': sys.argv[1],
    'timestamp': sys.argv[2],
}), file=sys.stderr)
" "$LAST_RELEASE_DATE" "$NOW"
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

# ---------------------------------------------------------------------------
# Stub path: changes exist but this is sub-issue 1/3 -- no release created.
# ---------------------------------------------------------------------------

python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'stub',
    'reason': 'release flow stub -- no GitHub Release created (sub-issue 2/3 not yet merged)',
    'merged_prs': int(sys.argv[1]),
    'closed_issues': int(sys.argv[2]),
    'last_release_date': sys.argv[3],
    'timestamp': sys.argv[4],
}), file=sys.stderr)
" "$MERGED_PRS" "$CLOSED_ISSUES" "$LAST_RELEASE_DATE" "$NOW"

echo "AI_AGILE_STATUS: complete"
