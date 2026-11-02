#!/usr/bin/env bash
# Behavioral tests for drive-item.sh's epic-driving mode -- issue #657.
#
# Traces to
# docs/features/maos-run-epic-mode-detection-child-discovery-and-per-child-driving-loop.md:
#   Scenario: maos-run drives each child of an epic issue in sub-issue order (R1)
#   Scenario: maos-run on a non-epic issue follows the existing single-issue path (R2)
#   Scenario: epic-driving loop stops at the first child that halts for a human gate (R3)
#
# Like test_drive_item.sh, this drives the real script via PATH-prepended mock
# gh/python3 binaries rather than asserting on source text, so a change that
# breaks the actual epic-driving behavior fails here even if the source still
# contains the right-looking strings.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIVE_SCRIPT="${REPO_ROOT}/scripts/drive-item.sh"

TEST_REPO="owner/repo"

# ---------------------------------------------------------------------------
# Helper: a workspace with mock gh/python3 on PATH, able to serve a different
# label-read sequence per issue number (so a parent epic and its children can
# each have their own script), plus a canned sub_issues response.
#
# Caller sets, before calling setup_epic_mocks:
#   labels_<N>      — one line per tick, comma-separated label set issue N
#                     carries AFTER that tick (same semantics as
#                     test_drive_item.sh's label_sequence, just one per issue).
#   sub_issues_list — space-separated child issue numbers the epic's
#                     sub_issues endpoint returns (empty string for none).
# ---------------------------------------------------------------------------
setup_epic_mocks() {
  WORK_DIR="$(mktemp -d)"
  MOCK_DIR="${WORK_DIR}/bin"
  mkdir -p "${MOCK_DIR}" "${WORK_DIR}/pipeline" "${WORK_DIR}/state"
  CALLS_LOG="${WORK_DIR}/calls.log"
  : >"${CALLS_LOG}"

  echo "# fake orchestrator" >"${WORK_DIR}/pipeline/pipeline_orchestrator.py"
  printf '%s' "${sub_issues_list:-}" >"${WORK_DIR}/state/sub_issues.txt"

  cat >"${MOCK_DIR}/gh" <<'GHEOF'
#!/usr/bin/env bash
WORK_DIR="__WORK_DIR__"
echo "gh $*" >> "${WORK_DIR}/calls.log"
args="$*"

if [[ "$args" == *"/sub_issues"* ]]; then
  if [[ -f "${WORK_DIR}/state/sub_issues_fail" ]]; then
    echo "gh: HTTP 502 (simulated API failure)" >&2
    exit 1
  fi
  tr ' ' '\n' <"${WORK_DIR}/state/sub_issues.txt" | grep -v '^$' || true
  exit 0
fi

num=$(echo "$args" | grep -oE '/issues/[0-9]+' | head -1 | grep -oE '[0-9]+')

# A bare /issues/<N> lookup (no /labels, no /sub_issues) is the child's open/
# closed state check. Defaults to "open" unless a per-issue state file says
# otherwise, and never consumes a label-sequence read (that would shift the
# tick-loop's own label reads by one, the same class of bug this epic-mode
# code was fixed for).
if [[ "$args" != *"/labels"* ]]; then
  state_file="${WORK_DIR}/state/state_${num}.txt"
  if [[ -f "$state_file" ]]; then
    cat "$state_file"
  else
    echo "open"
  fi
  exit 0
fi
seq_file="${WORK_DIR}/state/labels_${num}.txt"
reads_file="${WORK_DIR}/state/reads_${num}"
[[ -f "$seq_file" ]] || exit 0
[[ -f "$reads_file" ]] || echo 0 >"$reads_file"
n=$(cat "$reads_file")
echo $(( n + 1 )) >"$reads_file"
sed -n "$(( n + 1 ))p" "$seq_file" | tr ',' '\n' | grep -v '^$' || true
GHEOF
  sed -i "s#__WORK_DIR__#${WORK_DIR}#" "${MOCK_DIR}/gh"
  chmod +x "${MOCK_DIR}/gh"

  cat >"${MOCK_DIR}/python3" <<PYEOF
#!/usr/bin/env bash
echo "python3 \$*" >> "${CALLS_LOG}"
exit 0
PYEOF
  chmod +x "${MOCK_DIR}/python3"
}

