#!/usr/bin/env bash
# Tests drive-item.sh: the /maos-run drive loop, extracted from the command
# file for AS-3 (issue #407).
#
# Uses PATH-prepended mock binaries to intercept gh and python3, so the loop's
# own behaviour -- when it ticks again, when it stops, and what it refuses to
# do at a gate -- is exercised without a repo, a token, or an orchestrator.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIVE_SCRIPT="${REPO_ROOT}/.github/scripts/drive-item.sh"

TEST_REPO="owner/repo"
ISSUE_NUM=407

# ---------------------------------------------------------------------------
# Helper: a workspace with a fake orchestrator on the standalone path, plus
# mock gh/python3 on PATH.
#
# Caller sets these before calling setup_mocks:
#   label_sequence  — one line per tick, each a comma-separated label set the
#                     issue carries AFTER that tick. The mock gh serves the
#                     next line each time the label list is read past the
#                     first read of a tick.
#   orch_exit       — exit code the fake orchestrator returns (default 0)
# ---------------------------------------------------------------------------
setup_mocks() {
  WORK_DIR="$(mktemp -d)"
  MOCK_DIR="${WORK_DIR}/bin"
  mkdir -p "${MOCK_DIR}" "${WORK_DIR}/pipeline"
  CALLS_LOG="${WORK_DIR}/calls.log"
  : >"${CALLS_LOG}"

  # The orchestrator the script must find and invoke.
  echo "# fake orchestrator" >"${WORK_DIR}/pipeline/pipeline_orchestrator.py"

  printf '%s\n' "${label_sequence}" >"${WORK_DIR}/labels.txt"
  echo 0 >"${WORK_DIR}/reads"

  cat >"${MOCK_DIR}/gh" <<GHEOF
#!/usr/bin/env bash
echo "gh \$*" >> "${CALLS_LOG}"
# Each label read advances one line of the sequence, so the "before" read of
# tick N and the "after" read of tick N-1 see the same state.
n=\$(cat "${WORK_DIR}/reads")
echo \$(( n + 1 )) > "${WORK_DIR}/reads"
sed -n "\$(( n + 1 ))p" "${WORK_DIR}/labels.txt" | tr ',' '\n' | grep -v '^\$' || true
GHEOF
  chmod +x "${MOCK_DIR}/gh"

  cat >"${MOCK_DIR}/python3" <<PYEOF
#!/usr/bin/env bash
echo "python3 \$*" >> "${CALLS_LOG}"
exit ${orch_exit:-0}
PYEOF
  chmod +x "${MOCK_DIR}/python3"
}

run_drive() {
  ( cd "${WORK_DIR}" && PATH="${MOCK_DIR}:${PATH}" REPO="${TEST_REPO}" \
      bash "${DRIVE_SCRIPT}" "$@" >"${WORK_DIR}/out.txt" 2>&1 )
}

teardown() { rm -rf "${WORK_DIR}"; }

# ---------------------------------------------------------------------------
# It keeps ticking while the labels keep changing
# ---------------------------------------------------------------------------
label_sequence="a:complete
a:complete,b:complete
a:complete,b:complete,c:complete
a:complete,b:complete,c:complete"
orch_exit=0
setup_mocks
rc=0; run_drive "${ISSUE_NUM}" || rc=$?
ticks=$(grep -c '^python3 ' "${CALLS_LOG}" || true)
if [ "${rc}" -eq 0 ] && [ "${ticks}" -ge 2 ]; then
  pass "ticks again while a tick keeps changing the labels (${ticks} ticks)"
else
  fail "expected repeated ticks then a clean stop; rc=${rc} ticks=${ticks}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

# ---------------------------------------------------------------------------
# It stops when a tick advances nothing
# ---------------------------------------------------------------------------
label_sequence="a:complete
a:complete"
orch_exit=0
setup_mocks
rc=0; run_drive "${ISSUE_NUM}" || rc=$?
if [ "${rc}" -eq 0 ] && grep -q "advanced nothing" "${WORK_DIR}/out.txt"; then
  pass "stops, exit 0, when a tick advances nothing"
