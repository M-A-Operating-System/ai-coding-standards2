#!/usr/bin/env bash
# Tests new-branch-pr.sh: the /maos-new-branch-pr procedure, extracted from the
# command file for AS-3 (issue #407).
#
# The script is an adapter, not a second implementation: it resolves the flow's
# naming from pipeline.json and hands off to create-pr.sh, which already owns
# the branch/PR/title/label/comment behaviour and has its own tests. These
# tests cover the adapter's own job -- the resolution, and what it refuses.
#
# create-pr.sh is replaced by a stub on PATH-adjacent disk so nothing here
# reaches GitHub.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_REL=".github/scripts/new-branch-pr.sh"

# A checkout-shaped sandbox: the real orchestrator and pipeline.json, the real
# adapter, and a stub create-pr.sh that only records the env it was handed.
setup() {
  WORK_DIR="$(mktemp -d)"
  mkdir -p "${WORK_DIR}/.github/scripts" "${WORK_DIR}/pipeline"
  cp "${REPO_ROOT}/${SCRIPT_REL}" "${WORK_DIR}/.github/scripts/"
  cp "${REPO_ROOT}/pipeline/pipeline_orchestrator.py" "${WORK_DIR}/pipeline/"
  cp "${REPO_ROOT}/pipeline/pipeline.json" "${WORK_DIR}/pipeline/"
  cp "${REPO_ROOT}/pipeline/statuses.json" "${WORK_DIR}/pipeline/"
  cp -r "${REPO_ROOT}/pipeline/schemas" "${WORK_DIR}/pipeline/" 2>/dev/null || true
  cat >"${WORK_DIR}/.github/scripts/create-pr.sh" <<'STUB'
#!/usr/bin/env bash
echo "create-pr REPO=${REPO} ISSUE_NUMBER=${ISSUE_NUMBER} AI_AGILE_BRANCH=${AI_AGILE_BRANCH} PR_CLOSES_ISSUE=${PR_CLOSES_ISSUE}"
STUB
  chmod +x "${WORK_DIR}/.github/scripts/create-pr.sh"
}

teardown() { rm -rf "${WORK_DIR}"; }

run_it() {
  ( cd "${WORK_DIR}" && bash "${WORK_DIR}/${SCRIPT_REL}" "$@" \
      >"${WORK_DIR}/out.txt" 2>&1 )
}

# ---------------------------------------------------------------------------
# It resolves the branch from the flow's naming, not from a pattern of its own
# ---------------------------------------------------------------------------
setup
rc=0; REPO="owner/repo" run_it 42 || rc=$?
if [ "${rc}" -eq 0 ] && grep -q "AI_AGILE_BRANCH=issue-42" "${WORK_DIR}/out.txt"; then
  pass "resolves the branch from pipeline.json's flow naming"
else
  fail "expected AI_AGILE_BRANCH=issue-42; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi
if grep -q "PR_CLOSES_ISSUE=true" "${WORK_DIR}/out.txt"; then
  pass "passes the flow's closes_issue through"
else
  fail "expected PR_CLOSES_ISSUE=true"
  cat "${WORK_DIR}/out.txt"
fi

# ---------------------------------------------------------------------------
# It hands off rather than reimplementing
# ---------------------------------------------------------------------------
if grep -q "^create-pr " "${WORK_DIR}/out.txt"; then
  pass "delegates to create-pr.sh -- the same script the pipeline step runs"
else
  fail "expected create-pr.sh to be executed"
  cat "${WORK_DIR}/out.txt"
fi
if grep -q "ISSUE_NUMBER=42" "${WORK_DIR}/out.txt"; then
  pass "passes the issue number through"
else
  fail "expected ISSUE_NUMBER=42"
fi
teardown

# ---------------------------------------------------------------------------
# It refuses bad input rather than guessing
# ---------------------------------------------------------------------------
setup
rc=0; REPO="owner/repo" run_it not-a-number || rc=$?
if [ "${rc}" -ne 0 ] && grep -q "not an integer" "${WORK_DIR}/out.txt"; then
  pass "a non-numeric issue number is refused"
else
  fail "expected a refusal for a non-numeric issue number; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi

rc=0; ( cd "${WORK_DIR}" && REPO="" bash "${WORK_DIR}/${SCRIPT_REL}" 42 \
        >"${WORK_DIR}/out.txt" 2>&1 ) || rc=$?
if [ "${rc}" -ne 0 ] && grep -q "REPO" "${WORK_DIR}/out.txt"; then
  pass "a missing REPO is refused"
else
  fail "expected a refusal naming REPO; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi

rc=0; ( cd "${WORK_DIR}" && bash "${WORK_DIR}/${SCRIPT_REL}" \
        >"${WORK_DIR}/out.txt" 2>&1 ) || rc=$?
if [ "${rc}" -ne 0 ] && grep -q "usage" "${WORK_DIR}/out.txt"; then
  pass "a missing issue number is refused"
else
  fail "expected a usage refusal; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi

# ---------------------------------------------------------------------------
# A step that names no branch is a named stop, not a guess
# ---------------------------------------------------------------------------
rc=0; REPO="owner/repo" AI_AGILE_STEP="no/such-step" run_it 42 || rc=$?
if [ "${rc}" -ne 0 ] && grep -q "not declared in pipeline.json" "${WORK_DIR}/out.txt"; then
  pass "an unknown step stops with a named reason"
else
  fail "expected a stop naming the unknown step; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

echo
echo "new-branch-pr.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
