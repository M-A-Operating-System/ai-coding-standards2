#!/usr/bin/env bash
# create-pr.sh must leave the shared working tree on the branch it found it on.
#
# The script checks the issue branch out in the SHARED tree to create it and add
# the placeholder commit. Left there, the next commit_after step cannot check
# the same branch into its own isolated worktree -- git refuses one branch in two
# working trees:
#
#   fatal: cannot force update the branch 'issue-N-docs' used by worktree at ...
#
# and the step hard-fails, needing a person to restore the branch by hand. Seen
# on issue #425, where create-docs-pr and prd-docs-updater ran in one tick.
#
# Two tests: the restore itself, and the consequence it exists to prevent.

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CREATE_PR="${SCRIPT_DIR}/../.github/scripts/create-pr.sh"
FAILURES=0

fail() { echo "FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "ok: $*"; }

# --- 1. the trap exists and fires on every exit path ------------------------
if grep -q 'trap _restore_entry_ref EXIT' "$CREATE_PR"; then
    pass "create-pr.sh restores the entry ref on EXIT"
else
    fail "create-pr.sh has no EXIT trap restoring the branch it started on"
fi

if grep -q '_ENTRY_REF=$(git rev-parse --abbrev-ref HEAD' "$CREATE_PR"; then
    pass "create-pr.sh records the branch it started on"
else
    fail "create-pr.sh does not record the entry branch"
fi

# --- 1b. the trap must not write to stdout after the status sentinel --------
# This script's last statement is `echo "AI_AGILE_STATUS: complete"`, and the
# EXIT trap runs after it. The orchestrator requires the sentinel to be the
# final output line and searches only the last five lines for it
# (_parse_agent_sentinel) -- a window narrowed to resist sentinel spoofing, not
# to absorb trailing diagnostics. A restore note on stdout works today only on
# that margin; one more trailing line and a successful step reads as :failed.
_TRAP_BODY=$(awk '/^_restore_entry_ref\(\) \{/,/^\}/' "$CREATE_PR")
_STDOUT_ECHOES=$(printf '%s\n' "$_TRAP_BODY" | grep -E '^[[:space:]]*echo ' | grep -v '>&2' || true)
if [[ -z "$_STDOUT_ECHOES" ]]; then
    pass "the EXIT trap writes only to stderr, leaving the sentinel last on stdout"
else
    fail "the EXIT trap writes to stdout after AI_AGILE_STATUS:, spending the sentinel window; needs >&2: ${_STDOUT_ECHOES}"
fi

# --- 2. the failure it prevents, against real git ---------------------------
# Guard rather than assert: this reproduces git's refusal, so if a future git
# stopped refusing, the restore would still be correct and the test should say
# so rather than fail.
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

git init -q --bare "$T/origin.git" -b main
git clone -q "$T/origin.git" "$T/work" 2>/dev/null
(
  cd "$T/work"
  git config user.email t@example.invalid
  git config user.name t
  echo x > README.md
  git add -A
  git commit -qm init
  git push -q origin main 2>/dev/null
  git checkout -q -B issue-999-docs origin/main
  git commit -q --allow-empty -m placeholder
  git push -q -u origin issue-999-docs 2>/dev/null
) >/dev/null 2>&1

# Shared tree is now ON issue-999-docs, as create-pr.sh would leave it unrestored.
if git -C "$T/work" worktree add --force -B issue-999-docs "$T/wt" \
     origin/issue-999-docs >/dev/null 2>&1; then
    echo "note: this git allows a branch in two working trees; the restore is" \
         "still correct but this environment cannot demonstrate the failure"
else
    pass "git refuses a branch checked out twice -- the restore is load-bearing"
fi

# And with the tree restored first, the same worktree add succeeds.
git -C "$T/work" checkout -q main
if git -C "$T/work" worktree add --force -B issue-999-docs "$T/wt2" \
     origin/issue-999-docs >/dev/null 2>&1; then
    pass "with the shared tree restored, the isolated worktree is created"
else
    fail "worktree creation still fails after restoring the shared tree"
fi

if [[ "$FAILURES" -gt 0 ]]; then
    echo "FAILED: $FAILURES check(s)" >&2
    exit 1
fi
echo "all checks passed"
