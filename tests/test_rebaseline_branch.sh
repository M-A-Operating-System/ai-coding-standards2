#!/usr/bin/env bash
# Tests rebaseline-branch.sh: the /maos-rebaseline procedure, extracted from
# the command file for AS-3 (issue #407).
#
# Runs against real throwaway git repositories -- a rebaseline IS git
# behaviour, so mocking git would test nothing.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/rebaseline-branch.sh"

g() { git -c user.email=t@t -c user.name=t -c push.negotiate=false "$@"; }

# A bare remote with main at one commit, and a clone of it.
setup() {
  WORK_DIR="$(mktemp -d)"
  REMOTE="${WORK_DIR}/remote.git"
  CLONE="${WORK_DIR}/clone"
  git init --bare -q -b main "${REMOTE}"
  git init -q -b main "${WORK_DIR}/seed"
  ( cd "${WORK_DIR}/seed" \
    && echo one > file.txt && g add file.txt && g commit -qm one \
    && g push -q "${REMOTE}" main:refs/heads/main )
  git clone -q "${REMOTE}" "${CLONE}"
  ( cd "${CLONE}" && g config user.email t@t && g config user.name t )
}

teardown() { rm -rf "${WORK_DIR}"; }

run_it() {
  ( cd "${CLONE}" && bash "${SCRIPT}" "$@" >"${WORK_DIR}/out.txt" 2>&1 )
}

# ---------------------------------------------------------------------------
# It refuses to run over uncommitted work -- and loses nothing
# ---------------------------------------------------------------------------
for kind in unstaged untracked staged; do
  setup
  case "${kind}" in
    unstaged)  ( cd "${CLONE}" && echo edited > file.txt ) ;;
    untracked) ( cd "${CLONE}" && echo notes > my_notes.md ) ;;
    staged)    ( cd "${CLONE}" && echo new > added.txt && g add added.txt ) ;;
  esac
  rc=0; run_it || rc=$?
  if [ "${rc}" -ne 0 ] && grep -q "working tree is not clean" "${WORK_DIR}/out.txt"; then
    pass "refuses to run over ${kind} work"
  else
    fail "expected a refusal for ${kind} work; rc=${rc}"
    cat "${WORK_DIR}/out.txt"
  fi
  # Nothing the person had may have been touched.
  case "${kind}" in
    unstaged)  [ "$(cat "${CLONE}/file.txt")" = "edited" ] \
                 && pass "${kind} work survives" || fail "${kind} work was lost" ;;
    untracked) [ -f "${CLONE}/my_notes.md" ] \
                 && pass "${kind} work survives" || fail "${kind} work was lost" ;;
    staged)    [ -f "${CLONE}/added.txt" ] \
                 && pass "${kind} work survives" || fail "${kind} work was lost" ;;
  esac
  teardown
done

# ---------------------------------------------------------------------------
# It resets a diverged local branch to the remote, and says what it discarded
# ---------------------------------------------------------------------------
setup
( cd "${CLONE}" && echo two > file.txt && g add file.txt && g commit -qm "local only" )
LOCAL_SHA=$( cd "${CLONE}" && git rev-parse HEAD )
rc=0; run_it || rc=$?
REMOTE_SHA=$( cd "${REMOTE}" && git rev-parse main )
NOW_SHA=$( cd "${CLONE}" && git rev-parse HEAD )
if [ "${rc}" -eq 0 ] && [ "${NOW_SHA}" = "${REMOTE_SHA}" ]; then
  pass "resets the local branch to the remote"
else
  fail "expected a reset to origin/main; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi
if grep -q "local only" "${WORK_DIR}/out.txt" && grep -q "reflog" "${WORK_DIR}/out.txt"; then
  pass "names the local-only commit it discarded, and how to recover it"
else
  fail "expected the discarded commit to be named"
  cat "${WORK_DIR}/out.txt"
fi
if ( cd "${CLONE}" && git cat-file -e "${LOCAL_SHA}" 2>/dev/null ); then
  pass "the discarded commit is still recoverable"
else
  fail "the discarded commit is gone entirely"
fi
teardown

# ---------------------------------------------------------------------------
# It never deletes untracked files -- no git clean, ever
# ---------------------------------------------------------------------------
if grep -q "git clean" "${SCRIPT}" && ! grep -qE '^\s*git clean' "${SCRIPT}"; then
  pass "git clean is named only in the comment explaining why it is absent"
else
  fail "rebaseline-branch.sh must not run git clean, and must say why"
fi

# ---------------------------------------------------------------------------
# It creates the target branch when the checkout never had it
# ---------------------------------------------------------------------------
setup
( cd "${WORK_DIR}/seed" && g checkout -q -b develop \
  && echo dev > file.txt && g add file.txt && g commit -qm dev \
  && g push -q "${REMOTE}" develop:refs/heads/develop )
( cd "${CLONE}" && g fetch -q origin )
rc=0; run_it develop || rc=$?
BRANCH=$( cd "${CLONE}" && git rev-parse --abbrev-ref HEAD )
if [ "${rc}" -eq 0 ] && [ "${BRANCH}" = "develop" ]; then
  pass "creates and checks out a branch the clone never had"
else
  fail "expected to be on develop; rc=${rc} branch=${BRANCH}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

# ---------------------------------------------------------------------------
# It reports the commit it landed on
# ---------------------------------------------------------------------------
setup
rc=0; run_it || rc=$?
if [ "${rc}" -eq 0 ] && grep -q "is now at" "${WORK_DIR}/out.txt" \
   && grep -q "no local-only commits were discarded" "${WORK_DIR}/out.txt"; then
  pass "reports where it landed and that nothing was discarded"
else
  fail "expected a report of the resulting commit; rc=${rc}"
  cat "${WORK_DIR}/out.txt"
fi
teardown

echo
echo "rebaseline-branch.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
