#!/usr/bin/env bash
# Tests ensure-gh-cli.sh: gh present/absent, REST auth probe success/failure.
#
# Uses an isolated PATH containing only mock binaries so the real system gh
# (present in this environment) never shadows the "gh missing" scenarios.
# `"${BASH_BIN}" "${SCRIPT}"` is invoked with PATH restricted to the mock dir only --
# bash itself is resolved by the caller's own (unrestricted) PATH first, so
# only the script's internal apt-get/gh calls are sandboxed.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/ensure-gh-cli.sh"
# Resolved once, up front, with the real PATH -- the mock dir used per test
# deliberately excludes the real system bash from its own PATH.
BASH_BIN="$(command -v bash)"

setup_mock_dir() {
  MOCK_DIR="$(mktemp -d)"
  mkdir -p "${MOCK_DIR}/bin"
  # Mock gh/apt-get scripts are themselves `#!/usr/bin/env bash` scripts, and
  # the mock apt-get itself shells out to cp/chmod to "install" gh -- all
  # need to resolve under the restricted mock-only PATH the script under
  # test runs with.
  ln -s "${BASH_BIN}" "${MOCK_DIR}/bin/bash"
  ln -s "$(command -v cp)" "${MOCK_DIR}/bin/cp"
  ln -s "$(command -v chmod)" "${MOCK_DIR}/bin/chmod"
}

teardown_mock_dir() {
  rm -rf -- "${MOCK_DIR}"
}

test_gh_present_and_probe_succeeds() {
  setup_mock_dir
  cat >"${MOCK_DIR}/bin/gh" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "api" && "$2" == "user" ]]; then
  echo "agbush2"
  exit 0
fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/bin/gh"

  set +e
  OUT="$(PATH="${MOCK_DIR}/bin" "${BASH_BIN}" "${SCRIPT}")"
  RC=$?
  set -e

  if [[ "${RC}" -eq 0 ]]; then
    pass "gh present + probe succeeds: exits 0"
  else
    fail "gh present + probe succeeds: expected exit 0, got ${RC}"
  fi
  if echo "${OUT}" | grep -q "REST-authenticated as agbush2"; then
    pass "gh present + probe succeeds: reports authenticated identity"
  else
    fail "gh present + probe succeeds: missing identity in output — got: ${OUT}"
  fi

  teardown_mock_dir
}

test_gh_missing_installs_via_apt_then_probes() {
  setup_mock_dir
  cat >"${MOCK_DIR}/gh_src" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "api" && "$2" == "user" ]]; then
  echo "agbush2"
  exit 0
fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/gh_src"
  cat >"${MOCK_DIR}/bin/apt-get" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "install" ]]; then
  cp "${MOCK_DIR}/gh_src" "${MOCK_DIR}/bin/gh"
  chmod +x "${MOCK_DIR}/bin/gh"
fi
exit 0
EOF
  chmod +x "${MOCK_DIR}/bin/apt-get"

  set +e
  OUT="$(PATH="${MOCK_DIR}/bin" "${BASH_BIN}" "${SCRIPT}" 2>&1)"
  RC=$?
  set -e

  if [[ "${RC}" -eq 0 ]]; then
    pass "gh missing: installs via apt then succeeds"
  else
    fail "gh missing: expected exit 0 after install, got ${RC} — output: ${OUT}"
  fi
  if echo "${OUT}" | grep -q "gh CLI installed"; then
    pass "gh missing: reports install"
  else
    fail "gh missing: missing install message — got: ${OUT}"
  fi
  if echo "${OUT}" | grep -q "REST-authenticated as agbush2"; then
    pass "gh missing: probes newly-installed gh successfully"
  else
    fail "gh missing: missing post-install probe success — got: ${OUT}"
  fi

  teardown_mock_dir
}

test_apt_install_failure_reports_stderr() {
  setup_mock_dir
  cat >"${MOCK_DIR}/bin/apt-get" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "install" ]]; then
  echo "E: Unable to locate package gh" >&2
  exit 100
fi
exit 0
EOF
  chmod +x "${MOCK_DIR}/bin/apt-get"

  set +e
  OUT="$(PATH="${MOCK_DIR}/bin" "${BASH_BIN}" "${SCRIPT}" 2>&1)"
  RC=$?
  set -e

  if [[ "${RC}" -ne 0 ]]; then
    pass "apt install failure: exits non-zero"
  else
    fail "apt install failure: expected non-zero exit, got 0"
  fi
  if echo "${OUT}" | grep -q "Unable to locate package gh"; then
    pass "apt install failure: reports captured stderr"
  else
    fail "apt install failure: missing captured stderr — got: ${OUT}"
  fi

  teardown_mock_dir
}

test_probe_failure_reports_stderr() {
  setup_mock_dir
  cat >"${MOCK_DIR}/bin/gh" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "api" && "$2" == "user" ]]; then
  echo "HTTP 401: Bad credentials" >&2
  exit 1
fi
exit 1
EOF
  chmod +x "${MOCK_DIR}/bin/gh"

  set +e
  OUT="$(PATH="${MOCK_DIR}/bin" "${BASH_BIN}" "${SCRIPT}" 2>&1)"
  RC=$?
  set -e

  if [[ "${RC}" -ne 0 ]]; then
    pass "probe failure: exits non-zero"
  else
    fail "probe failure: expected non-zero exit, got 0"
  fi
  if echo "${OUT}" | grep -q "HTTP 401: Bad credentials"; then
    pass "probe failure: reports captured stderr"
  else
    fail "probe failure: missing captured stderr — got: ${OUT}"
  fi

  teardown_mock_dir
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
test_gh_present_and_probe_succeeds
test_gh_missing_installs_via_apt_then_probes
test_apt_install_failure_reports_stderr
test_probe_failure_reports_stderr

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -eq 0 ]]
