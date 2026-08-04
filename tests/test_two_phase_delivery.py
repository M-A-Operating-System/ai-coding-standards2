"""Tests for issue #247: two-phase design->build delivery.

The design phase publishes the approved documentation to main via a design PR
(issue-{N}-docs, no Closes) that merges at the prd-docs-updater:approved gate;
the build phase then opens the code PR (issue-{N}, Closes) from the updated
main. Covers:

  - pipeline.json wires the two-phase chain in the right order,
  - prd-docs-updater targets the design branch via branch_suffix,
  - load_pipeline parses branch_suffix (and defaults it to ""),
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
from pipeline_orchestrator import AgentDef, _invoke_commit_after, load_pipeline

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
# branch_suffix: design branch vs code branch
# ---------------------------------------------------------------------------

class TestBranchSuffix:
    def test_prd_docs_updater_targets_design_branch(self):
        assert _agents_by_name()["01_product_docs/prd-docs-updater"].branch_suffix == "-docs"

    def test_coder_targets_code_branch_by_default(self):
        assert _agents_by_name()["03_execute/coder"].branch_suffix == ""

    def test_load_pipeline_defaults_branch_suffix_to_empty(self, tmp_path):
        pipeline_data = {"pipeline": [{
            "agent": "01_product_docs/issue-classifier",
            "phase": "01_product_docs",
            "object": ["issue"],
            "trigger": {"event": "issue.opened"},
            "dependencies": [],
            "human_gate_after": False,
            "description": "test",
        }]}
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        agents, _ = load_pipeline(path)
        assert agents[0].branch_suffix == ""

    def test_load_pipeline_reads_branch_suffix(self, tmp_path):
        pipeline_data = {"pipeline": [{
            "agent": "01_product_docs/prd-docs-updater",
            "phase": "01_product_docs",
            "object": ["issue"],
            "trigger": {"label": "create-docs-pr:complete"},
            "dependencies": [],
            "human_gate_after": True,
            "human_gate_label": "prd-docs-updater:approved",
            "branch_suffix": "-docs",
            "description": "test",
        }]}
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        agents, _ = load_pipeline(path)
        assert agents[0].branch_suffix == "-docs"

    def test_branch_suffix_in_schema(self):
        """The schema permits branch_suffix (additionalProperties is false)."""
        schema = json.loads((REPO_ROOT / "pipeline" / "schemas" / "pipeline.schema.json").read_text())
        assert "branch_suffix" in schema["definitions"]["agent"]["properties"]


# ---------------------------------------------------------------------------
# create-docs-pr.sh delegates to create-pr.sh with the design-phase params
# ---------------------------------------------------------------------------

class TestCreateDocsPrWrapper:
    def test_sets_design_phase_params_and_delegates(self):
        text = (SCRIPTS / "create-docs-pr.sh").read_text()
        assert 'BRANCH_SUFFIX="-docs"' in text
        assert 'PR_CLOSES_ISSUE="false"' in text
        assert 'CREATE_PR_AGENT="01_product_docs/create-docs-pr"' in text
        assert "create-pr.sh" in text

    def test_create_pr_defaults_preserve_code_pr_behaviour(self):
        """create-pr.sh keeps issue-{N} + Closes when the design params are unset."""
        text = (SCRIPTS / "create-pr.sh").read_text()
        assert 'BRANCH_SUFFIX="${BRANCH_SUFFIX:-}"' in text
        assert 'PR_CLOSES_ISSUE="${PR_CLOSES_ISSUE:-true}"' in text
        assert 'PR_BODY="Closes #${ISSUE_NUMBER}"' in text


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
        mock_gh.write_text(
            "#!/usr/bin/env bash\n"
            'case "$1 $2" in\n'
            f'  "pr list") echo "{pr_number}" ;;\n'
            f'  "pr view") echo "{mergeable}" ;;\n'
            f'  "pr merge") exit {merge_exit} ;;\n'
            '  "issue view") echo "0" ;;\n'
            "esac\n"
            "exit 0\n"
        )
        mock_gh.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ.get('PATH', '')}",
            "REPO": "owner/repo",
            "ISSUE_NUMBER": "247",
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


def _commit_after_agent(branch_suffix: str, name: str) -> AgentDef:
    """Minimal commit_after AgentDef carrying a branch_suffix."""
    return AgentDef(
        agent=name,
        phase=name.split("/")[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
        commit_after=True,
        branch_suffix=branch_suffix,
    )


class TestCommitAfterBranchSuffix:
    """_invoke_commit_after must forward branch_suffix so docs commits land on
    issue-{N}-docs, not the not-yet-existing issue-{N} code branch."""

    def _captured_env(self, branch_suffix, name):
        agent = _commit_after_agent(branch_suffix, name)
        work_item = MagicMock()
        work_item.number = 247
        with patch(
            "pipeline_orchestrator.subprocess.run",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ) as run:
            result = _invoke_commit_after(agent, work_item)
        assert result is None
        assert run.call_count == 1
        return run.call_args.kwargs["env"]

    def test_design_step_forwards_docs_suffix(self):
        """prd-docs-updater (branch_suffix="-docs") resolves to issue-{N}-docs."""
        env = self._captured_env("-docs", "01_product_docs/prd-docs-updater")
        assert env["BRANCH_SUFFIX"] == "-docs"
        assert f"issue-{env['ISSUE_NUMBER']}{env['BRANCH_SUFFIX']}" == "issue-247-docs"

    def test_code_step_forwards_empty_suffix(self):
        """The coder (default empty suffix) resolves to issue-{N}, unchanged."""
        env = self._captured_env("", "03_execute/coder")
        assert env["BRANCH_SUFFIX"] == ""
        assert f"issue-{env['ISSUE_NUMBER']}{env['BRANCH_SUFFIX']}" == "issue-247"


class TestCommitAgentWorkBranchDerivation:
    """The script itself must honour BRANCH_SUFFIX when deriving BRANCH."""

    def test_branch_line_uses_optional_suffix(self):
        text = COMMIT_AGENT_WORK_SCRIPT.read_text()
        assert 'BRANCH="issue-${ISSUE_NUMBER}${BRANCH_SUFFIX:-}"' in text
