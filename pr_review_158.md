<!-- ai-agile/artefact/v1 by 03_execute/pr-reviewer -->
## PR Review (Re-run)

**Verdict: REQUEST CHANGES**
**Summary:** 0 Critical · 1 High · 1 Medium · 1 Low · 2 Informational

---

### SC-001[DP+SC] — Remove `.tmp_*` temp files committed from a foreign agent run   [High]

**File:** `.tmp_announcement.md`, `.tmp_closing.md`, `.tmp_new_body.md`, `.tmp_snapshot.md` (all new files in diff)
**Persona:** DP+SC
**Standard:** STD-ARCH-006; P-1

**Description:** Four prd-writer temp artefacts for **issue #155** (not issue #151) are permanently committed to the `issue-151` branch. The new `.gitignore` entry (which correctly reads "prd-writer agent temp artefacts — must never be committed to source") prevents future occurrences, but the four already-tracked files are in the diff and will enter git history on merge. Each file carries content from a completely different issue (`#155 — [#142 - 3/6] Extract per-agent hooks to post_steps scripts`), indicating they were present in the working tree when `commit-agent-work.sh` staged files for this branch. P-1 requires state to live in GitHub (labels, comments, issue bodies) — not as committed files. STD-ARCH-006 requires defects visible in the current diff to be fixed inline, not deferred.

**Remediation:**
1. On the `issue-151` branch, run: `git rm .tmp_announcement.md .tmp_closing.md .tmp_new_body.md .tmp_snapshot.md`
2. Commit the deletion: `git commit -m "chore: remove stray prd-writer temp files from issue #155"`
3. Push: `git push origin issue-151`
4. Verify the four files are absent from `git ls-files | grep "^\.tmp_"`.
5. Root cause: `commit-agent-work.sh` uses `git stash show --name-only -u` to identify which files the agent wrote, but falls back to `git add -A` when that list is empty (lines 102-109 of the script). Investigate whether the stash-show fallback allowed foreign files to be staged; if so, harden the script to skip the `git add -A` fallback or add an explicit allowlist guard.

---

### QA-001 — Add a test for the clean-working-tree exit path of `commit-agent-work.sh`   [Medium]

**File:** `tests/test_orchestrator_logic.py` (no equivalent test exists in `TestCommitAgentWorkScript`)
**Persona:** QA
**Standard:** STD-TEST-001

**Description:** The deleted `TestRunCommitAfter.test_no_working_tree_changes_returns_true` verified that when `git status --porcelain` returns empty, `_run_commit_after` returns `True` and issues no commit. The replacement `TestCommitAgentWorkScript` has no test for this path. Lines 53-57 of `.github/scripts/commit-agent-work.sh` implement the identical early-exit: `if [ -z "$DIRTY" ]; then ... exit 0`. This path is untested: if a regression silently removes the guard, agents with nothing to commit will proceed to `git stash push` and potentially corrupt branch state.

**Remediation:**
Add a test to `tests/test_orchestrator_logic.py` in `TestCommitAgentWorkScript` that sets up a minimal git repo with a clean working tree (no untracked or modified files), invokes `commit-agent-work.sh`, asserts exit code 0, and asserts that `git log --oneline issue-N` on the bare origin contains no `[agent]` commit.

---

### DP-001 — Use `[[` instead of `[` in `commit-agent-work.sh`   [Low]

**File:** `.github/scripts/commit-agent-work.sh:54,102,117,118,144`
**Persona:** DP

**Description:** The script uses POSIX single-bracket (`[ ]`) conditionals throughout. While variables are properly quoted so there is no immediate word-splitting risk, `[[ ]]` is the bash-native form: it handles empty variables gracefully without quoting, supports pattern matching, avoids POSIX portability footguns, and is safer against future edits that drop a quote. The shebang is `#!/usr/bin/env bash`, so `[[ ]]` is available and preferred.

**Remediation:** Replace all `[ ]` test expressions in the script with `[[ ]]`:
- Line 54: `if [[ -z "$DIRTY" ]]; then`
- Line 102: `if [[ -n "$STASH_FILES" ]]; then`
- Line 117: `if [[ -n "$WORKFLOW_FILES" ]]; then`
- Line 118: `if [[ -z "$_BOT_TOKEN" ]]; then`
- Line 144: `if [[ -n "$WORKFLOW_FILES" ]] && [[ -n "$_BOT_TOKEN" ]]; then`

---

### SA-001 — `.github/scripts/commit-agent-work.sh` is not marked executable (mode 100644)   [Informational]

**File:** `.github/scripts/commit-agent-work.sh:1` (diff header: `new file mode 100644`)
**Persona:** SA

**Description:** The script is added with mode `100644` (not executable). The orchestrator invokes it via `["bash", str(script_file)]`, so the missing executable bit does not cause a functional failure. However, convention for shell scripts is `100755` — anyone running the script directly from the shell will get "Permission denied". Future post_steps scripts or CI tooling that calls scripts without explicitly prepending `bash` will silently fail in a confusing way.

**Remediation:** `git update-index --chmod=+x .github/scripts/commit-agent-work.sh` then re-commit.

---

### QA-002 — End-to-end git integration test placed in the unit test file   [Informational]

**File:** `tests/test_orchestrator_logic.py:2393` (`test_commit_agent_work_script_creates_correct_commit_message`)
**Persona:** QA
**Standard:** STD-TEST-002

**Description:** `test_commit_agent_work_script_creates_correct_commit_message` creates a real git repository in `tmp_path`, runs real `git` subcommands, and executes the shell script end-to-end. STD-TEST-002 exempts writes to `tmp_path`, so there is no standards violation. The concern is organisational: an end-to-end script integration test in `tests/test_orchestrator_logic.py` makes the suite slower and harder to run selectively. `tests/integration/` is the conventional home per STD-TEST-002.

**Remediation (optional / low priority):** Move the test to `tests/integration/test_commit_agent_work.py` and exclude it from the default `pytest` run via a marker or `testpaths`. Can be deferred to a follow-up if CI run time is acceptable.

---

_On APPROVE: PR is marked ready for human review. On REQUEST CHANGES: the orchestrator will automatically re-invoke the coder (up to 3 cycles). After 3 cycles without agreement, human sign-off is required._
