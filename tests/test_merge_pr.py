"""Tests for scripts/merge-pr.sh -- deterministic PR merge + branch delete.

Uses a mock `gh` on PATH (like test_delete_branch.py) that dispatches on the
subcommand and is parameterized per scenario via env vars.
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MERGE_PR = REPO_ROOT / "scripts" / "merge-pr.sh"

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
#   api --method PATCH .../issues/<N>        -> logs the call, exit $CLOSE_RC
MOCK_GH = r"""#!/usr/bin/env bash
cmd="$1"; shift || true
if [ "$cmd" = "api" ]; then
  allargs="$*"
  case "$allargs" in
    *"--method PUT"*"/merge"*)
      echo "MOCK-MERGE-PUT: $allargs"; exit "${MERGE_RC:-0}" ;;
    *"--method PATCH"*"/issues/"*)
      echo "MOCK-CLOSE-ISSUE: $allargs"; exit "${CLOSE_RC:-0}" ;;
    *"--method DELETE"*)
      echo "MOCK-DELETE-REF: $allargs"; exit "${DELETE_RC:-0}" ;;
    *"git/refs/heads/"*)
      exit "${BRANCH_REF_RC:-0}" ;;
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


def _run_split(tmp_path, args, *, pr_exists=0, state_json="", issue_pr="",
               merge_rc=0, delete_rc=0, branch_ref_rc=0, close_rc=0):
    """Returns (stdout, stderr, rc) for stream-sensitive assertions."""
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
        "BRANCH_REF_RC": str(branch_ref_rc),
        "CLOSE_RC": str(close_rc),
    }
    result = subprocess.run(
        ["bash", str(MERGE_PR), *args],
        env=env, capture_output=True, text=True,
    )
    return result.stdout, result.stderr, result.returncode


def _run(tmp_path, args, *, pr_exists=0, state_json="", issue_pr="",
         merge_rc=0, delete_rc=0, branch_ref_rc=0, close_rc=0):
    stdout, stderr, rc = _run_split(tmp_path, args, pr_exists=pr_exists,
                                    state_json=state_json, issue_pr=issue_pr,
                                    merge_rc=merge_rc, delete_rc=delete_rc,
                                    branch_ref_rc=branch_ref_rc, close_rc=close_rc)
    return stdout + stderr, rc


# REST pull objects (as `gh api repos/O/R/pulls/N` returns). state is lowercase;
# mergeable_state is "clean"/"dirty"/...; cross-repo is derived by comparing
# head.repo.full_name against base.repo.full_name.
_SAME_REPO = '"head":{"ref":"issue-5","repo":{"full_name":"owner/repo"}},"base":{"ref":"main","repo":{"full_name":"owner/repo","default_branch":"main"}},"draft":false'
_OPEN = '{"state":"open","merged":false,"mergeable_state":"clean",' + _SAME_REPO + '}'
_MERGED = '{"state":"closed","merged":true,"mergeable_state":"unknown",' + _SAME_REPO + '}'
_CONFLICT = '{"state":"open","merged":false,"mergeable_state":"dirty",' + _SAME_REPO + '}'
_CLOSED = '{"state":"closed","merged":false,"mergeable_state":"unknown",' + _SAME_REPO + '}'

# A PR that merges into a parent epic's shared integration branch (not the
# repo's default branch) and whose body declares it closes a sub-issue --
# the scenario where GitHub's own "Closes #N" keyword never fires (issue
# #734's #761/#762).
_INTEGRATION_BRANCH_SAME_REPO = (
    '"head":{"ref":"issue-761","repo":{"full_name":"owner/repo"}},'
    '"base":{"ref":"issue-734","repo":{"full_name":"owner/repo","default_branch":"main"}},'
    '"draft":false,"body":"Closes #761"'
)
_OPEN_INTO_INTEGRATION_BRANCH = (
    '{"state":"open","merged":false,"mergeable_state":"clean",' + _INTEGRATION_BRANCH_SAME_REPO + '}'
)
_MERGED_INTO_INTEGRATION_BRANCH = (
    '{"state":"closed","merged":true,"mergeable_state":"unknown",' + _INTEGRATION_BRANCH_SAME_REPO + '}'
)

# The same shape, but merging into the default branch directly -- GitHub's
# own keyword already covers this, so no explicit close should be issued.
_DEFAULT_BRANCH_WITH_CLOSES_BODY = (
    '"head":{"ref":"issue-5","repo":{"full_name":"owner/repo"}},'
    '"base":{"ref":"main","repo":{"full_name":"owner/repo","default_branch":"main"}},'
    '"draft":false,"body":"Closes #5"'
)
_OPEN_INTO_DEFAULT_WITH_CLOSES = (
    '{"state":"open","merged":false,"mergeable_state":"clean",' + _DEFAULT_BRANCH_WITH_CLOSES_BODY + '}'
)


