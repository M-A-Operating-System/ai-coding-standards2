#!/usr/bin/env bash
# push-patch-tag.sh -- per-PR PATCH tag pipeline step (issue #694).
#
# Fires when a PR is merged to main via the orchestrator's
# pull_request.closed (merged) signal. Bumps the PATCH version and
# pushes a vX.Y.Z annotated tag for traceability. Does NOT publish a
# GitHub Release.
#
# Versioning (STD-PROC-033):
#   This step owns PATCH only. MINOR is bumped weekly by run-release-flow.sh.
#   MAJOR is cut deliberately by a human pushing an explicit vX.0.0 tag.
#
# The tags pushed here use the app token (AI_AGILE_BOT_TOKEN -> GH_TOKEN).
# GitHub Actions does not re-trigger other workflows push:tags: events for
# tags pushed with the default GITHUB_TOKEN, and app-token-pushed tags
# behave the same way in a standard setup, so this will not cause
# release.yml's off-cycle push:tags path to fire unintentionally.
#
# Idempotent: skips the tag push when the current HEAD of main is already
# tagged with a vX.Y.Z tag. This guard prevents double-tagging if the
# pull_request.closed event fires more than once for the same merge.
#
# Outcomes (AI_AGILE_STATUS: complete | blocked):
#   complete:  tag pushed, or skipped because HEAD was already tagged
#   blocked:   could not read HEAD SHA, compute the next tag, or push
#
# Required env (injected by the orchestrator):
#   REPO                      -- owner/name of the repository
#   GH_TOKEN or GITHUB_TOKEN  -- resolved by lib/github-identity.sh

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/github-identity.sh
. "$SCRIPT_DIR/lib/github-identity.sh"

REPO="${REPO:?push-patch-tag.sh requires REPO}"

if [[ -z "${GH_TOKEN:-}" ]]; then
    echo "push-patch-tag: ERROR: no GitHub credential available (GH_TOKEN unset after identity resolution)" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

# ---------------------------------------------------------------------------
# Get the current HEAD SHA of main.
# ---------------------------------------------------------------------------

HEAD_SHA=""
if ! HEAD_SHA="$(gh api "repos/$REPO/git/refs/heads/main" --jq '.object.sha' 2>/dev/null)"; then
    echo "push-patch-tag: ERROR: could not get HEAD SHA for main" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi
if [[ -z "$HEAD_SHA" ]]; then
    echo "push-patch-tag: ERROR: HEAD SHA is empty" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

echo "push-patch-tag: HEAD SHA: $HEAD_SHA" >&2

# ---------------------------------------------------------------------------
# Fetch all vX.Y.Z tags once, used for both the idempotency check and the
# next-tag computation.  /repos/{owner}/{repo}/tags auto-dereferences
# annotated tag objects, so .commit.sha is always the target commit SHA.
# ---------------------------------------------------------------------------

TAGS_JSON=""
if ! TAGS_JSON="$(gh api --paginate --slurp "repos/$REPO/tags" 2>/dev/null)"; then
    # Fail loudly rather than substituting an empty tag list: that would
    # skip the idempotency guard (treating an already-tagged HEAD as
    # untagged) and compute the wrong PATCH version from a false "no tags
    # exist" baseline.
    echo "push-patch-tag: ERROR: could not list tags for $REPO" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

# ---------------------------------------------------------------------------
# Idempotency guard: skip if HEAD is already tagged with a vX.Y.Z tag.
# ---------------------------------------------------------------------------

EXISTING_TAG=""
if EXISTING_TAG="$(printf '%s' "$TAGS_JSON" | python3 -I -c "
import json, sys, re
pages = json.load(sys.stdin)
tags = [t for page in pages for t in page]
head = sys.argv[1]
for t in tags:
    if t.get('commit', {}).get('sha') == head:
        name = t.get('name', '')
        if re.match(r'^v\d+\.\d+\.\d+$', name):
            print(name)
            sys.exit(0)
" "$HEAD_SHA" 2>/dev/null)"; then
    :
fi

if [[ -n "$EXISTING_TAG" ]]; then
    echo "push-patch-tag: HEAD already tagged ($EXISTING_TAG) -- skipping." >&2
    echo "AI_AGILE_STATUS: complete"
    exit 0
fi

# ---------------------------------------------------------------------------
# Compute the next PATCH tag from all existing vX.Y.Z tags.
# ---------------------------------------------------------------------------

NEXT_TAG=""
if NEXT_TAG="$(printf '%s' "$TAGS_JSON" | python3 -I -c "
import json, sys, re
pages = json.load(sys.stdin)
tags = [t for page in pages for t in page]
versions = []
for t in tags:
    m = re.match(r'^v(\d+)\.(\d+)\.(\d+)$', t.get('name', ''))
    if m:
        versions.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
if not versions:
    latest = (0, 0, 0)
else:
    versions.sort(reverse=True)
    latest = versions[0]
major, minor, patch = latest
print('v{}.{}.{}'.format(major, minor, patch + 1))
" 2>/dev/null)"; then
    :
fi

if [[ -z "$NEXT_TAG" ]]; then
    echo "push-patch-tag: ERROR: could not compute next PATCH tag" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

echo "push-patch-tag: next PATCH tag: $NEXT_TAG" >&2

# ---------------------------------------------------------------------------
# Create the annotated tag object.
# ---------------------------------------------------------------------------

TAG_OBJ_SHA=""
if ! TAG_OBJ_SHA="$(gh api "repos/$REPO/git/tags" \
        --method POST \
        -F "tag=$NEXT_TAG" \
        -F "message=Release $NEXT_TAG" \
        -F "object=$HEAD_SHA" \
        -F "type=commit" \
        --jq '.sha' 2>/dev/null)"; then
    echo "push-patch-tag: ERROR: could not create tag object for $NEXT_TAG" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi
if [[ -z "$TAG_OBJ_SHA" ]]; then
    echo "push-patch-tag: ERROR: tag object SHA is empty for $NEXT_TAG" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

# ---------------------------------------------------------------------------
# Create the git ref pointing to the tag object.
# ---------------------------------------------------------------------------

if ! gh api "repos/$REPO/git/refs" \
        --method POST \
        -F "ref=refs/tags/$NEXT_TAG" \
        -F "sha=$TAG_OBJ_SHA" > /dev/null 2>&1; then
    echo "push-patch-tag: ERROR: could not create git ref refs/tags/$NEXT_TAG" >&2
    echo "AI_AGILE_STATUS: blocked"
    exit 0
fi

echo "push-patch-tag: pushed $NEXT_TAG" >&2
echo "AI_AGILE_STATUS: complete"
exit 0
