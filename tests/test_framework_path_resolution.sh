#!/usr/bin/env bash
# Tests that status.sh, aggregate-metrics.sh, and generate-metrics-report.sh
# locate their own framework files via SUBMODULE_ROOT (script-relative), not
# via AI_AGILE_ROOT or literal .. path tokens (issue #596).
#
# Covers the acceptance criteria from the PRD:
#   - bootstrap-triggers exits 0 in a submodule layout with no pipeline-path arg
#   - bootstrap-triggers exits 0 in a standalone layout with no pipeline-path arg
#   - no .. path-segment token in the fixed scripts
#   - AI_AGILE_ROOT is not read for framework file paths
#   - aggregate-metrics.sh finds metrics_aggregator.py in a submodule layout
#   - generate-metrics-report.sh finds metrics_report.py in a submodule layout

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# A minimal stub for gh that accepts label operations without reaching GitHub.
_write_gh_stub() {
  local dir="$1"
  cat >"${dir}/gh" <<'GHSTUB'
#!/usr/bin/env bash
# Accept label list, label create, and label POST silently.
case "${1:-}" in
  label)
    case "${2:-}" in
      list) echo '[]' ;;
      create) exit 0 ;;
    esac ;;
  api) exit 0 ;;
  config) exit 0 ;;
  *) exit 0 ;;
esac
GHSTUB
  chmod +x "${dir}/gh"
}

# ---------------------------------------------------------------------------
# Scenario: no .. path-segment token in the fixed scripts
# ---------------------------------------------------------------------------
for script in scripts/status.sh scripts/aggregate-metrics.sh scripts/generate-metrics-report.sh; do
  full="${REPO_ROOT}/${script}"
  if grep -qE '(^|[^.])\.\./' "${full}" || grep -qE '/\.\.([ "$]|$)' "${full}"; then
    fail "${script}: contains a literal .. path-segment token"
  else
    pass "${script}: contains no .. path-segment token"
  fi
done

# ---------------------------------------------------------------------------
# Scenario: AI_AGILE_ROOT is not referenced in the three fixed scripts
# (for framework file resolution -- any remaining references should be absent)
# ---------------------------------------------------------------------------
for script in scripts/status.sh scripts/aggregate-metrics.sh scripts/generate-metrics-report.sh; do
  full="${REPO_ROOT}/${script}"
  if grep -q 'AI_AGILE_ROOT' "${full}"; then
    fail "${script}: still reads AI_AGILE_ROOT"
  else
    pass "${script}: does not reference AI_AGILE_ROOT"
  fi
done

# ---------------------------------------------------------------------------
# Helpers for sandbox tests
# ---------------------------------------------------------------------------

_setup_submodule_sandbox() {
  # Creates:
  #   WORK/                            <- consuming repo root (no pipeline/ here)
  #   WORK/ai-coding-standards2/       <- submodule
  #   WORK/ai-coding-standards2/scripts/
  #   WORK/ai-coding-standards2/pipeline/
  WORK_DIR="$(mktemp -d)"
  SUBMOD="${WORK_DIR}/ai-coding-standards2"
  mkdir -p "${SUBMOD}/scripts" "${SUBMOD}/pipeline"
  MOCK_BIN="${WORK_DIR}/.mock-bin"
  mkdir -p "${MOCK_BIN}"
  _write_gh_stub "${MOCK_BIN}"
}

_setup_standalone_sandbox() {
  # Creates:
  #   WORK/                <- repo root
  #   WORK/scripts/
  #   WORK/pipeline/
  WORK_DIR="$(mktemp -d)"
  mkdir -p "${WORK_DIR}/scripts" "${WORK_DIR}/pipeline"
  MOCK_BIN="${WORK_DIR}/.mock-bin"
  mkdir -p "${MOCK_BIN}"
  _write_gh_stub "${MOCK_BIN}"
}

teardown() { rm -rf "${WORK_DIR:-}"; }

# ---------------------------------------------------------------------------
# Scenario: bootstrap-triggers exits 0 in a submodule layout with no
# pipeline-path argument
# ---------------------------------------------------------------------------
_setup_submodule_sandbox
SUBMOD="${WORK_DIR}/ai-coding-standards2"
cp "${REPO_ROOT}/scripts/status.sh" "${SUBMOD}/scripts/"
cp "${REPO_ROOT}/pipeline/pipeline.json" "${SUBMOD}/pipeline/"
cp "${REPO_ROOT}/pipeline/statuses.json" "${SUBMOD}/pipeline/"

rc=0
OUTPUT=$(
  PATH="${MOCK_BIN}:${PATH}" \
  GITHUB_REPOSITORY="owner/repo" \
  bash "${SUBMOD}/scripts/status.sh" bootstrap-triggers 2>&1
) || rc=$?

if [[ "${rc}" -eq 0 ]]; then
  pass "submodule layout: bootstrap-triggers exits 0 with no pipeline-path arg"
else
  fail "submodule layout: bootstrap-triggers exited ${rc} -- output: ${OUTPUT}"
fi
teardown

# ---------------------------------------------------------------------------
# Scenario: bootstrap-triggers exits 0 in a standalone layout with no
# pipeline-path argument
# ---------------------------------------------------------------------------
_setup_standalone_sandbox
cp "${REPO_ROOT}/scripts/status.sh" "${WORK_DIR}/scripts/"
cp "${REPO_ROOT}/pipeline/pipeline.json" "${WORK_DIR}/pipeline/"
cp "${REPO_ROOT}/pipeline/statuses.json" "${WORK_DIR}/pipeline/"

