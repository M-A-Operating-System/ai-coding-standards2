#!/usr/bin/env bash
# Tests that create-pr.sh posts a PR link comment on the issue after opening
# a new draft PR, does NOT post a duplicate when one already exists, and
# retries a failed comment on subsequent runs even when the PR already exists.
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
#
# Caller sets these before calling setup_mocks:
#   mode_pr_list        — value returned by mock "gh pr list"
#                         (empty = no existing PR; integer = PR exists)
#   mock_comments_count — integer returned by "gh issue view --json comments"
#                         0 = comment not yet posted; 1 = already posted
#   comment_exit        — "exit 0" (success) or "exit 1" (failure)
#
# NOTE: The mock returns mode_pr_list directly rather than JSON, bypassing the
# jq filter (-q '.[0].number // empty') that the real gh CLI applies internally.
# The downstream check ([[ -n "${EXISTING_PR}" ]]) works with a raw integer so
# tests pass, but a breakage in the JSON/jq path would go undetected here.
# JSON/jq correctness is covered by integration tests against the real gh CLI.
# ---------------------------------------------------------------------------
setup_mocks() {
  MOCK_DIR="$(mktemp -d)"
  CALLS_LOG="${MOCK_DIR}/calls.log"
  touch "${CALLS_LOG}"

  # ---- git mock -----------------------------------------------------------
  cat >"${MOCK_DIR}/git" <<GITEOF
#!/usr/bin/env bash
echo "git \$*" >> "${CALLS_LOG}"
case "\$1" in
  ls-remote) exit 1 ;;
  *)         exit 0 ;;
esac
GITEOF
  chmod +x "${MOCK_DIR}/git"

  # ---- gh mock ------------------------------------------------------------
  cat >"${MOCK_DIR}/gh" <<GHEOF
#!/usr/bin/env bash
echo "gh \$*" >> "${CALLS_LOG}"
ARGS="\$*"
case "\$ARGS" in
  *"api --method POST"*"/comments"*)
    # Comment write (converted from 'gh issue comment' to
    # 'gh api --method POST .../comments -f body=...').
    echo "ISSUE_COMMENT_CALLED" >> "${CALLS_LOG}"
    ${comment_exit}
    ;;
  *"api --method"*)
    # PR creation (POST /repos/.../pulls) and label POST (link-pr-to-issue)
    echo '{"number":${PR_NUM},"html_url":"https://github.com/${TEST_REPO}/pull/${PR_NUM}"}'
    ;;
  *"api /user"*)
    echo "bot"
    ;;
  *"/compare/"*)
    echo "1"
    ;;
  *"/comments"*)
    # Idempotency check: the script streams comment objects
    # (gh api --paginate --jq '.[]') and counts matches with an external jq -s.
    # Emit mock_comments_count objects carrying the create-pr marker so the
    # slurped count comes out right (0 objects -> length 0).
    _n=${mock_comments_count}; _c=0
    while [ "\$_c" -lt "\$_n" ]; do
      echo '{"body":"ai-agile/announcement/v1 by 01_product_docs/create-pr"}'
      _c=\$((_c + 1))
    done
    ;;
  *"/pulls"*)
    # PR existence lookup (converted from 'gh pr list' to 'gh api .../pulls?head=')
    echo "${mode_pr_list}"
    ;;
  *"/issues/"*)
    # Issue title lookup (converted from 'gh issue view --json title')
    echo "Test Issue"
    ;;
  *)
    # default branch (gh api repos/owner/repo), repo preflight, labels, etc.
    echo "main"
    ;;
esac
GHEOF
  chmod +x "${MOCK_DIR}/gh"
}

teardown_mock_dir() {
  rm -rf "${MOCK_DIR:-}"
}

# ---------------------------------------------------------------------------
# Test 1 (happy path): new PR creation → comment is posted.
# ---------------------------------------------------------------------------
test_new_pr_posts_comment() {
  mode_pr_list=""
  mock_comments_count="0"
  comment_exit="exit 0"
  setup_mocks

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
# Test 2 (no duplicate): PR exists and comment already posted → skipped.
# ---------------------------------------------------------------------------
test_existing_pr_comment_already_posted_no_duplicate() {
  mode_pr_list="${PR_NUM}"
  mock_comments_count="1"    # comment already exists
  comment_exit="exit 0"
  setup_mocks

  SCRIPT_OUTPUT=$(
    PATH="${MOCK_DIR}:${PATH}" \
    REPO="${TEST_REPO}" \
    ISSUE_NUMBER="${ISSUE_NUM}" \
    GITHUB_TOKEN="fake-token" \
    GH_TOKEN="fake-token" \
    bash "${CREATE_PR_SCRIPT}" 2>&1
  ) || true

  if grep -q "ISSUE_COMMENT_CALLED" "${CALLS_LOG}"; then
    fail "no duplicate: gh issue comment was called when comment already posted"
  else
    pass "no duplicate: gh issue comment is NOT called"
  fi

  if echo "${SCRIPT_OUTPUT}" | grep -q "AI_AGILE_STATUS: complete"; then
    pass "no duplicate: script exits AI_AGILE_STATUS: complete"
  else
    fail "no duplicate: missing AI_AGILE_STATUS: complete — output: ${SCRIPT_OUTPUT}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Test 3 (error path): comment post fails → script exits non-zero.
# ---------------------------------------------------------------------------
test_comment_failure_exits_nonzero() {
  mode_pr_list=""
  mock_comments_count="0"
  comment_exit="exit 1"
  setup_mocks

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
# Test 4 (retry after failure): PR exists but comment was never posted.
# Simulates a prior run where PR creation succeeded but gh issue comment
# failed — the script must post the comment on re-run.
# ---------------------------------------------------------------------------
test_retry_posts_comment_when_pr_exists_but_not_commented() {
  mode_pr_list="${PR_NUM}"   # PR already exists from failed prior run
  mock_comments_count="0"    # comment was never posted
  comment_exit="exit 0"
  setup_mocks

  SCRIPT_OUTPUT=$(
    PATH="${MOCK_DIR}:${PATH}" \
    REPO="${TEST_REPO}" \
    ISSUE_NUMBER="${ISSUE_NUM}" \
    GITHUB_TOKEN="fake-token" \
    GH_TOKEN="fake-token" \
    bash "${CREATE_PR_SCRIPT}" 2>&1
  ) || true

  if grep -q "ISSUE_COMMENT_CALLED" "${CALLS_LOG}"; then
    pass "retry: gh issue comment IS called when PR exists but no comment posted"
  else
    fail "retry: gh issue comment was NOT called — output: ${SCRIPT_OUTPUT}"
  fi

  if echo "${SCRIPT_OUTPUT}" | grep -q "AI_AGILE_STATUS: complete"; then
    pass "retry: script exits AI_AGILE_STATUS: complete"
  else
    fail "retry: missing AI_AGILE_STATUS: complete — output: ${SCRIPT_OUTPUT}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_new_pr_posts_comment
test_existing_pr_comment_already_posted_no_duplicate
test_comment_failure_exits_nonzero
test_retry_posts_comment_when_pr_exists_but_not_commented

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
