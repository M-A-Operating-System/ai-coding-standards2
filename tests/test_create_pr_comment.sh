#!/usr/bin/env bash
# Tests that create-pr.sh posts a PR link comment on the issue after opening
# a new draft PR, and does NOT post a duplicate comment on idempotent re-run.
#
# Uses PATH-prepended mock binaries to intercept gh and git calls.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREATE_PR_SCRIPT="${REPO_ROOT}/.github/scripts/create-pr.sh"

PR_NUM=42
ISSUE_NUM=66
TEST_REPO="owner/repo"

# ---------------------------------------------------------------------------
# Helper: create a temp mock dir; writes mock gh and git into it.
# Parameters:
#   $1 — "new"      → simulate no existing PR (full creation flow)
#        "existing" → simulate PR already exists (idempotent early exit)
#        "comment_fail" → simulate comment post failing
# ---------------------------------------------------------------------------
setup_mocks() {
  local mode="$1"
  MOCK_DIR="$(mktemp -d)"
  CALLS_LOG="${MOCK_DIR}/calls.log"
  touch "${CALLS_LOG}"

  # ---- git mock -----------------------------------------------------------
  # Records calls; ls-remote returns 1 (branch absent) so creation proceeds.
  cat >"${MOCK_DIR}/git" <<GITEOF
#!/usr/bin/env bash
echo "git \$*" >> "${CALLS_LOG}"
case "\$1" in
  ls-remote) exit 1 ;;   # branch does not exist yet
  *)         exit 0 ;;
esac
GITEOF
  chmod +x "${MOCK_DIR}/git"

  # ---- gh mock ------------------------------------------------------------
  cat >"${MOCK_DIR}/gh" <<GHEOF
#!/usr/bin/env bash
# Record every call
echo "gh \$*" >> "${CALLS_LOG}"

# Determine sub-command from first two args (skip any leading env-var tokens)
CMD="\$1 \$2"

case "\$CMD" in
  "pr list")
    # Return existing PR number when mode=existing; empty when mode=new
    echo "${mode_pr_list}"
    ;;
  "repo view")
    echo "main"
    ;;
  "api /user")
    echo "bot"
    ;;
  "api /repos/${TEST_REPO}/compare/"*)
    # Return just the ahead_by value (script uses --jq '.ahead_by')
    echo "1"
    ;;
  "api /repos/${TEST_REPO}")
    # Return full_name (script uses --jq '.full_name' and discards output)
    echo "${TEST_REPO}"
    ;;
  "api --method")
    # PR creation: return JSON with PR number
    echo '{"number":${PR_NUM},"html_url":"https://github.com/${TEST_REPO}/pull/${PR_NUM}"}'
    ;;
  "issue view")
    echo "Test Issue"
    ;;
  "issue comment")
    echo "ISSUE_COMMENT_CALLED" >> "${CALLS_LOG}"
    # Fail if mode=comment_fail
    ${comment_exit}
    ;;
  "label create") exit 0 ;;
  "pr edit")      exit 0 ;;
  *)              exit 0 ;;
esac
GHEOF
  chmod +x "${MOCK_DIR}/gh"
}

teardown_mock_dir() {
  rm -rf "${MOCK_DIR:-}"
}

# ---------------------------------------------------------------------------
# Test 1 (happy path): new PR creation → gh issue comment is called.
# ---------------------------------------------------------------------------
test_new_pr_posts_comment() {
  mode_pr_list=""            # no existing PR
  comment_exit="exit 0"      # comment succeeds
  setup_mocks "new"

  SCRIPT_OUTPUT=$(
    PATH="${MOCK_DIR}:${PATH}" \
    REPO="${TEST_REPO}" \
    ISSUE_NUMBER="${ISSUE_NUM}" \
    GITHUB_TOKEN="fake-token" \
    GH_TOKEN="fake-token" \
    bash "${CREATE_PR_SCRIPT}" 2>&1
  ) || true

  if grep -q "ISSUE_COMMENT_CALLED" "${CALLS_LOG}"; then
    pass "new PR: gh issue comment is called"
  else
    fail "new PR: gh issue comment was NOT called — output: ${SCRIPT_OUTPUT}"
  fi

  if echo "${SCRIPT_OUTPUT}" | grep -q "AI_AGILE_STATUS: complete"; then
    pass "new PR: script exits AI_AGILE_STATUS: complete"
  else
    fail "new PR: missing AI_AGILE_STATUS: complete — output: ${SCRIPT_OUTPUT}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Test 2 (idempotent re-run): PR already exists → no duplicate comment.
# ---------------------------------------------------------------------------
test_existing_pr_no_duplicate_comment() {
  mode_pr_list="${PR_NUM}"   # existing PR found
  comment_exit="exit 0"
  setup_mocks "existing"

  SCRIPT_OUTPUT=$(
    PATH="${MOCK_DIR}:${PATH}" \
    REPO="${TEST_REPO}" \
    ISSUE_NUMBER="${ISSUE_NUM}" \
    GITHUB_TOKEN="fake-token" \
    GH_TOKEN="fake-token" \
    bash "${CREATE_PR_SCRIPT}" 2>&1
  ) || true

  if grep -q "ISSUE_COMMENT_CALLED" "${CALLS_LOG}"; then
    fail "idempotent re-run: gh issue comment was called (duplicate)"
  else
    pass "idempotent re-run: gh issue comment is NOT called"
  fi

  if echo "${SCRIPT_OUTPUT}" | grep -q "AI_AGILE_STATUS: complete"; then
    pass "idempotent re-run: script exits AI_AGILE_STATUS: complete"
  else
    fail "idempotent re-run: missing AI_AGILE_STATUS: complete — output: ${SCRIPT_OUTPUT}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Test 3 (error path): gh issue comment fails → script exits non-zero.
# ---------------------------------------------------------------------------
test_comment_failure_exits_nonzero() {
  mode_pr_list=""            # no existing PR
  comment_exit="exit 1"      # comment fails
  setup_mocks "comment_fail"

  SCRIPT_EXIT=0
  PATH="${MOCK_DIR}:${PATH}" \
  REPO="${TEST_REPO}" \
  ISSUE_NUMBER="${ISSUE_NUM}" \
  GITHUB_TOKEN="fake-token" \
  GH_TOKEN="fake-token" \
  bash "${CREATE_PR_SCRIPT}" >/dev/null 2>&1 || SCRIPT_EXIT=$?

  if [[ "${SCRIPT_EXIT}" -ne 0 ]]; then
    pass "comment failure: script exits non-zero"
  else
    fail "comment failure: script did not exit non-zero"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_new_pr_posts_comment
test_existing_pr_no_duplicate_comment
test_comment_failure_exits_nonzero

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
