#!/usr/bin/env bash
# link-pr-to-issue.sh
#
# Applies a source-issue:{N} label to a specific PR immediately after the
# orchestrator creates it. Called inline by create-pr.sh only.
#
# NOT a pipeline step — does not emit AI_AGILE_STATUS:.
#
# The orchestrator already wrote "Closes #{N}" to the PR body at creation
# time, which is what creates GitHub's Development sidebar link on the issue.
# This script only applies the source-issue label for label-based filtering.
#
# Environment (set by orchestrator):
#   REPO            — owner/repo
#   ISSUE_NUMBER    — the issue the PR was opened for
#   PR_NUMBER       — the PR that was just created

set -euo pipefail

# The identity every headless system action on GitHub uses (MI-7): the
# dedicated bot when the repository configures one, otherwise exactly the token
# this script used before. Resolved in one place, never here.
# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"
: "${PR_NUMBER:?PR_NUMBER must be set}"

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: ISSUE_NUMBER is not a valid integer: ${ISSUE_NUMBER}" >&2
  exit 1
fi

if [[ ! "${PR_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: PR_NUMBER is not a valid integer: ${PR_NUMBER}" >&2
  exit 1
fi

SOURCE_LABEL="source-issue:${ISSUE_NUMBER}"

# Ensure the label exists in the repo (422 = already exists; suppress).
gh label create "${SOURCE_LABEL}" \
  --repo "${REPO}" \
  --color "0075ca" \
  --description "PR was opened by an agent working on issue #${ISSUE_NUMBER}" \
  2>/dev/null || true

# Apply the label to the PR.
gh api --method POST "repos/${REPO}/issues/${PR_NUMBER}/labels" -f "labels[]=${SOURCE_LABEL}" >/dev/null

echo "Applied ${SOURCE_LABEL} to PR #${PR_NUMBER}."

# Copy the issue's classification label to the PR so release notes can
# categorise pipeline PRs (release.yml groups by classification: {type}).
CLASSIFICATION_LABEL=$(
  gh api "repos/${REPO}/issues/${ISSUE_NUMBER}" \
    --jq '.labels[].name | select(startswith("classification: "))' \
  2>/dev/null | head -1 || true
)

if [[ -n "${CLASSIFICATION_LABEL}" ]]; then
  gh label create "${CLASSIFICATION_LABEL}" \
    --repo "${REPO}" \
    --color "d93f0b" \
    --description "Issue classification" \
    2>/dev/null || true
  gh api --method POST "repos/${REPO}/issues/${PR_NUMBER}/labels" \
    -f "labels[]=${CLASSIFICATION_LABEL}" >/dev/null
  echo "Applied ${CLASSIFICATION_LABEL} to PR #${PR_NUMBER}."
fi