set_issue_labels() {
  local num="$1" sequence="$2"
  printf '%s\n' "${sequence}" >"${WORK_DIR}/state/labels_${num}.txt"
}

set_issue_state() {
  local num="$1" state="$2"
  printf '%s\n' "${state}" >"${WORK_DIR}/state/state_${num}.txt"
}

fail_sub_issues_lookup() {
  : >"${WORK_DIR}/state/sub_issues_fail"
}

run_drive() {
  ( cd "${WORK_DIR}" && PATH="${MOCK_DIR}:${PATH}" REPO="${TEST_REPO}" \
      bash "${DRIVE_SCRIPT}" "$@" >"${WORK_DIR}/out.txt" 2>&1 )
}

teardown() { rm -rf "${WORK_DIR}"; }

# ---------------------------------------------------------------------------
# R1: epic + blocked + non-empty sub-issue list drives each child, in order,
# through its own tick loop.
# ---------------------------------------------------------------------------
sub_issues_list="601 602"
setup_epic_mocks
set_issue_labels 600 "epic,blocked"
# Each child settles ("advanced nothing") on its own first tick.
set_issue_labels 601 "child601:complete
child601:complete"
set_issue_labels 602 "child602:complete
child602:complete"

rc=0
run_drive 600 || rc=$?

if [[ $rc -eq 0 ]]; then
  pass "epic drive on #600 exits 0 when every child settles"
else
  fail "epic drive on #600 should exit 0 when every child settles; got rc=${rc}"
fi

if grep -q "child #601 of epic #600" "${WORK_DIR}/out.txt" && \
   grep -q "child #602 of epic #600" "${WORK_DIR}/out.txt"; then
  pass "epic drive reports driving both children"
else
  fail "epic drive should report driving both children"
fi

# Sub-issue order is preserved: #601 is driven (its labels endpoint is hit)
# strictly before #602's.
first_601=$(grep -n "/issues/601/labels" "${CALLS_LOG}" | head -1 | cut -d: -f1)
first_602=$(grep -n "/issues/602/labels" "${CALLS_LOG}" | head -1 | cut -d: -f1)
if [[ -n "$first_601" && -n "$first_602" && "$first_601" -lt "$first_602" ]]; then
  pass "children are driven in sub-issue order (601 before 602)"
else
  fail "children should be driven in sub-issue order (601 before 602)"
fi

if grep -q "all children of epic #600 completed" "${WORK_DIR}/out.txt"; then
  pass "epic drive reports completion once every child settles"
else
  fail "epic drive should report completion once every child settles"
fi

teardown

# ---------------------------------------------------------------------------
# R2a: epic label without blocked falls through to the single-issue path --
# the sub_issues endpoint is never even consulted.
# ---------------------------------------------------------------------------
sub_issues_list="601"
setup_epic_mocks
set_issue_labels 600 "epic
epic"

run_drive 600 || true

if grep -q "/sub_issues" "${CALLS_LOG}"; then
  fail "epic label alone (no blocked) must not trigger sub-issue discovery"
else
  pass "epic label alone (no blocked) does not trigger sub-issue discovery"
fi

if grep -q "drive-item: tick 1 on #600" "${WORK_DIR}/out.txt"; then
  pass "epic label alone (no blocked) falls through to the single-issue tick loop"
else
  fail "epic label alone (no blocked) should fall through to the single-issue tick loop"
fi

teardown

# ---------------------------------------------------------------------------
# R2b: epic + blocked but an empty sub-issue list also falls through to the
# single-issue path.
# ---------------------------------------------------------------------------
sub_issues_list=""
setup_epic_mocks
set_issue_labels 600 "epic,blocked
epic,blocked"

run_drive 600 || true

if grep -q "drive-item: tick 1 on #600" "${WORK_DIR}/out.txt"; then
  pass "epic+blocked with an empty sub-issue list falls through to the single-issue tick loop"
else
  fail "epic+blocked with an empty sub-issue list should fall through to the single-issue tick loop"
fi

teardown

# ---------------------------------------------------------------------------
# R2c: a failed sub_issues API call warns and falls through to the
# single-issue path, rather than silently behaving as "no children".
# ---------------------------------------------------------------------------
sub_issues_list="601"
setup_epic_mocks
fail_sub_issues_lookup
set_issue_labels 600 "epic,blocked
epic,blocked"

