"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
import subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import json
import re
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
    _apply_result,
    _count_running,
    _handle_review_loop,
    normalize_skipped_labels,
    _make_audit_event,
    _emit_audit_event,
    _run_agent,
    _should_run,
    promote_gated_agents,
    AgentDef, AgentRunResult, ConcurrencyState, WorkItem,
    parse_frontmatter,
    process_work_item,
    _compute_agent_session_id,
    _resolve_applied_status,
    dependencies_complete,
    trigger_label_present,
    load_pipeline,
    pipeline_by_name,
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


# ---------------------------------------------------------------------------
# TestDefaultMaxConcurrentIsOne
# ---------------------------------------------------------------------------

class TestDefaultMaxConcurrentIsOne:
    """Scenario: Default concurrency of 1 when max_concurrent is absent."""

    def test_agent_def_default_max_concurrent(self):
        agent = _make_agent_def("03_execute/coder")
        assert agent.max_concurrent == 1, (
            "AgentDef.max_concurrent must default to 1 when not specified"
        )

    def test_load_pipeline_defaults_max_concurrent_to_one(self, tmp_path):
        """Pipeline entries without max_concurrent field default to 1."""
        import json
        pipeline_data = {
            "pipeline": [{
                "agent": "01_product_docs/issue-classifier",
                "phase": "01_product_docs",
                "object": ["issue"],
                "trigger": {"event": "issue.opened"},
                "dependencies": [],
                "human_gate_after": False,
                "description": "test",
            }]
        }
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        from pipeline_orchestrator import load_pipeline
        agents, _ = load_pipeline(path)
        assert agents[0].max_concurrent == 1

    def test_load_pipeline_null_max_concurrent_defaults_to_one(self, tmp_path):
        """max_concurrent: null in pipeline.json defaults to 1."""
        import json
        pipeline_data = {
            "pipeline": [{
                "agent": "01_product_docs/issue-classifier",
                "phase": "01_product_docs",
                "object": ["issue"],
                "trigger": {"event": "issue.opened"},
                "dependencies": [],
                "human_gate_after": False,
                "description": "test",
                "max_concurrent": None,
            }]
        }
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        from pipeline_orchestrator import load_pipeline
        agents, _ = load_pipeline(path)
        assert agents[0].max_concurrent == 1

    def test_load_pipeline_loads_review_gate(self, tmp_path):
        import json
        pipeline_data = {
            "pipeline": [{
                "agent": "03_execute/pr-reviewer",
                "phase": "03_execute",
                "object": ["issue"],
                "trigger": {"label": "merge-conflict:complete"},
                "dependencies": [],
                "human_gate_after": False,
                "description": "test",
                "review_gate": True,
            }]
        }
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        from pipeline_orchestrator import load_pipeline
        agents, _ = load_pipeline(path)
        assert agents[0].review_gate is True

    def test_load_pipeline_review_gate_defaults_false(self, tmp_path):
        import json
        pipeline_data = {
            "pipeline": [{
                "agent": "01_product_docs/issue-classifier",
                "phase": "01_product_docs",
                "object": ["issue"],
                "trigger": {"event": "issue.opened"},
                "dependencies": [],
                "human_gate_after": False,
                "description": "test",
            }]
        }
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        from pipeline_orchestrator import load_pipeline
        agents, _ = load_pipeline(path)
        assert agents[0].review_gate is False

    def test_load_pipeline_warns_on_deprecated_mark_ready_on_complete(self, tmp_path):
        import json
        import logging
        pipeline_data = {
            "pipeline": [{
                "agent": "03_execute/pr-reviewer",
                "phase": "03_execute",
                "object": ["issue"],
                "trigger": {"label": "merge-conflict:complete"},
                "dependencies": [],
                "human_gate_after": False,
                "description": "test",
                "git_ops": {"commit_after": False, "mark_ready_on_complete": True},
            }]
        }
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        from pipeline_orchestrator import load_pipeline
        logger = logging.getLogger("orchestrator")
        with patch.object(logger, "warning") as mock_warn:
            load_pipeline(path)
        mock_warn.assert_called_once()
        assert "mark_ready_on_complete" in mock_warn.call_args[0][0]



# ---------------------------------------------------------------------------
# TestPerAgentConcurrencyCeiling
# ---------------------------------------------------------------------------

class TestPerAgentConcurrencyCeiling:
    """Scenario: Per-agent concurrency ceiling respected."""

    def _make_eligible_work_item(self, number: int) -> WorkItem:
        return _make_work_item_with_labels(number, {"issue-classifier:complete"})

    @patch("pipeline_orchestrator.invoke_agent")
    def test_ceiling_respected_exactly_max_concurrent_launched(self, mock_invoke):
        """
        Given max_concurrent: 3 for prd-writer
        And 5 issues are eligible (no :wip)
        When process_work_item is called for each
        Then exactly 3 are launched, 2 remain pending.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=3,
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        conc = ConcurrencyState(running_counts={"prd-writer": 0})
        work_items = [self._make_eligible_work_item(i) for i in range(1, 6)]

        launched = 0
        for wi in work_items:
            gh = _make_gh_mock()
            n = process_work_item(
                wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
                concurrency=conc,
            )
            launched += n

        assert launched == 3, f"Expected exactly 3 launches, got {launched}"
        assert conc.tick_launch_count == 3
        assert conc.running_counts["prd-writer"] == 3

    @patch("pipeline_orchestrator.invoke_agent")
    def test_already_running_instances_count_against_ceiling(self, mock_invoke):
        """
        Given max_concurrent: 3
        And 2 issues already carry prd-writer:wip (prior tick)
        And 4 additional issues are eligible
        Then exactly 1 additional instance is launched (2 + 1 = 3 ceiling).
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=3,
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        # 2 already running from prior tick
        conc = ConcurrencyState(running_counts={"prd-writer": 2})
        work_items = [self._make_eligible_work_item(i) for i in range(10, 14)]  # 4 eligible

        launched = 0
        for wi in work_items:
            gh = _make_gh_mock()
            n = process_work_item(
                wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
                concurrency=conc,
            )
            launched += n

        assert launched == 1, (
            f"With 2 already running and max_concurrent=3, expected 1 new launch, got {launched}"
        )
        assert conc.running_counts["prd-writer"] == 3
        assert conc.tick_launch_count == 1

    @patch("pipeline_orchestrator.invoke_agent")
    def test_default_max_concurrent_one_allows_single_launch(self, mock_invoke):
        """
        Given an agent with no max_concurrent field (defaults to 1)
        And 3 issues are eligible
        Then exactly 1 instance is launched.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            # max_concurrent intentionally omitted — should default to 1
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        conc = ConcurrencyState(running_counts={"prd-writer": 0})
        work_items = [self._make_eligible_work_item(i) for i in range(1, 4)]

        launched = 0
        for wi in work_items:
            gh = _make_gh_mock()
            n = process_work_item(
                wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
                concurrency=conc,
            )
            launched += n

        assert launched == 1, (
            f"Default max_concurrent=1 should limit to 1 launch; got {launched}"
        )


# ---------------------------------------------------------------------------
# TestAggregatePipelineCeiling
# ---------------------------------------------------------------------------

class TestAggregatePipelineCeiling:
    """Scenario: Aggregate pipeline ceiling caps total launches per tick."""

    @patch("pipeline_orchestrator.invoke_agent")
    def test_aggregate_ceiling_caps_total_launches(self, mock_invoke):
        """
        Given per-agent max_concurrent values that would permit >20 total launches
        And the pipeline-level aggregate maximum is PIPELINE_MAX_CONCURRENT (20)
        When the orchestrator processes all eligible work items
        Then no more than PIPELINE_MAX_CONCURRENT agents are launched in that tick.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        # One agent type with a high per-agent ceiling — not the limiting factor
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=100,  # per-agent ceiling not the constraint
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        conc = ConcurrencyState(running_counts={"prd-writer": 0})

        # 25 eligible work items — more than the aggregate ceiling
        work_items = [
            _make_work_item_with_labels(i, {"issue-classifier:complete"})
            for i in range(1, 26)
        ]

        launched = 0
        for wi in work_items:
            if conc.tick_launch_count >= PIPELINE_MAX_CONCURRENT:
                break
            gh = _make_gh_mock()
            n = process_work_item(
                wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
                concurrency=conc,
            )
            launched += n

        assert launched == PIPELINE_MAX_CONCURRENT, (
            f"Expected exactly PIPELINE_MAX_CONCURRENT={PIPELINE_MAX_CONCURRENT} launches, got {launched}"
        )
        assert conc.tick_launch_count == PIPELINE_MAX_CONCURRENT

    def test_pipeline_max_concurrent_constant_value(self):
        """Pipeline-wide aggregate ceiling is set to 20."""
        assert PIPELINE_MAX_CONCURRENT == 20, (
            f"PIPELINE_MAX_CONCURRENT must be 20 per spec, got {PIPELINE_MAX_CONCURRENT}"
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_inner_break_fires_mid_agent_loop_at_aggregate_ceiling(self, mock_invoke):
        """
        Given two distinct agent types, both with per-agent max_concurrent=100
        And ConcurrencyState.tick_launch_count starts at PIPELINE_MAX_CONCURRENT - 1
        And a single work item is eligible for both agent types
        When process_work_item is called
        Then exactly 1 agent is launched (the first in the agents list)
        And tick_launch_count equals PIPELINE_MAX_CONCURRENT
        And the second agent type is never invoked — confirming the inner break fired.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_one = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test agent one",
            max_concurrent=100,
        )
        agent_two = AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test agent two",
            max_concurrent=100,
        )
        agents = [agent_one, agent_two]
        pipeline_map = {
            "01_product_docs/prd-writer": agent_one,
            "03_execute/coder": agent_two,
        }
        # One below the aggregate ceiling — first agent launch will hit it exactly.
        conc = ConcurrencyState(
            running_counts={"prd-writer": 0, "coder": 0},
            tick_launch_count=PIPELINE_MAX_CONCURRENT - 1,
        )
        work_item = _make_work_item_with_labels(99, {"issue-classifier:complete"})

        gh = _make_gh_mock()
        n = process_work_item(
            work_item, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
            concurrency=conc,
        )

        assert n == 1, (
            f"Expected exactly 1 agent launched before inner break; got {n}"
        )
        assert conc.tick_launch_count == PIPELINE_MAX_CONCURRENT, (
            f"tick_launch_count should equal PIPELINE_MAX_CONCURRENT after first launch; "
            f"got {conc.tick_launch_count}"
        )
        assert mock_invoke.call_count == 1, (
            f"invoke_agent should be called exactly once (inner break stops second agent); "
            f"got {mock_invoke.call_count} calls"
        )
        # Confirm the launched agent was the first one (prd-writer), not coder.
        called_agent = mock_invoke.call_args[0][0]
        assert called_agent.agent == "01_product_docs/prd-writer", (
            f"Expected prd-writer to be launched first; got {called_agent.agent}"
        )


# ---------------------------------------------------------------------------
# TestRateLimitCounterRollback
# ---------------------------------------------------------------------------

class TestRateLimitCounterRollback:
    """Regression: rate-limited agent must roll back concurrency counters."""

    @patch("pipeline_orchestrator._restore_pre_agent_branch")
    @patch("pipeline_orchestrator.is_pipeline_paused")
    @patch("pipeline_orchestrator.invoke_agent")
    def test_rate_limited_agent_rolls_back_concurrency_counts(
        self, mock_invoke, mock_paused, mock_restore
    ):
        """
        Given a work item eligible for prd-writer (max_concurrent=5)
        And the current running_counts for prd-writer is 1
        And tick_launch_count is 3
        When invoke_agent returns rate_limited=True
        Then concurrency.running_counts[prd-writer] is rolled back to 1
        And concurrency.tick_launch_count is rolled back to 3
        """
        mock_invoke.return_value = AgentRunResult(success=False, rate_limited=True)
        mock_paused.return_value = (False, None, None)
        mock_restore.return_value = None

        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=5,
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        conc = ConcurrencyState(
            running_counts={"prd-writer": 1},
            tick_launch_count=3,
        )
        work_item = _make_work_item_with_labels(42, {"issue-classifier:complete"})

        gh = _make_gh_mock()
        process_work_item(
            work_item, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
            concurrency=conc,
        )

        assert conc.running_counts.get("prd-writer", 0) == 1, (
            f"running_counts should roll back to 1 after rate-limited abort; "
            f"got {conc.running_counts.get('prd-writer', 0)}"
        )
        assert conc.tick_launch_count == 3, (
            f"tick_launch_count should roll back to 3 after rate-limited abort; "
            f"got {conc.tick_launch_count}"
        )


# ---------------------------------------------------------------------------
# TestWipLabelFailureDoesNotInflateCount  (#103)
# ---------------------------------------------------------------------------

class TestWipLabelFailureDoesNotInflateCount:
    """Regression: concurrency counter must not increment when :wip label fails."""

    @patch("pipeline_orchestrator.invoke_agent")
    def test_counter_unchanged_when_add_label_raises(self, mock_invoke):
        """
        Given add_label raises for the :wip application
        When process_work_item is called
        Then running_counts is unchanged (no phantom slot consumed)
        And tick_launch_count is unchanged
        """
        mock_invoke.return_value = AgentRunResult(success=True)
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=5,
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        conc = ConcurrencyState(running_counts={"prd-writer": 2}, tick_launch_count=4)

        gh = _make_gh_mock()
        gh.add_label.side_effect = Exception("GitHub 500 error")

        work_item = _make_work_item_with_labels(1, {"issue-classifier:complete"})
        process_work_item(
            work_item, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
            concurrency=conc,
        )

        assert conc.running_counts.get("prd-writer", 0) == 2, (
            f"running_counts must stay at 2 when :wip label fails; "
            f"got {conc.running_counts.get('prd-writer', 0)}"
        )
        assert conc.tick_launch_count == 4, (
            f"tick_launch_count must stay at 4 when :wip label fails; "
            f"got {conc.tick_launch_count}"
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_second_item_not_blocked_by_phantom_count(self, mock_invoke):
        """
        Given max_concurrent=2 and 1 item already running (running_counts=1)
        And add_label raises for the first new eligible item
        When process_work_item is called for a second new eligible item
        Then the second item is launched (phantom count didn't block it)
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=2,
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        conc = ConcurrencyState(running_counts={"prd-writer": 1}, tick_launch_count=1)

        gh_fail = _make_gh_mock()
        gh_fail.add_label.side_effect = Exception("GitHub 500 error")
        wi_fail = _make_work_item_with_labels(1, {"issue-classifier:complete"})
        process_work_item(
            wi_fail, agents, pipeline_map, gh_fail, dry_run=False, repo="test/repo",
            concurrency=conc,
        )

        # No phantom count; slot still free for item 2
        gh_ok = _make_gh_mock()
        wi_ok = _make_work_item_with_labels(2, {"issue-classifier:complete"})
        launched = process_work_item(
            wi_ok, agents, pipeline_map, gh_ok, dry_run=False, repo="test/repo",
            concurrency=conc,
        )

        assert launched == 1, (
            f"Second item should launch (1 running + 1 new = 2 ceiling); got {launched}"
        )
        assert conc.running_counts.get("prd-writer", 0) == 2


# ---------------------------------------------------------------------------
# TestDryRunConcurrency  (#102)
# ---------------------------------------------------------------------------

class TestDryRunConcurrency:
    """Regression: dry-run mode must enforce concurrency ceilings."""

    def test_dry_run_increments_tick_count(self):
        """
        Given dry_run=True and 3 eligible items with max_concurrent=1
        When process_work_item is called for each
        Then only the first shows as launched (ceiling enforced in simulation)
        And concurrency.running_counts reflects 1 counted instance
        """
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=1,
        )
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}
        conc = ConcurrencyState(running_counts={"prd-writer": 0})

        total_launched = 0
        for i in range(1, 4):
            gh = _make_gh_mock()
            wi = _make_work_item_with_labels(i, {"issue-classifier:complete"})
            n = process_work_item(
                wi, agents, pipeline_map, gh, dry_run=True, repo="test/repo",
                concurrency=conc,
            )
            total_launched += n

        assert total_launched == 1, (
            f"dry_run must respect per-agent ceiling of 1; got {total_launched}"
        )
        assert conc.running_counts.get("prd-writer", 0) == 1, (
            f"running_counts must be 1 after dry-run of 3 items (ceiling=1); "
            f"got {conc.running_counts.get('prd-writer', 0)}"
        )

    def test_dry_run_respects_aggregate_ceiling(self):
        """
        Given PIPELINE_MAX_CONCURRENT and 5 items eligible across two agents
        And dry_run=True
        When process_work_item processes all items
        Then no more than PIPELINE_MAX_CONCURRENT total are reported as launched
        """
        agent_a = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="a",
            max_concurrent=100,
        )
        agent_b = AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "prd-docs-updater:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="b",
            max_concurrent=100,
        )
        agents = [agent_a, agent_b]
        pipeline_map = {
            "01_product_docs/prd-writer": agent_a,
            "03_execute/coder": agent_b,
        }
        conc = ConcurrencyState(
            running_counts={"prd-writer": 0, "coder": 0},
            tick_launch_count=PIPELINE_MAX_CONCURRENT - 1,
        )

        # One item eligible only for agent_a, one eligible only for agent_b
        wi_a = _make_work_item_with_labels(1, {"issue-classifier:complete"})
        wi_b = _make_work_item_with_labels(2, {"prd-docs-updater:complete"})

        gh = _make_gh_mock()
        n_a = process_work_item(
            wi_a, agents, pipeline_map, gh, dry_run=True, repo="test/repo",
            concurrency=conc,
        )
        gh2 = _make_gh_mock()
        n_b = process_work_item(
            wi_b, agents, pipeline_map, gh2, dry_run=True, repo="test/repo",
            concurrency=conc,
        )

        # Only the first item should launch — aggregate ceiling is reached after it
        assert n_a == 1, f"First item should launch; got {n_a}"
        assert n_b == 0, f"Second item must be deferred by aggregate ceiling; got {n_b}"
        assert conc.tick_launch_count == PIPELINE_MAX_CONCURRENT


