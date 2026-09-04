"""Tests for issue #247: two-phase design->build delivery.

The design phase publishes the approved documentation to main via a design PR
(issue-{N}-docs, no Closes) that merges at the prd-docs-updater:approved gate;
the build phase then opens the code PR (issue-{N}, Closes) from the updated
main. Covers:

  - pipeline.json wires the two-phase chain in the right order,
  - the flow declares both pull requests and each step says which it
    commits to (issue #406 -- naming is declared, never computed),
  - the new scripts exist and delegate/behave correctly,
  - delete-branch.sh cleans up issue-{N}-docs.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
from pipeline_orchestrator import (
    AgentDef, WorkItem, _invoke_commit_after, load_pipeline,
)

REPO_ROOT = Path(__file__).parent.parent
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"
SCRIPTS = REPO_ROOT / ".github" / "scripts"
DELETE_BRANCH_SCRIPT = SCRIPTS / "delete-branch.sh"
MERGE_DOCS_PR_SCRIPT = SCRIPTS / "merge-docs-pr.sh"


def _agents_by_name():
    agents, _ = load_pipeline(PIPELINE_JSON)
    return {a.agent: a for a in agents}


# ---------------------------------------------------------------------------
# pipeline.json two-phase chain
# ---------------------------------------------------------------------------

class TestTwoPhaseChain:
    def test_design_to_build_trigger_order(self):
        """The design->build chain is wired in order via trigger labels."""
        a = _agents_by_name()
        # design phase
        assert a["01_product_docs/create-docs-pr"].trigger["label"] == "prd-writer:complete"
        assert a["01_product_docs/prd-docs-updater"].trigger["label"] == "create-docs-pr:complete"
        assert a["01_product_docs/merge-docs-pr"].trigger["label"] == "prd-docs-updater:complete"
        # build phase
        assert a["01_product_docs/create-pr"].trigger["label"] == "merge-docs-pr:complete"
        assert a["03_execute/coder"].trigger["label"] == "create-pr:complete"

    def test_dependencies_track_the_chain(self):
        a = _agents_by_name()
        assert a["01_product_docs/prd-docs-updater"].dependencies == ["01_product_docs/create-docs-pr"]
        assert a["01_product_docs/merge-docs-pr"].dependencies == ["01_product_docs/prd-docs-updater"]
        assert a["01_product_docs/create-pr"].dependencies == ["01_product_docs/merge-docs-pr"]
        assert a["03_execute/coder"].dependencies == ["01_product_docs/create-pr"]

    def test_new_steps_are_scripts_pointing_at_real_files(self):
        a = _agents_by_name()
        for name, script in (
            ("01_product_docs/create-docs-pr", "create-docs-pr.sh"),
            ("01_product_docs/merge-docs-pr", "merge-docs-pr.sh"),
        ):
            assert a[name].step_type == "script"
            assert a[name].script_path == f".github/scripts/{script}"
            assert (REPO_ROOT / a[name].script_path).is_file()

    def test_prd_docs_updater_gate_and_self_gates_unchanged(self):
        """The design gate stays on prd-docs-updater:approved with self_gates."""
        upd = _agents_by_name()["01_product_docs/prd-docs-updater"]
        assert upd.human_gate_after is True
        assert upd.human_gate_label == "prd-docs-updater:approved"
        assert upd.self_gates is True


# ---------------------------------------------------------------------------
# Flow naming: the design pull request and the code pull request (issue #406)
#
# The two phases are two pull requests DECLARED by one flow, not a suffix
# computed in code: the step says which of the flow's pull requests it commits
# to, and the flow says what that pull request's branch is called and whether
# it closes the issue.
# ---------------------------------------------------------------------------

class TestFlowNaming:
    def test_flow_declares_both_pull_requests(self):
        upd = _agents_by_name()["01_product_docs/prd-docs-updater"]
        assert upd.flow == "standard-delivery"
        assert upd.flow_naming["branch"] == "issue-{number}"
        prs = {pr["id"]: pr for pr in upd.flow_naming["pull_requests"]}
        assert prs["docs"]["branch"] == "issue-{number}-docs"
        assert prs["docs"]["closes_issue"] is False
        assert prs["code"]["branch"] == "issue-{number}"
        assert prs["code"]["closes_issue"] is True

    def test_design_steps_commit_to_the_docs_pull_request(self):
        a = _agents_by_name()
        for name in (
            "01_product_docs/create-docs-pr",
            "01_product_docs/prd-docs-updater",
            "01_product_docs/merge-docs-pr",
        ):
            assert a[name].commits_to == "docs", name

    def test_build_steps_commit_to_the_code_pull_request(self):
        a = _agents_by_name()
        assert a["01_product_docs/create-pr"].commits_to == "code"
        assert a["03_execute/coder"].commits_to == "code"

    def test_prd_docs_updater_resolves_to_the_design_branch(self):
        from pipeline_orchestrator import WorkItem, step_branch
        wi = WorkItem(number=247, kind="issue", title="t", labels=set(), url="u")
        assert step_branch(_agents_by_name()["01_product_docs/prd-docs-updater"], wi) == "issue-247-docs"

    def test_coder_resolves_to_the_code_branch(self):
        from pipeline_orchestrator import WorkItem, step_branch
        wi = WorkItem(number=247, kind="issue", title="t", labels=set(), url="u")
        assert step_branch(_agents_by_name()["03_execute/coder"], wi) == "issue-247"

    def test_ci_gate_without_commits_to_uses_the_flow_primary_branch(self):
        from pipeline_orchestrator import WorkItem, step_branch
        wi = WorkItem(number=247, kind="issue", title="t", labels=set(), url="u")
        assert step_branch(_agents_by_name()["03_execute/ci-gate"], wi) == "issue-247"

    def test_design_pr_does_not_close_the_issue_and_the_code_pr_does(self):
        from pipeline_orchestrator import step_pr_closes_issue
        a = _agents_by_name()
        assert step_pr_closes_issue(a["01_product_docs/create-docs-pr"]) is False
        assert step_pr_closes_issue(a["01_product_docs/create-pr"]) is True

    def test_steps_are_told_their_branch_and_closing_shape(self):
        import pipeline_orchestrator as orch
        from pipeline_orchestrator import WorkItem
        wi = WorkItem(number=247, kind="issue", title="t", labels=set(), url="u")
        env = orch._flow_context_env(_agents_by_name()["01_product_docs/create-docs-pr"], wi)
        assert env["AI_AGILE_BRANCH"] == "issue-247-docs"
        assert env["PR_CLOSES_ISSUE"] == "false"
        assert env["AI_AGILE_FLOW"] == "standard-delivery"
        env = orch._flow_context_env(_agents_by_name()["01_product_docs/create-pr"], wi)
        assert env["AI_AGILE_BRANCH"] == "issue-247"
        assert env["PR_CLOSES_ISSUE"] == "true"

    def test_no_step_declares_a_retired_branch_suffix(self):
        """branch_suffix is superseded by commits_to + the flow's naming."""
        raw = json.loads(PIPELINE_JSON.read_text())
        for flow in raw["flows"].values():
            for step in flow["steps"]:
                assert "branch_suffix" not in step, step["agent"]
        schema = json.loads((REPO_ROOT / "pipeline" / "schemas" / "pipeline.schema.json").read_text())
        assert "branch_suffix" not in schema["definitions"]["step"]["properties"]

    def test_schema_declares_flow_naming(self):
        schema = json.loads((REPO_ROOT / "pipeline" / "schemas" / "pipeline.schema.json").read_text())
        naming = schema["definitions"]["flow"]["properties"]["naming"]
        assert "branch" in naming["properties"]
        assert "pull_requests" in naming["properties"]
        assert "commits_to" in schema["definitions"]["step"]["properties"]["git_ops"]["properties"]


