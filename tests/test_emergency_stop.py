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
    def test_returns_zero_when_no_marker(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        stopped, reason = is_pipeline_stopped()
        assert stopped == 0
        assert reason == ""

    def test_returns_level_3_with_reason_when_marker_has_no_level(self, tmp_path, monkeypatch):
        """A marker without a level field defaults to level 3 (stops everything)."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "bad prompt deployed",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped == 3
        assert reason == "bad prompt deployed"

    def test_returns_explicit_level_when_marker_has_level_field(self, tmp_path, monkeypatch):
        """A marker with an explicit level field returns that level."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "partial stop",
            "level": 2,
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped == 2
        assert reason == "partial stop"

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
        assert stopped == 3
        assert reason == "old stop from the past"
        assert marker_path.exists(), "Stop marker must NOT be auto-deleted"

    def test_malformed_marker_returns_level_3(self, tmp_path, monkeypatch):
        """Malformed JSON in marker defaults to level 3 (fail-safe, stops everything)."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text("this is not json {{{")
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped == 3

    def test_missing_reason_field_returns_default(self, tmp_path, monkeypatch):
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({"stopped_at": "2026-06-01T00:00:00Z"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)
        stopped, reason = is_pipeline_stopped()
        assert stopped == 3
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
        args.headless = False
        args.print_prompt = False
        args.interactive_result = False
        args.confirm_gate = False
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def test_main_exits_early_when_stopped(self, tmp_path, monkeypatch):
        """When stop marker exists and --headless, main() must not load the pipeline."""
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

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=self._make_args(headless=True)), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load), \
             patch.object(pipeline_orchestrator, "_emit_audit_event"), \
             patch.object(pipeline_orchestrator, "GitHubClient"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert not load_called, "load_pipeline must not be called when headless and stop marker is set"

    def test_main_emits_emergency_stop_audit_event(self, tmp_path, monkeypatch, capsys):
        """When stop marker is detected with --headless, a system.emergency_stop event is printed."""
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "billing control",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=self._make_args(headless=True)), \
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
            with patch.object(pipeline_orchestrator, "parse_args",
                              return_value=self._make_args(headless=True)), \
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

    def test_stop_marker_present_during_run_does_not_exit_early_for_level1(self, tmp_path, monkeypatch):
        """A level-1 stop does not cause main() to exit before loading the pipeline.

        Stop is evaluated per-step in _should_run(); main() only exits early for
        level-3 (full) stops. A level-1 stop marker must allow the pipeline to
        load and run higher-priority steps.
        """
        marker_path = tmp_path / ".pipeline-stop"
        marker_path.write_text(json.dumps({
            "stopped_at": "2026-06-01T12:00:00Z",
            "reason": "low-priority stop",
            "level": 1,
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker_path)

        loaded = []

        def fake_load(path):
            loaded.append(True)
            return [], []

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=self._make_args(headless=True)), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load), \
             patch.object(pipeline_orchestrator, "_emit_audit_event"), \
             patch.object(pipeline_orchestrator, "GitHubClient") as MockGH, \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            MockGH.return_value.list_open_issues.return_value = []
            pipeline_orchestrator.main()

        assert loaded, "load_pipeline must be called for a level-1 stop (not a full stop)"


# ---------------------------------------------------------------------------
# TestCheckControls
# ---------------------------------------------------------------------------

class TestCheckControls:
    """Tests for the _check_controls() guard function (pause only; stop is per-step)."""

    def test_returns_run_when_neither_stopped_nor_paused(self, tmp_path, monkeypatch):
        """Returns 'run' when no stop or pause marker is present."""
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", tmp_path / ".pipeline-pause")
        assert _check_controls("test/repo") == "run"

    def test_returns_run_when_stop_marker_exists(self, tmp_path, monkeypatch):
        """Returns 'run' even when a stop marker is present.

        Stop is now evaluated per-step in _should_run(), not at the work-item
        level in _check_controls(). The work-item loop proceeds so that
        high-priority steps (above the active stop level) can still run.
        """
        stop_path = tmp_path / ".pipeline-stop"
        stop_path.write_text(json.dumps({"reason": "test stop", "stopped_at": "2026-01-01T00:00:00Z"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", stop_path)
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", tmp_path / ".pipeline-pause")
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)
        assert _check_controls("test/repo") == "run"

    def test_returns_pause_when_pause_marker_active(self, tmp_path, monkeypatch):
        """Returns 'pause' when a non-expired pause marker is present."""
        import datetime
        pause_path = tmp_path / ".pipeline-pause"
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        pause_path.write_text(json.dumps({"until": future, "reason": "rate limit", "paused_at": future}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", pause_path)
        assert _check_controls("test/repo") == "pause"

    def test_pause_applies_independently_of_stop_marker(self, tmp_path, monkeypatch):
        """Returns 'pause' when both stop and pause markers are present.

        Stop no longer affects _check_controls(); pause still applies
        regardless of any stop marker present.
        """
        import datetime
        stop_path = tmp_path / ".pipeline-stop"
        stop_path.write_text(json.dumps({"reason": "test stop"}))
        pause_path = tmp_path / ".pipeline-pause"
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        pause_path.write_text(json.dumps({"until": future, "reason": "rate limit", "paused_at": future}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", stop_path)
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", pause_path)
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)
        assert _check_controls("test/repo") == "pause"

    def test_returns_run_when_pause_marker_expired(self, tmp_path, monkeypatch):
        """Returns 'run' when pause marker exists but has expired."""
        import datetime
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
        pause_path = tmp_path / ".pipeline-pause"
        pause_path.write_text(json.dumps({"until": past, "reason": "expired", "paused_at": past}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")
        monkeypatch.setattr(pipeline_orchestrator, "PAUSE_MARKER_PATH", pause_path)
        assert _check_controls("test/repo") == "run"

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
# TestAgentDefStopOnLevel
# ---------------------------------------------------------------------------

class TestAgentDefStopOnLevel:
    """AgentDef gains a stop_on_level field with a default of 1."""

    def test_default_stop_on_level_is_1(self):
        """AgentDef.stop_on_level defaults to 1 when pipeline.json omits stopOnLevel."""
        from pipeline_orchestrator import AgentDef
        agent_def = AgentDef(
            agent="test/agent",
            phase="test",
            objects=["issue"],
            trigger={"label": "test:pending"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
        )
        assert agent_def.stop_on_level == 1

    def test_stop_on_level_can_be_set_explicitly(self):
        """stop_on_level can be overridden when constructing AgentDef."""
        from pipeline_orchestrator import AgentDef
        agent_def = AgentDef(
            agent="test/agent",
            phase="test",
            objects=["issue"],
            trigger={"label": "test:pending"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            stop_on_level=3,
        )
        assert agent_def.stop_on_level == 3

    def test_load_pipeline_reads_stop_on_level_from_json(self, tmp_path):
        """_steps_from_flows passes stopOnLevel from pipeline.json into AgentDef.stop_on_level."""
        import json as _json
        from pipeline_orchestrator import _steps_from_flows
        minimal = {
            "flows": {
                "standard-delivery": {
                    "trigger": {"kind": "issue"},
                    "steps": [
                        {
                            "agent": "01_product_docs/issue-classifier",
                            "phase": "01_product_docs",
                            "trigger": {"event": "issue.opened"},
                            "dependencies": [],
                            "human_gate_after": False,
                            "stopOnLevel": 2,
                            "description": "test",
                        }
                    ],
                }
            }
        }
        steps = _steps_from_flows(minimal)
        assert steps[0].stop_on_level == 2

    def test_load_pipeline_defaults_stop_on_level_when_omitted(self, tmp_path):
        """stop_on_level defaults to 1 when stopOnLevel is absent from pipeline.json."""
        from pipeline_orchestrator import _steps_from_flows
        minimal = {
            "flows": {
                "standard-delivery": {
                    "trigger": {"kind": "issue"},
                    "steps": [
                        {
                            "agent": "01_product_docs/issue-classifier",
                            "phase": "01_product_docs",
                            "trigger": {"event": "issue.opened"},
                            "dependencies": [],
                            "human_gate_after": False,
                            "description": "test",
                        }
                    ],
                }
            }
        }
        steps = _steps_from_flows(minimal)
        assert steps[0].stop_on_level == 1


# ---------------------------------------------------------------------------
# TestTieredStopLevels
# ---------------------------------------------------------------------------

class TestTieredStopLevels:
    """Per-step eligibility checks against active stop levels (R3a, R4, R2a, R2b).

    active_stop_level is computed by process_work_item() (from is_pipeline_stopped())
    and passed to _should_run(); these tests pass it directly to keep tests
    independent of file-system state.
    """

    def _make_agent_def(self, stop_on_level, trigger_label="trigger:pending"):
        from pipeline_orchestrator import AgentDef
        return AgentDef(
            agent=f"test/agent-sol{stop_on_level}",
            phase="test",
            objects=["issue"],
            trigger={"label": trigger_label},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description=f"agent with stop_on_level {stop_on_level}",
            stop_on_level=stop_on_level,
        )

    def _make_work_item(self, trigger_label="trigger:pending"):
        from pipeline_orchestrator import WorkItem
        return WorkItem(
            number=1,
            kind="issue",
            title="test issue",
            labels={trigger_label},
            url="https://example.com/1",
        )

    def test_level1_stop_blocks_step_with_stop_on_level_1(self, monkeypatch):
        """Level-1 stop blocks a step whose stop_on_level is 1 (R3a)."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        agent = self._make_agent_def(stop_on_level=1)
        wi = self._make_work_item()
        result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=1)
        assert result is False

    def test_level1_stop_does_not_block_step_with_stop_on_level_2(self, monkeypatch):
        """Level-1 stop leaves a step with stop_on_level 2 unblocked (R4)."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        agent = self._make_agent_def(stop_on_level=2)
        wi = self._make_work_item()
        result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=1)
        assert result is True

    def test_level1_stop_does_not_block_step_with_stop_on_level_3(self, monkeypatch):
        """Level-1 stop leaves a step with stop_on_level 3 unblocked (R4)."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        agent = self._make_agent_def(stop_on_level=3)
        wi = self._make_work_item()
        result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=1)
        assert result is True

    def test_level2_stop_blocks_step_with_stop_on_level_1(self, monkeypatch):
        """Level-2 stop blocks a step with stop_on_level 1 (R3a)."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        agent = self._make_agent_def(stop_on_level=1)
        wi = self._make_work_item()
        result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=2)
        assert result is False

    def test_level2_stop_blocks_step_with_stop_on_level_2(self, monkeypatch):
        """Level-2 stop blocks a step with stop_on_level 2 (R3a)."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        agent = self._make_agent_def(stop_on_level=2)
        wi = self._make_work_item()
        result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=2)
        assert result is False

    def test_level2_stop_does_not_block_step_with_stop_on_level_3(self, monkeypatch):
        """Level-2 stop leaves a step with stop_on_level 3 unblocked (R4)."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        agent = self._make_agent_def(stop_on_level=3)
        wi = self._make_work_item()
        result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=2)
        assert result is True

    def test_level3_stop_blocks_all_steps(self, monkeypatch):
        """Level-3 stop blocks steps at all levels (R3a)."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        wi = self._make_work_item()
        for sol in (1, 2, 3):
            agent = self._make_agent_def(stop_on_level=sol)
            result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=3)
            assert result is False, f"Expected stop_on_level={sol} to be blocked at level-3 stop"

    def test_no_stop_does_not_block_any_step(self, monkeypatch):
        """When active_stop_level is 0 (not stopped), no step is blocked."""
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)

        wi = self._make_work_item()
        for sol in (1, 2, 3):
            agent = self._make_agent_def(stop_on_level=sol)
            result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=0)
            assert result is True, f"Expected stop_on_level={sol} to be unblocked when not stopped"

    def test_interactive_mode_does_not_block_any_step(self, monkeypatch):
        """Interactive runs do not receive a non-zero active_stop_level (R3b).

        process_work_item() zeroes out active_stop_level for interactive runs
        before passing it to _should_run(), so this function never sees a
        non-zero level in interactive mode.
        """
        from pipeline_orchestrator import _should_run
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", False)

        wi = self._make_work_item()
        for sol in (1, 2, 3):
            agent = self._make_agent_def(stop_on_level=sol)
            # active_stop_level=0 because process_work_item zeroes it for interactive
            result = _should_run(agent, wi, wi.labels, {}, None, active_stop_level=0)
            assert result is True, (
                f"Expected stop_on_level={sol} to be unblocked in interactive mode"
            )

    def test_is_pipeline_stopped_returns_level_from_marker(self, tmp_path, monkeypatch):
        """is_pipeline_stopped returns the level from the marker file (R2a)."""
        marker = tmp_path / ".pipeline-stop"
        marker.write_text(json.dumps({"reason": "test", "level": 2}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker)
        level, reason = is_pipeline_stopped()
        assert level == 2

    def test_is_pipeline_stopped_defaults_to_level3_when_no_level_field(self, tmp_path, monkeypatch):
        """is_pipeline_stopped defaults to level 3 when marker has no level field (R2b)."""
        marker = tmp_path / ".pipeline-stop"
        marker.write_text(json.dumps({"reason": "old format marker"}))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker)
        level, reason = is_pipeline_stopped()
        assert level == 3


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
        assert "workflow_dispatch" in self._on_block("ai_emergency_stop.yml"), \
            "workflow must be triggerable via workflow_dispatch"

    def test_emergency_stop_workflow_has_reason_input(self):
        inputs = self._dispatch_inputs("ai_emergency_stop.yml")
        assert "reason" in inputs, f"Expected 'reason' in workflow_dispatch.inputs; got {list(inputs)}"

    def test_emergency_stop_workflow_has_cancel_runs_input(self):
        inputs = self._dispatch_inputs("ai_emergency_stop.yml")
        assert "cancel_runs" in inputs, f"Expected 'cancel_runs' in workflow_dispatch.inputs; got {list(inputs)}"

    def test_no_restart_workflow(self):
        """The restart workflow was removed: restarting is clearing the marker,
        which an owner runs at any time (git rm .pipeline-stop / --clear-stop)."""
        restart = Path(__file__).parent.parent / ".github/workflows/pipeline-restart.yml"
        assert not restart.exists(), "pipeline-restart.yml must not exist"