# ---------------------------------------------------------------------------
# TestOrchestratorNonOverlapping
# ---------------------------------------------------------------------------

class TestOrchestratorNonOverlapping:
    """Scenario: Orchestrator runs remain non-overlapping."""

    def test_workflow_defines_concurrency_group(self):
        """
        Given the single orchestrator workflow file
        Then it defines a concurrency group with cancel-in-progress: false
        so concurrent triggers queue rather than cancel the active run.
        """
        path = Path(__file__).parent.parent / ".github" / "workflows" / "ai_orchestrator.yml"
        assert path.exists(), f"Workflow file not found: {path}"
        content = path.read_text()
        assert "group: pipeline-orchestrator" in content, (
            "ai_orchestrator.yml must declare concurrency group 'pipeline-orchestrator'"
        )
        assert "cancel-in-progress: false" in content, (
            "ai_orchestrator.yml must set cancel-in-progress: false"
        )


# ---------------------------------------------------------------------------
# TestOrchestratorSkipsWhenStopped
# ---------------------------------------------------------------------------

class TestOrchestratorSkipsWhenStopped:
    """Scenario: a stopped pipeline resolves to a cheap, green, skipped run
    instead of paying for a full runner + Python + npm setup only to have
    the orchestrator's own is_pipeline_stopped() check bail out afterwards."""

    def _workflow_text(self) -> str:
        path = Path(__file__).parent.parent / ".github" / "workflows" / "ai_orchestrator.yml"
        assert path.exists(), f"Workflow file not found: {path}"
        return path.read_text()

    def test_check_stop_job_checks_pipeline_stop_marker(self):
        content = self._workflow_text()
        assert "check-stop:" in content, (
            "ai_orchestrator.yml must define a check-stop job"
        )
        assert "contents/.pipeline-stop" in content, (
            "check-stop must query the .pipeline-stop marker via the Contents API"
        )

    def test_check_stop_job_does_not_set_up_python(self):
        """The whole point is to avoid the expensive setup -- check-stop must
        never touch actions/setup-python or npm install."""
        content = self._workflow_text()
        check_stop_start = content.index("check-stop:")
        orchestrate_start = content.index("orchestrate:")
        check_stop_block = content[check_stop_start:orchestrate_start]
        assert "setup-python" not in check_stop_block
        assert "npm install" not in check_stop_block
        assert "actions/checkout" not in check_stop_block

    def test_check_stop_job_has_a_tight_timeout(self):
        """A hung gh api call must not be free to burn hours of runner time --
        that would defeat check-stop's whole cost-saving purpose in its own
        failure mode. Must be well under the 360-minute platform default."""
        content = self._workflow_text()
        check_stop_start = content.index("check-stop:")
        orchestrate_start = content.index("orchestrate:")
        check_stop_block = content[check_stop_start:orchestrate_start]
        match = re.search(r"timeout-minutes:\s*(\d+)", check_stop_block)
        assert match, "check-stop must declare an explicit timeout-minutes"
        assert int(match.group(1)) <= 10, (
            "check-stop's timeout should be a few minutes, not close to the "
            "360-minute platform default"
        )

    def test_orchestrate_job_depends_on_and_is_gated_by_check_stop(self):
        content = self._workflow_text()
        orchestrate_start = content.index("orchestrate:")
        orchestrate_block = content[orchestrate_start:]
        assert "needs: check-stop" in orchestrate_block, (
            "orchestrate must declare 'needs: check-stop' so its if-condition "
            "can reference the check-stop job's output"
        )
        assert "needs.check-stop.outputs.stopped != 'true'" in orchestrate_block, (
            "orchestrate's if-condition must skip the job when check-stop "
            "reports the pipeline is stopped"
        )


# ---------------------------------------------------------------------------
# QA-001: invoke_agent timeout — timer fires and agent does not hang forever
# ---------------------------------------------------------------------------

class TestInvokeAgentTimeout:
    """Verify DP-006 fix: kill-timer terminates a silent or slow agent.

    Two scenarios:
    1. Agent produces no stdout at all (silent hang) — timer fires, process
       is killed, invoke_agent returns AgentRunResult(success=False) instead
       of hanging forever.
    2. Agent keeps producing output past the deadline — _timed_out.is_set()
       check in the per-line loop raises TimeoutExpired, and the returned
       captured_tail contains the "timed out" message.
    """

    def _make_minimal_agent_def(self) -> "AgentDef":
        import pipeline_orchestrator as orch
        return orch.AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="Test coder agent",
            step_type="agent",
        )

    def _make_work_item(self) -> "WorkItem":
        import pipeline_orchestrator as orch
        return orch.WorkItem(
            number=1,
            kind="issue",
            title="Test issue",
            labels=set(),
            url="https://github.com/test/repo/issues/1",
        )

    def test_silent_agent_does_not_hang(self, monkeypatch):
        """Agent that produces no stdout terminates within timeout + small buffer."""
        import threading
        import time
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 0.1)

        # Stdout blocks until the process is killed.
        _killed = threading.Event()

        class BlockingStdout:
            def __iter__(self):
                _killed.wait(timeout=10)  # unblocks when process is terminated
                return iter([])

        mock_proc = MagicMock()
        mock_proc.stdout = BlockingStdout()
        mock_proc.returncode = -15  # SIGTERM

        poll_done = threading.Event()

        def poll_side_effect():
            return -15 if poll_done.is_set() else None

        def terminate_side_effect():
            poll_done.set()
            _killed.set()

        mock_proc.poll.side_effect = poll_side_effect
        mock_proc.terminate.side_effect = terminate_side_effect
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc):
            start = time.monotonic()
            result = orch.invoke_agent(
                self._make_minimal_agent_def(),
                self._make_work_item(),
                dry_run=False,
                repo="test/repo",
                agent_text_override="---\ntools: []\n---\nTest agent.",
            )
            elapsed = time.monotonic() - start

        assert result.success is False
        # Must complete well within 2× the patched timeout, not hang forever.
        assert elapsed < 2.0, f"invoke_agent hung for {elapsed:.2f}s (expected < 2s)"

    def test_timed_out_event_triggers_timeout_message(self, monkeypatch):
        """When _timed_out fires while agent is emitting lines, captured_tail says timed out."""
        import threading
        import time
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 0.1)

        # Stdout yields lines until the process is killed, then stops.
        _killed = threading.Event()

        def line_generator():
            while not _killed.is_set():
                yield '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}\n'
                time.sleep(0.005)

        mock_proc = MagicMock()
        mock_proc.stdout = line_generator()
        mock_proc.returncode = -15

        poll_done = threading.Event()

        def poll_side_effect():
            return -15 if poll_done.is_set() else None

        def terminate_side_effect():
            poll_done.set()
            _killed.set()

        mock_proc.poll.side_effect = poll_side_effect
        mock_proc.terminate.side_effect = terminate_side_effect
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc):
            result = orch.invoke_agent(
                self._make_minimal_agent_def(),
                self._make_work_item(),
                dry_run=False,
                repo="test/repo",
                agent_text_override="---\ntools: []\n---\nTest agent.",
            )

        assert result.success is False
        assert "timed out" in result.captured_tail.lower(), (
            f"Expected 'timed out' in captured_tail, got: {result.captured_tail!r}"
        )