# ---------------------------------------------------------------------------
# create-docs-pr.sh delegates to create-pr.sh under its own identity
# ---------------------------------------------------------------------------

class TestCreateDocsPrWrapper:
    def test_delegates_under_its_own_announcement_identity(self):
        text = (SCRIPTS / "create-docs-pr.sh").read_text()
        assert 'CREATE_PR_AGENT="01_product_docs/create-docs-pr"' in text
        assert "create-pr.sh" in text

    def test_wrapper_no_longer_computes_the_design_branch_itself(self):
        """The branch and the non-closing body come from the flow, not the wrapper."""
        text = (SCRIPTS / "create-docs-pr.sh").read_text()
        assert "BRANCH_SUFFIX" not in text
        assert 'PR_CLOSES_ISSUE="false"' not in text

    def test_create_pr_takes_its_branch_and_closing_shape_from_the_flow(self):
        text = (SCRIPTS / "create-pr.sh").read_text()
        assert 'BRANCH="${AI_AGILE_BRANCH:?' in text
        assert 'PR_CLOSES_ISSUE="${PR_CLOSES_ISSUE:?' in text
        assert 'PR_BODY="Closes #${ISSUE_NUMBER}"' in text
        assert 'BRANCH="issue-${ISSUE_NUMBER}' not in text


