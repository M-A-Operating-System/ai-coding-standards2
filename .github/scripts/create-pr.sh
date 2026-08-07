#!/usr/bin/env bash
# create-pr.sh
#
# Creates the shared issue branch and opens a draft PR immediately after
# the PRD is approved, before any documentation or code agents run.
# All subsequent agent commits (docs, code) accumulate in this PR.
#
# Idempotent: if the branch and PR already exist, emits complete and exits.
# The PR link comment is posted idempotently — checked independently of PR
# existence so a failed comment on a prior run is retried automatically.
#
# Environment (set by orchestrator):
#   REPO            — owner/repo
#   ISSUE_NUMBER    — the issue being processed
#   GITHUB_TOKEN    — token with repo write access (used for all git/gh calls)
#   AI_AGILE_BOT_TOKEN — optional PAT used only for gh pr create when org policy
#                        blocks GITHUB_TOKEN from creating pull requests

set -euo pipefail

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: ISSUE_NUMBER is not a valid integer: ${ISSUE_NUMBER}" >&2
  exit 1
fi

# Phase parameterisation (issue #247, two-phase design->build delivery).
# Defaults reproduce the original single-code-PR behaviour exactly, so the
# code-PR step (create-pr) is unchanged. The design-PR step (create-docs-pr)
# sets these to open issue-{N}-docs with a non-closing body under a distinct
# announcement identity.
BRANCH_SUFFIX="${BRANCH_SUFFIX:-}"                       # "" for code PR, "-docs" for design PR
PR_CLOSES_ISSUE="${PR_CLOSES_ISSUE:-true}"              # "false" for the design PR (must not close the issue)
CREATE_PR_AGENT="${CREATE_PR_AGENT:-01_product_docs/create-pr}"  # announcement identity + idempotency marker

BRANCH="issue-${ISSUE_NUMBER}${BRANCH_SUFFIX}"
PLACEHOLDER_MSG="chore: open branch for ${BRANCH}"

if [[ "${PR_CLOSES_ISSUE}" == "false" ]]; then
  # Design PR: merges to main at the prd-docs-updater:approved gate ahead of the
  # build phase; it must NOT close the issue (only the code PR does -- STD-PROC-001).
  PR_BODY="Design documentation for issue #${ISSUE_NUMBER} (branch ${BRANCH}). Merges to main at the prd-docs-updater:approved gate, ahead of the build phase; does not close the issue -- the code PR does."
else
  PR_BODY="Closes #${ISSUE_NUMBER}"
fi

# Idempotency: check for an existing open PR on this branch.
# NOTE: gh api returns JSON; --jq runs jq internally to extract the number.
# If the PR already exists we fall through to the comment-posting block below
# rather than exiting here, so a comment that failed on a prior run is retried.
EXISTING_PR=$(
  gh api \
    "repos/${REPO}/pulls?head=${REPO%%/*}:${BRANCH}&state=open&per_page=1" \
    --jq '.[0].number // empty' \
  2>/dev/null || true
)

if [[ -n "${EXISTING_PR}" ]]; then
  echo "PR #${EXISTING_PR} already exists for branch ${BRANCH}."
  PR_NUMBER="${EXISTING_PR}"
  PR_URL="https://github.com/${REPO}/pull/${PR_NUMBER}"