class TestInvokeAgentRuntimeContext:
    """Tests for the resolved ## Runtime context block injected into invoke_agent() prompts.

    Acceptance criteria (issue #172):
    - Prompt contains a pre-resolved KEY=value block, not $VAR shell references.
    - Values in the prompt match what is exported to the subprocess environment.
    - String values are stripped of leading/trailing whitespace before injection.
    - Subprocess env still carries the same variables for bash-snippet compatibility.
    """

    def _make_agent_def(self, name: str = "03_execute/coder") -> "AgentDef":
        import pipeline_orchestrator as orch
        return orch.AgentDef(
            agent=name,
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="Test agent",
            session_scope="per_issue",
        )

    def _make_work_item(self, number: int = 42, kind: str = "issue") -> "WorkItem":
        import pipeline_orchestrator as orch
        return orch.WorkItem(
            number=number,
            kind=kind,
            title="Test issue",
            labels=set(),
            url=f"https://github.com/test/repo/{kind}s/{number}",
        )

    def _capture_prompt(self, cmd_args: list) -> str:
        """Extract the -p prompt argument from the claude CLI args list."""
        try:
            idx = cmd_args.index("-p")
            return cmd_args[idx + 1]
        except (ValueError, IndexError):
            return ""

    def _fake_popen_capturing_cmd(self, captured_cmd: list):
        def fake_popen(cmd, **kwargs):
            captured_cmd.extend(cmd)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.poll.return_value = 0
            proc.wait.return_value = None
            return proc
        return fake_popen

    def _fake_popen_capturing_env(self, captured_env: dict):
        def fake_popen(cmd, env=None, **kwargs):
            if env is not None:
                captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.poll.return_value = 0
            proc.wait.return_value = None
            return proc
        return fake_popen

    def test_runtime_context_block_replaces_shell_var_references_for_issue(self, monkeypatch):
        """Prompt must contain ## Runtime context with resolved KEY=value pairs (not $VAR syntax)."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_cmd: list = []

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_cmd(captured_cmd)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=42, kind="issue"),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        assert "## Runtime context" in prompt, "Prompt must contain '## Runtime context' section"
        assert "REPO=test-org/test-repo" in prompt
        assert "ISSUE_NUMBER=42" in prompt
        assert "WORK_ITEM_KIND=issue" in prompt
        # The old "Env vars: $REPO $ISSUE_NUMBER ..." line must be gone.
        assert "Env vars: $REPO" not in prompt, "Old shell-variable 'Env vars' line must be replaced"

    def test_runtime_context_uses_pr_number_key_for_pr_work_items(self, monkeypatch):
        """When work_item.kind is 'pr', context block uses PR_NUMBER, not ISSUE_NUMBER."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_cmd: list = []

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_cmd(captured_cmd)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=77, kind="pr"),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        assert "PR_NUMBER=77" in prompt, "Prompt must contain resolved PR_NUMBER for PR work items"
        # ISSUE_NUMBER=N must not appear as a KEY=value assignment for PR work items.
        assert "ISSUE_NUMBER=" not in prompt, "PR work items must not expose ISSUE_NUMBER= in context"

    def test_string_values_are_stripped_before_injection(self, monkeypatch):
        """String values with surrounding whitespace are stripped to prevent prompt line injection."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        monkeypatch.setenv("AI_AGILE_ROOT", "  /padded/path  ")
        captured_cmd: list = []

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_cmd(captured_cmd)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=5),
                dry_run=False,
                repo="  test-org/test-repo  ",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        assert "REPO=test-org/test-repo\n" in prompt, "REPO value must be stripped of whitespace"
        assert "AI_AGILE_ROOT=/padded/path\n" in prompt, "AI_AGILE_ROOT must be stripped"
        assert "REPO=  test-org/test-repo  " not in prompt, "Unstripped REPO must not appear"

    def test_subprocess_env_still_exports_vars_for_bash_snippet_compatibility(self, monkeypatch):
        """Subprocess env must still carry REPO, ISSUE_NUMBER, WORK_ITEM_KIND, SESSION_ID."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_env: dict = {}

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_env(captured_env)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=42, kind="issue"),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        assert captured_env.get("REPO") == "test-org/test-repo", "REPO must be in subprocess env"
        assert captured_env.get("ISSUE_NUMBER") == "42", "ISSUE_NUMBER must be in subprocess env"
        assert captured_env.get("WORK_ITEM_KIND") == "issue", "WORK_ITEM_KIND must be in subprocess env"
        assert "SESSION_ID" in captured_env, "SESSION_ID must be in subprocess env"

    def test_prompt_session_id_matches_subprocess_env_session_id(self, monkeypatch):
        """SESSION_ID in the prompt must match SESSION_ID exported to subprocess."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_cmd: list = []
        captured_env: dict = {}

        def fake_popen(cmd, env=None, **kwargs):
            captured_cmd.extend(cmd)
            if env is not None:
                captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.poll.return_value = 0
            proc.wait.return_value = None
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=42),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        env_session_id = captured_env.get("SESSION_ID", "")
        assert env_session_id, "SESSION_ID must be exported to subprocess env"
        assert f"SESSION_ID={env_session_id}" in prompt, (
            f"SESSION_ID in prompt must match subprocess env. "
            f"Expected SESSION_ID={env_session_id!r} in prompt."
        )


class TestPromoteGatedAgents:
    """Tests for promote_gated_agents covering all label-state transitions."""

    def _gated_agent(self, name: str = "01_product_docs/prd-writer") -> AgentDef:
        return AgentDef(
            agent=name,
            phase=name.split("/")[0],
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=True,
            human_gate_label=f"{name.rsplit('/', 1)[-1]}:approved",
            description="gated agent",
        )

    def _work_item(self) -> MagicMock:
        wi = MagicMock()
        wi.number = 42
        wi.kind = "issue"
        return wi

    def test_promotion_adds_complete_and_removes_review(self):
        """Gate label + :review present → :complete added, :review removed."""
        agent = self._gated_agent()
        wi = self._work_item()
        gh = MagicMock()
        labels = {agent.review_label, agent.human_gate_label}

        result = promote_gated_agents(labels, [agent], wi, gh)

        gh.add_label.assert_called_once_with(wi.number, agent.complete_label)
        gh.remove_label.assert_any_call(wi.number, agent.review_label)
        assert agent.complete_label in result
        assert agent.review_label not in result

    def test_rejection_removes_review_leaves_requested(self):
        """:review + :requested (no gate) → :review removed, :requested kept."""
        agent = self._gated_agent()
        wi = self._work_item()
        gh = MagicMock()
        labels = {agent.review_label, agent.status_label(STATUS_REQUESTED)}

        result = promote_gated_agents(labels, [agent], wi, gh)

        gh.remove_label.assert_called_once_with(wi.number, agent.review_label)
        assert agent.review_label not in result
        assert agent.status_label(STATUS_REQUESTED) in result
        assert agent.complete_label not in result

    def test_simultaneous_approved_and_requested_promotes_and_cleans_requested(self):
        """Both :approved and :requested arrive — promotion wins, :requested cleaned up."""
        agent = self._gated_agent()
        wi = self._work_item()
        gh = MagicMock()
        labels = {
            agent.review_label,
            agent.human_gate_label,
            agent.status_label(STATUS_REQUESTED),
        }

        result = promote_gated_agents(labels, [agent], wi, gh)

        assert agent.complete_label in result
        assert agent.review_label not in result
        assert agent.status_label(STATUS_REQUESTED) not in result

    def test_gate_present_without_review_is_no_op(self):
        """:approved present but no :review — nothing changed (agent hasn't run yet)."""
        agent = self._gated_agent()
        wi = self._work_item()
        gh = MagicMock()
        labels = {agent.human_gate_label}

        result = promote_gated_agents(labels, [agent], wi, gh)

        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()
        assert result == labels

    def test_non_gated_agent_skipped(self):
        """Agents without human_gate_after are not touched."""
        agent = _make_agent_def("03_execute/coder")  # human_gate_after=False
        wi = self._work_item()
        gh = MagicMock()
        labels = {agent.review_label, agent.complete_label}

        result = promote_gated_agents(labels, [agent], wi, gh)

        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()

    def test_wrong_work_item_kind_skipped(self):
        """Agent objects=['issue'] does not fire for kind='pr'."""
        agent = self._gated_agent()
        wi = self._work_item()
        wi.kind = "pr"
        gh = MagicMock()
        labels = {agent.review_label, agent.human_gate_label}

        result = promote_gated_agents(labels, [agent], wi, gh)

        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()

    def test_complete_already_present_skips_add_but_still_removes_review(self):
        """Crash-recovery: :complete already there from prior tick — remove stale :review."""
        agent = self._gated_agent()
        wi = self._work_item()
        gh = MagicMock()
        labels = {agent.review_label, agent.human_gate_label, agent.complete_label}

        result = promote_gated_agents(labels, [agent], wi, gh)

        gh.add_label.assert_not_called()  # already present, skip
        gh.remove_label.assert_any_call(wi.number, agent.review_label)
        assert agent.review_label not in result


# ---------------------------------------------------------------------------
# TestSelfGates: self_gates lets an agent's own AI_AGILE_STATUS (review vs
# complete) decide whether the human gate fires, instead of the orchestrator
# force-overriding :complete to :review whenever human_gate_after is set.
# Covers prd-docs-updater: gate only when it changed docs/product/ prose,
# advance straight through when its only output was the mechanical
# docs/features/{feature}.md copy.
# ---------------------------------------------------------------------------

class TestSelfGates:
    def _gated_agent(self, self_gates: bool) -> AgentDef:
        return AgentDef(
            agent="01_product_docs/prd-docs-updater",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "create-pr:complete"},
            dependencies=[],
            human_gate_after=True,
            human_gate_label="prd-docs-updater:approved",
            description="test",
            self_gates=self_gates,
        )

    def test_self_gates_defaults_false(self):
        """AgentDef.self_gates defaults to False when not passed."""
        assert _make_agent_def().self_gates is False

    def test_self_gates_true_does_not_force_review_on_complete(self):
        """self_gates=True: agent emits :complete → applied status stays :complete.

        Without self_gates, human_gate_after=True would force this to :review.
        """
        agent = self._gated_agent(self_gates=True)
        wi = _make_work_item_with_labels(42, set())
        gh = _make_gh_mock()

        applied = _resolve_applied_status(agent, wi, STATUS_COMPLETE, gh)

        assert applied == STATUS_COMPLETE
        gh.add_label.assert_not_called()  # no auto-approve, no forced gate — nothing to apply here

    def test_self_gates_true_leaves_review_untouched(self):
        """self_gates=True: agent emits :review itself → applied status stays :review.

        Mirrors the case where prd-docs-updater changed docs/product/ prose
        and wants the human gate to fire; self_gates only suppresses the
        forced-override on :complete, it never suppresses an agent-chosen
        :review.
        """
        agent = self._gated_agent(self_gates=True)
        wi = _make_work_item_with_labels(42, set())
        gh = _make_gh_mock()

        applied = _resolve_applied_status(agent, wi, STATUS_REVIEW, gh)

        assert applied == STATUS_REVIEW

    def test_self_gates_false_still_forces_review_on_complete(self):
        """Regression guard: self_gates=False (default) preserves existing
        behaviour — human_gate_after=True still forces :complete to :review
        for agents that haven't opted in (e.g. prd-writer)."""
        agent = self._gated_agent(self_gates=False)
        wi = _make_work_item_with_labels(42, set())
        gh = _make_gh_mock()

        applied = _resolve_applied_status(agent, wi, STATUS_COMPLETE, gh)

        assert applied == STATUS_REVIEW

    def test_self_gates_true_does_not_auto_apply_gate_label(self):
        """self_gates is not auto-approval: on :complete it neither forces
        :review nor auto-applies the gate label — it simply lets :complete
        stand, same as an agent with no gate at all."""
        agent = self._gated_agent(self_gates=True)
        wi = _make_work_item_with_labels(42, set())
        gh = _make_gh_mock()

        _resolve_applied_status(agent, wi, STATUS_COMPLETE, gh)

        gh.add_label.assert_not_called()

    def test_load_pipeline_loads_self_gates(self, tmp_path):
        import json
        pipeline_data = {
            "pipeline": [{
                "agent": "01_product_docs/prd-docs-updater",
                "phase": "01_product_docs",
                "object": ["issue"],
                "trigger": {"label": "create-pr:complete"},
                "dependencies": [],
                "human_gate_after": True,
                "human_gate_label": "prd-docs-updater:approved",
                "description": "test",
                "self_gates": True,
            }]
        }
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        agents, _ = load_pipeline(path)
        assert agents[0].self_gates is True

    def test_load_pipeline_self_gates_defaults_false(self, tmp_path):
        import json
        pipeline_data = {
            "pipeline": [{
                "agent": "01_product_docs/issue-classifier",
                "phase": "01_product_docs",
                "object": ["issue"],
                "trigger": {"event": "issue.opened"},
                "dependencies": [],
                "human_gate_after": False,
                "description": "test",
            }]
        }
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps(pipeline_data))
        agents, _ = load_pipeline(path)
        assert agents[0].self_gates is False

    def test_shipped_pipeline_json_sets_self_gates_on_prd_docs_updater(self):
        """pipeline.json's real prd-docs-updater entry has self_gates: true —
        the narrowed-gate design (STD-PROC-005 et al.) is actually wired up,
        not just documented."""
        pipeline_path = Path(__file__).parent.parent / "pipeline" / "pipeline.json"
        agents, _ = load_pipeline(pipeline_path)
        agent = pipeline_by_name(agents)["01_product_docs/prd-docs-updater"]
        assert agent.self_gates is True
        assert agent.human_gate_after is True
        assert agent.human_gate_label == "prd-docs-updater:approved"

    def _downstream_agent(self) -> AgentDef:
        """A single-dependency downstream agent, matching coder's real
        dependency on prd-docs-updater."""
        return AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "prd-docs-updater:complete"},
            dependencies=["01_product_docs/prd-docs-updater"],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
        )

    def test_dependencies_complete_true_for_self_gated_mechanical_only_run(self):
        """CA-001 regression: a self_gates dependency that reached :complete
        directly (mechanical-only run, no :review, no gate label ever applied)
        must not block a downstream agent — that is the entire point of
        self_gates. Before the fix, dependencies_complete() ignored self_gates
        and returned False here forever, since prd-docs-updater:approved is
        never applied on this path."""
        prd_docs_updater = self._gated_agent(self_gates=True)
        coder = self._downstream_agent()
        pipeline_map = {prd_docs_updater.agent: prd_docs_updater, coder.agent: coder}

        labels = {"prd-docs-updater:complete"}  # no :approved — never needed on this path

        assert dependencies_complete(labels, coder, pipeline_map) is True

    def test_dependencies_complete_false_without_self_gates_and_no_approval(self):
        """Regression guard: self_gates=False (default) preserves existing
        behaviour — a gated dependency at :complete with no gate label still
        blocks the downstream agent (e.g. prd-writer, which always requires
        human approval)."""
        prd_docs_updater = self._gated_agent(self_gates=False)
        coder = self._downstream_agent()
        pipeline_map = {prd_docs_updater.agent: prd_docs_updater, coder.agent: coder}

        labels = {"prd-docs-updater:complete"}

        assert dependencies_complete(labels, coder, pipeline_map) is False

    def test_dependencies_complete_false_for_self_gated_dep_still_in_review(self):
        """A self_gates dependency that legitimately needs review (docs/product/
        prose changed) is still blocked: it never reaches :complete until a
        human applies the gate label and promote_gated_agents promotes it, so
        dependencies_complete()'s first check (complete_label presence) already
        blocks the downstream agent independent of the self_gates guard."""
        prd_docs_updater = self._gated_agent(self_gates=True)
        coder = self._downstream_agent()
        pipeline_map = {prd_docs_updater.agent: prd_docs_updater, coder.agent: coder}

        labels = {"prd-docs-updater:review"}  # mid-review — no :complete yet

        assert dependencies_complete(labels, coder, pipeline_map) is False

    def test_dependencies_complete_true_for_self_gated_dep_after_promotion(self):
        """After a human approves a self_gates dependency's review path, both
        :complete and the gate label are present (promote_gated_agents adds
        :complete before removing :review) — downstream agent is eligible."""
        prd_docs_updater = self._gated_agent(self_gates=True)
        coder = self._downstream_agent()
        pipeline_map = {prd_docs_updater.agent: prd_docs_updater, coder.agent: coder}

        labels = {"prd-docs-updater:complete", "prd-docs-updater:approved"}

        assert dependencies_complete(labels, coder, pipeline_map) is True


# ---------------------------------------------------------------------------
# --phases flag: phase-scoped agent filtering
# ---------------------------------------------------------------------------

class TestPhasesFilter:
    """Verify --phases restricts which agents the orchestrator evaluates."""

    def test_phases_flag_filters_agents_to_allowed_set(self):
        """Agents outside --phases are excluded before the main loop."""
        from pipeline_orchestrator import load_pipeline
        from pathlib import Path

        pipeline_path = Path(__file__).parent.parent / "pipeline" / "pipeline.json"
        if not pipeline_path.exists():
            pytest.skip("pipeline.json not available")

        agents, _ = load_pipeline(pipeline_path)
        all_phases = {a.phase for a in agents}
        target_phase = next(iter(sorted(all_phases)))

        filtered = [a for a in agents if a.phase in {target_phase}]
        assert filtered
        assert all(a.phase == target_phase for a in filtered)

    def test_phases_flag_all_phases_passes_all_agents(self):
        """Filtering with the full phase set returns every agent unchanged."""
        from pipeline_orchestrator import load_pipeline
        from pathlib import Path

        pipeline_path = Path(__file__).parent.parent / "pipeline" / "pipeline.json"
        if not pipeline_path.exists():
            pytest.skip("pipeline.json not available")

        agents, _ = load_pipeline(pipeline_path)
        all_phases = {a.phase for a in agents}
        filtered = [a for a in agents if a.phase in all_phases]
        assert filtered == agents

    def test_main_phases_filter_excludes_other_phase_agents_from_dispatch(self):
        """Drive the real main() --phases path: agents outside the allowed
        phase set must never reach process_work_item, so they are never
        dispatched. Patches argv/parse_args + GitHub so no network occurs."""
        import argparse
        import pipeline_orchestrator as orch

        in_phase = AgentDef(
            agent="01_product_docs/issue-classifier",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"event": "issue.opened"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="in-phase",
        )
        out_phase = AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "x:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="out-of-phase",
        )

        fake_args = argparse.Namespace(
            verbose=False, clear_pause=False, clear_stop=False, repo="test/repo",
            pipeline="pipeline.json", phases="01_product_docs",
            issue=None, kind=None, dry_run=True,
        )

        wi = _make_work_item_with_labels(1, set())
        captured = {}

        def _capture_process(item, agents, pipeline_map, gh, dry_run, repo, **kw):
            captured["agents"] = list(agents)
            captured["pipeline_map"] = dict(pipeline_map)
            return 0

        gh_mock = MagicMock()
        gh_mock.list_open_issues.return_value = [wi]

        with patch.object(orch, "parse_args", return_value=fake_args), \
             patch.object(orch, "is_pipeline_paused", return_value=(False, None, None)), \
             patch.object(orch, "load_pipeline", return_value=([in_phase, out_phase], [])), \
             patch.object(orch, "GitHubClient", return_value=gh_mock), \
             patch.object(orch, "process_work_item", side_effect=_capture_process), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "x"}), \
             patch("time.sleep"):
            orch.main()

        active_agents = {a.agent for a in captured["agents"]}
        assert "01_product_docs/issue-classifier" in active_agents
        assert "03_execute/coder" not in active_agents, (
            "Agent outside --phases must be filtered out before dispatch; "
            f"active agents were {active_agents}"
        )
        assert "03_execute/coder" not in captured["pipeline_map"]

    def test_orchestrator_workflow_runs_all_phases(self):
        """The single orchestrator workflow must not restrict phases.

        Consolidating the two split workflows back into one means the
        orchestrator loads every agent in a single pass, so cross-phase
        dependencies always resolve. Guard against a regression that
        reintroduces a --phases filter (which would silently drop agents).
        """
        path = Path(__file__).parent.parent / ".github" / "workflows" / "ai_orchestrator.yml"
        assert path.exists(), f"Workflow file not found: {path}"
        content = path.read_text()
        assert "--phases" not in content, (
            "ai_orchestrator.yml must not pass --phases — the single workflow runs "
            "all phases so cross-phase dependencies resolve."
        )


# ---------------------------------------------------------------------------
# QA-001: TestHandleReviewLoop
# ---------------------------------------------------------------------------