# ---------------------------------------------------------------------------
# merge-docs-pr.sh idempotent no-PR path (subprocess, PATH-mocked gh)
# ---------------------------------------------------------------------------

class TestMergeDocsPrScript:
    def _run(self, tmp_path, issue_number, pr_list_output=""):
        mock_dir = tmp_path / "mocks"
        mock_dir.mkdir()
        mock_gh = mock_dir / "gh"
        # Mock gh: echo the configured pr-list output; succeed for every call.
        mock_gh.write_text(
            "#!/usr/bin/env bash\n"
            f"if [[ \"$1\" == \"pr\" && \"$2\" == \"list\" ]]; then echo '{pr_list_output}'; fi\n"
            "exit 0\n"
        )
        mock_gh.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ.get('PATH', '')}",
            "REPO": "owner/repo",
            "ISSUE_NUMBER": str(issue_number),
            # The design branch is declared by the flow and exported by the
            # orchestrator (issue #406), not derived inside the script.
            "AI_AGILE_BRANCH": f"issue-{issue_number}-docs",
        }
        env.pop("GITHUB_TOKEN", None)
        env.pop("GH_TOKEN", None)
        env.pop("AI_AGILE_BOT_TOKEN", None)
        result = subprocess.run(
            ["bash", str(MERGE_DOCS_PR_SCRIPT)],
            env=env, capture_output=True, text=True,
        )
        return result.stdout + result.stderr, result.returncode

    def test_no_open_design_pr_is_complete_and_idempotent(self, tmp_path):
        """No open issue-{N}-docs PR (already merged) -> complete, nothing merged."""
        output, rc = self._run(tmp_path, 247, pr_list_output="")
        assert rc == 0
        assert "AI_AGILE_STATUS: complete" in output
        assert "nothing to do" in output.lower()

    def test_rejects_non_integer_issue_number(self, tmp_path):
        output, rc = self._run(tmp_path, "not-a-number")
        assert rc != 0
        assert "not a valid integer" in output.lower()

    def _run_with_pr(self, tmp_path, mergeable="MERGEABLE", merge_exit=0, pr_number="5"):
        """Mock an OPEN design PR; configure its mergeable state and merge exit."""
        mock_dir = tmp_path / "mocks"
        mock_dir.mkdir()
        mock_gh = mock_dir / "gh"
        # Map the old GraphQL mergeable values onto REST mergeable_state.
        mergeable_state = "dirty" if mergeable == "CONFLICTING" else "clean"
        mock_gh.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "api" ]]; then\n'
            '  args="$*"\n'
            '  case "$args" in\n'
            # Merge (PUT .../pulls/N/merge): succeed or fail per merge_exit.
            f'    *"--method PUT"*"/merge"*) exit {merge_exit} ;;\n'
            # Best-effort branch ref delete.
            '    *"--method DELETE"*) exit 0 ;;\n'
            # Resolve the open design PR by head branch.
            f'    *"pulls?head="*) echo "{pr_number}" ;;\n'
            # Idempotency check on issue comments.
            '    *"/comments"*) echo "0" ;;\n'
            # Read the PR mergeable_state.
            f'    *"mergeable_state"*) echo "{mergeable_state}" ;;\n'
            "  esac\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        )
        mock_gh.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ.get('PATH', '')}",
            "REPO": "owner/repo",
            "ISSUE_NUMBER": "247",
            "AI_AGILE_BRANCH": "issue-247-docs",
            "GITHUB_TOKEN": "x",
        }
        result = subprocess.run(
            ["bash", str(MERGE_DOCS_PR_SCRIPT)],
            env=env, capture_output=True, text=True,
        )
        return result.stdout + result.stderr, result.returncode

    def test_conflicting_design_pr_emits_review_not_merge(self, tmp_path):
        """A design PR conflicting with main must emit review, never force a merge."""
        out, rc = self._run_with_pr(tmp_path, mergeable="CONFLICTING")
        assert rc == 0
        assert "AI_AGILE_STATUS: review" in out
        assert "AI_AGILE_STATUS: complete" not in out
        assert "conflict" in out.lower()

    def test_merge_failure_emits_review(self, tmp_path):
        """A blocked/failed `gh pr merge` must emit review, not silently pass."""
        out, rc = self._run_with_pr(tmp_path, mergeable="MERGEABLE", merge_exit=1)
        assert rc == 0
        assert "AI_AGILE_STATUS: review" in out
        assert "AI_AGILE_STATUS: complete" not in out
        assert "could not be merged" in out.lower()

    def test_clean_design_pr_merges_and_completes(self, tmp_path):
        """A mergeable design PR is merged and the step completes."""
        out, rc = self._run_with_pr(tmp_path, mergeable="MERGEABLE", merge_exit=0)
        assert rc == 0
        assert "AI_AGILE_STATUS: complete" in out
        assert "merged design pr" in out.lower()