else
  # Resolve the repo's default branch for the PR base.
  DEFAULT_BRANCH=$(
    gh api "repos/${REPO}" --jq '.default_branch' \
    2>/dev/null || echo "main"
  )
  echo "DEBUG: DEFAULT_BRANCH='${DEFAULT_BRANCH}' BRANCH='${BRANCH}'"

  # PR token setup.
  _PR_TOKEN="${AI_AGILE_BOT_TOKEN:-${GH_TOKEN:-${GITHUB_TOKEN}}}"
  _TOKEN_SOURCE="${AI_AGILE_BOT_TOKEN:+AI_AGILE_BOT_TOKEN}"
  _TOKEN_SOURCE="${_TOKEN_SOURCE:-${GH_TOKEN:+GH_TOKEN}}"
  _TOKEN_SOURCE="${_TOKEN_SOURCE:-GITHUB_TOKEN}"

  _TOKEN_USER=$(GH_TOKEN="${_PR_TOKEN}" gh api "/user" --jq '.login' 2>/dev/null || echo "unknown")
  echo "PR token source: ${_TOKEN_SOURCE}, authenticated as: ${_TOKEN_USER}"

  # Get issue title for the PR title.
  ISSUE_TITLE=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}" --jq '.title')
  PR_TITLE="${BRANCH}: ${ISSUE_TITLE:0:60}"

  # Git identity for commits.
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git config user.name "github-actions[bot]"

  # Create the branch from the LATEST origin/${DEFAULT_BRANCH} if it doesn't
  # exist on the remote. Cut from origin/${DEFAULT_BRANCH}, NOT the local
  # ${DEFAULT_BRANCH} ref: `git fetch origin main` updates origin/main but
  # leaves a stale local main behind, so `git checkout main && git checkout -b`
  # would base the issue branch on an old main and lose the shared merge base
  # with the current tip (issue #197). `checkout -B ... origin/main` bases the
  # new branch on the freshly-fetched remote tip.
  if ! git ls-remote --exit-code --heads origin "${BRANCH}" &>/dev/null; then
    git fetch origin "${DEFAULT_BRANCH}"
    git checkout -B "${BRANCH}" "origin/${DEFAULT_BRANCH}"
    git commit --allow-empty -m "${PLACEHOLDER_MSG}"
    git push -u origin "${BRANCH}"
    echo "Created branch ${BRANCH} from origin/${DEFAULT_BRANCH} with placeholder commit."
  else
    echo "Branch ${BRANCH} already exists on remote."
  fi

  # Use the GitHub API compare endpoint to check how many unique commits the branch
  # has — this is the same check GitHub runs before allowing PR creation.
  AHEAD_BY=$(
    GH_TOKEN="${_PR_TOKEN}" gh api \
      "/repos/${REPO}/compare/${DEFAULT_BRANCH}...${BRANCH}" \
      --jq '.ahead_by' 2>/dev/null || echo 0
  )
  echo "DEBUG: GitHub compare: ${BRANCH} is ${AHEAD_BY} commit(s) ahead of ${DEFAULT_BRANCH}"

  if [[ "${AHEAD_BY}" -eq 0 ]]; then
    echo "GitHub sees no unique commits on ${BRANCH} — resetting to ${DEFAULT_BRANCH} and adding placeholder..."
    git fetch origin "${DEFAULT_BRANCH}"
    git checkout -B "${BRANCH}" "origin/${DEFAULT_BRANCH}"
    git commit --allow-empty -m "${PLACEHOLDER_MSG}"
    # Only force-push if the remote branch HEAD is still the known placeholder
    # commit (or the branch is brand-new). This prevents destroying agent commits
    # if create-pr is re-triggered after prd-docs-updater or coder has pushed work.
    # Fetch first so the local tracking ref reflects the true remote state.
    git fetch origin "${BRANCH}" 2>/dev/null || true
    REMOTE_MSG=$(git log -1 --format="%s" "origin/${BRANCH}" 2>/dev/null || echo "")
    if [[ "${REMOTE_MSG}" == "${PLACEHOLDER_MSG}" || -z "${REMOTE_MSG}" ]]; then
      git push -f origin "${BRANCH}"
      echo "Reset ${BRANCH} to ${DEFAULT_BRANCH} and pushed placeholder commit."
    else
      echo "Branch ${BRANCH} has non-placeholder commits ('${REMOTE_MSG}') — skipping force-push to preserve agent work." >&2
    fi
  fi

  # Flag a stale issue branch before the coder runs (issue #197). Non-fatal:
  # a stale branch is surfaced as a warning, not a hard failure, so create-pr
  # still opens the PR. A freshly-cut branch (from origin/${DEFAULT_BRANCH}
  # above) reports FRESH; an existing branch that has fallen far behind main is
  # flagged so the drift is visible rather than silently derailing later agents.
  _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if ! bash "${_SCRIPT_DIR}/check-branch-freshness.sh" "${BRANCH}"; then
    echo "WARNING: ${BRANCH} is stale relative to origin/${DEFAULT_BRANCH} (see above). Agents may hit merge-base issues until it is refreshed." >&2
  fi

  # Pre-flight: verify the token can access this repo.
  REPO_CHECK_ERR=$(GH_TOKEN="${_PR_TOKEN}" gh api "/repos/${REPO}" --jq '.full_name' 2>&1 >/dev/null) || {
    echo "ERROR: Token (${_TOKEN_SOURCE}, user=${_TOKEN_USER}) cannot access repo ${REPO}." >&2
    echo "       API error: ${REPO_CHECK_ERR}" >&2
    exit 1
  }

  echo "DEBUG: PR params: head='${BRANCH}' base='${DEFAULT_BRANCH}' title='${PR_TITLE}'"

  PR_JSON=$(
    GH_TOKEN="${_PR_TOKEN}" gh api \
      --method POST \
      "/repos/${REPO}/pulls" \
      -f "title=${PR_TITLE}" \
      -f "body=${PR_BODY}" \
      -f "head=${BRANCH}" \
      -f "base=${DEFAULT_BRANCH}" \
      -F "draft=true" 2>&1
  ) || {
    echo "ERROR: PR creation failed. Response: ${PR_JSON}" >&2
    exit 1
  }

  PR_NUMBER=$(echo "${PR_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin)['number'])" 2>/dev/null) || {
    echo "ERROR: Could not parse PR number from response: ${PR_JSON}" >&2
    exit 1
  }
  PR_URL="https://github.com/${REPO}/pull/${PR_NUMBER}"

  echo "Opened draft PR #${PR_NUMBER} for issue #${ISSUE_NUMBER} on branch ${BRANCH}."

  # Apply source-issue:{N} label to the PR immediately.
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO="${REPO}" ISSUE_NUMBER="${ISSUE_NUMBER}" PR_NUMBER="${PR_NUMBER}" \
    bash "${SCRIPT_DIR}/link-pr-to-issue.sh"
fi

# Post PR link comment on the issue — idempotent across re-runs and retries.
# Checks whether this step already commented before posting, so a comment that
# failed on a prior run (after PR creation succeeded) is retried automatically.
ALREADY_COMMENTED=$(
  gh api "repos/${REPO}/issues/${ISSUE_NUMBER}/comments" --paginate --jq '.[]' 2>/dev/null \
    | jq -s "[.[] | select(.body | contains(\"${CREATE_PR_AGENT}\"))] | length" 2>/dev/null || echo "0"
)

if [[ "${ALREADY_COMMENTED}" -eq 0 ]]; then
  gh issue comment "${ISSUE_NUMBER}" \
    --repo "${REPO}" \
    --body "$(cat <<EOF
<!-- ai-agile/announcement/v1 by ${CREATE_PR_AGENT} -->
Draft PR opened for this issue: [#${PR_NUMBER}](${PR_URL})
EOF
)" || {
    echo "ERROR: Failed to post PR link comment on issue #${ISSUE_NUMBER}." >&2
    exit 1
  }
  echo "Posted PR link comment on issue #${ISSUE_NUMBER}."
else
  echo "PR link comment already posted on issue #${ISSUE_NUMBER}; skipping."
fi

echo "AI_AGILE_STATUS: complete"