else
  fail "expected exit 0 and 'advanced nothing'; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

# ---------------------------------------------------------------------------
# It halts at a gate and does NOT cross it (MI-7)
# ---------------------------------------------------------------------------
for halt in "01_product_docs/prd-writer:review" "03_execute/coder:blocked" "03_execute/coder:failed"; do
  label_sequence="a:complete
${halt}"
  orch_exit=0
  setup_mocks
  rc=0; run_drive "${ISSUE_NUM}" || rc=$?
  if [ "${rc}" -eq 2 ] && grep -q "halted" "${WORK_DIR}/out.txt"; then
    pass "halts with exit 2 on ${halt}"
  else
    fail "expected exit 2 on ${halt}; rc=${rc}"
    cat "${WORK_DIR}/out.txt"
  fi
  # Whatever it did, it must never have written a label itself.
  if grep -qE 'gh (issue edit|api --method POST)' "${CALLS_LOG}"; then
    fail "drive-item.sh wrote a label at ${halt} -- MI-7 forbids it"
  else
    pass "wrote no label at ${halt}"
  fi
  teardown
done

# ---------------------------------------------------------------------------
# A failing tick stops the loop rather than ticking on
# ---------------------------------------------------------------------------
label_sequence="a:complete
a:complete,b:complete"
orch_exit=1
setup_mocks
rc=0; run_drive "${ISSUE_NUM}" || rc=$?
ticks=$(grep -c '^python3 ' "${CALLS_LOG}" || true)
if [ "${rc}" -eq 1 ] && [ "${ticks}" -eq 1 ]; then
  pass "a non-zero orchestrator exit stops the loop (STD-ARCH-014)"
else
  fail "expected exit 1 after one tick; rc=${rc} ticks=${ticks}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

# ---------------------------------------------------------------------------
# The tick budget bounds the loop
# ---------------------------------------------------------------------------
label_sequence="a:1
a:2
a:3
a:4
a:5
a:6"
orch_exit=0
setup_mocks
rc=0
( cd "${WORK_DIR}" && PATH="${MOCK_DIR}:${PATH}" REPO="${TEST_REPO}" AI_AGILE_MAX_TICKS=2 \
    bash "${DRIVE_SCRIPT}" "${ISSUE_NUM}" >"${WORK_DIR}/out.txt" 2>&1 ) || rc=$?
ticks=$(grep -c '^python3 ' "${CALLS_LOG}" || true)
if [ "${rc}" -eq 1 ] && [ "${ticks}" -eq 2 ]; then
  pass "AI_AGILE_MAX_TICKS bounds the loop"
else
  fail "expected exit 1 after 2 ticks; rc=${rc} ticks=${ticks}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

# ---------------------------------------------------------------------------
# Prerequisites are named, not worked around
# ---------------------------------------------------------------------------
label_sequence="a:complete"
orch_exit=0
setup_mocks
rm "${WORK_DIR}/pipeline/pipeline_orchestrator.py"
rc=0; run_drive "${ISSUE_NUM}" || rc=$?
if [ "${rc}" -eq 1 ] && grep -q "no orchestrator found" "${WORK_DIR}/out.txt"; then
  pass "a missing orchestrator is a named stop, not a silent no-op"
else
  fail "expected exit 1 naming the missing orchestrator; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

setup_mocks
rc=0
( cd "${WORK_DIR}" && PATH="${MOCK_DIR}:${PATH}" REPO="" \
    bash "${DRIVE_SCRIPT}" "${ISSUE_NUM}" >"${WORK_DIR}/out.txt" 2>&1 ) || rc=$?
if [ "${rc}" -ne 0 ] && grep -q "REPO" "${WORK_DIR}/out.txt"; then
  pass "a missing REPO is refused"
else
  fail "expected a refusal naming REPO; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

echo
echo "drive-item.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
