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
    _check_controls,
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
             patch.object(pipeline_orchestrator, "_emit_audit_event"), \
             patch.object(pipeline_orchestrator, "GitHubClient"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert not load_called, "load_pipeline must not be called when stop marker is set"

    def test_main_emits_emergency_stop_audit_event(self, tmp_path, monkeypatch, capsys):
        """When stop marker is detected, a system.emergency_stop audit event is printed."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "billing control",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        with patch.object(pipeline_orchestrator, "parse_args", return_value=self._make_args()), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "GitHubClient"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        import json as _json
        lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
        event_types = []
        for line in lines:
            try:
                event_types.append(_json.loads(line).get("event"))
            except _json.JSONDecodeError:
                pass
        assert "system.emergency_stop" in event_types, (
            f"Expected system.emergency_stop audit event in stdout; got {event_types}"
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
             patch.object(pipeline_orchestrator, "_emit_audit_event"), \
             patch.object(pipeline_orchestrator, "GitHubClient") as MockGH, \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
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
                 patch.object(pipeline_orchestrator, "_emit_audit_event"), \
                 patch.object(pipeline_orchestrator, "GitHubClient"), \
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

    def test_stop_marker_detected_mid_loop(self, tmp_path, monkeypatch):
        """Stop detected at entry of process_work_item() must prevent all work for that item.

        Under the refactored architecture, _check_controls() is called once per work item
        at the top of process_work_item(). When it returns "stop", the function returns 0
        immediately — before promote_gated_agents or any agent invocation.
        """
        marker_path = tmp_path / ".pipeline-stop"
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        call_count = 0

        def fake_is_stopped():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (False, "")   # startup check in main() — not stopped
            return (True, "mid-run stop")  # per-item check via _check_controls() — stopped

        promote_calls = []

        def fake_promote(labels, agents, work_item, gh, **kw):
            promote_calls.append(work_item)
            return labels

        wi1 = MagicMock()
        wi1.labels = set()
        wi1.number = 1
        wi2 = MagicMock()
        wi2.labels = set()
        wi2.number = 2

        gh_mock = MagicMock()
        gh_mock.list_open_issues.return_value = [wi1, wi2]

        with patch.object(pipeline_orchestrator, "parse_args", return_value=self._make_args()), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "is_pipeline_stopped", side_effect=fake_is_stopped), \
             patch.object(pipeline_orchestrator, "load_pipeline", return_value=([], [])), \
             patch.object(pipeline_orchestrator, "GitHubClient", return_value=gh_mock), \
             patch.object(pipeline_orchestrator, "promote_gated_agents", side_effect=fake_promote), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert len(promote_calls) == 0, (
            "promote_gated_agents must not be called when _check_controls() returns 'stop'; "
            f"got {len(promote_calls)} call(s)"
        )


# ---------------------------------------------------------------------------
# TestCheckControls
# ---------------------------------------------------------------------------

class TestCheckControls:
    """Tests for the consolidated _check_controls() guard function."""

    def test_returns_run_when_neither_stopped_nor_paused(self, tmp_path, monkeypatch):
        """Returns 'run' when no stop or pause marker is present."""
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", tmp_path / ".pipeline-pause")
        assert _check_controls("test/repo") == "run"

    def test_returns_stop_when_stop_marker_exists(self, tmp_path, monkeypatch, capsys):
        """Returns 'stop' when a stop marker is present, regardless of pause state."""
        stop_path = tmp_path / ".pipeline-stop"
        stop_path.write_text(json.dumps({"reason": "test stop", "stopped_at": "2026-01-01T00:00:00Z"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", stop_path)
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", tmp_path / ".pipeline-pause")
        assert _check_controls("test/repo") == "stop"

    def test_returns_pause_when_pause_marker_active(self, tmp_path, monkeypatch):
        """Returns 'pause' when a non-expired pause marker is present."""
        import datetime
        pause_path = tmp_path / ".pipeline-pause"
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        pause_path.write_text(json.dumps({"until": future, "reason": "rate limit", "paused_at": future}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", pause_path)
        assert _check_controls("test/repo") == "pause"

    def test_stop_takes_priority_over_pause(self, tmp_path, monkeypatch):
        """Returns 'stop' even when both stop and pause markers are present."""
        import datetime
        stop_path = tmp_path / ".pipeline-stop"
        stop_path.write_text(json.dumps({"reason": "test stop"}))
        pause_path = tmp_path / ".pipeline-pause"
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        pause_path.write_text(json.dumps({"until": future, "reason": "rate limit", "paused_at": future}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", stop_path)
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", pause_path)
        assert _check_controls("test/repo") == "stop"

    def test_returns_run_when_pause_marker_expired(self, tmp_path, monkeypatch):
        """Returns 'run' when pause marker exists but has expired."""
        import datetime
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
        pause_path = tmp_path / ".pipeline-pause"
        pause_path.write_text(json.dumps({"until": past, "reason": "expired", "paused_at": past}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", pause_path)
        assert _check_controls("test/repo") == "run"

    def test_process_work_item_returns_zero_when_stopped(self, tmp_path, monkeypatch):
        """process_work_item returns 0 immediately when _check_controls detects stop."""
        from pipeline_orchestrator import process_work_item, AgentDef, WorkItem, ConcurrencyState
        stop_path = tmp_path / ".pipeline-stop"
        stop_path.write_text(json.dumps({"reason": "test stop", "stopped_at": "2026-01-01T00:00:00Z"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", stop_path)
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", tmp_path / ".pipeline-pause")

        promote_calls = []

        def fake_promote(labels, agents, work_item, gh, **kw):
            promote_calls.append(True)
            return labels

        wi = WorkItem(number=1, kind="issue", title="test", labels=set(), url="https://example.com/1")
        gh = MagicMock()

        with patch.object(pipeline_orchestrator, "promote_gated_agents", side_effect=fake_promote):
            result = process_work_item(wi, [], {}, gh, dry_run=False, repo="test/repo")

        assert result == 0
        assert len(promote_calls) == 0, "promote_gated_agents must not run when stop is detected at entry"

    def test_process_work_item_returns_zero_when_paused(self, tmp_path, monkeypatch):
        """process_work_item returns 0 immediately when _check_controls detects pause."""
        import datetime
        from pipeline_orchestrator import process_work_item, WorkItem
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        pause_path = tmp_path / ".pipeline-pause"
        pause_path.write_text(json.dumps({"until": future, "reason": "rate limit", "paused_at": future}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", pause_path)

        promote_calls = []

        def fake_promote(labels, agents, work_item, gh, **kw):
            promote_calls.append(True)
            return labels

        wi = WorkItem(number=2, kind="issue", title="test", labels=set(), url="https://example.com/2")
        gh = MagicMock()

        with patch.object(pipeline_orchestrator, "promote_gated_agents", side_effect=fake_promote):
            result = process_work_item(wi, [], {}, gh, dry_run=False, repo="test/repo")

        assert result == 0
        assert len(promote_calls) == 0, "promote_gated_agents must not run when pause is detected at entry"


# ---------------------------------------------------------------------------
# TestWorkflowProposals
# ---------------------------------------------------------------------------

class TestWorkflowProposals:
    """Verify the workflow files exist with the required workflow_dispatch inputs."""

    def _parse_workflow(self, name: str) -> dict:
        import yaml
        path = Path(__file__).parent.parent / ".github/workflows" / name
        assert path.exists(), f"Workflow not found at {path}"
        return yaml.safe_load(path.read_text())

    def _on_block(self, name: str) -> dict:
        wf = self._parse_workflow(name)
        # PyYAML parses the bare `on:` key as Python True, not the string "on".
        return wf.get(True, wf.get("on", {}))

    def _dispatch_inputs(self, name: str) -> dict:
        return self._on_block(name).get("workflow_dispatch", {}).get("inputs", {})

    def test_emergency_stop_workflow_exists(self):
        assert "workflow_dispatch" in self._on_block("pipeline-emergency-stop.yml"), \
            "workflow must be triggerable via workflow_dispatch"

    def test_emergency_stop_workflow_has_reason_input(self):
        inputs = self._dispatch_inputs("pipeline-emergency-stop.yml")
        assert "reason" in inputs, f"Expected 'reason' in workflow_dispatch.inputs; got {list(inputs)}"

    def test_emergency_stop_workflow_has_cancel_runs_input(self):
        inputs = self._dispatch_inputs("pipeline-emergency-stop.yml")
        assert "cancel_runs" in inputs, f"Expected 'cancel_runs' in workflow_dispatch.inputs; got {list(inputs)}"

    def test_restart_workflow_exists(self):
        assert "workflow_dispatch" in self._on_block("pipeline-restart.yml"), \
            "workflow must be triggerable via workflow_dispatch"

    def test_restart_workflow_has_trigger_run_input(self):
        inputs = self._dispatch_inputs("pipeline-restart.yml")
        assert "trigger_run" in inputs, f"Expected 'trigger_run' in workflow_dispatch.inputs; got {list(inputs)}"
