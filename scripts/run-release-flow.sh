#!/usr/bin/env bash
# run-release-flow.sh -- weekly release flow (issue #604).
#
# Fires on the weekly Wednesday cadence and supports manual dispatch.
# Determines the previous published release boundary, discovers merged PRs and
# closed issues since that boundary, applies publication gates, generates
# deterministic release-notes Markdown, and publishes a GitHub Release.
#
# Outcomes (emitted as structured JSON to stderr + AI_AGILE_STATUS to stdout):
#   no-change:   no merged PRs or closed issues since the last release
#   skipped:     a release for the computed tag already exists (idempotent rerun)
#   gate-failed: coverage threshold not met
#   published:   GitHub Release created successfully
#   error:       notes generation or gh release create failed (blocked)
#
# Idempotent: a rerun with an existing release tag exits with "skipped" and
# leaves the existing release untouched.
#
# Required env (injected by the orchestrator):
#   REPO                      -- owner/name of the repository
#   GH_TOKEN or GITHUB_TOKEN
#
# Optional env:
#   RELEASE_COVERAGE_THRESHOLD  -- minimum merged PRs required (default: 1)
#   RELEASE_NOTES_FILE_OVERRIDE -- pre-generated notes file path (test hook)

set -euo pipefail

# The identity every headless system action on GitHub uses (MI-7): the
# dedicated bot when the repository configures one, otherwise exactly the token
# this script used before. Resolved in one place, never here.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/github-identity.sh
. "$SCRIPT_DIR/lib/github-identity.sh"

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
if PULLS_JSON="$(gh api --paginate --slurp "repos/$REPO/pulls?state=closed&per_page=100" 2>/dev/null)"; then
    MERGED_PRS="$(printf '%s' "$PULLS_JSON" \
        | python3 -I -c "
import json, sys
last = sys.argv[1]
pages = json.load(sys.stdin)
pulls = [p for page in pages for p in page]
count = sum(1 for p in pulls if p.get('merged_at') and p['merged_at'] > last)
print(count)
" "$LAST_RELEASE_DATE")"
fi

# ---------------------------------------------------------------------------
# Count closed issues since the last release (excluding pull requests).
# ---------------------------------------------------------------------------

CLOSED_ISSUES=0
# -f/--raw-field (with --method GET) sends since as a properly URL-encoded
# query parameter instead of interpolating it into the URL string by hand
# (STD-SEC-020: last_release_date is API-controlled today, but an
# unvalidated value landing raw in a query string is the pattern that bites
# later when that assumption quietly stops holding).
if ISSUES_JSON="$(gh api --method GET --paginate --slurp \
        -f state=closed -f "since=${LAST_RELEASE_DATE}" -f per_page=100 \
        "repos/$REPO/issues" 2>/dev/null)"; then
    CLOSED_ISSUES="$(printf '%s' "$ISSUES_JSON" \
        | python3 -I -c "
import json, sys
last = sys.argv[1]
pages = json.load(sys.stdin)
issues = [i for page in pages for i in page]
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
# Full release path: changes exist -- compute tag, apply gates, and publish.
# ---------------------------------------------------------------------------

# Compute the next MINOR release tag from all existing vX.Y.Z tags.
# Both the gh API call and the Python post-processing are wrapped in
# conditionals so a failure produces a structured error rather than silently
# falling back to a hardcoded version string (which would cause the
# duplicate-release gate to fire indefinitely).
NEXT_TAG=""
if TAGS_JSON="$(gh api --paginate --slurp "repos/$REPO/git/refs/tags")"; then
    if NEXT_TAG="$(printf '%s' "$TAGS_JSON" | python3 -I -c "
import json, sys, re
pages = json.load(sys.stdin)
refs = [r for page in pages for r in page]
tags = []
for ref in refs:
    name = ref['ref'].replace('refs/tags/', '')
    m = re.match(r'^v(\d+)\.(\d+)\.(\d+)$', name)
    if m:
        tags.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
if not tags:
    print('v2.1.0')
    sys.exit(0)
tags.sort(reverse=True)
major, minor, _ = tags[0]
print('v{}.{}.0'.format(major, minor + 1))
")"; then
        :
    fi
fi
if [[ -z "$NEXT_TAG" ]]; then
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'error',
    'reason': 'tag discovery failed: could not compute next release tag',
    'timestamp': sys.argv[1],
}), file=sys.stderr)
" "$NOW"
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