run_drive 600 || true

if grep -q "WARNING: could not fetch sub-issues" "${WORK_DIR}/out.txt"; then
  pass "a failed sub_issues lookup is reported as a warning, not silently swallowed"
else
  fail "a failed sub_issues lookup should be reported as a warning"
fi

if grep -q "drive-item: tick 1 on #600" "${WORK_DIR}/out.txt"; then
  pass "a failed sub_issues lookup falls through to the single-issue tick loop"
else
  fail "a failed sub_issues lookup should fall through to the single-issue tick loop"
fi

teardown

# ---------------------------------------------------------------------------
# R3: the first child that halts for a human decision stops the whole epic
# drive -- the next child in sub-issue order is never touched.
# ---------------------------------------------------------------------------
sub_issues_list="601 602"
setup_epic_mocks
set_issue_labels 600 "epic,blocked"
# #601 halts on its very first tick.
set_issue_labels 601 "child601:review
child601:review"

rc=0
run_drive 600 || rc=$?

if [[ $rc -eq 2 ]]; then
  pass "epic drive propagates the halting child's exit code (2)"
else
  fail "epic drive should propagate the halting child's exit code (2); got rc=${rc}"
fi

if grep -q "child #601 halted" "${WORK_DIR}/out.txt" && \
   grep -q "stopping epic drive" "${WORK_DIR}/out.txt"; then
  pass "epic drive reports which child halted and that it is stopping"
else
  fail "epic drive should report which child halted and that it is stopping"
fi

if grep -q "/issues/602/labels" "${CALLS_LOG}"; then
  fail "epic drive must not touch the next child (#602) once an earlier child halts"
else
  pass "epic drive never touches the next child (#602) once an earlier child halts"
fi

teardown

# ---------------------------------------------------------------------------
# An already-closed child is skipped entirely -- no recursive drive-item.sh
# invocation, no labels read for it -- and the epic drive still completes.
# ---------------------------------------------------------------------------
sub_issues_list="601 602"
setup_epic_mocks
set_issue_labels 600 "epic,blocked"
set_issue_state 601 "closed"
set_issue_labels 602 "child602:complete
child602:complete"

rc=0
run_drive 600 || rc=$?

if [[ $rc -eq 0 ]]; then
  pass "epic drive exits 0 when a closed child is skipped and the rest settle"
else
  fail "epic drive should exit 0 when a closed child is skipped and the rest settle; got rc=${rc}"
fi

if grep -q "child #601 already closed; skipping" "${WORK_DIR}/out.txt"; then
  pass "a closed child is reported as skipped"
else
  fail "a closed child should be reported as skipped"
fi

if grep -q "/issues/601/labels" "${CALLS_LOG}"; then
  fail "a closed child must never be recursively driven (no /issues/601/labels read)"
else
  pass "a closed child is never recursively driven (no /issues/601/labels read)"
fi

if grep -q "child #602 of epic #600" "${WORK_DIR}/out.txt"; then
  pass "the next child after a closed one is still driven"
else
  fail "the next child after a closed one should still be driven"
fi

teardown

# ---------------------------------------------------------------------------
# An epic that (incorrectly) lists itself as its own sub-issue skips that
# self-reference rather than recursing into itself.
# ---------------------------------------------------------------------------
sub_issues_list="600 601"
setup_epic_mocks
set_issue_labels 600 "epic,blocked"
set_issue_labels 601 "child601:complete
child601:complete"

rc=0
run_drive 600 || rc=$?

if [[ $rc -eq 0 ]]; then
  pass "epic drive exits 0 when its own number is skipped from a self-referencing sub-issue list"
else
  fail "epic drive should exit 0 when its own number is skipped; got rc=${rc}"
fi

if grep -q "epic cannot.*be its own sub-issue" "${WORK_DIR}/out.txt"; then
  pass "a self-referencing sub-issue entry is reported as skipped"
else
  fail "a self-referencing sub-issue entry should be reported as skipped"
fi

if grep -q "child #601 of epic #600" "${WORK_DIR}/out.txt"; then
  pass "the real child is still driven alongside a skipped self-reference"
else
  fail "the real child should still be driven alongside a skipped self-reference"
fi

teardown

echo
echo "drive-item.sh epic mode: ${PASS} passed, ${FAIL} failed"
[[ $FAIL -eq 0 ]]
