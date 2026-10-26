#!/usr/bin/env bash
# Tests that create-pr.sh sets the PR title verbatim from the issue title and
# copies the ### Release Notes section into the PR body when present.
#
# AC1: PR title equals the issue title exactly (no branch prefix, no truncation).
# AC2: When the issue has a ### Release Notes section, it is appended to PR body.
# AC3: When the issue has no ### Release Notes section, PR body is Closes #N only.
#
# Uses PATH-prepended mock binaries to intercept gh and git calls.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREATE_PR_SCRIPT="${REPO_ROOT}/scripts/create-pr.sh"

PR_NUM=42
ISSUE_NUM=99
TEST_REPO="owner/repo"

# ---------------------------------------------------------------------------
# setup_mocks — writes mock gh and git binaries.
#
# Caller sets before calling:
#   mock_issue_title  — the issue title the mock returns for --jq '.title'
#   mock_issue_body   — the issue body the mock returns for --jq '.body // ""'
#
# After the script runs, ${MOCK_DIR}/pr_creation_args.txt contains the full
# args passed to the gh POST /pulls call (may span multiple lines when the
# PR body contains newlines).
# ---------------------------------------------------------------------------
setup_mocks() {
  MOCK_DIR="$(mktemp -d)"
  CALLS_LOG="${MOCK_DIR}/calls.log"
  touch "${CALLS_LOG}"

  cat >"${MOCK_DIR}/git" <<GITEOF
#!/usr/bin/env bash
echo "git \$*" >> "${CALLS_LOG}"
case "\$1" in
  ls-remote) exit 1 ;;
  *)         exit 0 ;;
esac
GITEOF
  chmod +x "${MOCK_DIR}/git"

  cat >"${MOCK_DIR}/gh" <<GHEOF
#!/usr/bin/env bash
echo "gh \$*" >> "${CALLS_LOG}"
ARGS="\$*"
case "\$ARGS" in
  *"api --method POST"*"/pulls"*)
    # Write the full args to a dedicated file so multi-line bodies are preserved.
    printf '%s' "\$*" > "${MOCK_DIR}/pr_creation_args.txt"
    echo '{"number":${PR_NUM},"html_url":"https://github.com/${TEST_REPO}/pull/${PR_NUM}"}'
    ;;
  *"api --method POST"*"/comments"*)
    echo "ISSUE_COMMENT_CALLED" >> "${CALLS_LOG}"
    exit 0
    ;;
  *"api --method"*)
    echo '{"number":${PR_NUM}}'
    ;;
  *"api /user"*)
    echo "bot"
    ;;
  *"/compare/"*)
    echo "1"
    ;;
  *"/comments"*)
    true
    ;;
  *"/pulls"*)
    true
    ;;
  *"/issues/"*".title"*)
    echo "${mock_issue_title}"
    ;;
  *"/issues/"*".body"*)
    printf '%s' "${mock_issue_body}"
    ;;
  *"/issues/"*)
    echo "${mock_issue_title}"
    ;;
  *)
    echo "main"
    ;;
esac
GHEOF
  chmod +x "${MOCK_DIR}/gh"
}

teardown_mock_dir() {
  rm -rf "${MOCK_DIR:-}"
}

run_script() {
  PATH="${MOCK_DIR}:${PATH}" \
  REPO="${TEST_REPO}" \
  ISSUE_NUMBER="${ISSUE_NUM}" \
  BRANCH="issue-${ISSUE_NUM}" \
  PR_CLOSES_ISSUE="true" \
  GITHUB_TOKEN="fake-token" \
  GH_TOKEN="fake-token" \
  bash "${CREATE_PR_SCRIPT}" 2>&1 || true
}

# ---------------------------------------------------------------------------
# AC1: PR title equals the issue title verbatim (no prefix, no truncation).
# Uses a title longer than 60 characters to confirm both behaviors at once.
# ---------------------------------------------------------------------------
test_pr_title_is_verbatim_issue_title() {
  mock_issue_title="This is a very long issue title that is definitely more than sixty characters long"
  mock_issue_body=""
  setup_mocks

  run_script >/dev/null

  PR_ARGS=$(cat "${MOCK_DIR}/pr_creation_args.txt" 2>/dev/null || true)

  if echo "${PR_ARGS}" | grep -qF "title=${mock_issue_title}"; then
    pass "AC1: PR title equals verbatim issue title"
  else
    fail "AC1: PR title does not match verbatim -- args: ${PR_ARGS}"
  fi

  BRANCH_PREFIX="issue-${ISSUE_NUM}:"
  if echo "${PR_ARGS}" | grep -qF "title=${BRANCH_PREFIX}"; then
    fail "AC1: PR title still contains branch prefix"
  else
    pass "AC1: PR title has no branch prefix"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# AC2: When the issue has a ### Release Notes section, it is appended to the
# PR body alongside Closes #N.
# ---------------------------------------------------------------------------
test_pr_body_includes_release_notes_when_present() {
  mock_issue_title="My Issue"
  mock_issue_body="## Problem statement

Some problem.

### Release Notes

This feature does the thing.

## Dependencies

None."
  setup_mocks

  run_script >/dev/null

  PR_ARGS=$(cat "${MOCK_DIR}/pr_creation_args.txt" 2>/dev/null || true)

  if echo "${PR_ARGS}" | grep -qF "Closes #${ISSUE_NUM}"; then
    pass "AC2: PR body contains Closes #N"
  else
    fail "AC2: PR body missing Closes #N -- args: ${PR_ARGS}"
  fi

  if echo "${PR_ARGS}" | grep -qF "### Release Notes"; then
    pass "AC2: PR body contains Release Notes heading"
  else
    fail "AC2: PR body missing Release Notes heading -- args: ${PR_ARGS}"
  fi

  if echo "${PR_ARGS}" | grep -qF "This feature does the thing."; then
    pass "AC2: PR body contains Release Notes prose"
  else
    fail "AC2: PR body missing Release Notes prose -- args: ${PR_ARGS}"
  fi

  # Content after the next heading (## Dependencies) must not be included.
  if echo "${PR_ARGS}" | grep -qF "None."; then
    fail "AC2: PR body includes content from section after Release Notes"
  else
    pass "AC2: PR body stops before next heading"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# AC3: When the issue has no ### Release Notes section, PR body is Closes #N.
# ---------------------------------------------------------------------------
test_pr_body_is_closes_only_when_no_release_notes() {
  mock_issue_title="Another Issue"
  mock_issue_body="## Problem statement

No release notes section here.

## Acceptance criteria

- Some criterion."
  setup_mocks

  run_script >/dev/null

  PR_ARGS=$(cat "${MOCK_DIR}/pr_creation_args.txt" 2>/dev/null || true)

  if echo "${PR_ARGS}" | grep -qF "Closes #${ISSUE_NUM}"; then
    pass "AC3: PR body is Closes #N when no Release Notes section"
  else
    fail "AC3: unexpected PR body -- args: ${PR_ARGS}"
  fi

  if echo "${PR_ARGS}" | grep -qF "### Release Notes"; then
    fail "AC3: PR body unexpectedly contains Release Notes"
  else
    pass "AC3: PR body contains no Release Notes"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_pr_title_is_verbatim_issue_title
test_pr_body_includes_release_notes_when_present
test_pr_body_is_closes_only_when_no_release_notes

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