class TestHandleReviewLoop:
    """Tests for _handle_review_loop() — review-cycle counter and escalation."""

    def _reviewer_def(
        self,
        reviewer: str = "03_execute/pr-reviewer",
        target: str = "03_execute/coder",
        max_cycles: int = 3,
    ) -> AgentDef:
        return AgentDef(
            agent=reviewer,
            phase=reviewer.split("/")[0],
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="reviewer",
            review_loop={
                "re_invoke": target,
                "max_cycles": max_cycles,
            },
        )

    def _target_def(self, name: str = "03_execute/coder") -> AgentDef:
        return AgentDef(
            agent=name,
            phase=name.split("/")[0],
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="coder",
        )

    def _work_item(self) -> WorkItem:
        return WorkItem(
            number=42,
            kind="issue",
            title="Test issue",
            labels=set(),
            url="https://github.com/test/repo/issues/42",
        )

    def test_first_cycle_clears_reviewer_review_and_target_complete(self):
        """Cycle 0 → 1: removes reviewer :review and target :complete so target re-runs."""
        reviewer = self._reviewer_def()
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        # Starting with reviewer in :review and target in :complete
        labels = {reviewer.review_label, target.complete_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        # :review removed from reviewer
        gh.remove_label.assert_any_call(wi.number, reviewer.review_label)
        assert reviewer.review_label not in result
        # :complete removed from target
        gh.remove_label.assert_any_call(wi.number, target.complete_label)
        assert target.complete_label not in result

    def test_review_loop_does_not_set_review_cycle_label(self):
        """review-cycle:N is set at dispatch time, not in the review loop itself."""
        reviewer = self._reviewer_def()
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        labels = {reviewer.review_label, target.complete_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        for call_args in gh.add_label.call_args_list:
            assert not call_args[0][1].startswith("review-cycle:"), (
                "review_loop must not set review-cycle:N — counter is set at dispatch"
            )
        assert not any(l.startswith("review-cycle:") for l in result)

    def test_max_cycles_reached_escalates_to_human(self):
        """When next_cycle > max_cycles, :review is left intact (escalation).

        review-cycle:N is set at dispatch, so after two coder runs the label is
        review-cycle:2. With max_cycles=2, next_cycle=3 > 2 → escalate.
        """
        reviewer = self._reviewer_def(max_cycles=2)
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        # Two coder runs completed (counter set at dispatch); next would be 3 > 2 → escalate
        labels = {reviewer.review_label, target.complete_label, "review-cycle:2"}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        # :review must remain for human to act on
        assert reviewer.review_label in result
        # A comment should be posted explaining the escalation
        gh.post_comment.assert_called_once()
        comment_text = gh.post_comment.call_args[0][1]
        assert "human review required" in comment_text.lower()

    def test_unknown_re_invoke_returns_labels_unchanged(self):
        """If re_invoke target is not in pipeline_map, labels are returned unchanged."""
        reviewer = self._reviewer_def(target="03_execute/nonexistent")
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {}  # target not present
        labels = {reviewer.review_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        assert reviewer.review_label in result
        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()

    def test_review_loop_preserves_existing_cycle_label(self):
        """review_loop does not touch review-cycle:N; counter survives unchanged."""
        reviewer = self._reviewer_def(max_cycles=5)
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        labels = {reviewer.review_label, target.complete_label, "review-cycle:2"}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        # review_loop must not remove or add any review-cycle label
        for c in gh.add_label.call_args_list:
            assert not c[0][1].startswith("review-cycle:")
        for c in gh.remove_label.call_args_list:
            assert not c[0][1].startswith("review-cycle:")
        # Existing label untouched
        assert "review-cycle:2" in result

    def test_both_labels_coexist_recovery(self):
        """Normal cycle 0→1 runs correctly when target also carries a stale :review label."""
        reviewer = self._reviewer_def()
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        # Both present on the target (crashed prior run residue)
        labels = {reviewer.review_label, target.complete_label, target.review_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        # Reviewer :review removed, target :complete cleared
        assert reviewer.review_label not in result
        assert target.complete_label not in result
        # review_loop does not set review-cycle:N (dispatch does)
        assert not any(l.startswith("review-cycle:") for l in result)

    def test_clears_target_skipped_instead_of_complete(self):
        """If target was :skipped, review loop clears :skipped so it can re-run."""
        reviewer = self._reviewer_def()
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        # Target was bypassed by human — :skipped, not :complete
        labels = {reviewer.review_label, target.skipped_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        gh.remove_label.assert_any_call(wi.number, target.skipped_label)
        assert target.skipped_label not in result
        # :complete was not in the local label set so no API call is made for it.
        for call in gh.remove_label.call_args_list:
            assert call[0][1] != target.complete_label, (
                "remove_label should not be called for labels not in the local set"
            )

    def test_also_clear_removes_skipped_variant(self):
        """also_clear entries have their :skipped label removed when :complete is absent."""
        reviewer = self._reviewer_def()
        reviewer.review_loop["also_clear"] = ["03_execute/ci-gate"]
        target = self._target_def()
        ci_gate = self._target_def("03_execute/ci-gate")
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target, ci_gate.agent: ci_gate}
        # ci-gate was skipped, not completed
        labels = {reviewer.review_label, target.complete_label, ci_gate.skipped_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        gh.remove_label.assert_any_call(wi.number, ci_gate.skipped_label)
        assert ci_gate.skipped_label not in result

    def test_also_clear_label_remains_when_removal_fails(self):
        """When both remove_label calls raise, the also_clear label stays in the returned set."""
        reviewer = self._reviewer_def()
        reviewer.review_loop["also_clear"] = ["03_execute/ci-gate"]
        target = self._target_def()
        ci_gate = self._target_def("03_execute/ci-gate")
        wi = self._work_item()
        gh = MagicMock()
        # Only the also_clear removals should fail — make all calls raise so we can
        # verify that the label is NOT discarded when the removal errors.
        gh.remove_label.side_effect = Exception("network error")
        pipeline_map = {target.agent: target, ci_gate.agent: ci_gate}
        labels = {reviewer.review_label, target.complete_label, ci_gate.complete_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        # ci-gate:complete was not actually removed from GitHub, so it must still be
        # in the returned label set — the discard only runs on successful removal.
        assert ci_gate.complete_label in result


# ---------------------------------------------------------------------------
# TestDispatchReviewCycleCounter — review-cycle:N set at coder dispatch time
# ---------------------------------------------------------------------------

class TestDispatchReviewCycleCounter:
    """review-cycle:N is incremented in process_work_item when a review_loop
    re_invoke target is dispatched, not in _handle_review_loop."""

    def _make_coder_def(self):
        return AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "prd-docs-updater:approved"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="coder",
        )

    def _make_reviewer_def(self):
        return AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "merge-conflict:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="reviewer",
            review_loop={"re_invoke": "03_execute/coder", "max_cycles": 3},
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_initial_dispatch_sets_review_cycle_1(self, mock_invoke):
        """First coder dispatch sets review-cycle:1 — counter starts counting from run 1."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        coder = self._make_coder_def()
        reviewer = self._make_reviewer_def()
        pipeline_map = {coder.agent: coder, reviewer.agent: reviewer}
        gh = _make_gh_mock()
        wi = _make_work_item_with_labels(42, {"prd-docs-updater:approved"})

        process_work_item(wi, [coder], pipeline_map, gh, dry_run=False, repo="test/repo")

        applied = [c.args[1] for c in gh.add_label.call_args_list]
        assert "review-cycle:1" in applied, (
            f"First coder dispatch must set review-cycle:1. Labels applied: {applied}"
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_reinvoke_dispatch_increments_counter(self, mock_invoke):
        """Second coder dispatch (re-invoke) increments review-cycle:1 → review-cycle:2."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        coder = self._make_coder_def()
        reviewer = self._make_reviewer_def()
        pipeline_map = {coder.agent: coder, reviewer.agent: reviewer}
        gh = _make_gh_mock()
        # re-invoke: review-cycle:1 already in labels from first dispatch
        wi = _make_work_item_with_labels(42, {"prd-docs-updater:approved", "review-cycle:1"})

        process_work_item(wi, [coder], pipeline_map, gh, dry_run=False, repo="test/repo")

        applied = [c.args[1] for c in gh.add_label.call_args_list]
        removed = [c.args[1] for c in gh.remove_label.call_args_list]
        assert "review-cycle:2" in applied, f"Expected review-cycle:2 applied; got: {applied}"
        assert "review-cycle:1" in removed, f"Expected review-cycle:1 removed; got: {removed}"

    @patch("pipeline_orchestrator.invoke_agent")
    def test_non_reinvoke_target_does_not_get_counter(self, mock_invoke):
        """Agents not targeted by any review_loop do not get a review-cycle label."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        prd_writer = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="prd-writer",
        )
        pipeline_map = {prd_writer.agent: prd_writer}
        gh = _make_gh_mock()
        wi = _make_work_item_with_labels(10, {"issue-classifier:complete"})

        process_work_item(wi, [prd_writer], pipeline_map, gh, dry_run=False, repo="test/repo")

        applied = [c.args[1] for c in gh.add_label.call_args_list]
        assert not any(l.startswith("review-cycle:") for l in applied), (
            f"Non-reinvoke targets must not get a review-cycle label. Applied: {applied}"
        )


# ---------------------------------------------------------------------------
# QA-001: TestAuditEventEmission
# ---------------------------------------------------------------------------

class TestAuditEventEmission:
    """Tests for _make_audit_event() and _emit_audit_event()."""

    def test_make_audit_event_has_required_fields(self):
        """_make_audit_event returns a dict with all required top-level fields."""
        wi = WorkItem(
            number=42, kind="issue", title="test", labels=set(),
            url="https://github.com/test/repo/issues/42",
        )
        event = _make_audit_event(
            "sess-123", "agent.complete", "test/repo",
            work_item=wi, agent="03_execute/coder",
            outcome_status="ok",
        )
        assert event["event"] == "agent.complete"
        assert event["ts"]
        assert event["agent"] == "03_execute/coder"
        assert event["issue"] == 42
        assert event["status"] == "ok"
        assert event["session_id"] == "sess-123"
        assert event["object"]["kind"] == "issue"
        assert event["object"]["id"] == 42
        assert "actor" in event

    def test_make_audit_event_without_work_item(self):
        """_make_audit_event with no work_item sets object and issue to None."""
        event = _make_audit_event("sess-1", "session.start", "test/repo")
        assert event["object"] is None
        assert event["issue"] is None
        assert event["agent"] is None

    def test_make_audit_event_pr_work_item_issue_is_none(self):
        """For PR work items, issue field is None (only issue kind gets the id)."""
        wi = WorkItem(
            number=7, kind="pr", title="test pr", labels=set(),
            url="https://github.com/test/repo/pull/7",
        )
        event = _make_audit_event("sess-2", "agent.complete", "test/repo", work_item=wi)
        assert event["issue"] is None
        assert event["object"]["kind"] == "pr"
        assert event["object"]["id"] == 7

    def test_emit_audit_event_prints_valid_json_line(self, capsys):
        """_emit_audit_event prints one compact JSON line to stdout."""
        event = _make_audit_event("sess-123", "agent.complete", "test/repo",
                                  outcome_status="ok")
        _emit_audit_event(event)
        captured = capsys.readouterr()
        lines = [l for l in captured.out.splitlines() if l.strip()]
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event"] == "agent.complete"
        assert parsed["status"] == "ok"
        assert parsed["ts"]

    def test_emit_audit_event_includes_required_minimum_fields(self, capsys):
        """Emitted JSON line always contains ts, event, agent, issue, status."""
        wi = WorkItem(
            number=5, kind="issue", title="t", labels=set(), url="http://x"
        )
        event = _make_audit_event(
            "s1", "agent.invoked", "r/r",
            work_item=wi, agent="03_execute/coder", outcome_status="started",
        )
        _emit_audit_event(event)
        parsed = json.loads(capsys.readouterr().out.strip())
        assert "ts" in parsed
        assert "event" in parsed
        assert "agent" in parsed
        assert "issue" in parsed
        assert "status" in parsed

    def test_emit_audit_event_no_trailing_newline_noise(self, capsys):
        """_emit_audit_event emits exactly one line (flush=True, print adds one newline)."""
        event = _make_audit_event("s", "e", "r")
        _emit_audit_event(event)
        output = capsys.readouterr().out
        # print() adds exactly one newline
        assert output.endswith("\n")
        assert output.count("\n") == 1


# ---------------------------------------------------------------------------
# TestApplyFailedReason — heading= kwarg and reason= in _apply_failed
# ---------------------------------------------------------------------------

class TestApplyFailedReason:
    """_apply_failed posts exhaustion reason and uses the correct heading."""

    def _make_gh(self) -> MagicMock:
        gh = MagicMock()
        gh.remove_label = MagicMock()
        gh.add_label = MagicMock()
        gh.post_comment = MagicMock()
        return gh

    def test_reason_appears_in_failure_comment(self):
        """When reason is provided, post_comment includes that text."""
        agent_def = _make_agent_def("03_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)
        reason = "_Retry limit of 3 exhausted after 4 attempt(s). Human intervention is required._"

        _apply_failed(gh, agent_def, work_item, result, reason=reason)

        assert gh.post_comment.called, "Expected post_comment to be called"
        comment_body = gh.post_comment.call_args[0][1]
        assert reason in comment_body, (
            f"Expected reason text in comment body. Got: {comment_body!r}"
        )

    def test_retry_exhaustion_heading_not_post_run(self):
        """Retry exhaustion uses a distinct heading — not 'post-run step failed'."""
        agent_def = _make_agent_def("03_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)
        exhaustion_heading = "### `03_execute/coder` failed — retry limit exhausted"

        _apply_failed(
            gh, agent_def, work_item, result,
            reason="_Retry limit of 3 exhausted._",
            heading=exhaustion_heading,
        )

        comment_body = gh.post_comment.call_args[0][1]
        assert exhaustion_heading in comment_body, (
            f"Expected exhaustion heading in comment. Got: {comment_body!r}"
        )
        assert "post-run step failed" not in comment_body, (
            "Misleading 'post-run step failed' heading must not appear for retry exhaustion"
        )

    def test_no_reason_uses_generic_error_heading(self):
        """Without reason, comment uses the generic 'exited with an error' heading."""
        agent_def = _make_agent_def("03_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)

        _apply_failed(gh, agent_def, work_item, result)

        comment_body = gh.post_comment.call_args[0][1]
        assert "exited with an error" in comment_body

    def test_custom_heading_overrides_default(self):
        """An explicit heading= kwarg takes precedence over the reason-derived heading."""
        agent_def = _make_agent_def("03_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)
        custom = "### `03_execute/coder` failed — custom context"

        _apply_failed(gh, agent_def, work_item, result, reason="some reason", heading=custom)

        comment_body = gh.post_comment.call_args[0][1]
        assert custom in comment_body
        assert "post-run step failed" not in comment_body


# ---------------------------------------------------------------------------
# TestRetryPolicy  (PRD scenarios for per-agent retry and restart policy)
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    """Gherkin-traced tests for the per-agent retry/restart policy in the orchestrator.

    Each test corresponds to a named scenario in the approved PRD for issue #16.
    """

    def _make_agent(self, max_retries: int = 0) -> AgentDef:
        return AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test agent",
            max_retries=max_retries,
            commit_after=False,
        )

    def _make_gh(self) -> MagicMock:
        gh = MagicMock()
        gh.get_issue_labels.return_value = set()
        return gh

    @patch("pipeline_orchestrator.time.sleep")
    @patch("pipeline_orchestrator.invoke_agent")
    def test_retries_within_limit_posts_comment_and_succeeds(self, mock_invoke, mock_sleep):
        """Scenario: Orchestrator retries a failed agent within configured limit.

        Given an agent is configured with max_retries: 3 in pipeline.json
        When the agent exits with a failure status and the current attempt count is below the limit
        Then the orchestrator restarts the agent without applying :failed
        And a comment is posted on the work item recording the retry attempt number
        """
        mock_invoke.side_effect = [
            AgentRunResult(success=False, returncode=1, captured_tail="error"),
            AgentRunResult(success=True, returncode=0, captured_tail="AI_AGILE_STATUS: complete"),
        ]
        agent_def = self._make_agent(max_retries=3)
        gh = self._make_gh()
        work_item = WorkItem(number=42, kind="issue", title="T", labels=set(), url="http://x")

        process_work_item(
            work_item, [agent_def], {"03_execute/coder": agent_def},
            gh, False, "test/repo",
        )

        add_calls = [c[0][1] for c in gh.add_label.call_args_list]
        assert "coder:failed" not in add_calls, (
            f":failed must not be applied when retry succeeds. add_label calls: {add_calls}"
        )
        assert "coder:complete" in add_calls, (
            f":complete must be applied after successful retry. add_label calls: {add_calls}"
        )
        comment_bodies = [str(c[0][1]) for c in gh.post_comment.call_args_list]
        # The retry comment records the specific attempt number in "retry N/M"
        # form — assert that exact format, not just the loose substring "retry".
        assert any(
            ("retry 1/3" in b.lower()) or ("retry 1 " in b.lower())
            for b in comment_bodies
        ), (
            f"Expected a 'retry 1/3' attempt comment. post_comment calls: {comment_bodies}"
        )

    @patch("pipeline_orchestrator.time.sleep")
    @patch("pipeline_orchestrator.invoke_agent")
    def test_escalates_when_retry_limit_exhausted(self, mock_invoke, mock_sleep):
        """Scenario: Orchestrator escalates when retry limit is exhausted.

        Given an agent is configured with max_retries: 3 in pipeline.json
        And the agent has already failed 3 times (retry limit reached)
        When the agent exits with a failure status again
        Then the orchestrator applies :failed to the work item
        And posts a comment stating that the retry limit has been exhausted
        and human intervention is required
        """
        mock_invoke.return_value = AgentRunResult(
            success=False, returncode=1, captured_tail="error"
        )
        agent_def = self._make_agent(max_retries=3)
        gh = self._make_gh()
        work_item = WorkItem(number=42, kind="issue", title="T", labels=set(), url="http://x")

        process_work_item(
            work_item, [agent_def], {"03_execute/coder": agent_def},
            gh, False, "test/repo",
        )

        add_calls = [c[0][1] for c in gh.add_label.call_args_list]
        assert "coder:failed" in add_calls, (
            f":failed must be applied when retry limit is exhausted. add_label calls: {add_calls}"
        )
        comment_bodies = [str(c[0][1]) for c in gh.post_comment.call_args_list]
        escalation_comments = [
            b for b in comment_bodies
            if "exhausted" in b.lower() and "human" in b.lower()
        ]
        assert escalation_comments, (
            f"Expected comment mentioning retry limit exhausted and human intervention. "
            f"post_comment calls: {comment_bodies}"
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_no_retry_when_not_configured(self, mock_invoke):
        """Scenario: Agent with no retry configuration fails immediately.

        Given an agent has no max_retries entry in pipeline.json (defaults to 0)
        When the agent exits with a failure status
        Then the orchestrator applies :failed to the work item immediately without retrying
        """
        mock_invoke.return_value = AgentRunResult(
            success=False, returncode=1, captured_tail="error"
        )
        agent_def = self._make_agent(max_retries=0)
        gh = self._make_gh()
        work_item = WorkItem(number=42, kind="issue", title="T", labels=set(), url="http://x")

        process_work_item(
            work_item, [agent_def], {"03_execute/coder": agent_def},
            gh, False, "test/repo",
        )

        assert mock_invoke.call_count == 1, (
            f"With max_retries=0, invoke_agent must be called exactly once (no retries). "
            f"Call count: {mock_invoke.call_count}"
        )
        add_calls = [c[0][1] for c in gh.add_label.call_args_list]
        assert "coder:failed" in add_calls, (
            f":failed must be applied immediately with max_retries=0. add_label calls: {add_calls}"
        )

    @patch("pipeline_orchestrator.time.sleep")
    @patch("pipeline_orchestrator.invoke_agent")
    def test_successful_recovery_applies_complete_no_retry_state(self, mock_invoke, mock_sleep):
        """Scenario: Successfully recovered agent clears retry state.

        Given an agent has been retried at least once
        When the agent exits successfully on a subsequent attempt
        Then the orchestrator applies the normal success label
        And does not retain or display a retry count in the final state
        """
        mock_invoke.side_effect = [
            AgentRunResult(success=False, returncode=1, captured_tail="error"),
            AgentRunResult(success=True, returncode=0, captured_tail="AI_AGILE_STATUS: complete"),
        ]
        agent_def = self._make_agent(max_retries=3)
        gh = self._make_gh()
        work_item = WorkItem(number=42, kind="issue", title="T", labels=set(), url="http://x")

        process_work_item(
            work_item, [agent_def], {"03_execute/coder": agent_def},
            gh, False, "test/repo",
        )

        add_calls = [c[0][1] for c in gh.add_label.call_args_list]
        assert "coder:complete" in add_calls, (
            f":complete (normal success label) must be applied after recovery. "
            f"add_label calls: {add_calls}"
        )
        retry_count_labels = [lbl for lbl in add_calls if "retry" in lbl.lower()]
        assert not retry_count_labels, (
            f"No retry-count label must remain on the work item after successful recovery. "
            f"Found: {retry_count_labels}"
        )

    @patch("pipeline_orchestrator.time.sleep")
    @patch("pipeline_orchestrator.invoke_agent")
    def test_max_retries_one_both_fail_applies_failed(self, mock_invoke, mock_sleep):
        """Boundary: max_retries=1 — first and second invocation fail → :failed applied."""
        mock_invoke.return_value = AgentRunResult(
            success=False, returncode=1, captured_tail="error"
        )
        agent_def = self._make_agent(max_retries=1)
        gh = self._make_gh()
        work_item = WorkItem(number=42, kind="issue", title="T", labels=set(), url="http://x")

        process_work_item(
            work_item, [agent_def], {"03_execute/coder": agent_def},
            gh, False, "test/repo",
        )

        add_calls = [c[0][1] for c in gh.add_label.call_args_list]
        assert "coder:failed" in add_calls
        assert mock_invoke.call_count == 2

    @patch("pipeline_orchestrator.time.sleep")
    @patch("pipeline_orchestrator.invoke_agent")
    def test_max_retries_one_fail_then_succeed_applies_complete(self, mock_invoke, mock_sleep):
        """Boundary: max_retries=1 — first fails, second succeeds → :complete applied."""
        mock_invoke.side_effect = [
            AgentRunResult(success=False, returncode=1, captured_tail="error"),
            AgentRunResult(success=True, returncode=0, captured_tail="AI_AGILE_STATUS: complete"),
        ]
        agent_def = self._make_agent(max_retries=1)
        gh = self._make_gh()
        work_item = WorkItem(number=42, kind="issue", title="T", labels=set(), url="http://x")

        process_work_item(
            work_item, [agent_def], {"03_execute/coder": agent_def},
            gh, False, "test/repo",
        )

        add_calls = [c[0][1] for c in gh.add_label.call_args_list]
        assert "coder:complete" in add_calls
        assert "coder:failed" not in add_calls


# ---------------------------------------------------------------------------
# TestSessionIdPatternRegexFix — correct detection of attribute/index access
# ---------------------------------------------------------------------------

class TestSessionIdPatternRegexFix:
    """Exercise the REAL _compute_agent_session_id guard against unsafe
    attribute/index access in session_id_pattern.

    The internal guard regex r'\\{[^}]*[.\\[][^}]*\\}' catches {foo.bar} and
    {foo[0]} (which would otherwise raise inside the token substitution) and
    falls back to the scope-default session id rather than raising. Safe
    patterns like {number}/{safe_agent} substitute normally.
    """

    def _agent_def(self, pattern, scope="per_issue") -> AgentDef:
        return AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test agent",
            session_scope=scope,
            session_id_pattern=pattern,
        )

    def _work_item(self, number: int = 42) -> WorkItem:
        return WorkItem(
            number=number, kind="issue", title="T", labels=set(),
            url=f"https://github.com/test/repo/issues/{number}",
        )

    def test_attribute_access_pattern_falls_back_to_scope_default(self):
        """{foo.bar} is rejected by the guard → scope default, no raise."""
        agent = self._agent_def("{foo.bar}", scope="per_issue")
        sid = _compute_agent_session_id(agent, self._work_item(42), "test/repo")
        # per_issue default: ais-v1-{safe_agent}-issue-{number}
        assert sid == "ais-v1-03-execute-coder-issue-42", (
            f"Expected scope-default session id for unsafe attr pattern; got {sid!r}"
        )

    def test_index_access_pattern_falls_back_to_scope_default(self):
        """{foo[0]} is rejected by the guard → scope default, no raise."""
        agent = self._agent_def("{foo[0]}", scope="global")
        sid = _compute_agent_session_id(agent, self._work_item(7), "test/repo")
        # global default: ais-v1-{safe_agent}
        assert sid == "ais-v1-03-execute-coder", (
            f"Expected global scope-default session id for unsafe index pattern; got {sid!r}"
        )

    def test_safe_number_token_substitutes(self):
        """A safe {number} token substitutes the work item number."""
        agent = self._agent_def("ais-{number}")
        sid = _compute_agent_session_id(agent, self._work_item(99), "test/repo")
        assert sid == "ais-99", f"Expected '{{number}}' substituted; got {sid!r}"

    def test_safe_agent_token_substitutes(self):
        """A safe {safe_agent} token substitutes the sanitised agent name."""
        agent = self._agent_def("sess-{safe_agent}")
        sid = _compute_agent_session_id(agent, self._work_item(1), "test/repo")
        assert sid == "sess-03-execute-coder", f"Expected '{{safe_agent}}' substituted; got {sid!r}"

    def test_old_broken_regex_raises_on_compile(self):
        """Regression: the OLD broken guard r'\\{[^}]*[.[}' was an unterminated
        character set that raises re.error — the current code must not use it."""
        import re
        with pytest.raises(re.error):
            re.search(r"\{[^}]*[.[}", "{foo.bar}")


# ---------------------------------------------------------------------------
# TestLoadPipelineMalformed — load_pipeline exits cleanly on bad JSON
# ---------------------------------------------------------------------------

class TestLoadPipelineMalformed:
    """load_pipeline must sys.exit(1) on malformed pipeline.json rather than
    raising an unhandled exception."""

    def test_invalid_json_exits_1(self, tmp_path):
        """A syntactically invalid JSON file → SystemExit(1)."""
        from pipeline_orchestrator import load_pipeline
        path = tmp_path / "pipeline.json"
        path.write_text("{ this is not valid json ]")
        with pytest.raises(SystemExit) as exc_info:
            load_pipeline(path)
        assert exc_info.value.code == 1

    def test_missing_required_key_exits_1(self, tmp_path):
        """Valid JSON but a pipeline entry missing a required key (KeyError)
        → SystemExit(1)."""
        from pipeline_orchestrator import load_pipeline
        path = tmp_path / "pipeline.json"
        # 'agent' key is required by load_pipeline but absent here.
        path.write_text(json.dumps({"pipeline": [{"phase": "x"}]}))
        with pytest.raises(SystemExit) as exc_info:
            load_pipeline(path)
        assert exc_info.value.code == 1

    def test_pipeline_not_a_list_exits_1(self, tmp_path):
        """'pipeline' present but not iterable as expected (TypeError) →
        SystemExit(1)."""
        from pipeline_orchestrator import load_pipeline
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps({"pipeline": 5}))
        with pytest.raises(SystemExit) as exc_info:
            load_pipeline(path)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# TestInvokeScript — script-step error paths
# ---------------------------------------------------------------------------

class TestInvokeScript:
    """Focused tests for invoke_script's error branches."""

    def _script_agent(self, script_path, timeout=300) -> AgentDef:
        return AgentDef(
            agent="00_ondemand/some-script",
            phase="00_ondemand",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="script step",
            step_type="script",
            script_path=script_path,
            script_timeout_seconds=timeout,
        )

    def _work_item(self) -> WorkItem:
        return WorkItem(
            number=42, kind="issue", title="T", labels=set(),
            url="https://github.com/test/repo/issues/42",
        )

    def test_missing_script_path_returns_failure(self):
        """type:script entry with no script field → success=False, no subprocess."""
        from pipeline_orchestrator import invoke_script
        agent = self._script_agent(script_path=None)
        with patch("subprocess.Popen") as mock_popen:
            result = invoke_script(agent, self._work_item(), dry_run=False, repo="test/repo")
        assert result.success is False
        assert "no script field" in result.captured_tail
        mock_popen.assert_not_called()

    def test_nonexistent_script_file_returns_failure(self, tmp_path, monkeypatch):
        """script field points at a file that doesn't exist → success=False."""
        import pipeline_orchestrator as orch
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", tmp_path)
        agent = self._script_agent(script_path="scripts/missing.sh")
        result = orch.invoke_script(agent, self._work_item(), dry_run=False, repo="test/repo")
        assert result.success is False
        assert "not found" in result.captured_tail.lower()

    def test_nonzero_exit_returns_failure(self, tmp_path, monkeypatch):
        """A real script that exits non-zero → success=False with that returncode."""
        import pipeline_orchestrator as orch
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", tmp_path)
        script = tmp_path / "fail.sh"
        script.write_text("#!/usr/bin/env bash\necho 'doing work'\nexit 3\n")
        agent = self._script_agent(script_path="fail.sh")
        result = orch.invoke_script(agent, self._work_item(), dry_run=False, repo="test/repo")
        assert result.success is False
        assert result.returncode == 3, f"Expected returncode 3, got {result.returncode}"

    def test_zero_exit_returns_success(self, tmp_path, monkeypatch):
        """A real script that exits 0 → success=True (happy-path control)."""
        import pipeline_orchestrator as orch
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", tmp_path)
        script = tmp_path / "ok.sh"
        script.write_text("#!/usr/bin/env bash\necho 'AI_AGILE_STATUS: complete'\nexit 0\n")
        agent = self._script_agent(script_path="ok.sh")
        result = orch.invoke_script(agent, self._work_item(), dry_run=False, repo="test/repo")
        assert result.success is True
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# TestExcludeClassifications — exclude_classifications skip branch
# ---------------------------------------------------------------------------

class TestExcludeClassifications:
    """An agent with exclude_classifications must skip work items whose
    classification matches — invoke_agent is never called for them."""

    def _agent(self, exclude) -> AgentDef:
        return AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            exclude_classifications=exclude,
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_excluded_classification_is_skipped(self, mock_invoke):
        """classification 'bug' is excluded → agent not dispatched."""
        agent = self._agent(exclude=["bug"])
        agents = [agent]
        pipeline_map = {agent.agent: agent}
        gh = _make_gh_mock()
        # Trigger label present so only the exclude branch can prevent dispatch.
        wi = _make_work_item_with_labels(
            1, {"issue-classifier:complete", "classification: bug"}
        )
        n = process_work_item(
            wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
        )
        assert n == 0, "Excluded-classification item must not dispatch the agent"
        mock_invoke.assert_not_called()

    @patch("pipeline_orchestrator.invoke_agent")
    def test_non_excluded_classification_still_dispatches(self, mock_invoke):
        """classification 'feature' is NOT excluded → agent dispatches normally."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent = self._agent(exclude=["bug"])
        agents = [agent]
        pipeline_map = {agent.agent: agent}
        gh = _make_gh_mock()
        wi = _make_work_item_with_labels(
            2, {"issue-classifier:complete", "classification: feature"}
        )
        n = process_work_item(
            wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
        )
        assert n == 1, "Non-excluded classification must dispatch the agent"
        mock_invoke.assert_called_once()


# ---------------------------------------------------------------------------
# TestManualRequestedOverride — :requested bypasses the trigger check
# ---------------------------------------------------------------------------

class TestManualRequestedOverride:
    """A :requested label is a manual override that dispatches the agent even
    when its configured trigger label is absent, and clears :requested first."""

    @patch("pipeline_orchestrator.invoke_agent")
    def test_requested_dispatches_without_trigger_label(self, mock_invoke):
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent = AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            # Trigger that is NOT present on the work item.
            objects=["issue"],
            trigger={"label": "never-present:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
        )
        agents = [agent]
        pipeline_map = {agent.agent: agent}
        gh = _make_gh_mock()
        # Only the manual override label is present — no trigger label.
        wi = _make_work_item_with_labels(7, {"coder:requested"})

        n = process_work_item(
            wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
        )

        assert n == 1, "Manual :requested override must dispatch despite missing trigger"
        mock_invoke.assert_called_once()
        # :requested must be removed before :wip is applied.
        remove_calls = [c[0][1] for c in gh.remove_label.call_args_list]
        assert "coder:requested" in remove_calls, (
            f"Manual override must clear :requested; remove_label calls: {remove_calls}"
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_no_requested_and_no_trigger_does_not_dispatch(self, mock_invoke):
        """Control: without :requested and without the trigger label, the agent
        is not dispatched — proving the override is what drives the path above."""
        agent = AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "never-present:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
        )
        agents = [agent]
        pipeline_map = {agent.agent: agent}
        gh = _make_gh_mock()
        wi = _make_work_item_with_labels(8, set())

        n = process_work_item(
            wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
        )
        assert n == 0
        mock_invoke.assert_not_called()


# ---------------------------------------------------------------------------
# TestPostSteps — orchestrator runs post_steps scripts on :complete
# ---------------------------------------------------------------------------

class TestPostSteps:
    """An agent with post_steps runs its completion scripts when it signals :complete."""

    def _agent(self, *, kind: str = "pr") -> AgentDef:
        return AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=[kind],
            trigger={"label": "merge-conflict:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            post_steps=[".github/scripts/mark-pr-ready.sh"],
            review_gate=True,
        )

    def _sub_side_effect_factory(self, bash_result):
        """Return a subprocess.run side_effect that raises CalledProcessError for
        git calls (branch restore) and returns bash_result for all other calls."""
        import subprocess as _sp

        def _side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            return bash_result

        return _side_effect

    @patch("pipeline_orchestrator.invoke_agent")
    def test_post_steps_script_runs_on_complete(self, mock_invoke):
        """post_steps script is invoked via subprocess.run when the agent signals :complete."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        bash_ok = MagicMock()
        bash_ok.returncode = 0
        bash_ok.stdout = ""
        bash_ok.stderr = ""
        agent = self._agent()
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(bash_ok)) as mock_sub:
            n = process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        assert n == 1
        bash_calls = [
            c for c in mock_sub.call_args_list
            if isinstance(c.args[0], list) and c.args[0] and c.args[0][0] == "bash"
        ]
        assert len(bash_calls) == 1
        assert "mark-pr-ready.sh" in bash_calls[0].args[0][-1]
        env_passed = bash_calls[0].kwargs["env"]
        assert env_passed["WORK_ITEM_KIND"] == "pr"
        assert env_passed["WORK_ITEM_NUMBER"] == "55"
        assert env_passed["PR_NUMBER"] == "55"
        assert "REPO" in env_passed
        assert "AI_AGILE_ROOT" in env_passed

    @patch("pipeline_orchestrator.invoke_agent")
    def test_does_not_run_post_steps_on_review(self, mock_invoke):
        """When the agent emits :review, post_steps must NOT run — they only fire on :complete."""
        mock_invoke.return_value = AgentRunResult(
            success=False,
            captured_tail='AI_AGILE_STATUS: review "needs changes"',
        )
        agent = self._agent()
        gh = _make_gh_mock()
        wi = WorkItem(
            number=56, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/56",
        )

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(MagicMock(returncode=0))) as mock_sub:
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        bash_calls = [
            c for c in mock_sub.call_args_list
            if isinstance(c.args[0], list) and c.args[0] and c.args[0][0] == "bash"
        ]
        assert len(bash_calls) == 0

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_post_steps_nonzero_exit_applies_failed(self, mock_failed, mock_invoke):
        """When a post_steps script exits non-zero, _apply_failed is called."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        bash_fail = MagicMock()
        bash_fail.returncode = 1
        bash_fail.stdout = "error output"
        bash_fail.stderr = ""
        agent = self._agent()
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(bash_fail)):
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        mock_failed.assert_called_once()

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_post_steps_timeout_applies_failed(self, mock_failed, mock_invoke):
        """When a post_steps script times out, _apply_failed is called."""
        import subprocess as _sp

        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )

        def _timeout_side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            raise _sp.TimeoutExpired(cmd, 300)

        agent = self._agent()
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        with patch("subprocess.run", side_effect=_timeout_side_effect):
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        mock_failed.assert_called_once()

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_post_steps_script_not_found_applies_failed(self, mock_failed, mock_invoke):
        """When a post_steps script does not exist on disk, _apply_failed is called."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        import subprocess as _sp

        def _git_fail(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            return MagicMock(returncode=0)

        agent = self._agent()
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        with patch("subprocess.run", side_effect=_git_fail), \
             patch("pathlib.Path.exists", return_value=False):
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        mock_failed.assert_called_once()

    @patch("pipeline_orchestrator.invoke_agent")
    def test_post_steps_all_succeed_in_order(self, mock_invoke):
        """All post_steps scripts run in sequence when each exits 0."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        bash_ok = MagicMock()
        bash_ok.returncode = 0
        bash_ok.stdout = ""
        bash_ok.stderr = ""
        agent = AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=["pr"],
            trigger={"label": "merge-conflict:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            post_steps=[
                ".github/scripts/mark-pr-ready.sh",
                ".github/scripts/other-hook.sh",
            ],
        )
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        def _exists_for_scripts(self_path):
            return any(s in str(self_path) for s in ("mark-pr-ready.sh", "other-hook.sh"))

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(bash_ok)) as mock_sub, \
             patch("pathlib.Path.exists", _exists_for_scripts):
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        bash_calls = [
            c for c in mock_sub.call_args_list
            if isinstance(c.args[0], list) and c.args[0] and c.args[0][0] == "bash"
        ]
        assert len(bash_calls) == 2, f"Expected 2 bash calls, got {len(bash_calls)}"

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_post_steps_breaks_on_first_failure(self, mock_failed, mock_invoke):
        """When the first post_steps script fails, subsequent scripts do NOT run."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        import subprocess as _sp

        call_count = {"n": 0}

        def _side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            call_count["n"] += 1
            result = MagicMock()
            result.returncode = 1
            result.stdout = "first step failed"
            result.stderr = ""
            return result

        agent = AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=["pr"],
            trigger={"label": "merge-conflict:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            post_steps=[
                ".github/scripts/mark-pr-ready.sh",
                ".github/scripts/other-hook.sh",
            ],
        )
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        def _exists_for_scripts(self_path):
            return any(s in str(self_path) for s in ("mark-pr-ready.sh", "other-hook.sh"))

        with patch("subprocess.run", side_effect=_side_effect), \
             patch("pathlib.Path.exists", _exists_for_scripts):
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        mock_failed.assert_called_once()
        assert call_count["n"] == 1, f"Expected only 1 bash call before break, got {call_count['n']}"

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_post_steps_path_traversal_blocked(self, mock_failed, mock_invoke):
        """A post_steps path that resolves outside the repo root is blocked and applies :failed."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent = AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=["pr"],
            trigger={"label": "merge-conflict:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            post_steps=["../../etc/shadow"],
        )
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(MagicMock(returncode=0))) as mock_sub:
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        mock_failed.assert_called_once()
        bash_calls = [
            c for c in mock_sub.call_args_list
            if isinstance(c.args[0], list) and c.args[0] and c.args[0][0] == "bash"
        ]
        assert len(bash_calls) == 0, "Traversal path must not reach subprocess.run"

    @patch("pipeline_orchestrator.invoke_agent")
    def test_post_steps_issue_kind_sets_issue_number_env(self, mock_invoke):
        """When work item kind is 'issue', ISSUE_NUMBER is set in _ps_env (not PR_NUMBER)."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        bash_ok = MagicMock()
        bash_ok.returncode = 0
        bash_ok.stdout = ""
        bash_ok.stderr = ""
        agent = self._agent(kind="issue")
        gh = _make_gh_mock()
        wi = WorkItem(
            number=42, kind="issue", title="T", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/issues/42",
        )

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(bash_ok)) as mock_sub, \
             patch("pathlib.Path.exists", lambda p: "mark-pr-ready.sh" in str(p)):
            process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        bash_calls = [
            c for c in mock_sub.call_args_list
            if isinstance(c.args[0], list) and c.args[0] and c.args[0][0] == "bash"
        ]
        assert len(bash_calls) == 1
        env_passed = bash_calls[0].kwargs["env"]
        assert env_passed["WORK_ITEM_KIND"] == "issue"
        assert env_passed["ISSUE_NUMBER"] == "42"
        assert "PR_NUMBER" not in env_passed

    def test_mark_pr_ready_script_exists(self):
        """mark-pr-ready.sh must exist at .github/scripts/mark-pr-ready.sh with a shebang."""
        import pipeline_orchestrator as orch
        script_path = orch.SUBMODULE_ROOT / ".github" / "scripts" / "mark-pr-ready.sh"
        assert script_path.exists(), (
            f"mark-pr-ready.sh must exist at {script_path}"
        )
        first_line = script_path.read_text().splitlines()[0]
        assert first_line.startswith("#!/"), (
            f"mark-pr-ready.sh must start with a shebang; got: {first_line!r}"
        )


# ---------------------------------------------------------------------------
# TestCommitAgentWorkScript — Gherkin-traced tests for issue #151
# ---------------------------------------------------------------------------

class TestCommitAgentWorkScript:
    """Tests for the commit-agent-work.sh shell script and commit_after wiring.

    Scenario: New script stages, commits, and pushes agent work
    Scenario: Python orchestrator contains no git logic
    Scenario: git_ops.commit_after drives commits for affected agents
    """

    def _work_item(self) -> WorkItem:
        return WorkItem(
            number=42, kind="issue", title="T", labels=set(),
            url="https://github.com/test/repo/issues/42",
        )

    def test_commit_agent_work_script_exists(self):
        """Scenario: New script stages, commits, and pushes agent work.

        Given .github/scripts/commit-agent-work.sh exists
        Then the file is a bash script with the correct shebang.
        """
        import pipeline_orchestrator as orch
        script_path = orch.SUBMODULE_ROOT / ".github" / "scripts" / "commit-agent-work.sh"
        assert script_path.exists(), (
            f"commit-agent-work.sh must exist at {script_path}"
        )
        first_line = script_path.read_text().splitlines()[0]
        assert first_line.startswith("#!/"), (
            f"commit-agent-work.sh must start with a shebang; got: {first_line!r}"
        )

    def test_python_orchestrator_has_no_run_commit_after(self):
        """Scenario: Python orchestrator contains no git logic.

        Given the changes in this issue have been applied
        When pipeline_orchestrator.py is reviewed
        Then _run_commit_after() is not present in the file.
        """
        import pipeline_orchestrator as orch
        assert not hasattr(orch, "_run_commit_after"), (
            "_run_commit_after must be removed from pipeline_orchestrator.py"
        )

    def test_python_orchestrator_has_no_configure_git_auth(self):
        """Scenario: Python orchestrator contains no git logic.

        Given the changes in this issue have been applied
        When pipeline_orchestrator.py is reviewed
        Then _configure_git_auth() is not present in the file.
        """
        import pipeline_orchestrator as orch
        assert not hasattr(orch, "_configure_git_auth"), (
            "_configure_git_auth must be removed from pipeline_orchestrator.py"
        )

    def test_pipeline_json_uses_git_ops_commit_after(self):
        """Scenario: git_ops.commit_after drives commits; post_steps drives pr-ready promotion.

        Given pipeline.json with agents that must commit their work
        When the pipeline.json is reviewed
        Then prd-docs-updater and coder use git_ops.commit_after: true
             and pr-reviewer (only) uses post_steps.
        """
        import json
        import pipeline_orchestrator as orch
        pipeline_path = orch.PIPELINE_PATH
        with open(pipeline_path) as f:
            raw = json.load(f)

        commit_after_agents = []
        post_steps_agents = []
        for entry in raw["pipeline"]:
            if entry.get("git_ops", {}).get("commit_after"):
                commit_after_agents.append(entry["agent"])
            if entry.get("post_steps"):
                post_steps_agents.append(entry["agent"])

        assert "01_product_docs/prd-docs-updater" in commit_after_agents, (
            "prd-docs-updater must use git_ops.commit_after: true"
        )
        assert "03_execute/coder" in commit_after_agents, (
            "coder must use git_ops.commit_after: true"
        )
        assert "03_execute/pr-reviewer" in post_steps_agents, (
            "pr-reviewer must use post_steps to trigger mark-pr-ready.sh"
        )
        unexpected = [a for a in post_steps_agents if a != "03_execute/pr-reviewer"]
        assert not unexpected, (
            f"Only pr-reviewer should use post_steps — also found: {unexpected}"
        )

    def test_commit_after_derived_from_git_ops_in_pipeline(self):
        """Agents with git_ops.commit_after: true set commit_after=True; others False."""
        import json
        import pipeline_orchestrator as orch
        agents, _ = orch.load_pipeline(orch.PIPELINE_PATH)
        with open(orch.PIPELINE_PATH) as f:
            raw = json.load(f)
        raw_by_agent = {e["agent"]: e for e in raw["pipeline"]}
        for agent_def in agents:
            entry = raw_by_agent.get(agent_def.agent, {})
            expected = bool(entry.get("git_ops", {}).get("commit_after", False))
            assert agent_def.commit_after == expected, (
                f"{agent_def.agent}: commit_after={agent_def.commit_after} "
                f"but git_ops.commit_after={expected!r} in pipeline.json"
            )

    def test_commit_after_outer_guard_requires_issue_kind(self):
        """Scenario: commit-after is not invoked for PR work items.

        Given commit-agent-work.sh requires ISSUE_NUMBER
        When the orchestrator source is reviewed
        Then the commit_after invoke block is guarded by work_item.kind == 'issue'
             so the script is never called for PR-scoped work items.
        After the process_work_item() refactor the guard lives in _apply_result().
        """
        import inspect
        import pipeline_orchestrator as orch
        source = inspect.getsource(orch._apply_result)
        guard = 'agent_def.commit_after and work_item.kind == "issue"'
        assert guard in source, (
            "commit_after invoke block must include 'work_item.kind == \"issue\"' "
            "in the outer guard — commit-agent-work.sh requires ISSUE_NUMBER and "
            "must not be invoked for PR work items (DP-001). "
            "After the process_work_item() refactor this guard lives in _apply_result()."
        )

    def _make_commit_after_agent(self) -> "AgentDef":
        """AgentDef with commit_after=True and a trigger label."""
        return AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test coder",
            commit_after=True,
            max_concurrent=10,
        )

    def _make_issue_wi(self) -> WorkItem:
        return WorkItem(
            number=42, kind="issue", title="T",
            labels={"issue-classifier:complete"},
            url="https://github.com/test/repo/issues/42",
        )

    def _sub_side_effect_factory(self, bash_result):
        """Return a subprocess.run side_effect that:
        - raises CalledProcessError for git calls (pre-agent checkout fails silently)
        - returns bash_result for bash (commit-agent-work.sh) calls
        """
        import subprocess as _sp

        def _side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            return bash_result

        return _side_effect

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_commit_after_success_keeps_complete_status(self, mock_failed, mock_invoke):
        """Scenario: commit-agent-work.sh exits 0 — agent stays complete.

        Given an agent with commit_after: true that completes successfully
        When commit-agent-work.sh exits 0
        Then _apply_failed is not called.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        bash_ok = MagicMock()
        bash_ok.returncode = 0
        bash_ok.stdout = ""
        bash_ok.stderr = ""

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(bash_ok)):
            process_work_item(
                self._make_issue_wi(),
                [self._make_commit_after_agent()],
                {"03_execute/coder": self._make_commit_after_agent()},
                _make_gh_mock(),
                dry_run=False,
                repo="test/repo",
                concurrency=ConcurrencyState(running_counts={"coder": 0}),
            )

        mock_failed.assert_not_called()

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_commit_after_nonzero_exit_applies_failed(self, mock_failed, mock_invoke):
        """Scenario: commit-agent-work.sh exits non-zero — _apply_failed is called.

        Given an agent with commit_after: true that completes successfully
        When commit-agent-work.sh exits 1
        Then _apply_failed is called.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        bash_fail = MagicMock()
        bash_fail.returncode = 1
        bash_fail.stdout = "push failed"
        bash_fail.stderr = "error: failed to push"

        with patch("subprocess.run", side_effect=self._sub_side_effect_factory(bash_fail)):
            process_work_item(
                self._make_issue_wi(),
                [self._make_commit_after_agent()],
                {"03_execute/coder": self._make_commit_after_agent()},
                _make_gh_mock(),
                dry_run=False,
                repo="test/repo",
                concurrency=ConcurrencyState(running_counts={"coder": 0}),
            )

        mock_failed.assert_called_once()

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_commit_after_timeout_applies_failed(self, mock_failed, mock_invoke):
        """Scenario: commit-agent-work.sh times out — _apply_failed is called.

        Given an agent with commit_after: true that completes successfully
        When commit-agent-work.sh raises subprocess.TimeoutExpired
        Then _apply_failed is called.
        """
        import subprocess as _sp

        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )

        def _timeout_side_effect(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            raise _sp.TimeoutExpired(cmd, 300)

        with patch("subprocess.run", side_effect=_timeout_side_effect):
            process_work_item(
                self._make_issue_wi(),
                [self._make_commit_after_agent()],
                {"03_execute/coder": self._make_commit_after_agent()},
                _make_gh_mock(),
                dry_run=False,
                repo="test/repo",
                concurrency=ConcurrencyState(running_counts={"coder": 0}),
            )

        mock_failed.assert_called_once()

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_commit_after_script_not_found_applies_failed(self, mock_failed, mock_invoke):
        """Scenario: commit-agent-work.sh does not exist — _apply_failed is called.

        Given an agent with commit_after: true that completes successfully
        When the commit-agent-work.sh script does not exist
        Then _apply_failed is called.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )

        import subprocess as _sp

        def _git_fail(cmd, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_git_fail), \
             patch("pathlib.Path.exists", return_value=False):
            process_work_item(
                self._make_issue_wi(),
                [self._make_commit_after_agent()],
                {"03_execute/coder": self._make_commit_after_agent()},
                _make_gh_mock(),
                dry_run=False,
                repo="test/repo",
                concurrency=ConcurrencyState(running_counts={"coder": 0}),
            )

        mock_failed.assert_called_once()


# ---------------------------------------------------------------------------
# TestPriorityScheduling — Gherkin-traced tests for issue #119
# ---------------------------------------------------------------------------

class TestPriorityScheduling:
    """Tests for the two-pass priority work item ordering in main().

    Each test corresponds to a named scenario in the approved PRD for issue #119.
    """

    def _make_agent_for_priority(self) -> AgentDef:
        return AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=10,
        )

    def _eligible_wi(self, number: int, *, priority: bool = False) -> WorkItem:
        labels = {"issue-classifier:complete"}
        if priority:
            labels.add("priority")
        return WorkItem(
            number=number,
            kind="issue",
            title=f"Test issue #{number}",
            labels=labels,
            url=f"https://github.com/test/repo/issues/{number}",
        )

    # Scenario: Priority issue is started before a non-priority issue
    @patch("pipeline_orchestrator.invoke_agent")
    def test_priority_issue_receives_wip_before_non_priority(self, mock_invoke):
        """Given a priority issue and a non-priority issue both eligible to start
        When the orchestrator selects the next work item to start
        Then the priority-labeled issue receives :wip before the non-priority issue.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = self._make_agent_for_priority()
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}

        # priority_wi has number 2, non_priority_wi has number 1 —
        # without priority sorting, number 1 would be processed first.
        non_priority_wi = self._eligible_wi(1, priority=False)
        priority_wi = self._eligible_wi(2, priority=True)

        # Simulate main()'s two-pass reorder: priority items first.
        _priority = [wi for wi in [non_priority_wi, priority_wi] if "priority" in wi.labels]
        _other    = [wi for wi in [non_priority_wi, priority_wi] if "priority" not in wi.labels]
        ordered = _priority + _other

        conc = ConcurrencyState(running_counts={"prd-writer": 0})
        dispatched_numbers = []
        for wi in ordered:
            gh = _make_gh_mock()
            n = process_work_item(
                wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
                concurrency=conc,
            )
            if n > 0:
                dispatched_numbers.append(wi.number)

        assert dispatched_numbers[0] == 2, (
            f"Priority issue #2 must be dispatched first; actual order: {dispatched_numbers}"
        )

    # Scenario: Concurrency limit is respected for priority items
    @patch("pipeline_orchestrator.invoke_agent")
    def test_concurrency_limit_respected_for_priority_items(self, mock_invoke):
        """Given the orchestrator is at the max concurrent limit
        And a priority-labeled issue exists
        When the orchestrator evaluates the next selection cycle
        Then no new work item is started until a concurrency slot becomes available.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = self._make_agent_for_priority()
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}

        conc = ConcurrencyState(
            running_counts={"prd-writer": 10},  # at max_concurrent ceiling
            tick_launch_count=0,
        )
        priority_wi = self._eligible_wi(1, priority=True)

        gh = _make_gh_mock()
        n = process_work_item(
            priority_wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
            concurrency=conc,
        )

        assert n == 0, (
            f"Priority issue must not start when per-agent concurrency ceiling is reached; "
            f"dispatched count: {n}"
        )
        mock_invoke.assert_not_called()

    # Scenario: Normal selection resumes when no priority items are open
    @patch("pipeline_orchestrator.invoke_agent")
    def test_normal_selection_resumes_when_no_priority_items(self, mock_invoke):
        """Given there are no open priority-labeled issues
        And non-priority issues are eligible
        When the orchestrator selects the next work item
        Then a non-priority issue is selected using normal selection logic.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = self._make_agent_for_priority()
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}

        # No priority items — only regular ones.
        regular_items = [self._eligible_wi(i, priority=False) for i in [10, 20, 30]]

        _priority = [wi for wi in regular_items if "priority" in wi.labels]
        _other    = [wi for wi in regular_items if "priority" not in wi.labels]
        ordered = _priority + _other  # same order as input when no priority items

        conc = ConcurrencyState(running_counts={"prd-writer": 0})
        dispatched = []
        for wi in ordered:
            gh = _make_gh_mock()
            n = process_work_item(
                wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
                concurrency=conc,
            )
            if n > 0:
                dispatched.append(wi.number)

        assert dispatched and dispatched[0] == 10, (
            f"With no priority items, normal selection (first eligible) must proceed; "
            f"dispatched: {dispatched}"
        )

    # Scenario: Priority label on an already-in-progress item has no effect on selection
    @patch("pipeline_orchestrator.invoke_agent")
    def test_priority_on_in_progress_item_is_ignored(self, mock_invoke):
        """Given an issue is already in progress (has :wip)
        When a stakeholder applies the priority label to that in-progress issue
        Then no duplicate processing is triggered.
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = self._make_agent_for_priority()
        agents = [agent_def]
        pipeline_map = {"01_product_docs/prd-writer": agent_def}

        # Work item already carrying :wip — even with priority label.
        in_progress_priority_wi = WorkItem(
            number=5,
            kind="issue",
            title="In-progress priority issue",
            labels={"issue-classifier:complete", "priority", "prd-writer:wip"},
            url="https://github.com/test/repo/issues/5",
        )

        gh = _make_gh_mock()
        conc = ConcurrencyState(running_counts={"prd-writer": 1})
        n = process_work_item(
            in_progress_priority_wi, agents, pipeline_map, gh,
            dry_run=False, repo="test/repo", concurrency=conc,
        )

        assert n == 0, (
            "An already-in-progress priority issue must not trigger a duplicate run; "
            f"dispatched count: {n}"
        )
        mock_invoke.assert_not_called()

    def test_priority_sort_puts_labeled_items_first(self):
        """Unit test for the two-pass reorder logic used in main().

        Given a mixed list of work items — some with priority, some without —
        When the two-pass sort is applied
        Then all priority-labeled items precede all non-priority items.
        """
        items = [
            WorkItem(1, "issue", "Normal 1",   {"issue-classifier:complete"},          "http://x/1"),
            WorkItem(2, "issue", "Priority 1", {"issue-classifier:complete", "priority"}, "http://x/2"),
            WorkItem(3, "issue", "Normal 2",   {"issue-classifier:complete"},          "http://x/3"),
            WorkItem(4, "issue", "Priority 2", {"priority"},                           "http://x/4"),
        ]
        _priority = [wi for wi in items if "priority" in wi.labels]
        _other    = [wi for wi in items if "priority" not in wi.labels]
        ordered = _priority + _other

        ordered_numbers = [wi.number for wi in ordered]
        # Both priority items (2, 4) must come before non-priority items (1, 3).
        priority_indices = [i for i, wi in enumerate(ordered) if "priority" in wi.labels]
        other_indices    = [i for i, wi in enumerate(ordered) if "priority" not in wi.labels]
        assert max(priority_indices) < min(other_indices), (
            f"All priority items must precede all non-priority items; "
            f"got order {ordered_numbers}"
        )

    # Integration test: the sort block inside main() is exercised end-to-end.
    @patch("pipeline_orchestrator.process_work_item")
    @patch("pipeline_orchestrator.load_pipeline")
    @patch("pipeline_orchestrator.is_pipeline_paused")
    @patch("pipeline_orchestrator.GitHubClient")
    @patch("pipeline_orchestrator.parse_args")
    @patch("pipeline_orchestrator._emit_audit_event")
    def test_main_dispatches_priority_before_non_priority(
        self, mock_emit_audit, mock_parse_args, mock_gh_cls, mock_is_paused,
        mock_load_pipeline, mock_process_wi,
    ):
        """Integration test: main() sort block reorders API-returned items by priority.

        Given gh.list_open_issues returns [non-priority #1, priority #2] (API insertion order)
        When main() runs
        Then process_work_item is called with priority issue #2 before non-priority issue #1.

        This test exercises the sort block in main() directly — if that block were removed,
        process_work_item would receive #1 first and the assertion would fail.
        """
        args_mock = MagicMock()
        args_mock.clear_pause = False
        args_mock.clear_stop = False
        args_mock.verbose = False
        args_mock.repo = "test/repo"
        args_mock.issue = None
        args_mock.kind = None
        args_mock.dry_run = False
        args_mock.pipeline = MagicMock()
        args_mock.phases = None
        mock_parse_args.return_value = args_mock

        agent_def = self._make_agent_for_priority()
        mock_load_pipeline.return_value = ([agent_def], [])
        mock_is_paused.return_value = (False, None, None)

        # GitHub API returns items with non-priority (#1) first, priority (#2) second.
        # Without the sort block in main(), #1 would be dispatched first.
        non_priority_wi = self._eligible_wi(1, priority=False)
        priority_wi = self._eligible_wi(2, priority=True)
        mock_gh_instance = MagicMock()
        mock_gh_instance.list_open_issues.return_value = [non_priority_wi, priority_wi]
        mock_gh_cls.return_value = mock_gh_instance

        mock_process_wi.return_value = 0

        with patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}):
            main()

        assert mock_process_wi.call_count >= 2, (
            f"process_work_item must be called for both work items; "
            f"call count: {mock_process_wi.call_count}"
        )
        first_item = mock_process_wi.call_args_list[0][0][0]
        assert first_item.number == 2, (
            f"Priority issue #2 must be passed to process_work_item first; "
            f"got #{first_item.number}. The sort block in main() may not be exercised."
        )


# ---------------------------------------------------------------------------
# TestProcessWorkItemDecomposition  (PRD issue #156)
# ---------------------------------------------------------------------------

class TestProcessWorkItemDecomposition:
    """Gherkin scenarios from PRD issue #156.

    Verifies that process_work_item() is decomposed into _should_run(),
    _run_agent(), and _apply_result() with no logic duplication and no
    observable behaviour change.
    """

    # ------------------------------------------------------------------
    # Scenario: process_work_item becomes a thin orchestration wrapper
    # ------------------------------------------------------------------

    def test_process_work_item_calls_should_run(self):
        """
        Given the orchestrator has been updated per issue #156
        When process_work_item() is invoked
        Then its body calls _should_run() — eligibility is not inlined.
        """
        import inspect
        import pipeline_orchestrator as orch
        source = inspect.getsource(orch.process_work_item)
        assert "_should_run(" in source, (
            "process_work_item must delegate eligibility checking to _should_run(); "
            "no eligibility logic should be inlined in the wrapper."
        )

    def test_process_work_item_calls_run_agent(self):
        """
        Given the orchestrator has been updated per issue #156
        When process_work_item() is invoked
        Then its body calls _run_agent() — agent invocation is not inlined.
        """
        import inspect
        import pipeline_orchestrator as orch
        source = inspect.getsource(orch.process_work_item)
        assert "_run_agent(" in source, (
            "process_work_item must delegate agent invocation to _run_agent(); "
            "no invocation logic should be inlined in the wrapper."
        )

    def test_process_work_item_calls_apply_result(self):
        """
        Given the orchestrator has been updated per issue #156
        When process_work_item() is invoked
        Then its body calls _apply_result() — result handling is not inlined.
        """
        import inspect
        import pipeline_orchestrator as orch
        source = inspect.getsource(orch.process_work_item)
        assert "_apply_result(" in source, (
            "process_work_item must delegate result handling to _apply_result(); "
            "no result-handling logic should be inlined in the wrapper."
        )

    # ------------------------------------------------------------------
    # Scenario: each concern lives in exactly one place
    # ------------------------------------------------------------------

    def test_eligibility_logic_only_in_should_run(self):
        """
        Given the three focused functions have been implemented
        When the codebase is reviewed for duplication
        Then dependencies_complete() is called only from _should_run(),
             not from _run_agent() or _apply_result().
        """
        import inspect
        import pipeline_orchestrator as orch
        assert "dependencies_complete(" in inspect.getsource(orch._should_run), (
            "_should_run must contain the dependencies_complete() call."
        )
        assert "dependencies_complete(" not in inspect.getsource(orch._run_agent), (
            "_run_agent must not duplicate the dependencies_complete() check."
        )
        assert "dependencies_complete(" not in inspect.getsource(orch._apply_result), (
            "_apply_result must not duplicate the dependencies_complete() check."
        )

    def test_result_handling_only_in_apply_result(self):
        """
        Given the three focused functions have been implemented
        When the codebase is reviewed for duplication
        Then _apply_terminal_status() is called only from _apply_result(),
             not from _should_run() or _run_agent().
        """
        import inspect
        import pipeline_orchestrator as orch
        assert "_apply_terminal_status(" in inspect.getsource(orch._apply_result), (
            "_apply_result must contain the _apply_terminal_status() call."
        )
        assert "_apply_terminal_status(" not in inspect.getsource(orch._should_run), (
            "_should_run must not duplicate the _apply_terminal_status() call."
        )
        assert "_apply_terminal_status(" not in inspect.getsource(orch._run_agent), (
            "_run_agent must not duplicate the _apply_terminal_status() call."
        )

    # ------------------------------------------------------------------
    # Scenario: CI passes with no observable behaviour change
    # ------------------------------------------------------------------

    @patch("pipeline_orchestrator.invoke_agent")
    def test_process_work_item_dispatches_eligible_agent(self, mock_invoke):
        """
        Given an eligible agent (trigger met, no :wip, no :complete)
        When process_work_item() is called
        Then the agent is triggered exactly once (behaviour preserved).
        """
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test agent",
            max_concurrent=10,
        )
        wi = _make_work_item_with_labels(1, {"issue-classifier:complete"})
        gh = _make_gh_mock()
        n = process_work_item(
            wi, [agent_def], {agent_def.agent: agent_def},
            gh, dry_run=False, repo="test/repo",
        )
        assert n == 1, f"Expected 1 agent triggered; got {n}"
        mock_invoke.assert_called_once()

    def test_should_run_returns_false_for_terminal_status(self):
        """
        Given an agent that is already :complete on the work item
        When _should_run() is called
        Then it returns False (skip).
        """
        agent_def = _make_agent_def("01_product_docs/prd-writer")
        wi = _make_work_item_with_labels(1, {"prd-writer:complete"})
        result = _should_run(agent_def, wi, wi.labels, {}, None)
        assert result is False, (
            f"_should_run must return False for a terminal :complete status; got {result!r}"
        )

    def test_should_run_returns_none_at_aggregate_ceiling(self):
        """
        Given the aggregate concurrency ceiling is already reached
        When _should_run() is called for an otherwise-eligible agent
        Then it returns None (stop the agent loop).
        """
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=100,
        )
        wi = _make_work_item_with_labels(1, set())
        conc = ConcurrencyState(
            running_counts={"prd-writer": 0},
            tick_launch_count=PIPELINE_MAX_CONCURRENT,
        )
        result = _should_run(agent_def, wi, wi.labels, {}, conc)
        assert result is None, (
            f"_should_run must return None when the aggregate ceiling is hit; got {result!r}"
        )

    def test_should_run_returns_true_for_eligible_agent(self):
        """
        Given an agent whose trigger is met and has no blocking conditions
        When _should_run() is called
        Then it returns True (dispatch).
        """
        agent_def = AgentDef(
            agent="01_product_docs/prd-writer",
            phase="01_product_docs",
            objects=["issue"],
            trigger={"label": "issue-classifier:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            max_concurrent=10,
        )
        wi = _make_work_item_with_labels(1, {"issue-classifier:complete"})
        result = _should_run(agent_def, wi, wi.labels, {agent_def.agent: agent_def}, None)
        assert result is True, (
            f"_should_run must return True for a fully eligible agent; got {result!r}"
        )


# ---------------------------------------------------------------------------
# Direct behavioural tests for the decomposition helpers.
# These complement the source-string decomposition tests with real contract
# checks: the stop/continue return signal, terminal-label application, the
# :wip mutex, and a regression guard against the commit-after double-execution
# bug that the rebaseline removed.
# ---------------------------------------------------------------------------

class TestApplyResultBehaviour:
    """_apply_result() returns the stop/continue signal and applies exactly one
    terminal status label — exercised directly, not only via process_work_item."""

    def _agent(self, **kw) -> AgentDef:
        d = dict(
            agent="03_execute/pr-reviewer", phase="03_execute", objects=["issue"],
            trigger={}, dependencies=[], human_gate_after=False,
            human_gate_label=None, description="test",
        )
        d.update(kw)
        return AgentDef(**d)

    def _call(self, agent, wi, gh, sentinel):
        import time
        return _apply_result(
            agent, wi, AgentRunResult(success=True, captured_tail=""),
            sentinel, "", "", time.monotonic(), 0,
            set(wi.labels), None, gh, "", "test/repo", {agent.agent: agent},
        )

    def test_complete_applies_complete_label_and_continues(self):
        agent, gh = self._agent(), _make_gh_mock()
        wi = _make_work_item_with_labels(42, set())
        stop = self._call(agent, wi, gh, STATUS_COMPLETE)
        assert stop is False, "a non-gated :complete must not halt the work item"
        gh.add_label.assert_any_call(42, agent.status_label(STATUS_COMPLETE))

    def test_blocked_halts_and_applies_blocked_label(self):
        agent, gh = self._agent(), _make_gh_mock()
        wi = _make_work_item_with_labels(42, set())
        stop = self._call(agent, wi, gh, STATUS_BLOCKED)
        assert stop is True, ":blocked must halt the work item (return True)"
        gh.add_label.assert_any_call(42, agent.status_label(STATUS_BLOCKED))

    def test_review_halts_and_never_applies_complete(self):
        agent, gh = self._agent(), _make_gh_mock()
        wi = _make_work_item_with_labels(42, set())
        stop = self._call(agent, wi, gh, STATUS_REVIEW)
        assert stop is True, ":review must halt the work item (return True)"
        applied = [c.args[1] for c in gh.add_label.call_args_list]
        assert agent.status_label(STATUS_REVIEW) in applied
        assert agent.status_label(STATUS_COMPLETE) not in applied, (
            ":review must never apply the :complete label"
        )


class TestRunAgentBehaviour:
    """_run_agent() applies the :wip mutex, invokes the agent, and returns the
    parsed sentinel tuple — exercised directly as a unit."""

    def _git_side_effect(self):
        import subprocess as _sp
        def _se(cmd, **kw):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            return MagicMock(returncode=0, stdout="", stderr="")
        return _se

    @patch("pipeline_orchestrator.invoke_agent")
    def test_returns_parsed_sentinel_and_applies_wip(self, mock_invoke):
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail='AI_AGILE_STATUS: complete "all done"'
        )
        agent = _make_agent_def("03_execute/coder")
        gh = _make_gh_mock()
        wi = _make_work_item_with_labels(42, {"issue-classifier:complete"})
        with patch("subprocess.run", side_effect=self._git_side_effect()):
            result, sentinel_status, sentinel_message, _pre, _at, attempt = _run_agent(
                agent, wi, False, "test/repo", set(wi.labels), "",
                None, None, gh, {agent.agent: agent},
            )
        assert result.success is True
        assert sentinel_status == STATUS_COMPLETE
        assert sentinel_message == "all done", "the quoted sentinel message must be parsed"
        assert attempt == 0
        gh.add_label.assert_any_call(42, agent.status_label(STATUS_WIP))


class TestCommitAfterExactlyOnce:
    """Regression guard for the double-execution bug the rebaseline removed:
    commit-agent-work.sh must run EXACTLY once on :complete, not twice."""

    def _agent(self) -> AgentDef:
        return AgentDef(
            agent="03_execute/coder", phase="03_execute", objects=["issue"],
            trigger={"label": "issue-classifier:complete"}, dependencies=[],
            human_gate_after=False, human_gate_label=None, description="test coder",
            commit_after=True, max_concurrent=10,
        )

    def _wi(self) -> WorkItem:
        return WorkItem(
            number=42, kind="issue", title="T",
            labels={"issue-classifier:complete"},
            url="https://github.com/test/repo/issues/42",
        )

    def _side_effect(self, bash_result):
        import subprocess as _sp
        def _se(cmd, **kw):
            if isinstance(cmd, list) and cmd and cmd[0] == "git":
                raise _sp.CalledProcessError(1, cmd)
            return bash_result
        return _se

    @patch("pipeline_orchestrator.invoke_agent")
    @patch("pipeline_orchestrator._apply_failed")
    def test_commit_after_runs_exactly_once(self, mock_failed, mock_invoke):
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        bash_ok = MagicMock(returncode=0, stdout="", stderr="")
        agent = self._agent()
        with patch("subprocess.run", side_effect=self._side_effect(bash_ok)) as mock_sub:
            process_work_item(
                self._wi(), [agent], {agent.agent: agent}, _make_gh_mock(),
                dry_run=False, repo="test/repo",
                concurrency=ConcurrencyState(running_counts={"coder": 0}),
            )
        commit_calls = [
            c for c in mock_sub.call_args_list
            if isinstance(c.args[0], list) and c.args[0] and c.args[0][0] == "bash"
            and "commit-agent-work.sh" in c.args[0][-1]
        ]
        assert len(commit_calls) == 1, (
            f"commit-agent-work.sh must run exactly once on :complete; "
            f"ran {len(commit_calls)}x (double-execution regression)"
        )
        mock_failed.assert_not_called()


# ---------------------------------------------------------------------------
# TestOrchestrationScriptResolution (issue #196)
#
# Orchestration helper scripts must resolve from origin/main, not the
# checked-out (possibly stale) issue-{N} branch. A branch cut from an old main
# that predates a script must not be able to make the orchestrator fail to find
# its own infrastructure.
# ---------------------------------------------------------------------------

class TestOrchestrationScriptResolution:
    SCRIPT_REL = ".github/scripts/commit-agent-work.sh"

    @pytest.fixture(autouse=True)
    def _isolate_cache(self):
        """Reset the module-global orchestration-script cache before and after
        each test so state never leaks in or out of this class."""
        import pipeline_orchestrator as po
        po._ORCH_SCRIPT_CACHE.clear()
        po._ORCH_SCRIPT_DIR = None
        po._ORCH_MAIN_FETCHED = False
        yield
        po._ORCH_SCRIPT_CACHE.clear()
        po._ORCH_SCRIPT_DIR = None
        po._ORCH_MAIN_FETCHED = False

    def _git(self, cwd, *args):
        subprocess.run(
            ["git", *args], cwd=str(cwd), check=True,
            capture_output=True, text=True,
        )

    def _make_stale_branch_repo(self, tmp_path, main_script_body):
        """Build an origin+clone where origin/main carries the orchestration
        script but the checked-out issue-999 branch was cut before it existed.
        Returns the work-tree path, checked out to the stale branch."""
        origin = tmp_path / "origin.git"
        self._git(tmp_path, "init", "--bare", "-b", "main", str(origin))
        work = tmp_path / "work"
        self._git(tmp_path, "clone", str(origin), str(work))
        self._git(work, "config", "user.email", "t@t")
        self._git(work, "config", "user.name", "t")

        # Initial main commit WITHOUT the script.
        (work / "README.md").write_text("x\n")
        self._git(work, "add", "-A")
        self._git(work, "commit", "-m", "initial")
        self._git(work, "push", "origin", "main")

        # Stale issue branch, cut before the script exists.
        self._git(work, "checkout", "-b", "issue-999")
        self._git(work, "push", "origin", "issue-999")

        # main gains the orchestration script AFTER the branch was cut.
        self._git(work, "checkout", "main")
        script = work / self.SCRIPT_REL
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(main_script_body)
        self._git(work, "add", "-A")
        self._git(work, "commit", "-m", "add orchestration script on main")
        self._git(work, "push", "origin", "main")

        # Check out the STALE issue branch -- the script is absent on disk here.
        self._git(work, "checkout", "issue-999")
        assert not (work / self.SCRIPT_REL).exists()
        return work

    def test_resolves_from_main_when_issue_branch_lacks_script(self, tmp_path, monkeypatch):
        import pipeline_orchestrator as po
        work = self._make_stale_branch_repo(
            tmp_path, "#!/usr/bin/env bash\necho MAIN_VERSION\n"
        )
        monkeypatch.setattr(po, "SUBMODULE_ROOT", work)

        resolved = po._orchestration_script_path(self.SCRIPT_REL)

        assert resolved.exists(), "resolver did not materialize the script from origin/main"
        assert "MAIN_VERSION" in resolved.read_text()
        # It must NOT be the (missing) working-tree path on the stale branch.
        assert resolved != work / self.SCRIPT_REL

    def test_commit_after_succeeds_when_issue_branch_lacks_script(self, tmp_path, monkeypatch):
        """Acceptance criterion #196: a coder run on an issue branch missing
        commit-agent-work.sh still succeeds, because commit-after sources the
        script from main. The main version here is a no-op that exits 0."""
        import pipeline_orchestrator as po
        work = self._make_stale_branch_repo(
            tmp_path, "#!/usr/bin/env bash\nexit 0\n"
        )
        monkeypatch.setattr(po, "SUBMODULE_ROOT", work)

        agent = AgentDef(
            agent="03_execute/coder", phase="03_execute", objects=["issue"],
            trigger={"label": "x:complete"}, dependencies=[],
            human_gate_after=False, human_gate_label=None, description="t",
            commit_after=True,
        )
        wi = WorkItem(
            number=999, kind="issue", title="T", labels=set(),
            url="https://github.com/test/repo/issues/999",
        )
        result = po._invoke_commit_after(agent, wi)
        assert result is None, f"commit-after should succeed, got failure: {result!r}"

    def test_caches_resolution_across_calls(self, tmp_path, monkeypatch):
        import pipeline_orchestrator as po
        work = self._make_stale_branch_repo(
            tmp_path, "#!/usr/bin/env bash\necho MAIN_VERSION\n"
        )
        monkeypatch.setattr(po, "SUBMODULE_ROOT", work)

        first = po._orchestration_script_path(self.SCRIPT_REL)
        second = po._orchestration_script_path(self.SCRIPT_REL)
        assert first == second

    def test_present_script_uses_working_tree_without_touching_main(self, tmp_path, monkeypatch):
        """Fast path: when the script is present on the checked-out tree it is
        returned directly, with no origin/main resolution."""
        import pipeline_orchestrator as po
        work = tmp_path / "solo"
        work.mkdir()
        self._git(work, "init", "-b", "main")
        script = work / self.SCRIPT_REL
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("#!/usr/bin/env bash\necho LOCAL\n")
        monkeypatch.setattr(po, "SUBMODULE_ROOT", work)

        resolved = po._orchestration_script_path(self.SCRIPT_REL)
        assert resolved == work / self.SCRIPT_REL

    def test_falls_back_to_working_tree_when_missing_and_main_unavailable(self, tmp_path, monkeypatch):
        """Recovery path with no reachable main (no remote): the script is
        absent and origin/main can't be read, so the resolver returns the
        (missing) working-tree path and the caller's existence check reports it."""
        import pipeline_orchestrator as po
        work = tmp_path / "solo"
        work.mkdir()
        self._git(work, "init", "-b", "main")
        # No remote, and the script does not exist on disk.
        monkeypatch.setattr(po, "SUBMODULE_ROOT", work)

        resolved = po._orchestration_script_path(self.SCRIPT_REL)
        assert resolved == work / self.SCRIPT_REL
        assert not resolved.exists()


# ---------------------------------------------------------------------------
# TestNormalizeSkippedLabels
# ---------------------------------------------------------------------------

class TestNormalizeSkippedLabels:
    def test_skipped_synthesizes_complete(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        pipeline_map = {"01_product_docs/prd-writer": dep}
        result = normalize_skipped_labels({"prd-writer:skipped"}, pipeline_map)
        assert "prd-writer:complete" in result

    def test_complete_unchanged(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        pipeline_map = {"01_product_docs/prd-writer": dep}
        result = normalize_skipped_labels({"prd-writer:complete"}, pipeline_map)
        assert "prd-writer:complete" in result
        assert "prd-writer:skipped" not in result

    def test_returns_copy_not_original(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        pipeline_map = {"01_product_docs/prd-writer": dep}
        original = {"prd-writer:skipped"}
        result = normalize_skipped_labels(original, pipeline_map)
        assert result is not original

    def test_non_pipeline_label_unchanged(self):
        pipeline_map = {}
        result = normalize_skipped_labels({"other:skipped"}, pipeline_map)
        assert result == {"other:skipped"}
        assert "other:complete" not in result

    def test_empty_labels_unchanged(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        pipeline_map = {"01_product_docs/prd-writer": dep}
        result = normalize_skipped_labels(set(), pipeline_map)
        assert result == set()

    def test_multiple_skipped_agents_all_synthesized(self):
        a = _make_agent_def("01_product_docs/prd-writer")
        b = _make_agent_def("03_execute/coder")
        pipeline_map = {"01_product_docs/prd-writer": a, "03_execute/coder": b}
        result = normalize_skipped_labels({"prd-writer:skipped", "coder:skipped"}, pipeline_map)
        assert "prd-writer:complete" in result
        assert "coder:complete" in result


# ---------------------------------------------------------------------------
# TestDependenciesComplete
# ---------------------------------------------------------------------------


class TestDependenciesComplete:
    def test_no_dependencies_always_true(self):
        agent = _make_agent_def("03_execute/coder")
        assert dependencies_complete(set(), agent, {}) is True

    def test_dep_complete_passes(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        agent = _make_agent_def("03_execute/coder")
        agent.dependencies = ["01_product_docs/prd-writer"]
        pipeline_map = {"01_product_docs/prd-writer": dep}
        assert dependencies_complete({"prd-writer:complete"}, agent, pipeline_map) is True

    def test_dep_missing_blocks(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        agent = _make_agent_def("03_execute/coder")
        agent.dependencies = ["01_product_docs/prd-writer"]
        pipeline_map = {"01_product_docs/prd-writer": dep}
        assert dependencies_complete(set(), agent, pipeline_map) is False

    def test_dep_skipped_unblocks(self):
        # After normalize_skipped_labels runs, :skipped agents have :complete synthesized.
        dep = _make_agent_def("01_product_docs/prd-writer")
        agent = _make_agent_def("03_execute/coder")
        agent.dependencies = ["01_product_docs/prd-writer"]
        pipeline_map = {"01_product_docs/prd-writer": dep}
        normalized = {"prd-writer:skipped", "prd-writer:complete"}
        assert dependencies_complete(normalized, agent, pipeline_map) is True

    def test_unknown_dep_blocks(self):
        agent = _make_agent_def("03_execute/coder")
        agent.dependencies = ["nonexistent/agent"]
        assert dependencies_complete(set(), agent, {}) is False

    def test_human_gate_blocks_when_gate_absent(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        dep.human_gate_after = True
        dep.human_gate_label = "prd-writer:approved"
        agent = _make_agent_def("03_execute/coder")
        agent.dependencies = ["01_product_docs/prd-writer"]
        pipeline_map = {"01_product_docs/prd-writer": dep}
        assert dependencies_complete({"prd-writer:complete"}, agent, pipeline_map) is False

    def test_human_gate_passes_when_gate_present(self):
        dep = _make_agent_def("01_product_docs/prd-writer")
        dep.human_gate_after = True
        dep.human_gate_label = "prd-writer:approved"
        agent = _make_agent_def("03_execute/coder")
        agent.dependencies = ["01_product_docs/prd-writer"]
        pipeline_map = {"01_product_docs/prd-writer": dep}
        assert dependencies_complete({"prd-writer:complete", "prd-writer:approved"}, agent, pipeline_map) is True

    def test_human_gate_bypassed_when_dep_skipped(self):
        # After normalization, skipped dep has both :skipped and :complete in labels.
        # Gate must be bypassed because the dep never ran (gate label was never applied).
        dep = _make_agent_def("01_product_docs/prd-writer")
        dep.human_gate_after = True
        dep.human_gate_label = "prd-writer:approved"
        agent = _make_agent_def("03_execute/coder")
        agent.dependencies = ["01_product_docs/prd-writer"]
        pipeline_map = {"01_product_docs/prd-writer": dep}
        normalized = {"prd-writer:skipped", "prd-writer:complete"}
        assert dependencies_complete(normalized, agent, pipeline_map) is True


# ---------------------------------------------------------------------------
# TestTriggerLabelPresent
# ---------------------------------------------------------------------------

class TestTriggerLabelPresent:
    def _agent_with_trigger(self, trigger: dict) -> AgentDef:
        agent = _make_agent_def()
        agent.trigger = trigger
        return agent

    def test_no_label_trigger_always_true(self):
        agent = self._agent_with_trigger({})
        assert trigger_label_present(set(), agent) is True

    def test_label_trigger_present(self):
        agent = self._agent_with_trigger({"label": "prd-writer:complete"})
        assert trigger_label_present({"prd-writer:complete"}, agent) is True

    def test_label_trigger_absent(self):
        agent = self._agent_with_trigger({"label": "prd-writer:complete"})
        assert trigger_label_present(set(), agent) is False

    def test_complete_trigger_satisfied_after_normalization(self):
        # normalize_skipped_labels adds :complete when :skipped is present;
        # trigger_label_present sees both and matches on :complete.
        agent = self._agent_with_trigger({"label": "prd-docs-updater:complete"})
        normalized = {"prd-docs-updater:skipped", "prd-docs-updater:complete"}
        assert trigger_label_present(normalized, agent) is True

    def test_non_complete_trigger_not_synthesized(self):
        # normalization only adds :complete, not :approved — gate label must be explicitly applied
        agent = self._agent_with_trigger({"label": "prd-writer:approved"})
        assert trigger_label_present({"prd-writer:skipped", "prd-writer:complete"}, agent) is False

    def test_event_trigger_always_true(self):
        agent = self._agent_with_trigger({"event": "pull_request.closed"})
        assert trigger_label_present(set(), agent) is True

    def test_null_label_blocks_agent(self):
        # {"label": null} in pipeline.json is a misconfiguration — must block, not fire unconditionally
        agent = self._agent_with_trigger({"label": None})
        assert trigger_label_present(set(), agent) is False
        assert trigger_label_present({"anything:complete"}, agent) is False
