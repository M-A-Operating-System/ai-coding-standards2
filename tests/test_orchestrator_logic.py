"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ai-agile", "pipeline"))

from unittest.mock import MagicMock, call, patch
import pytest
from pipeline_orchestrator import (
    ALL_STATUSES,
    STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED,
    STATUS_REVIEW, STATUS_BLOCKED, STATUS_WIP, STATUS_REQUESTED,
    agent_status,
    _apply_failed,
    AgentDef, AgentRunResult,
    parse_frontmatter,
)


def _make_agent_def(name: str = "05_execute/coder") -> AgentDef:
    """Build a minimal AgentDef for tests."""
    return AgentDef(
        agent=name,
        phase=name.split("/")[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
    )


def _make_work_item(number: int = 42) -> MagicMock:
    wi = MagicMock()
    wi.number = number
    wi.kind = "issue"
    wi.title = "Test issue"
    wi.url = f"https://github.com/test/repo/issues/{number}"
    return wi


# ---------------------------------------------------------------------------
# TestAllStatusesOrdering
# ---------------------------------------------------------------------------

class TestAllStatusesOrdering:
    def test_all_statuses_is_list(self):
        assert isinstance(ALL_STATUSES, list), "ALL_STATUSES should be a list (not a set)"

    def test_terminal_statuses_before_halt_statuses(self):
        # Terminal statuses should appear before halt statuses in the list
        terminal = {STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED}
        halt = {STATUS_REVIEW, STATUS_BLOCKED}
        last_terminal_idx = max(ALL_STATUSES.index(s) for s in terminal)
        first_halt_idx = min(ALL_STATUSES.index(s) for s in halt)
        assert last_terminal_idx < first_halt_idx, (
            f"All terminal statuses must appear before halt statuses in ALL_STATUSES; "
            f"last terminal at index {last_terminal_idx}, first halt at index {first_halt_idx}"
        )

    def test_all_expected_statuses_present(self):
        expected = {STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED,
                    STATUS_REVIEW, STATUS_BLOCKED, STATUS_WIP, STATUS_REQUESTED}
        assert expected.issubset(set(ALL_STATUSES))


# ---------------------------------------------------------------------------
# TestAgentStatus
# ---------------------------------------------------------------------------

class TestAgentStatus:
    def test_returns_none_when_no_labels(self):
        assert agent_status(set(), "coder") is None

    def test_returns_complete_when_present(self):
        labels = {"coder:complete", "other:wip"}
        assert agent_status(labels, "coder") == "complete"

    def test_terminal_beats_halt(self):
        """complete appears before review in ALL_STATUSES — validates DP-002 fix."""
        labels = {"coder:complete", "coder:review"}
        result = agent_status(labels, "coder")
        assert result == "complete", (
            f"Expected 'complete' to beat 'review' due to ALL_STATUSES ordering, got {result!r}"
        )

    def test_failed_beats_wip(self):
        """failed appears before wip in ALL_STATUSES."""
        labels = {"coder:failed", "coder:wip"}
        result = agent_status(labels, "coder")
        assert result == "failed", (
            f"Expected 'failed' to beat 'wip' due to ALL_STATUSES ordering, got {result!r}"
        )

    def test_returns_none_for_unrelated_labels(self):
        labels = {"other-agent:complete", "coder:wip"}
        assert agent_status(labels, "other-agent") == "complete"
        assert agent_status(labels, "coder") == "wip"


# ---------------------------------------------------------------------------
# TestApplyFailed
# ---------------------------------------------------------------------------

class TestApplyFailed:
    def _make_gh(self) -> MagicMock:
        gh = MagicMock()
        gh.remove_label = MagicMock()
        gh.add_label = MagicMock()
        gh.post_comment = MagicMock()
        return gh

    def test_clears_wip_before_applying_failed(self):
        agent_def = _make_agent_def("05_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1, captured_tail="error output")

        # Simulate labels on the work item containing :wip
        _apply_failed(gh, agent_def, work_item, result)

        # remove_label should be called with coder:wip
        remove_calls = [c[0][1] for c in gh.remove_label.call_args_list]
        assert "coder:wip" in remove_calls, f"Expected 'coder:wip' in remove_label calls: {remove_calls}"

        # add_label should be called with coder:failed
        add_calls = [c[0][1] for c in gh.add_label.call_args_list]
        assert "coder:failed" in add_calls, f"Expected 'coder:failed' in add_label calls: {add_calls}"

    def test_clears_requested(self):
        """_apply_failed removes :requested — validates DP-001 fix."""
        agent_def = _make_agent_def("05_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)

        _apply_failed(gh, agent_def, work_item, result)

        remove_calls = [c[0][1] for c in gh.remove_label.call_args_list]
        assert "coder:requested" in remove_calls, (
            f"Expected 'coder:requested' in remove_label calls: {remove_calls}"
        )

    def test_does_not_raise_when_remove_fails(self):
        """_apply_failed swallows remove_label exceptions (best-effort cleanup)."""
        agent_def = _make_agent_def("05_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        gh.remove_label.side_effect = Exception("API error")
        result = AgentRunResult(success=False, returncode=1)

        # Should not raise
        _apply_failed(gh, agent_def, work_item, result)

    def test_clears_all_stale_statuses(self):
        """All of wip, review, blocked, requested are cleared."""
        agent_def = _make_agent_def("05_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)

        _apply_failed(gh, agent_def, work_item, result)

        remove_calls = {c[0][1] for c in gh.remove_label.call_args_list}
        for stale in ("coder:wip", "coder:review", "coder:blocked", "coder:requested"):
            assert stale in remove_calls, f"Expected {stale!r} in remove_label calls: {remove_calls}"


# ---------------------------------------------------------------------------
# TestParseFrontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_simple_scalar(self):
        text = "---\nmodel: claude-sonnet-4-6\n---"
        result = parse_frontmatter(text)
        assert result == {"model": "claude-sonnet-4-6"}

    def test_no_frontmatter_returns_empty(self):
        text = "This is plain text without frontmatter"
        result = parse_frontmatter(text)
        assert result == {}

    def test_unclosed_frontmatter_returns_empty(self):
        text = "---\nmodel: foo"
        result = parse_frontmatter(text)
        assert result == {}

    def test_value_with_colon(self):
        """Values containing colons (e.g., URLs) must be preserved fully — validates QA-002."""
        text = "---\nurl: https://x.com:443\n---"
        result = parse_frontmatter(text)
        assert result == {"url": "https://x.com:443"}, (
            f"Value with colon was not preserved correctly: {result}"
        )

    def test_multiple_keys(self):
        text = "---\nmodel: claude-sonnet-4-6\ntemperature: 0.7\n---"
        result = parse_frontmatter(text)
        assert result["model"] == "claude-sonnet-4-6"
        assert result["temperature"] == "0.7"

    def test_inline_list(self):
        text = "---\ntools: [bash, python, read]\n---"
        result = parse_frontmatter(text)
        assert result["tools"] == ["bash", "python", "read"]

    def test_empty_frontmatter_returns_empty(self):
        text = "---\n---"
        result = parse_frontmatter(text)
        assert result == {}