rc=0
OUTPUT=$(
  PATH="${MOCK_BIN}:${PATH}" \
  GITHUB_REPOSITORY="owner/repo" \
  bash "${WORK_DIR}/scripts/status.sh" bootstrap-triggers 2>&1
) || rc=$?

if [[ "${rc}" -eq 0 ]]; then
  pass "standalone layout: bootstrap-triggers exits 0 with no pipeline-path arg"
else
  fail "standalone layout: bootstrap-triggers exited ${rc} -- output: ${OUTPUT}"
fi
teardown

# ---------------------------------------------------------------------------
# Scenario: AI_AGILE_ROOT set to unrelated dir -- status.sh still resolves
# framework files via SUBMODULE_ROOT, not AI_AGILE_ROOT
# ---------------------------------------------------------------------------
_setup_submodule_sandbox
SUBMOD="${WORK_DIR}/ai-coding-standards2"
cp "${REPO_ROOT}/scripts/status.sh" "${SUBMOD}/scripts/"
cp "${REPO_ROOT}/pipeline/pipeline.json" "${SUBMOD}/pipeline/"
cp "${REPO_ROOT}/pipeline/statuses.json" "${SUBMOD}/pipeline/"
UNRELATED_DIR="$(mktemp -d)"

rc=0
OUTPUT=$(
  PATH="${MOCK_BIN}:${PATH}" \
  GITHUB_REPOSITORY="owner/repo" \
  AI_AGILE_ROOT="${UNRELATED_DIR}" \
  bash "${SUBMOD}/scripts/status.sh" bootstrap-triggers 2>&1
) || rc=$?

if [[ "${rc}" -eq 0 ]]; then
  pass "AI_AGILE_ROOT isolation: bootstrap-triggers exits 0 when AI_AGILE_ROOT is unrelated"
else
  fail "AI_AGILE_ROOT isolation: bootstrap-triggers failed with unrelated AI_AGILE_ROOT -- output: ${OUTPUT}"
fi
rm -rf "${UNRELATED_DIR}"
teardown

# ---------------------------------------------------------------------------
# Scenario: aggregate-metrics.sh finds metrics_aggregator.py in a submodule
# layout (AI_AGILE_ROOT set to consuming repo root, not submodule root)
# ---------------------------------------------------------------------------
_setup_submodule_sandbox
SUBMOD="${WORK_DIR}/ai-coding-standards2"
cp "${REPO_ROOT}/scripts/aggregate-metrics.sh" "${SUBMOD}/scripts/"

# Minimal metrics_aggregator.py stub: succeeds and produces no records
cat >"${SUBMOD}/pipeline/metrics_aggregator.py" <<'PYSTUB'
#!/usr/bin/env python3
import sys
# Accept --period arg; emit nothing to stdout (no records this bucket)
PYSTUB

# append-metrics-record.sh stub (should not be called with no records)
cat >"${SUBMOD}/scripts/append-metrics-record.sh" <<'APPENDSTUB'
#!/usr/bin/env bash
echo "UNEXPECTED: append-metrics-record.sh was called" >&2
exit 1
APPENDSTUB
chmod +x "${SUBMOD}/scripts/append-metrics-record.sh"

rc=0
OUTPUT=$(
  AI_AGILE_ROOT="${WORK_DIR}" \
  bash "${SUBMOD}/scripts/aggregate-metrics.sh" 2>&1
) || rc=$?

if echo "${OUTPUT}" | grep -q 'metrics_aggregator.py not found'; then
  fail "submodule layout: aggregate-metrics.sh emitted blocked for missing metrics_aggregator.py -- output: ${OUTPUT}"
elif echo "${OUTPUT}" | grep -q 'AI_AGILE_STATUS: complete'; then
  pass "submodule layout: aggregate-metrics.sh found metrics_aggregator.py via SUBMODULE_ROOT"
else
  fail "submodule layout: aggregate-metrics.sh unexpected output (rc=${rc}) -- output: ${OUTPUT}"
fi
teardown

# ---------------------------------------------------------------------------
# Scenario: generate-metrics-report.sh finds metrics_report.py in a submodule
# layout (AI_AGILE_ROOT set to consuming repo root, not submodule root)
# ---------------------------------------------------------------------------
_setup_submodule_sandbox
SUBMOD="${WORK_DIR}/ai-coding-standards2"
cp "${REPO_ROOT}/scripts/generate-metrics-report.sh" "${SUBMOD}/scripts/"

# Minimal metrics_report.py stub: succeeds but produces no output PDF
# (script will take the "no PDF produced" path and exit complete)
cat >"${SUBMOD}/pipeline/metrics_report.py" <<'PYSTUB'
#!/usr/bin/env python3
import sys
# Accept --output arg; write nothing (no PDF)
PYSTUB

SCRATCH_DIR="$(mktemp -d)"

rc=0
OUTPUT=$(
  AI_AGILE_ROOT="${WORK_DIR}" \
  AI_AGILE_SCRATCH="${SCRATCH_DIR}" \
  bash "${SUBMOD}/scripts/generate-metrics-report.sh" 2>&1
) || rc=$?

if echo "${OUTPUT}" | grep -q 'metrics_report.py not found'; then
  fail "submodule layout: generate-metrics-report.sh emitted blocked for missing metrics_report.py -- output: ${OUTPUT}"
elif echo "${OUTPUT}" | grep -q 'AI_AGILE_STATUS:'; then
  pass "submodule layout: generate-metrics-report.sh found metrics_report.py via SUBMODULE_ROOT"
else
  fail "submodule layout: generate-metrics-report.sh unexpected output (rc=${rc}) -- output: ${OUTPUT}"
fi
rm -rf "${SCRATCH_DIR}"
teardown

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "framework-path-resolution: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
