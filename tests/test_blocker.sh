#!/usr/bin/env bash
# Tests blocker.sh: reciprocates blockedby:/blocks: (issue #405).
#
# Uses PATH-prepended mock binaries to intercept gh calls.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLOCKER_SCRIPT="${REPO_ROOT}/.github/scripts/blocker.sh"

TEST_REPO="owner/repo"
ISSUE_NUM=7
TARGET_NUM=12

# ---------------------------------------------------------------------------
# Helper: create a temp mock dir; writes a mock gh into it.
#
# Caller sets these before calling setup_mocks:
#   blockedby_label      — the blockedby:{N} label to report on the issue,
#                           or "" for none, or a malformed value to test that path
#   existing_labels      — labels already known to the repo (for label-create
#                           idempotency); "" means none exist yet
# ---------------------------------------------------------------------------
setup_mocks() {
  MOCK_DIR="$(mktemp -d)"
  CALLS_LOG="${MOCK_DIR}/calls.log"
  touch "${CALLS_LOG}"

  cat >"${MOCK_DIR}/gh" <<GHEOF
#!/usr/bin/env bash
echo "gh \$*" >> "${CALLS_LOG}"
ARGS="\$*"
case "\$ARGS" in
  *"issues/${ISSUE_NUM}"*"--jq"*)
    # blockedby: label lookup on the requesting issue.
    if [ -n "${blockedby_label}" ]; then
      echo "${blockedby_label}"
    fi
    ;;
  *"label list"*)
    if [ -n "${existing_labels}" ]; then
      echo "${existing_labels}"
    fi
    ;;
  *"label create"*)
    echo "LABEL_CREATE_CALLED" >> "${CALLS_LOG}"
    ;;
  *"api --method POST"*"issues/${TARGET_NUM}/labels"*)
    echo "RECIPROCAL_LABEL_APPLIED" >> "${CALLS_LOG}"
    ;;
  *)
    ;;
esac
GHEOF
  chmod +x "${MOCK_DIR}/gh"
}

teardown_mock_dir() {
  rm -rf "${MOCK_DIR:-}"
}

run_blocker() {
  PATH="${MOCK_DIR}:${PATH}" \
  REPO="${TEST_REPO}" \
  ISSUE_NUMBER="${ISSUE_NUM}" \
  bash "${BLOCKER_SCRIPT}" 2>&1
}

# ---------------------------------------------------------------------------
# Test 1 (happy path): blockedby:{N} present -> reciprocates blocks:{this}.
# ---------------------------------------------------------------------------
test_reciprocates_blocks_label_onto_target() {
  blockedby_label="blockedby:${TARGET_NUM}"
  existing_labels=""
  setup_mocks

  OUTPUT=$(run_blocker) || true

  if grep -q "RECIPROCAL_LABEL_APPLIED" "${CALLS_LOG}"; then
    pass "happy path: blocks:${ISSUE_NUM} applied to issue #${TARGET_NUM}"
  else
    fail "happy path: reciprocal label was NOT applied — output: ${OUTPUT}"
  fi

  if grep -q "LABEL_CREATE_CALLED" "${CALLS_LOG}"; then
    pass "happy path: missing blocks: label is created first"
  else
    fail "happy path: expected a label-create call when the label doesn't exist yet"
  fi

  if echo "${OUTPUT}" | grep -q "AI_AGILE_STATUS: complete"; then
    pass "happy path: script exits AI_AGILE_STATUS: complete"
  else
    fail "happy path: missing AI_AGILE_STATUS: complete — output: ${OUTPUT}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Test 2: blocks:{N} label already exists on the repo -> no duplicate create.
# ---------------------------------------------------------------------------
test_skips_label_create_when_already_present() {
  blockedby_label="blockedby:${TARGET_NUM}"
  existing_labels="blocks:${ISSUE_NUM}"
  setup_mocks

  run_blocker >/dev/null 2>&1 || true

  if grep -q "LABEL_CREATE_CALLED" "${CALLS_LOG}"; then
    fail "existing label: gh label create was called when the label already exists"
  else
    pass "existing label: gh label create is NOT called"
  fi

  if grep -q "RECIPROCAL_LABEL_APPLIED" "${CALLS_LOG}"; then
    pass "existing label: reciprocal label is still applied to the issue"
  else
    fail "existing label: reciprocal label was NOT applied"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Test 3: no blockedby: label on the requesting issue -> blocked, no write.
# ---------------------------------------------------------------------------
test_no_blockedby_label_reports_blocked_without_writing() {
  blockedby_label=""
  existing_labels=""
  setup_mocks

  SCRIPT_EXIT=0
  OUTPUT=$(run_blocker) || SCRIPT_EXIT=$?

  if grep -q "RECIPROCAL_LABEL_APPLIED" "${CALLS_LOG}"; then
    fail "no blockedby: a label was written despite nothing to reciprocate"
  else
    pass "no blockedby: no label is written"
  fi

  if echo "${OUTPUT}" | grep -q 'AI_AGILE_STATUS: blocked'; then
    pass "no blockedby: script reports blocked, not a silent no-op"
  else
    fail "no blockedby: missing AI_AGILE_STATUS: blocked — output: ${OUTPUT}"
  fi

  if [[ "${SCRIPT_EXIT}" -eq 0 ]]; then
    pass "no blockedby: script still exits 0 (a benign human mistake, not a crash)"
  else
    fail "no blockedby: script exited non-zero (${SCRIPT_EXIT})"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Test 4: malformed blockedby: label (non-numeric target) -> blocked, no write.
# ---------------------------------------------------------------------------
test_malformed_blockedby_label_reports_blocked_without_writing() {
  blockedby_label="blockedby:abc"
  existing_labels=""
  setup_mocks

  OUTPUT=$(run_blocker) || true

  if grep -q "RECIPROCAL_LABEL_APPLIED" "${CALLS_LOG}"; then
    fail "malformed: a label was written from a non-numeric blockedby: value"
  else
    pass "malformed: no label is written"
  fi

  if echo "${OUTPUT}" | grep -q 'AI_AGILE_STATUS: blocked'; then
    pass "malformed: script reports blocked"
  else
    fail "malformed: missing AI_AGILE_STATUS: blocked — output: ${OUTPUT}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_reciprocates_blocks_label_onto_target
test_skips_label_create_when_already_present
test_no_blockedby_label_reports_blocked_without_writing
test_malformed_blockedby_label_reports_blocked_without_writing

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