# ---------------------------------------------------------------------------
# delete-branch.sh cleans up the design branch issue-{N}-docs
# ---------------------------------------------------------------------------

class TestDeleteDesignBranch:
    def _run(self, tmp_path, branch, gh_exit=0, gh_output=""):
        mock_dir = tmp_path / "mocks"
        mock_dir.mkdir()
        mock_gh = mock_dir / "gh"
        mock_gh.write_text(f"#!/usr/bin/env bash\necho '{gh_output}'\nexit {gh_exit}\n")
        mock_gh.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ.get('PATH', '')}",
            "REPO": "owner/repo",
            "BRANCH": branch,
        }
        result = subprocess.run(
            ["bash", str(DELETE_BRANCH_SCRIPT)],
            env=env, capture_output=True, text=True,
        )
        return result.stdout + result.stderr, result.returncode

    def test_design_branch_is_deleted(self, tmp_path):
        """issue-{N}-docs matches the delete pattern and is removed."""
        output, rc = self._run(tmp_path, "issue-247-docs", gh_exit=0)
        assert rc == 0
        assert "AI_AGILE_STATUS: complete" in output
        assert "skipping" not in output.lower()

    def test_unrelated_docs_branch_is_skipped(self, tmp_path):
        """A branch that merely ends in -docs but is not issue-{N}-docs is skipped."""
        output, rc = self._run(tmp_path, "feature-docs")
        assert rc == 0
        assert "skipping" in output.lower()


# ---------------------------------------------------------------------------
# commit_after passes branch_suffix through to commit-agent-work.sh (issue #273)
# ---------------------------------------------------------------------------

COMMIT_AGENT_WORK_SCRIPT = SCRIPTS / "commit-agent-work.sh"


class TestCommitAfterUsesTheFlowsBranch:
    """_invoke_commit_after hands the script the branch the step's flow
    declares, so design commits land on issue-{N}-docs and code commits on
    issue-{N} -- the same two destinations as before, now declared rather
    than computed."""

    def _captured_env(self, name):
        agent = _agents_by_name()[name]
        work_item = WorkItem(
            number=247, kind="issue", title="t", labels=set(), url="u",
        )
        with patch(
            "pipeline_orchestrator.subprocess.run",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ) as run:
            result = _invoke_commit_after(agent, work_item)
        assert result is None
        assert run.call_count == 1
        return run.call_args.kwargs["env"]

    def test_design_step_commits_to_the_design_branch(self):
        env = self._captured_env("01_product_docs/prd-docs-updater")
        assert env["AI_AGILE_BRANCH"] == "issue-247-docs"
        assert env["ISSUE_NUMBER"] == "247"

    def test_code_step_commits_to_the_code_branch(self):
        env = self._captured_env("03_execute/coder")
        assert env["AI_AGILE_BRANCH"] == "issue-247"
        assert env["ISSUE_NUMBER"] == "247"

    def test_commit_after_fails_loud_without_a_declared_branch(self):
        """A committing step whose flow declares no branch is a broken
        declaration, not a run against a guessed name (STD-ARCH-014)."""
        agent = AgentDef(
            agent="03_execute/coder", phase="03_execute", objects=["issue"],
            trigger={}, dependencies=[], human_gate_after=False,
            human_gate_label=None, description="t", commit_after=True,
            flow="nameless-flow",
        )
        work_item = WorkItem(number=247, kind="issue", title="t", labels=set(), url="u")
        with patch("pipeline_orchestrator.subprocess.run") as run:
            result = _invoke_commit_after(agent, work_item)
        assert result is not None and "no naming.branch" in result
        run.assert_not_called()


class TestCommitAgentWorkBranchDerivation:
    """The script takes the branch it is given; it never derives one."""

    def test_branch_comes_from_the_orchestrator(self):
        text = COMMIT_AGENT_WORK_SCRIPT.read_text()
        assert 'BRANCH="${AI_AGILE_BRANCH:?' in text
        assert 'BRANCH="issue-${ISSUE_NUMBER}' not in text
