#!/usr/bin/env bash
# Tests that create-pr.sh's closing PR body also closes every sub-issue the
# sizer (00_ondemand/sizer, Step 4b) created for this issue.
#
# Context: a sub-issue's own code PR merges into the parent's shared
# integration branch (naming.base "issue-{parent_number}"), never into the
# repository's default branch -- so GitHub's "Closes #N" keyword on that PR
# never auto-closes it (the keyword only fires on a merge to the default
# branch). The PR this script opens for the parent/epic issue IS the one
# that merges to the default branch, so its body must also say "Closes #N"
# for every sub-issue, or they are left open forever (issue #734's #761/#762).
#
# AC1: when sub-issues (parent-issue:{N} label) exist, the PR body closes
#      each of them in addition to the issue itself.
# AC2: when no sub-issues exist, the PR body is unaffected (Closes #N only).
#
# Uses PATH-prepended mock binaries to intercept gh and git calls.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREATE_PR_SCRIPT="${REPO_ROOT}/scripts/create-pr.sh"

PR_NUM=70
ISSUE_NUM=34
TEST_REPO="owner/repo"

# ---------------------------------------------------------------------------
# setup_mocks — writes mock gh and git binaries.
#
# Caller sets before calling:
#   mock_sub_issues — space-separated sub-issue numbers the mock's
#                     labels=parent-issue:{N} lookup returns (may be empty).
#
# After the script runs, ${MOCK_DIR}/pr_creation_args.txt contains the full
# args passed to the gh POST /pulls call.
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
  *"issues?labels=parent-issue"*)
    # Already "--jq"-filtered: one sub-issue number per line, as the real
    # 'gh api ... --jq .[].number' call would print.
    for _n in ${mock_sub_issues}; do
      echo "\${_n}"
    done
    ;;
  *"api --method POST"*"/pulls"*)
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
    echo "An issue"
    ;;
  *"/issues/"*".body"*)
    printf ''
    ;;
  *"/issues/"*)
    echo "An issue"
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
# AC1: sub-issues exist -> each is closed alongside the parent.
# ---------------------------------------------------------------------------
test_pr_body_closes_every_sub_issue() {
  mock_sub_issues="761 762"
  setup_mocks

  run_script >/dev/null

  PR_ARGS=$(cat "${MOCK_DIR}/pr_creation_args.txt" 2>/dev/null || true)

  if echo "${PR_ARGS}" | grep -qF "Closes #${ISSUE_NUM}"; then
    pass "AC1: PR body still closes the parent issue"
  else
    fail "AC1: PR body missing Closes #${ISSUE_NUM} -- args: ${PR_ARGS}"
  fi

  if echo "${PR_ARGS}" | grep -qF "Closes #761"; then
    pass "AC1: PR body closes sub-issue #761"
  else
    fail "AC1: PR body missing Closes #761 -- args: ${PR_ARGS}"
  fi

  if echo "${PR_ARGS}" | grep -qF "Closes #762"; then
    pass "AC1: PR body closes sub-issue #762"
  else
    fail "AC1: PR body missing Closes #762 -- args: ${PR_ARGS}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# AC2: no sub-issues -> PR body is Closes #N only, as before.
# ---------------------------------------------------------------------------
test_pr_body_unchanged_without_sub_issues() {
  mock_sub_issues=""
  setup_mocks

  run_script >/dev/null

  PR_ARGS=$(cat "${MOCK_DIR}/pr_creation_args.txt" 2>/dev/null || true)

  if echo "${PR_ARGS}" | grep -qF "Closes #${ISSUE_NUM}"; then
    pass "AC2: PR body closes the issue"
  else
    fail "AC2: PR body missing Closes #${ISSUE_NUM} -- args: ${PR_ARGS}"
  fi

  # Count of "Closes #" occurrences must be exactly one -- no sub-issue noise.
  CLOSES_COUNT=$(echo "${PR_ARGS}" | grep -o "Closes #" | wc -l | tr -d ' ')
  if [[ "${CLOSES_COUNT}" -eq 1 ]]; then
    pass "AC2: PR body has exactly one Closes trailer"
  else
    fail "AC2: expected exactly one Closes trailer, found ${CLOSES_COUNT} -- args: ${PR_ARGS}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_pr_body_closes_every_sub_issue
test_pr_body_unchanged_without_sub_issues

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
