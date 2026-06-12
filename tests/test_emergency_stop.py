"""Tests for emergency stop functionality in pipeline_orchestrator.py."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import pipeline_orchestrator
from pipeline_orchestrator import (
    is_pipeline_stopped,
    clear_stop,
)


# ---------------------------------------------------------------------------
# TestIsPipelineStopped
# ---------------------------------------------------------------------------

class TestIsPipelineStopped:
    def test_returns_false_when_no_marker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        stopped, reason = is_pipeline_stopped()
        assert stopped is False
        assert reason == ""

    def test_returns_true_with_reason_when_marker_exists(self, tmp_path, monkeypatch):
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "bad prompt deployed",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped is True
        assert reason == "bad prompt deployed"

    def test_no_auto_expiry(self, tmp_path, monkeypatch):
        """Stop marker has no time field and must never be auto-deleted."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2020-01-01T00:00:00Z",
            "reason": "old stop from the past",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped is True
        assert reason == "old stop from the past"
        assert marker_path.exists(), "Stop marker must NOT be auto-deleted"

    def test_malformed_marker_returns_stopped_true(self, tmp_path, monkeypatch):
        """Malformed JSON in marker defaults to stopped (fail-safe)."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text("this is not json {{{")
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped is True

    def test_missing_reason_field_returns_default(self, tmp_path, monkeypatch):
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({"stopped_at": "2026-06-01T00:00:00Z"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped is True
        assert reason == "pipeline stopped"


# ---------------------------------------------------------------------------
# TestClearStop
# ---------------------------------------------------------------------------

class TestClearStop:
    def test_clear_stop_clears_marker_and_returns_true(self, tmp_path, monkeypatch):
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({"reason": "test stop"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        result = clear_stop()
        assert result is True
        assert not marker_path.exists()

    def test_clear_stop_returns_false_when_no_marker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        result = clear_stop()
        assert result is False

    def test_clear_stop_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        assert clear_stop() is False
        assert clear_stop() is False


# ---------------------------------------------------------------------------
# TestMainStopMarkerBehavior
# ---------------------------------------------------------------------------

class TestMainStopMarkerBehavior:
    """Tests that main() respects the stop marker."""

    def _make_args(self, **kwargs):
        args = MagicMock()
        args.clear_pause = False
        args.clear_stop = False
        args.repo = "test/repo"
        args.verbose = False
        args.dry_run = False
        args.issue = None
        args.pipeline = Path("pipeline/pipeline.json")
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def test_main_exits_early_when_stopped(self, tmp_path, monkeypatch):
        """When stop marker exists, main() must not load the pipeline or invoke agents."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "test stop",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        load_called = []

        def fake_load(path):
            load_called.append(True)
            return [], []

        with patch.object(pipeline_orchestrator, "parse_args", return_value=self._make_args()), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load), \
             patch.object(pipeline_orchestrator, "write_audit_log"), \
             patch.object(pipeline_orchestrator, "GitHubClient"), \
             patch.object(pipeline_orchestrator, "_configure_git_auth"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert not load_called, "load_pipeline must not be called when stop marker is set"

    def test_main_emits_emergency_stop_audit_event(self, tmp_path, monkeypatch):
        """When stop marker is detected, a system.emergency_stop audit event is emitted."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "billing control",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        written_events = []

        def capture_write(gh, events):
            written_events.extend(events)

        with patch.object(pipeline_orchestrator, "parse_args", return_value=self._make_args()), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "write_audit_log", side_effect=capture_write), \
             patch.object(pipeline_orchestrator, "GitHubClient"), \
             patch.object(pipeline_orchestrator, "_configure_git_auth"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        event_types = [e.get("event_type") for e in written_events]
        assert "system.emergency_stop" in event_types, (
            f"Expected system.emergency_stop audit event; got {event_types}"
        )

    def test_main_proceeds_when_not_stopped(self, tmp_path, monkeypatch):
        """When no stop marker exists, main() proceeds to load the pipeline."""
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")

        loaded = []

        def fake_load(path):
            loaded.append(True)
            return [], []

        with patch.object(pipeline_orchestrator, "parse_args", return_value=self._make_args()), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load), \
             patch.object(pipeline_orchestrator, "write_audit_log"), \
             patch.object(pipeline_orchestrator, "GitHubClient") as MockGH, \
             patch.object(pipeline_orchestrator, "_configure_git_auth"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            MockGH.return_value.list_open_issues.return_value = []
            pipeline_orchestrator.main()

        assert loaded, "load_pipeline must be called when no stop marker is set"

    def test_stop_marker_not_auto_cleared_between_main_calls(self, tmp_path, monkeypatch):
        """Stop marker must persist across multiple orchestrator invocations."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({"reason": "persistent stop"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        for _ in range(2):
            with patch.object(pipeline_orchestrator, "parse_args", return_value=self._make_args()), \
                 patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
                 patch.object(pipeline_orchestrator, "write_audit_log"), \
                 patch.object(pipeline_orchestrator, "GitHubClient"), \
                 patch.object(pipeline_orchestrator, "_configure_git_auth"), \
                 patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
                pipeline_orchestrator.main()

        assert marker_path.exists(), (
            "Stop marker must not be auto-cleared after orchestrator runs"
        )

    def test_clear_stop_flag_clears_marker_and_exits(self, tmp_path, monkeypatch):
        """--clear-stop clears the marker and exits without loading the pipeline."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({"reason": "test"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        loaded = []

        def fake_load(path):
            loaded.append(True)
            return [], []

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=self._make_args(clear_stop=True)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load):
            pipeline_orchestrator.main()

        assert not marker_path.exists(), "--clear-stop must delete the stop marker"
        assert not loaded, "--clear-stop must exit before loading the pipeline"


# ---------------------------------------------------------------------------
# TestWorkflowProposals
# ---------------------------------------------------------------------------

class TestWorkflowProposals:
    """Verify the workflow proposal files exist with the required inputs."""

    def _read_workflow(self, name: str) -> str:
        path = Path(__file__).parent.parent / "docs/workflow-proposals" / name
        assert path.exists(), f"Workflow proposal not found at {path}"
        return path.read_text()

    def test_emergency_stop_workflow_exists(self):
        content = self._read_workflow("pipeline-emergency-stop.yml")
        assert "workflow_dispatch" in content

    def test_emergency_stop_workflow_has_reason_input(self):
        content = self._read_workflow("pipeline-emergency-stop.yml")
        assert "reason" in content

    def test_emergency_stop_workflow_has_cancel_runs_input(self):
        content = self._read_workflow("pipeline-emergency-stop.yml")
        assert "cancel_runs" in content

    def test_restart_workflow_exists(self):
        content = self._read_workflow("pipeline-restart.yml")
        assert "workflow_dispatch" in content

    def test_restart_workflow_has_trigger_run_input(self):
        content = self._read_workflow("pipeline-restart.yml")
        assert "trigger_run" in content
