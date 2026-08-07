"""Tests for .github/scripts/merge-pr.sh -- deterministic PR merge + branch delete.

Uses a mock `gh` on PATH (like test_delete_branch.py) that dispatches on the
subcommand and is parameterized per scenario via env vars.
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MERGE_PR = REPO_ROOT / ".github" / "scripts" / "merge-pr.sh"

# A mock `gh` that branches on the new REST `gh api` invocations:
#   api repos/O/R/pulls?head=...&state=open  -> prints $ISSUE_PR (the resolved
#                                               PR number, or empty), exit 0
#   api repos/O/R/pulls/<N>  (probe or read) -> if the number is the input
#                                               NUMBER and $PR_EXISTS != 0, exit
#                                               $PR_EXISTS (the probe reports
#                                               "not a PR"); otherwise print the
#                                               REST pull object $STATE_JSON,
#                                               exit 0 (both the existence probe
#                                               and the state read hit this).
#   api --method PUT   .../pulls/<N>/merge   -> logs the call, exit $MERGE_RC
#   api --method DELETE .../git/refs/heads/B -> logs the call, exit $DELETE_RC
MOCK_GH = r"""#!/usr/bin/env bash
cmd="$1"; shift || true
if [ "$cmd" = "api" ]; then
  allargs="$*"
  case "$allargs" in
    *"--method PUT"*"/merge"*)
      echo "MOCK-MERGE-PUT: $allargs"; exit "${MERGE_RC:-0}" ;;
    *"--method DELETE"*)
      echo "MOCK-DELETE-REF: $allargs"; exit "${DELETE_RC:-0}" ;;
    *"pulls?head="*)
      printf '%s\n' "${ISSUE_PR}"; exit 0 ;;
    *)
      # Bare .../pulls/<N>: the existence probe and the state read both land
      # here. When the input number is not itself a PR (PR_EXISTS != 0), the
      # probe on that exact number must fail so the script falls back to the
      # issue-branch lookup.
      if [ "${PR_EXISTS:-0}" != "0" ]; then
        case "$allargs" in
          *"pulls/${INPUT_NUMBER}") exit "${PR_EXISTS}" ;;
        esac
      fi
      printf '%s' "${STATE_JSON}"; exit 0 ;;
  esac
fi
echo "mock gh: unhandled: $cmd $*" >&2
exit 99
"""


def _run(tmp_path, args, *, pr_exists=0, state_json="", issue_pr="",
         merge_rc=0, delete_rc=0):
    mock_dir = tmp_path / "bin"
    mock_dir.mkdir()
    gh = mock_dir / "gh"
    gh.write_text(MOCK_GH)
    gh.chmod(0o755)
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "REPO": "owner/repo",
        "INPUT_NUMBER": str(args[0]) if args else "",
        "PR_EXISTS": str(pr_exists),
        "STATE_JSON": state_json,
        "ISSUE_PR": issue_pr,
        "MERGE_RC": str(merge_rc),
        "DELETE_RC": str(delete_rc),
    }
    result = subprocess.run(
        ["bash", str(MERGE_PR), *args],
        env=env, capture_output=True, text=True,
    )
    return result.stdout + result.stderr, result.returncode


# REST pull objects (as `gh api repos/O/R/pulls/N` returns). state is lowercase;
# mergeable_state is "clean"/"dirty"/...; cross-repo is derived by comparing
# head.repo.full_name against base.repo.full_name.
_SAME_REPO = '"head":{"ref":"issue-5","repo":{"full_name":"owner/repo"}},"base":{"repo":{"full_name":"owner/repo"}},"draft":false'
_OPEN = '{"state":"open","merged":false,"mergeable_state":"clean",' + _SAME_REPO + '}'
_MERGED = '{"state":"closed","merged":true,"mergeable_state":"unknown",' + _SAME_REPO + '}'
_CONFLICT = '{"state":"open","merged":false,"mergeable_state":"dirty",' + _SAME_REPO + '}'
_CLOSED = '{"state":"closed","merged":false,"mergeable_state":"unknown",' + _SAME_REPO + '}'


class TestMergePr:
    def test_open_mergeable_pr_merges_and_deletes_branch(self, tmp_path):
        out, rc = _run(tmp_path, ["5"], pr_exists=0, state_json=_OPEN)
        assert rc == 0, out
        assert "Merged PR #5" in out
        # The branch was deleted via the REST ref-delete call on issue-5.
        assert "git/refs/heads/issue-5" in out

    def test_method_override_squash(self, tmp_path):
        out, rc = _run(tmp_path, ["5", "--squash"], pr_exists=0, state_json=_OPEN)
        assert rc == 0, out
        # The squash method reached the REST merge call, and the branch was deleted.
        assert "merge_method=squash" in out
        assert "git/refs/heads/issue-5" in out

    def test_already_merged_is_idempotent_and_deletes_branch(self, tmp_path):
        out, rc = _run(tmp_path, ["5"], pr_exists=0, state_json=_MERGED, delete_rc=0)
        assert rc == 0, out
        assert "already merged" in out
        assert "Deleted branch" in out

    def test_already_merged_branch_already_gone(self, tmp_path):
        out, rc = _run(tmp_path, ["5"], pr_exists=0, state_json=_MERGED, delete_rc=1)
        assert rc == 0, out
        assert "already gone" in out

    def test_conflicting_pr_is_refused(self, tmp_path):
        out, rc = _run(tmp_path, ["5"], pr_exists=0, state_json=_CONFLICT)
        assert rc == 1, out
        assert "conflict" in out.lower()

    def test_closed_unmerged_pr_is_refused(self, tmp_path):
        out, rc = _run(tmp_path, ["5"], pr_exists=0, state_json=_CLOSED)
        assert rc == 1, out
        assert "not open, not merged" in out

    def test_bad_number_is_usage_error(self, tmp_path):
        out, rc = _run(tmp_path, ["not-a-number"], state_json=_OPEN)
        assert rc == 2, out

    def test_bad_method_is_usage_error(self, tmp_path):
        out, rc = _run(tmp_path, ["5", "--octopus"], pr_exists=0, state_json=_OPEN)
        assert rc == 2, out

    def test_issue_number_resolves_to_issue_branch_pr(self, tmp_path):
        # The number is NOT a PR (pr_exists=1 -> gh pr view exits non-zero), but
        # issue-197's branch has open PR #241.
        out, rc = _run(tmp_path, ["197"], pr_exists=1, issue_pr="241", state_json=_OPEN)
        assert rc == 0, out
        assert "Merged PR #241" in out

    def test_unknown_number_not_pr_and_no_issue_branch(self, tmp_path):
        out, rc = _run(tmp_path, ["999"], pr_exists=1, issue_pr="")
        assert rc == 2, out
        assert "no PR #999" in out or "no open PR" in out
