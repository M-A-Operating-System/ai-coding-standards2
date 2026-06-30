"""Tests for issue #126: explicit branch cleanup when PRs close.

Covers three PRD Gherkin scenarios:
  - Branch deleted when PR merges
  - Branch deleted when PR is closed without merging
  - Non-issue branch is ignored
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
from pipeline_orchestrator import (
    _call_delete_branch,
    _read_pr_event_action,
    _wake,
    SUBMODULE_ROOT,
)

REPO_ROOT = Path(__file__).parent.parent
DELETE_BRANCH_SCRIPT = REPO_ROOT / ".github" / "scripts" / "delete-branch.sh"


# ---------------------------------------------------------------------------
# _read_pr_event_action helpers
# ---------------------------------------------------------------------------

class TestReadPrEventAction:
    def test_returns_closed_from_event_file(self, tmp_path):
        """_read_pr_event_action reads 'closed' from the GitHub event JSON."""
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps({"action": "closed", "number": 42}))
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_file)}):
            assert _read_pr_event_action() == "closed"

    def test_returns_opened_from_event_file(self, tmp_path):
        """_read_pr_event_action returns other actions correctly."""
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps({"action": "opened"}))
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_file)}):
            assert _read_pr_event_action() == "opened"

    def test_returns_empty_string_when_env_not_set(self):
        """_read_pr_event_action returns '' when GITHUB_EVENT_PATH is absent."""
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_EVENT_PATH"}
        with patch.dict(os.environ, env, clear=True):
            assert _read_pr_event_action() == ""

    def test_returns_empty_string_on_missing_file(self, tmp_path):
        """_read_pr_event_action returns '' when the event file does not exist."""
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(tmp_path / "missing.json")}):
            assert _read_pr_event_action() == ""

    def test_returns_empty_string_on_malformed_json(self, tmp_path):
        """_read_pr_event_action returns '' when the event file contains invalid JSON."""
        event_file = tmp_path / "event.json"
        event_file.write_text("not-json{{{")
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_file)}):
            assert _read_pr_event_action() == ""

    def test_returns_empty_string_when_action_key_absent(self, tmp_path):
        """_read_pr_event_action returns '' when the JSON has no 'action' key."""
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps({"number": 42}))
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_file)}):
            assert _read_pr_event_action() == ""


# ---------------------------------------------------------------------------
# _call_delete_branch helpers
# ---------------------------------------------------------------------------

class TestCallDeleteBranch:
    def test_skips_when_branch_is_empty(self, caplog):
        """_call_delete_branch logs a warning and returns without invoking the script."""
        with patch("pipeline_orchestrator.subprocess.run") as mock_run:
            _call_delete_branch("owner/repo", "")
            mock_run.assert_not_called()

    def test_skips_when_repo_is_empty(self, caplog):
        """_call_delete_branch logs a warning and returns without invoking the script."""
        with patch("pipeline_orchestrator.subprocess.run") as mock_run:
            _call_delete_branch("", "issue-42")
            mock_run.assert_not_called()

    def test_invokes_script_with_correct_env(self, tmp_path):
        """_call_delete_branch calls delete-branch.sh with REPO and BRANCH in env."""
        fake_script = tmp_path / ".github" / "scripts" / "delete-branch.sh"
        fake_script.parent.mkdir(parents=True)
        fake_script.write_text("#!/usr/bin/env bash\nexit 0\n")

        captured_env = {}

        def capture_run(cmd, *, env, **kwargs):
            captured_env.update(env)
            result = MagicMock()
            result.returncode = 0
            result.stdout = "Branch 'issue-42' deleted.\nAI_AGILE_STATUS: complete"
            result.stderr = ""
            return result

        with patch("pipeline_orchestrator.SUBMODULE_ROOT", tmp_path):
            with patch("pipeline_orchestrator.subprocess.run", side_effect=capture_run):
                _call_delete_branch("owner/repo", "issue-42")

        assert captured_env.get("REPO") == "owner/repo"
        assert captured_env.get("BRANCH") == "issue-42"

    def test_does_not_raise_on_timeout(self, tmp_path):
        """_call_delete_branch swallows TimeoutExpired and does not propagate it."""
        fake_script = tmp_path / ".github" / "scripts" / "delete-branch.sh"
        fake_script.parent.mkdir(parents=True)
        fake_script.write_text("#!/usr/bin/env bash\nexit 0\n")

        with patch("pipeline_orchestrator.SUBMODULE_ROOT", tmp_path):
            with patch(
                "pipeline_orchestrator.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["bash"], 60),
            ):
                _call_delete_branch("owner/repo", "issue-42")  # must not raise

    def test_does_not_raise_on_oserror(self, tmp_path):
        """_call_delete_branch swallows OSError (e.g. bash not in PATH)."""
        fake_script = tmp_path / ".github" / "scripts" / "delete-branch.sh"
        fake_script.parent.mkdir(parents=True)
        fake_script.write_text("#!/usr/bin/env bash\nexit 0\n")

        with patch("pipeline_orchestrator.SUBMODULE_ROOT", tmp_path):
            with patch(
                "pipeline_orchestrator.subprocess.run",
                side_effect=OSError("bash not found"),
            ):
                _call_delete_branch("owner/repo", "issue-42")  # must not raise

    def test_logs_warning_when_script_missing(self, caplog, tmp_path):
        """_call_delete_branch logs a warning when delete-branch.sh is absent."""
        import logging

        empty_dir = tmp_path / "no-scripts"
        empty_dir.mkdir()
        with patch("pipeline_orchestrator.SUBMODULE_ROOT", empty_dir):
            with caplog.at_level(logging.WARNING, logger="orchestrator"):
                _call_delete_branch("owner/repo", "issue-42")

        assert any("not found" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _wake — pull_request.closed path
# ---------------------------------------------------------------------------

def _minimal_wake_args(**overrides):
    """Return a minimal argparse.Namespace for _wake testing."""
    defaults = dict(
        clear_pause=False,
        clear_stop=False,
        repo="owner/repo",
        issue=None,
        kind=None,
        dry_run=False,
        pipeline=REPO_ROOT / "pipeline" / "pipeline.json",
        phases=None,
        verbose=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestWakePullRequestClosed:
    """Scenario: Branch deleted when PR merges / closed without merging."""

    def test_wake_returns_none_on_pr_closed(self, tmp_path):
        """_wake returns None immediately when pull_request.closed fires."""
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps({"action": "closed"}))
        args = _minimal_wake_args()

        env_patch = {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_HEAD_REF": "issue-42",
            "GITHUB_EVENT_PATH": str(event_file),
        }
        with patch.dict(os.environ, env_patch):
            with patch("pipeline_orchestrator._call_delete_branch") as mock_delete:
                result = _wake(args)

        assert result is None, "_wake must return None for pull_request.closed (no pipeline work)"
        mock_delete.assert_called_once_with("owner/repo", "issue-42")

    def test_wake_calls_delete_with_github_head_ref(self, tmp_path):
        """_wake passes GITHUB_HEAD_REF as the branch to _call_delete_branch."""
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps({"action": "closed"}))
        args = _minimal_wake_args()

        env_patch = {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_HEAD_REF": "issue-99",
            "GITHUB_EVENT_PATH": str(event_file),
        }
        with patch.dict(os.environ, env_patch):
            with patch("pipeline_orchestrator._call_delete_branch") as mock_delete:
                _wake(args)

        _, called_branch = mock_delete.call_args[0]
        assert called_branch == "issue-99"

    def test_wake_does_not_short_circuit_on_pr_opened(self, tmp_path):
        """_wake does NOT short-circuit for pull_request events with action != closed."""
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps({"action": "opened"}))
        args = _minimal_wake_args()

        env_patch = {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_HEAD_REF": "issue-42",
            "GITHUB_EVENT_PATH": str(event_file),
        }
        with patch.dict(os.environ, env_patch):
            with patch("pipeline_orchestrator._call_delete_branch") as mock_delete:
                with patch("pipeline_orchestrator.is_pipeline_paused", return_value=(True, "paused", None)):
                    # Pipeline is paused → _wake returns None for the pause, not for PR close
                    result = _wake(args)

        # _call_delete_branch must NOT have been called (action was "opened", not "closed")
        mock_delete.assert_not_called()

    def test_wake_handles_missing_github_head_ref(self, tmp_path):
        """_wake passes empty string to _call_delete_branch when GITHUB_HEAD_REF is unset."""
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps({"action": "closed"}))
        args = _minimal_wake_args()

        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_HEAD_REF",)}
        env["GITHUB_EVENT_NAME"] = "pull_request"
        env["GITHUB_EVENT_PATH"] = str(event_file)

        with patch.dict(os.environ, env, clear=True):
            with patch("pipeline_orchestrator._call_delete_branch") as mock_delete:
                result = _wake(args)

        assert result is None
        mock_delete.assert_called_once_with("owner/repo", "")

    def test_wake_non_pr_event_does_not_short_circuit(self, tmp_path):
        """_wake does not short-circuit for non-pull_request events."""
        args = _minimal_wake_args()

        env_patch = {"GITHUB_EVENT_NAME": "issues"}
        with patch.dict(os.environ, env_patch):
            with patch("pipeline_orchestrator._call_delete_branch") as mock_delete:
                with patch("pipeline_orchestrator.is_pipeline_paused", return_value=(True, "paused", None)):
                    result = _wake(args)

        mock_delete.assert_not_called()
        # result is None because of the pause check, not the PR-closed path


# ---------------------------------------------------------------------------
# delete-branch.sh script tests (subprocess-based, PATH-mocked)
# ---------------------------------------------------------------------------

class TestDeleteBranchScript:
    """Scenario: Non-issue branch is ignored (and script-level happy/error paths)."""

    def _run_script(self, tmp_path, repo, branch, gh_exit=0, gh_output=""):
        """Run delete-branch.sh with a mock gh binary and return (stdout, returncode)."""
        mock_dir = tmp_path / "mocks"
        mock_dir.mkdir()
        mock_gh = mock_dir / "gh"
        mock_gh.write_text(
            f"#!/usr/bin/env bash\n"
            f"echo '{gh_output}'\n"
            f"exit {gh_exit}\n"
        )
        mock_gh.chmod(0o755)

        env = {
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ.get('PATH', '')}",
            "REPO": repo,
            "BRANCH": branch,
        }
        result = subprocess.run(
            ["bash", str(DELETE_BRANCH_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
        )
        return result.stdout + result.stderr, result.returncode

    def test_non_issue_branch_is_skipped(self, tmp_path):
        """Scenario: Non-issue branch is ignored — script exits 0 without calling gh."""
        output, rc = self._run_script(tmp_path, "owner/repo", "claude/some-feature")
        assert rc == 0
        assert "AI_AGILE_STATUS: complete" in output
        assert "skipping" in output.lower()

    def test_main_branch_is_skipped(self, tmp_path):
        """main branch does not match issue-{N} — skipped silently."""
        output, rc = self._run_script(tmp_path, "owner/repo", "main")
        assert rc == 0
        assert "AI_AGILE_STATUS: complete" in output

    def test_issue_branch_deleted_on_success(self, tmp_path):
        """Scenario: Branch deleted when PR merges — gh DELETE succeeds."""
        output, rc = self._run_script(tmp_path, "owner/repo", "issue-42", gh_exit=0)
        assert rc == 0
        assert "AI_AGILE_STATUS: complete" in output

    def test_issue_branch_idempotent_when_already_deleted(self, tmp_path):
        """Scenario: Branch deleted when PR closed — gh DELETE fails (already gone) → still exits 0."""
        output, rc = self._run_script(tmp_path, "owner/repo", "issue-42", gh_exit=1)
        assert rc == 0, (
            "delete-branch.sh must exit 0 even when gh api returns non-zero "
            "(idempotency — branch may already be gone)"
        )
        assert "AI_AGILE_STATUS: complete" in output

    def test_requires_repo_env_var(self, tmp_path):
        """Missing REPO causes a non-zero exit (guard clause)."""
        mock_dir = tmp_path / "mocks"
        mock_dir.mkdir()
        mock_gh = mock_dir / "gh"
        mock_gh.write_text("#!/usr/bin/env bash\nexit 0\n")
        mock_gh.chmod(0o755)

        env = {
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ.get('PATH', '')}",
            "BRANCH": "issue-42",
        }
        env.pop("REPO", None)

        result = subprocess.run(
            ["bash", str(DELETE_BRANCH_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "delete-branch.sh must exit non-zero when REPO is unset"

    def test_requires_branch_env_var(self, tmp_path):
        """Missing BRANCH causes a non-zero exit (guard clause)."""
        mock_dir = tmp_path / "mocks"
        mock_dir.mkdir()
        mock_gh = mock_dir / "gh"
        mock_gh.write_text("#!/usr/bin/env bash\nexit 0\n")
        mock_gh.chmod(0o755)

        env = {
            **os.environ,
            "PATH": f"{mock_dir}:{os.environ.get('PATH', '')}",
            "REPO": "owner/repo",
        }
        env.pop("BRANCH", None)

        result = subprocess.run(
            ["bash", str(DELETE_BRANCH_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "delete-branch.sh must exit non-zero when BRANCH is unset"
