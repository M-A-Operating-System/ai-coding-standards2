#!/usr/bin/env bash
# create-pr.sh's handling of a declared base branch (naming.base, issue #609).
#
# Three scenarios:
#   1. No BASE_BRANCH declared -- unchanged behavior, PR opens against the
#      repository default branch.
#   2. BASE_BRANCH declared and it exists on origin -- PR opens against it.
#   3. BASE_BRANCH declared but missing from origin -- the script fails loudly
#      (exit non-zero, no PR created) rather than silently substituting the
#      default branch. A missing declared base is a lifecycle-ordering bug
#      (e.g. the parent epic's integration branch not yet created), and
#      swallowing it previously let every sub-issue PR land on main with no
#      accumulated-diff review ever happening on the epic itself (RV-001/
#      RV-002, issue #609).

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREATE_PR_SCRIPT="${REPO_ROOT}/scripts/create-pr.sh"

TEST_REPO="owner/repo"
ISSUE_NUM=99
PR_NUM=42

# ---------------------------------------------------------------------------
# setup_mocks -- mock gh and git on PATH, run from inside a real (empty) git
# repo so create-pr.sh's own `git rev-parse --abbrev-ref HEAD` resolves.
#
# Caller sets before calling:
#   base_branch_exists -- "true" or "false": what the mock `git ls-remote`
#                          reports for the declared BASE_BRANCH.
# ---------------------------------------------------------------------------
setup_mocks() {
  WORK_DIR="$(mktemp -d)"
  MOCK_DIR="${WORK_DIR}/bin"
  mkdir -p "${MOCK_DIR}"
  CALLS_LOG="${WORK_DIR}/calls.log"
  : >"${CALLS_LOG}"

  git init -q "${WORK_DIR}/repo"
  (cd "${WORK_DIR}/repo" \
    && git config user.email "test@example.com" \
    && git config user.name "Test" \
    && git commit -q --allow-empty -m "init")

  cat >"${MOCK_DIR}/git" <<GITEOF
#!/usr/bin/env bash
echo "git \$*" >> "${CALLS_LOG}"
case "\$1" in
  rev-parse) echo "main"; exit 0 ;;
  ls-remote)
    if [[ "\$*" == *"\${BASE_BRANCH:-__unset__}"* ]]; then
      [[ "${base_branch_exists:-false}" == "true" ]] && exit 0 || exit 1
    fi
    exit 1
    ;;
  config) exit 0 ;;
  *) exit 0 ;;
esac
GITEOF
  chmod +x "${MOCK_DIR}/git"

  cat >"${MOCK_DIR}/gh" <<GHEOF
#!/usr/bin/env bash
echo "gh \$*" >> "${CALLS_LOG}"
ARGS="\$*"
case "\$ARGS" in
  *"api --method POST"*"/pulls"*)
    echo "PR_CREATED" >> "${CALLS_LOG}"
    echo '{"number":${PR_NUM},"html_url":"https://github.com/${TEST_REPO}/pull/${PR_NUM}"}'
    ;;
  *"api --method POST"*"/comments"*) exit 0 ;;
  *"api /user"*) echo "bot" ;;
  *"/compare/"*) echo "1" ;;
  *"pulls?head="*) true ;;
  *"repos/${TEST_REPO}\"*--jq .default_branch"*) echo "main" ;;
  *".default_branch"*) echo "main" ;;
  *"/issues/"*".title"*) echo "Test issue" ;;
  *"/issues/"*".body"*) printf '' ;;
  *"/issues/"*) echo '{"full_name":"${TEST_REPO}"}' ;;
  *) echo '{}' ;;
esac
GHEOF
  chmod +x "${MOCK_DIR}/gh"
}

run_create_pr() {
  (
    cd "${WORK_DIR}/repo" && \
    PATH="${MOCK_DIR}:${PATH}" \
    REPO="${TEST_REPO}" ISSUE_NUMBER="${ISSUE_NUM}" BRANCH="issue-${ISSUE_NUM}" \
    PR_CLOSES_ISSUE=true GH_TOKEN="test-token" \
    BASE_BRANCH="${BASE_BRANCH:-}" \
    bash "${CREATE_PR_SCRIPT}" >"${WORK_DIR}/out.txt" 2>&1
  )
}

teardown() { rm -rf "${WORK_DIR}"; }

# ---------------------------------------------------------------------------
# 1. No BASE_BRANCH declared -- unchanged behavior.
# ---------------------------------------------------------------------------
unset BASE_BRANCH
base_branch_exists="false"
setup_mocks

rc=0
run_create_pr || rc=$?

if [[ $rc -eq 0 ]]; then
  pass "no declared base branch: create-pr.sh succeeds as before"
else
  fail "no declared base branch should not fail; got rc=${rc}: $(cat "${WORK_DIR}/out.txt")"
fi

if grep -q "PR_CREATED" "${CALLS_LOG}"; then
  pass "no declared base branch: a PR is created"
else
  fail "no declared base branch: a PR should be created"
fi

teardown

# ---------------------------------------------------------------------------
# 2. BASE_BRANCH declared and exists -- PR targets it.
# ---------------------------------------------------------------------------
export BASE_BRANCH="issue-609"
base_branch_exists="true"
setup_mocks

rc=0
run_create_pr || rc=$?

if [[ $rc -eq 0 ]]; then
  pass "declared base branch exists: create-pr.sh succeeds"
else
  fail "declared base branch exists: create-pr.sh should succeed; got rc=${rc}: $(cat "${WORK_DIR}/out.txt")"
fi

if grep -q "Using this flow's declared base branch: issue-609" "${WORK_DIR}/out.txt"; then
  pass "declared base branch exists: reported as the base in use"
else
  fail "declared base branch exists: should report it as the base in use"
fi

if grep -q "PR_CREATED" "${CALLS_LOG}"; then
  pass "declared base branch exists: a PR is created"
else
  fail "declared base branch exists: a PR should be created"
fi

teardown
unset BASE_BRANCH

# ---------------------------------------------------------------------------
# 3. BASE_BRANCH declared but missing -- fails loudly, no PR created.
# ---------------------------------------------------------------------------
export BASE_BRANCH="issue-609"
base_branch_exists="false"
setup_mocks

rc=0
run_create_pr || rc=$?

if [[ $rc -ne 0 ]]; then
  pass "declared base branch missing: create-pr.sh fails rather than substituting"
else
  fail "declared base branch missing: create-pr.sh should fail, not silently fall back"
fi

if grep -q "declared base branch 'issue-609' does not exist" "${WORK_DIR}/out.txt"; then
  pass "declared base branch missing: the failure names the missing branch"
else
  fail "declared base branch missing: the failure should name the missing branch"
fi

if grep -q "PR_CREATED" "${CALLS_LOG}"; then
  fail "declared base branch missing: no PR should be created"
else
  pass "declared base branch missing: no PR is created"
fi

teardown
unset BASE_BRANCH

echo
echo "create-pr.sh base branch: ${PASS} passed, ${FAIL} failed"
[[ $FAIL -eq 0 ]]
