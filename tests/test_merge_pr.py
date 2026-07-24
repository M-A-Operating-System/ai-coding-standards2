"""Tests for .github/scripts/merge-pr.sh -- deterministic PR merge + branch delete.

Uses a mock `gh` on PATH (like test_delete_branch.py) that dispatches on the
subcommand and is parameterized per scenario via env vars.
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MERGE_PR = REPO_ROOT / ".github" / "scripts" / "merge-pr.sh"

# A mock `gh` that branches on the subcommand:
#   pr view <n> --json state,merged,...   -> prints $STATE_JSON
#   pr view <n> --json number             -> exit $PR_EXISTS (0 = exists)
#   pr list ... --json number --jq ...     -> prints $ISSUE_PR
#   pr merge ...                           -> echoes args, exit $MERGE_RC
#   api --method DELETE ...                -> exit $DELETE_RC
MOCK_GH = r"""#!/usr/bin/env bash
cmd="$1"; shift || true
if [ "$cmd" = "pr" ]; then
  action="$1"; shift || true
  allargs="$*"
  case "$action" in
    view)
      if printf '%s' "$allargs" | grep -q -- 'state,merged,mergeable,headRefName,isCrossRepository'; then
        printf '%s' "$STATE_JSON"; exit 0
      fi
      exit "${PR_EXISTS:-0}"
      ;;
    list)  printf '%s' "$ISSUE_PR"; exit 0 ;;
    merge) echo "gh-merge: $*"; exit "${MERGE_RC:-0}" ;;
  esac
elif [ "$cmd" = "api" ]; then
  echo "gh-api: $*"; exit "${DELETE_RC:-0}"
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


_OPEN = '{"state":"OPEN","merged":false,"mergeable":"MERGEABLE","headRefName":"issue-5","isCrossRepository":false}'
_MERGED = '{"state":"MERGED","merged":true,"mergeable":"UNKNOWN","headRefName":"issue-5","isCrossRepository":false}'
_CONFLICT = '{"state":"OPEN","merged":false,"mergeable":"CONFLICTING","headRefName":"issue-5","isCrossRepository":false}'
_CLOSED = '{"state":"CLOSED","merged":false,"mergeable":"UNKNOWN","headRefName":"issue-5","isCrossRepository":false}'


class TestMergePr:
    def test_open_mergeable_pr_merges_and_deletes_branch(self, tmp_path):
        out, rc = _run(tmp_path, ["5"], pr_exists=0, state_json=_OPEN)
        assert rc == 0, out
        assert "Merged PR #5" in out
        assert "--delete-branch" in out  # the flag reached gh pr merge

    def test_method_override_squash(self, tmp_path):
        out, rc = _run(tmp_path, ["5", "--squash"], pr_exists=0, state_json=_OPEN)
        assert rc == 0, out
        assert "--squash" in out and "--delete-branch" in out

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