class TestMergePr:
    def test_open_mergeable_pr_merges_and_deletes_branch(self, tmp_path):
        out, rc = _run(tmp_path, ["5"], pr_exists=0, state_json=_OPEN)
        assert rc == 0, out
        assert "Merged PR #5" in out
        assert "deleted branch 'issue-5'" in out

    def test_method_override_squash(self, tmp_path):
        out, rc = _run(tmp_path, ["5", "--squash"], pr_exists=0, state_json=_OPEN)
        assert rc == 0, out
        assert "(squash)" in out
        assert "deleted branch 'issue-5'" in out

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

    # --- Gherkin-traced: docs/features/merge-pr-sh.md ---

    def test_delete_denied_after_successful_merge(self, tmp_path):
        # Scenario: The head branch delete is denied after a successful merge
        # DELETE fails (non-zero) and the branch ref still exists (GET succeeds).
        stdout, stderr, rc = _run_split(
            tmp_path, ["5"], pr_exists=0, state_json=_OPEN,
            merge_rc=0, delete_rc=1, branch_ref_rc=0,
        )
        assert rc == 0, stdout + stderr
        assert "deleted branch" not in stdout
        assert "could not delete" in stderr
        assert "Merged PR #5" in stdout

    def test_no_api_error_body_in_stdout(self, tmp_path):
        # Scenario: No API error body reaches stdout
        # Mock DELETE prints to stdout; script must suppress it via >/dev/null.
        stdout, stderr, rc = _run_split(
            tmp_path, ["5"], pr_exists=0, state_json=_OPEN,
            merge_rc=0, delete_rc=1, branch_ref_rc=0,
        )
        assert rc == 0, stdout + stderr
        assert "MOCK-DELETE-REF" not in stdout

    def test_delete_succeeds_after_merge(self, tmp_path):
        # Scenario: The head branch delete succeeds
        stdout, stderr, rc = _run_split(
            tmp_path, ["5"], pr_exists=0, state_json=_OPEN,
            merge_rc=0, delete_rc=0,
        )
        assert rc == 0, stdout + stderr
        assert "Merged PR #5" in stdout
        assert "deleted branch 'issue-5'" in stdout

    def test_branch_already_gone_by_delete_branch_on_merge(self, tmp_path):
        # Scenario: The branch was already removed by delete_branch_on_merge
        # DELETE fails and the subsequent GET also fails (branch is gone).
        stdout, stderr, rc = _run_split(
            tmp_path, ["5"], pr_exists=0, state_json=_OPEN,
            merge_rc=0, delete_rc=1, branch_ref_rc=1,
        )
        assert rc == 0, stdout + stderr
        assert "already gone" in stdout
        assert "deleted branch" not in stdout

    def test_unmergeable_pr_fails_loudly(self, tmp_path):
        # Scenario: A PR that cannot be merged still fails loudly
        stdout, stderr, rc = _run_split(
            tmp_path, ["5"], pr_exists=0, state_json=_OPEN,
            merge_rc=1, delete_rc=0,
        )
        assert rc == 1, stdout + stderr
        assert "could not be merged" in stderr
        assert "Merged PR #5" not in stdout


class TestExplicitCloseForNonDefaultBaseMerge:
    """A PR's 'Closes #N' keyword only auto-fires on a merge to the
    repository's default branch (issue #734's #761/#762): a merge into any
    other branch -- e.g. a decomposed parent epic's shared integration
    branch -- must explicitly close the referenced issue itself, since
    GitHub never will.
    """

    def test_merge_into_non_default_branch_explicitly_closes_referenced_issue(self, tmp_path):
        out, rc = _run(
            tmp_path, ["761"], pr_exists=0, state_json=_OPEN_INTO_INTEGRATION_BRANCH,
        )
        assert rc == 0, out
        assert "Closed #761 explicitly" in out

    def test_merge_into_default_branch_does_not_explicitly_close(self, tmp_path):
        # GitHub's own keyword already covers a merge straight to main --
        # an explicit close here would be redundant (and double-announce).
        out, rc = _run(
            tmp_path, ["5"], pr_exists=0, state_json=_OPEN_INTO_DEFAULT_WITH_CLOSES,
        )
        assert rc == 0, out
        assert "MOCK-CLOSE-ISSUE" not in out
        assert "Closed #5 explicitly" not in out

    def test_already_merged_into_non_default_branch_still_closes_issue(self, tmp_path):
        # Idempotent re-run: the PR was already merged on a prior tick, but
        # the explicit close must still happen if it hasn't already (or be a
        # harmless no-op on the GitHub side if it has).
        out, rc = _run(
            tmp_path, ["761"], pr_exists=0, state_json=_MERGED_INTO_INTEGRATION_BRANCH,
        )
        assert rc == 0, out
        assert "Closed #761 explicitly" in out

    def test_close_failure_warns_but_does_not_fail_the_script(self, tmp_path):
        out, rc = _run(
            tmp_path, ["761"], pr_exists=0, state_json=_OPEN_INTO_INTEGRATION_BRANCH,
            close_rc=1,
        )
        assert rc == 0, out
        assert "WARNING: could not close #761" in out
        assert "Merged PR #761" in out
