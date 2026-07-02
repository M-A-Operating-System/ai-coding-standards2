#!/usr/bin/env bash
# Regression test for CLAUDE-BUG-3ae293: ci-gate.sh line 90 crashed with
# "invalid variable name" whenever the check-run exclusion list (seen_names,
# an associative array) was non-empty. The bug was combining indirect
# array-keys expansion (${!array[*]}) with the default-value operator (:-),
# which bash does not compose the way it looks like it should.
#
# This test exercises the exact exclusion-list logging logic in isolation —
# not the full script (which requires REPO/ISSUE_NUMBER and live gh API
# calls) — so it fails loudly if the same pitfall is ever reintroduced.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CI_GATE_SCRIPT="${REPO_ROOT}/.github/scripts/ci-gate.sh"

# ---------------------------------------------------------------------------
# Test 1: the exact defect pattern (${!array[*]:-<none>}) must not appear in
# the script. This is the direct regression guard — if this string comes
# back, the crash comes back with it, regardless of what else changes.
# ---------------------------------------------------------------------------
test_broken_expansion_pattern_absent() {
  if grep -qF '${!seen_names[*]:-' "${CI_GATE_SCRIPT}"; then
    fail "ci-gate.sh still contains the broken \${!seen_names[*]:-...} pattern"
  else
    pass "ci-gate.sh does not contain the broken indirect-expansion-with-default pattern"
  fi
}

# ---------------------------------------------------------------------------
# Test 2 (non-empty array): the fixed logging logic must not crash and must
# print the job names. Mirrors ci-gate.sh's real exclusion-list population
# (job name as key, "1" as value) without invoking the full script.
# ---------------------------------------------------------------------------
test_logs_names_when_exclusion_list_non_empty() {
  local output exit_code=0
  output=$(bash -c '
    set -euo pipefail
    declare -A seen_names=()
    seen_names["Evaluate pipeline state"]=1
    seen_names["Onboard"]=1
    if [[ ${#seen_names[@]} -eq 0 ]]; then
        echo "excluded job names: <none>"
    else
        echo "excluded job names: ${!seen_names[*]}"
    fi
  ' 2>&1) || exit_code=$?

  if [[ "${exit_code}" -ne 0 ]]; then
    fail "non-empty exclusion list: script exited non-zero ($exit_code) — output: ${output}"
  else
    pass "non-empty exclusion list: exits zero"
  fi

  if echo "${output}" | grep -q "invalid variable name"; then
    fail "non-empty exclusion list: bash raised 'invalid variable name' — output: ${output}"
  else
    pass "non-empty exclusion list: no 'invalid variable name' error"
  fi

  if echo "${output}" | grep -q "Evaluate pipeline state" && echo "${output}" | grep -q "Onboard"; then
    pass "non-empty exclusion list: both job names are logged"
  else
    fail "non-empty exclusion list: expected job names missing — output: ${output}"
  fi
}

# ---------------------------------------------------------------------------
# Test 3 (empty array): must log the <none> placeholder without crashing.
# ---------------------------------------------------------------------------
test_logs_placeholder_when_exclusion_list_empty() {
  local output exit_code=0
  output=$(bash -c '
    set -euo pipefail
    declare -A seen_names=()
    if [[ ${#seen_names[@]} -eq 0 ]]; then
        echo "excluded job names: <none>"
    else
        echo "excluded job names: ${!seen_names[*]}"
    fi
  ' 2>&1) || exit_code=$?

  if [[ "${exit_code}" -ne 0 ]]; then
    fail "empty exclusion list: script exited non-zero ($exit_code) — output: ${output}"
  else
    pass "empty exclusion list: exits zero"
  fi

  if echo "${output}" | grep -q "<none>"; then
    pass "empty exclusion list: logs <none> placeholder"
  else
    fail "empty exclusion list: missing <none> placeholder — output: ${output}"
  fi
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_broken_expansion_pattern_absent
test_logs_names_when_exclusion_list_non_empty
test_logs_placeholder_when_exclusion_list_empty

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
