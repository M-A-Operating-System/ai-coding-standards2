#!/usr/bin/env bash
# Tests recover-unpushed-commits.sh against real git fixtures: an unpushed
# commit gets recovered before a branch reset would discard it, a clean
# branch is a no-op, a branch missing on origin is handled gracefully under
# `set -e` (see ADR-003's context for why this needs its own coverage), and
# a push that cannot succeed is reported rather than failing the script.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/recover-unpushed-commits.sh"

setup_repo() {
  WORK_DIR="$(mktemp -d)"
  ORIGIN="${WORK_DIR}/origin.git"
  WORK="${WORK_DIR}/work"
  git init -q --bare "${ORIGIN}"
  git clone -q "${ORIGIN}" "${WORK}"
  git -C "${WORK}" config user.email t@t
  git -C "${WORK}" config user.name t
  git -C "${WORK}" checkout -q -B issue-42
  echo a >"${WORK}/a.txt"
  git -C "${WORK}" add -A
  git -C "${WORK}" commit -qm init
  git -C "${WORK}" push -q origin issue-42
}

teardown_repo() {
  rm -rf -- "${WORK_DIR}"
}

test_unpushed_commit_is_recovered() {
  setup_repo
  echo b >"${WORK}/b.txt"
  git -C "${WORK}" add -A
  git -C "${WORK}" commit -qm "unpushed"
  local_head="$(git -C "${WORK}" rev-parse HEAD)"

  OUT="$(cd "${WORK}" && "${SCRIPT}" issue-42 2>&1)"
  RC=$?

  if [[ "${RC}" -eq 0 ]]; then
    pass "unpushed commit: exits 0"
  else
    fail "unpushed commit: expected exit 0, got ${RC} -- output: ${OUT}"
  fi
  remote_head="$(git -C "${ORIGIN}" rev-parse issue-42)"
  if [[ "${remote_head}" == "${local_head}" ]]; then
    pass "unpushed commit: origin now matches the local commit"
  else
    fail "unpushed commit: origin (${remote_head}) does not match local (${local_head})"
  fi
  if echo "${OUT}" | grep -q "recovered 1 unpushed commit(s)"; then
    pass "unpushed commit: reports recovery"
  else
    fail "unpushed commit: missing recovery message -- got: ${OUT}"
  fi

  teardown_repo
}

test_clean_branch_is_a_noop() {
  setup_repo
  before="$(git -C "${ORIGIN}" rev-parse issue-42)"

  OUT="$(cd "${WORK}" && "${SCRIPT}" issue-42 2>&1)"
  RC=$?

  if [[ "${RC}" -eq 0 ]]; then
    pass "clean branch: exits 0"
  else
    fail "clean branch: expected exit 0, got ${RC} -- output: ${OUT}"
  fi
  after="$(git -C "${ORIGIN}" rev-parse issue-42)"
  if [[ "${after}" == "${before}" ]]; then
    pass "clean branch: origin unchanged"
  else
    fail "clean branch: origin moved unexpectedly (${before} -> ${after})"
  fi
  if [[ -z "${OUT}" ]]; then
    pass "clean branch: no output"
  else
    fail "clean branch: expected no output, got: ${OUT}"
  fi

  teardown_repo
}

test_branch_missing_on_origin_exits_cleanly() {
  setup_repo

  set +e
  OUT="$(cd "${WORK}" && "${SCRIPT}" nonexistent-branch 2>&1)"
  RC=$?
  set -e

  if [[ "${RC}" -eq 0 ]]; then
    pass "branch missing on origin: exits 0 under set -e, not an abort"
  else
    fail "branch missing on origin: expected exit 0, got ${RC} -- output: ${OUT}"
  fi

  teardown_repo
}

test_push_failure_is_reported_not_fatal() {
  setup_repo
  echo b >"${WORK}/b.txt"
  git -C "${WORK}" add -A
  git -C "${WORK}" commit -qm "unpushed"
  # Point origin somewhere unreachable so the push fails.
  git -C "${WORK}" remote set-url origin "${WORK_DIR}/nonexistent.git"

  set +e
  OUT="$(cd "${WORK}" && "${SCRIPT}" issue-42 2>&1)"
  RC=$?
  set -e

  if [[ "${RC}" -eq 0 ]]; then
    pass "push failure: still exits 0 (best-effort, never fails the caller)"
  else
    fail "push failure: expected exit 0, got ${RC} -- output: ${OUT}"
  fi
  if echo "${OUT}" | grep -q "could not recover"; then
    pass "push failure: reports the failure"
  else
    fail "push failure: missing failure message -- got: ${OUT}"
  fi

  teardown_repo
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_unpushed_commit_is_recovered
test_clean_branch_is_a_noop
test_branch_missing_on_origin_exits_cleanly
test_push_failure_is_reported_not_fatal

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
