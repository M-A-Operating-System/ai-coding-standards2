#!/usr/bin/env bash
# merge-docs-pr.sh
#
# Merges the design pull request (issue-{N}-docs) to main at the
# prd-docs-updater:approved gate, ahead of the build phase (issue #247,
# two-phase design->build delivery). Publishing the approved design to main
# first means every subsequent (and parallel) build is cut from a tree that
# already carries the latest approved docs, and design conflicts surface at
# this small docs merge rather than late at the code merge.
#
# Idempotent: if no open design PR exists (already merged, or none was created),
# emits complete and exits. If the design PR cannot be merged cleanly (conflicts
# against main, or a protected-branch rule blocks it), it does NOT force the
# merge -- it posts a note and emits review so a human resolves it, leaving the
# build phase to proceed only once the design is on main.
#
# Environment (set by orchestrator): REPO, ISSUE_NUMBER, GITHUB_TOKEN,
#   optionally AI_AGILE_BOT_TOKEN.

set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: ISSUE_NUMBER is not a valid integer: ${ISSUE_NUMBER}" >&2
  exit 1
fi

DOCS_BRANCH="issue-${ISSUE_NUMBER}-docs"

# Find the open design PR for this issue's docs branch.
PR_NUMBER=$(
  gh api "repos/${REPO}/pulls?head=${REPO%%/*}:${DOCS_BRANCH}&state=open&per_page=1" \
    --jq '.[0].number // empty' 2>/dev/null || true
)

if [[ -z "${PR_NUMBER}" ]]; then
  echo "No open design PR for ${DOCS_BRANCH} -- already merged or never created; nothing to do."
  echo "AI_AGILE_STATUS: complete"
  exit 0
fi

# A PAT may be required where org policy blocks GITHUB_TOKEN from merging.
_MERGE_TOKEN="${AI_AGILE_BOT_TOKEN:-${GH_TOKEN:-${GITHUB_TOKEN:-}}}"

PR_URL="https://github.com/${REPO}/pull/${PR_NUMBER}"

# Refuse to auto-merge a PR that conflicts with main -- a human resolves it.
MERGEABLE=$(
  gh api "repos/${REPO}/pulls/${PR_NUMBER}" --jq '.mergeable_state' \
  2>/dev/null || echo "UNKNOWN"
)

if [[ "${MERGEABLE}" == "dirty" ]]; then
  echo "Design PR #${PR_NUMBER} conflicts with main -- needs human resolution." >&2
  gh issue comment "${ISSUE_NUMBER}" --repo "${REPO}" --body "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 01_product_docs/merge-docs-pr -->
Design PR [#${PR_NUMBER}](${PR_URL}) cannot be merged to \`main\` automatically -- it conflicts with the current \`main\`. Resolve the conflicts on \`${DOCS_BRANCH}\`, then re-trigger this step.
EOF
)" || true
  echo "AI_AGILE_STATUS: review \"Design PR #${PR_NUMBER} conflicts with main; needs human resolution before the docs merge.\""
  exit 0
fi

# The design PR is opened as a draft (by create-docs-pr). A draft cannot be
# merged, so mark it ready first. Non-fatal if it is already ready.
# gh pr ready has no REST equivalent; works on the CI runner. In a restricted interactive session the /maos-run driver marks the PR ready via the GitHub MCP tool.
GH_TOKEN="${_MERGE_TOKEN}" gh pr ready "${PR_NUMBER}" --repo "${REPO}" 2>/dev/null || true

# Merge to main and delete the docs branch. A merge commit keeps the design
# publication visible in main's history (matching the repo's merge convention).
if MERGE_OUTPUT=$(GH_TOKEN="${_MERGE_TOKEN}" gh api --method PUT \
  "repos/${REPO}/pulls/${PR_NUMBER}/merge" -f merge_method=merge 2>&1); then
  # --delete-branch equivalent: best-effort ref deletion (may be blocked; must not fail the script).
  GH_TOKEN="${_MERGE_TOKEN}" gh api --method DELETE "repos/${REPO}/git/refs/heads/${DOCS_BRANCH}" 2>/dev/null || true
  echo "Merged design PR #${PR_NUMBER} (${DOCS_BRANCH}) to main."
else
  echo "Could not merge design PR #${PR_NUMBER}: ${MERGE_OUTPUT}" >&2
  gh issue comment "${ISSUE_NUMBER}" --repo "${REPO}" --body "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 01_product_docs/merge-docs-pr -->
Design PR [#${PR_NUMBER}](${PR_URL}) could not be merged to \`main\` automatically (a branch-protection rule or required check may be blocking it). Merge it by hand, then re-trigger this step so the build phase proceeds from an updated \`main\`.
EOF
)" || true
  echo "AI_AGILE_STATUS: review \"Design PR #${PR_NUMBER} could not be merged automatically; needs a human merge.\""
  exit 0
fi

# Post the design-merge announcement on the issue (idempotent -- skip if the
# merge note is already present from a prior run).
ALREADY_COMMENTED=$(
  gh api "repos/${REPO}/issues/${ISSUE_NUMBER}/comments" --paginate \
    --jq '[.[] | select(.body | contains("01_product_docs/merge-docs-pr")) | select(.body | contains("merged to `main`"))] | length' \
  2>/dev/null || echo "0"
)

if [[ "${ALREADY_COMMENTED}" -eq 0 ]]; then
  gh issue comment "${ISSUE_NUMBER}" --repo "${REPO}" --body "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 01_product_docs/merge-docs-pr -->
Approved design documentation merged to \`main\` via [#${PR_NUMBER}](${PR_URL}), ahead of the build phase. The code branch (\`issue-${ISSUE_NUMBER}\`) will be cut from the now-updated \`main\`.
EOF
)" || true
fi

echo "AI_AGILE_STATUS: complete"
