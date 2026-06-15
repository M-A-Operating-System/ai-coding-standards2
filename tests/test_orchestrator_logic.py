"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
import subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest
from pipeline_orchestrator import (
    ALL_STATUSES,
    STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED,
    STATUS_REVIEW, STATUS_BLOCKED, STATUS_WIP, STATUS_REQUESTED,
    PIPELINE_MAX_CONCURRENT,
    agent_status,
    _apply_failed,
    _count_running,
    _handle_review_loop,
    _make_audit_event,
    write_audit_log,
    promote_gated_agents,
    AgentDef, AgentRunResult, ConcurrencyState, WorkItem,
    parse_frontmatter,
    process_work_item,
    _compute_agent_session_id,
    main,
)


def _make_agent_def(name: str = "03_execute/coder") -> AgentDef:
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
        """:wip must be removed BEFORE :failed is added so the item never
        carries two status labels at once — assert real ordering via the
        shared mock's recorded call sequence."""
        agent_def = _make_agent_def("03_execute/coder")
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

        # Ordering: the remove of coder:wip must precede the add of coder:failed.
        # gh is a single MagicMock so .mock_calls records both in dispatch order.
        method_args = [
            (c[0], c[1][1]) for c in gh.mock_calls
            if c[0] in ("remove_label", "add_label") and len(c[1]) >= 2
        ]
        wip_remove_idx = next(
            i for i, (m, lbl) in enumerate(method_args)
            if m == "remove_label" and lbl == "coder:wip"
        )
        failed_add_idx = next(
            i for i, (m, lbl) in enumerate(method_args)
            if m == "add_label" and lbl == "coder:failed"
        )
        assert wip_remove_idx < failed_add_idx, (
            f"coder:wip must be removed before coder:failed is added; "
            f"call order was {method_args}"
        )

    def test_clears_requested(self):
        """_apply_failed removes :requested — validates DP-001 fix."""
        agent_def = _make_agent_def("03_execute/coder")
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
        agent_def = _make_agent_def("03_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        gh.remove_label.side_effect = Exception("API error")
        result = AgentRunResult(success=False, returncode=1)

        # Should not raise
        _apply_failed(gh, agent_def, work_item, result)

    def test_clears_all_stale_statuses(self):
        """All of wip, review, blocked, requested are cleared."""
        agent_def = _make_agent_def("03_execute/coder")
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


# ---------------------------------------------------------------------------
# Concurrency helpers
# ---------------------------------------------------------------------------

def _make_agent_def_concurrent(name: str, max_concurrent: int = 1) -> AgentDef:
    """Build a minimal AgentDef with a configurable max_concurrent."""
    parts = name.split("/")
    return AgentDef(
        agent=name,
        phase=parts[0],
        objects=["issue"],
        trigger={"label": f"{parts[-1]}-dep:complete"},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
        max_concurrent=max_concurrent,
    )


def _make_work_item_with_labels(number: int, labels: set) -> WorkItem:
    return WorkItem(
        number=number,
        kind="issue",
        title=f"Test issue #{number}",
        labels=labels,
        url=f"https://github.com/test/repo/issues/{number}",
    )


def _make_gh_mock() -> MagicMock:
    gh = MagicMock()
    gh.add_label = MagicMock()
    gh.remove_label = MagicMock()
    gh.post_comment = MagicMock()
    gh.get_issue_labels = MagicMock(return_value=set())
    return gh


# ---------------------------------------------------------------------------
# TestCountRunning
# ---------------------------------------------------------------------------

class TestCountRunning:
    def test_returns_zero_when_no_wip(self):
        agents = [_make_agent_def_concurrent("01_product_docs/prd-writer")]
        work_items = [_make_work_item_with_labels(i, set()) for i in range(3)]
        counts = _count_running(work_items, agents)
        assert counts["prd-writer"] == 0

    def test_counts_wip_labels_across_work_items(self):
        """Prior-tick :wip labels are correctly tallied per agent."""
        agents = [_make_agent_def_concurrent("01_product_docs/prd-writer")]
        work_items = [
            _make_work_item_with_labels(1, {"prd-writer:wip"}),
            _make_work_item_with_labels(2, {"prd-writer:wip"}),
            _make_work_item_with_labels(3, {"some-other:complete"}),
        ]
        counts = _count_running(work_items, agents)
        assert counts["prd-writer"] == 2

    def test_counts_are_independent_per_agent(self):
        agents = [
            _make_agent_def_concurrent("01_product_docs/prd-writer"),
            _make_agent_def_concurrent("03_execute/coder"),
        ]
        work_items = [
            _make_work_item_with_labels(1, {"prd-writer:wip"}),
            _make_work_item_with_labels(2, {"coder:wip"}),
            _make_work_item_with_labels(3, {"coder:wip"}),
        ]
        counts = _count_running(work_items, agents)
        assert counts["prd-writer"] == 1
        assert counts["coder"] == 2

    def test_empty_work_items_returns_zeros(self):
        agents = [_make_agent_def_concurrent("01_product_docs/prd-writer")]
        counts = _count_running([], agents)
        assert counts["prd-writer"] == 0


# ---------------------------------------------------------------------------
# TestConcurrencyState
# ---------------------------------------------------------------------------

class TestConcurrencyState:
    def test_initial_tick_launch_count_is_zero(self):
        conc = ConcurrencyState(running_counts={})
        assert conc.tick_launch_count == 0

    def test_running_counts_initialised_from_dict(self):
        conc = ConcurrencyState(running_counts={"prd-writer": 2, "coder": 0})
        assert conc.running_counts["prd-writer"] == 2
        assert conc.running_counts["coder"] == 0

    def test_increment_updates_both_counters(self):
        conc = ConcurrencyState(running_counts={"prd-writer": 1})
        conc.running_counts["prd-writer"] += 1
        conc.tick_launch_count += 1
        assert conc.running_counts["prd-writer"] == 2
        assert conc.tick_launch_count == 1