echo "run-release-flow: next release tag: $NEXT_TAG" >&2

# Duplicate-release prevention gate: if a release for this tag already exists,
# exit cleanly without creating a duplicate.
if gh api "repos/$REPO/releases/tags/$NEXT_TAG" >/dev/null 2>&1; then
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'skipped',
    'reason': 'release already exists for this tag',
    'tag': sys.argv[1],
    'last_release_date': sys.argv[2],
    'timestamp': sys.argv[3],
}), file=sys.stderr)
" "$NEXT_TAG" "$LAST_RELEASE_DATE" "$NOW"
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

# Coverage threshold gate: at least RELEASE_COVERAGE_THRESHOLD merged PRs required.
COVERAGE_THRESHOLD="${RELEASE_COVERAGE_THRESHOLD:-1}"
if [[ "$MERGED_PRS" -lt "$COVERAGE_THRESHOLD" ]]; then
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'gate-failed',
    'reason': 'coverage threshold not met',
    'coverage_threshold': int(sys.argv[1]),
    'merged_prs': int(sys.argv[2]),
    'last_release_date': sys.argv[3],
    'timestamp': sys.argv[4],
}), file=sys.stderr)
" "$COVERAGE_THRESHOLD" "$MERGED_PRS" "$LAST_RELEASE_DATE" "$NOW"
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

# Generate release notes.
# RELEASE_NOTES_FILE_OVERRIDE may be set in tests to skip the HTTP-backed generator.
TMPDIR_NOTES="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_NOTES"' EXIT
NOTES_FILE="$TMPDIR_NOTES/release-notes.md"
DIAG_FILE="$TMPDIR_NOTES/diagnostics.json"

if [[ -n "${RELEASE_NOTES_FILE_OVERRIDE:-}" ]]; then
    cp "$RELEASE_NOTES_FILE_OVERRIDE" "$NOTES_FILE"
    printf '{"prs_in_window":%s,"issues_included":0,"cross_repo_refs":[],"excluded":[],"reopened":[],"missing_release_notes":[],"prs_outside_window":[],"prs_covered":[]}' \
        "$MERGED_PRS" > "$DIAG_FILE"
elif ! python3 -I "$SCRIPT_DIR/release_note_generator.py" \
        --repo "$REPO" \
        --start "$LAST_RELEASE_DATE" \
        --end   "$NOW" \
        --output   "$NOTES_FILE" \
        --diagnostics "$DIAG_FILE"; then
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'error',
    'reason': 'release notes generation failed',
    'tag': sys.argv[1],
    'timestamp': sys.argv[2],
}), file=sys.stderr)
" "$NEXT_TAG" "$NOW"
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

if [[ ! -s "$NOTES_FILE" ]]; then
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'error',
    'reason': 'release notes file is empty after generation',
    'tag': sys.argv[1],
    'timestamp': sys.argv[2],
}), file=sys.stderr)
" "$NEXT_TAG" "$NOW"
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

echo "run-release-flow: publishing release $NEXT_TAG" >&2

# Publish the GitHub Release.  Exclusion rules are applied by
# release_note_generator.py (EXCLUDED_LABELS), so the notes file is already
# filtered before this call.
if gh release create "$NEXT_TAG" \
        --repo "$REPO" \
        --title "$NEXT_TAG" \
        --notes-file "$NOTES_FILE" >/dev/null; then
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'published',
    'tag': sys.argv[1],
    'merged_prs': int(sys.argv[2]),
    'closed_issues': int(sys.argv[3]),
    'last_release_date': sys.argv[4],
    'timestamp': sys.argv[5],
}), file=sys.stderr)
" "$NEXT_TAG" "$MERGED_PRS" "$CLOSED_ISSUES" "$LAST_RELEASE_DATE" "$NOW"
    echo "AI_AGILE_STATUS: complete"
else
    python3 -I -c "
import json, sys
print(json.dumps({
    'outcome': 'error',
    'reason': 'gh release create failed',
    'tag': sys.argv[1],
    'merged_prs': int(sys.argv[2]),
    'timestamp': sys.argv[3],
}), file=sys.stderr)
" "$NEXT_TAG" "$MERGED_PRS" "$NOW"
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi
