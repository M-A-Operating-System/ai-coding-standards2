"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
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
        mock_paused.return_value = (True, "rate-limit", None)
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
        path = Path(__file__).parent.parent / ".github" / "workflows" / "orchestrator.yml"
        assert path.exists(), f"Workflow file not found: {path}"
        content = path.read_text()
        assert "group: pipeline-orchestrator" in content, (
            "orchestrator.yml must declare concurrency group 'pipeline-orchestrator'"
        )
        assert "cancel-in-progress: false" in content, (
            "orchestrator.yml must set cancel-in-progress: false"
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
            verbose=False, clear_pause=False, repo="test/repo",
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
             patch.object(orch, "_configure_git_auth"), \
             patch.object(orch, "GitHubClient", return_value=gh_mock), \
             patch.object(orch, "process_work_item", side_effect=_capture_process), \
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
        path = Path(__file__).parent.parent / ".github" / "workflows" / "orchestrator.yml"
        assert path.exists(), f"Workflow file not found: {path}"
        content = path.read_text()
        assert "--phases" not in content, (
            "orchestrator.yml must not pass --phases — the single workflow runs "
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

    def test_first_cycle_adds_review_cycle_label(self):
        """After cycle 0→1, review-cycle:1 label is applied."""
        reviewer = self._reviewer_def()
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        labels = {reviewer.review_label, target.complete_label}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        gh.add_label.assert_any_call(wi.number, "review-cycle:1")
        assert "review-cycle:1" in result

    def test_max_cycles_reached_escalates_to_human(self):
        """When next_cycle >= max_cycles, :review is left intact (escalation)."""
        reviewer = self._reviewer_def(max_cycles=2)
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        # Already at cycle 1; next would be 2 == max_cycles → escalate
        labels = {reviewer.review_label, target.complete_label, "review-cycle:1"}

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

    def test_second_cycle_removes_old_cycle_label(self):
        """On cycle 1→2, the review-cycle:1 label is removed before review-cycle:2 is added."""
        reviewer = self._reviewer_def(max_cycles=5)
        target = self._target_def()
        wi = self._work_item()
        gh = MagicMock()
        pipeline_map = {target.agent: target}
        labels = {reviewer.review_label, target.complete_label, "review-cycle:1"}

        result = _handle_review_loop(gh, reviewer, wi, labels, pipeline_map)

        gh.remove_label.assert_any_call(wi.number, "review-cycle:1")
        gh.add_label.assert_any_call(wi.number, "review-cycle:2")
        assert "review-cycle:1" not in result
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
        # Cycle label applied
        assert "review-cycle:1" in result


# ---------------------------------------------------------------------------
# QA-001: TestWriteAuditLog
# ---------------------------------------------------------------------------

class TestWriteAuditLog:
    """Tests for write_audit_log() and _make_audit_event()."""

    def _make_gh(self) -> MagicMock:
        gh = MagicMock()
        gh.repo = "test/repo"
        return gh

    def test_make_audit_event_has_required_fields(self):
        """_make_audit_event returns a dict with all schema-required fields."""
        wi = WorkItem(
            number=42, kind="issue", title="test", labels=set(),
            url="https://github.com/test/repo/issues/42",
        )
        event = _make_audit_event(
            "sess-123", "agent.complete", "test/repo",
            work_item=wi, agent="03_execute/coder",
            outcome_status="ok",
        )
        assert event["event_type"] == "agent.complete"
        assert event["session_id"] == "sess-123"
        assert event["agent"] == "03_execute/coder"
        assert event["outcome"]["status"] == "ok"
        assert event["object"]["kind"] == "issue"
        assert event["object"]["id"] == 42
        assert "ts" in event
        assert "actor" in event

    def test_make_audit_event_without_work_item(self):
        """_make_audit_event with no work_item sets object to None."""
        event = _make_audit_event("sess-1", "session.start", "test/repo")
        assert event["object"] is None
        assert event["agent"] is None

    def test_write_audit_log_no_op_on_empty_events(self):
        """write_audit_log returns without API calls when events list is empty."""
        gh = self._make_gh()
        write_audit_log(gh, [])
        gh._request.assert_not_called()

    def test_write_audit_log_emits_jsonl_lines(self):
        """write_audit_log writes one JSON line per event."""
        gh = self._make_gh()

        # Mock the branch-check GET (200 = branch exists)
        branch_response = MagicMock()
        branch_response.status_code = 200

        # Mock the file-not-found GET (404 = new file)
        file_response = MagicMock()
        file_response.status_code = 404

        # Mock a successful PUT
        put_response = MagicMock()
        put_response.status_code = 201

        gh._request.side_effect = [branch_response, file_response]
        gh._put.return_value = put_response

        event = _make_audit_event("s1", "agent.complete", "test/repo", outcome_status="ok")
        write_audit_log(gh, [event])

        # PUT must have been called with base64-encoded content
        assert gh._put.called
        put_body = gh._put.call_args[0][1]
        content = base64.b64decode(put_body["content"]).decode()
        parsed = json.loads(content.strip())
        assert parsed["event_type"] == "agent.complete"

    def test_write_audit_log_retries_on_409_conflict(self):
        """409 conflict triggers a retry — events must not be dropped silently.

        On the retry, the orchestrator must re-GET the file and re-send the
        *refreshed* sha so the second PUT no longer collides with the
        concurrent writer's commit.
        """
        gh = self._make_gh()

        branch_response = MagicMock()
        branch_response.status_code = 200

        # First attempt: file is brand new (404 → no sha sent), PUT races and
        # loses with a 409.
        file_response = MagicMock()
        file_response.status_code = 404

        conflict_response = MagicMock()
        conflict_response.status_code = 409

        # Retry attempt: the concurrent writer's commit now exists, so the GET
        # returns 200 with a refreshed sha and existing content.
        refreshed_sha = "refreshed-sha-deadbeef"
        file_response2 = MagicMock()
        file_response2.status_code = 200
        file_response2.json.return_value = {
            "sha": refreshed_sha,
            "content": base64.b64encode(b'{"prior":"line"}\n').decode(),
        }

        success_response = MagicMock()
        success_response.status_code = 201

        # First attempt: branch check, file 404, PUT → 409
        # Second attempt: file 200 (refreshed sha), PUT → 201
        gh._request.side_effect = [
            branch_response,
            file_response,
            file_response2,
        ]
        gh._put.side_effect = [conflict_response, success_response]

        event = _make_audit_event("s1", "test.event", "test/repo")

        with patch("time.sleep"):  # don't actually sleep in tests
            write_audit_log(gh, [event])

        # Should have been called twice (one conflict + one success)
        assert gh._put.call_count == 2

        # The first PUT carried no sha (file was new / 404).
        first_put_body = gh._put.call_args_list[0][0][1]
        assert "sha" not in first_put_body, (
            f"First PUT should not carry a sha for a new file; got {first_put_body!r}"
        )

        # The retried PUT must carry the refreshed sha fetched on the retry GET —
        # re-sending the stale (absent) sha would just 409 again.
        second_put_body = gh._put.call_args_list[1][0][1]
        assert second_put_body.get("sha") == refreshed_sha, (
            f"Retried PUT must re-send the refreshed sha {refreshed_sha!r}; "
            f"got {second_put_body.get('sha')!r}"
        )


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
# TestMarkReadyOnComplete — orchestrator marks PR ready on :complete
# ---------------------------------------------------------------------------

class TestMarkReadyOnComplete:
    """An agent with mark_ready_on_complete must trigger gh.mark_pr_ready when
    it completes on a PR work item."""

    def _agent(self) -> AgentDef:
        return AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=["pr"],
            trigger={"label": "coder:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            mark_ready_on_complete=True,
        )

    @patch("pipeline_orchestrator.invoke_agent")
    def test_marks_pr_ready_on_complete(self, mock_invoke):
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent = self._agent()
        agents = [agent]
        pipeline_map = {agent.agent: agent}
        gh = _make_gh_mock()
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"coder:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        n = process_work_item(
            wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
        )

        assert n == 1
        gh.mark_pr_ready.assert_called_once_with(55)

    @patch("pipeline_orchestrator.invoke_agent")
    def test_does_not_mark_ready_on_review(self, mock_invoke):
        """When the agent emits :review (not :complete), the PR must NOT be
        marked ready — readiness only fires on true completion."""
        mock_invoke.return_value = AgentRunResult(
            success=False,
            captured_tail='AI_AGILE_STATUS: review "needs changes"',
        )
        agent = self._agent()
        agents = [agent]
        pipeline_map = {agent.agent: agent}
        gh = _make_gh_mock()
        wi = WorkItem(
            number=56, kind="pr", title="PR", labels={"coder:complete"},
            url="https://github.com/test/repo/pull/56",
        )

        process_work_item(
            wi, agents, pipeline_map, gh, dry_run=False, repo="test/repo",
        )
        gh.mark_pr_ready.assert_not_called()

    @patch("pipeline_orchestrator.invoke_agent")
    def test_mark_pr_ready_called_on_issue_work_item(self, mock_invoke):
        """On APPROVE of an issue-scoped agent, mark_pr_ready is called with the
        PR number found via find_pr_by_branch."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent = AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "merge-conflict:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            mark_ready_on_complete=True,
        )
        gh = _make_gh_mock()
        gh.find_pr_by_branch = MagicMock(return_value=99)
        gh.find_pr_by_label = MagicMock(return_value=None)
        wi = WorkItem(
            number=42, kind="issue", title="issue", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/issues/42",
        )

        process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        gh.mark_pr_ready.assert_called_once_with(99)
        gh.find_pr_by_label.assert_not_called()

    @patch("pipeline_orchestrator.invoke_agent")
    def test_label_fallback_finds_pr_by_source_issue_label(self, mock_invoke):
        """When find_pr_by_branch returns None (rebased branch), falls back to
        find_pr_by_label('source-issue:{N}') and still marks the PR ready."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent = AgentDef(
            agent="03_execute/pr-reviewer",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "merge-conflict:complete"},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            mark_ready_on_complete=True,
        )
        gh = _make_gh_mock()
        gh.find_pr_by_branch = MagicMock(return_value=None)  # canonical branch not found
        gh.find_pr_by_label = MagicMock(return_value=132)    # found via source-issue label
        wi = WorkItem(
            number=23, kind="issue", title="issue", labels={"merge-conflict:complete"},
            url="https://github.com/test/repo/issues/23",
        )

        process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")

        gh.find_pr_by_branch.assert_called_once_with("issue-23")
        gh.find_pr_by_label.assert_called_once_with("source-issue:23")
        gh.mark_pr_ready.assert_called_once_with(132)

    @patch("pipeline_orchestrator.invoke_agent")
    def test_mark_pr_ready_exception_is_caught(self, mock_invoke):
        """mark_pr_ready exception is caught and logged — does not propagate."""
        mock_invoke.return_value = AgentRunResult(
            success=True, captured_tail="AI_AGILE_STATUS: complete"
        )
        agent = self._agent()  # kind="pr"
        gh = _make_gh_mock()
        gh.mark_pr_ready = MagicMock(side_effect=Exception("draft not supported"))
        wi = WorkItem(
            number=55, kind="pr", title="PR", labels={"coder:complete"},
            url="https://github.com/test/repo/pull/55",
        )

        # Must not raise — exception is caught internally and logged as warning.
        n = process_work_item(wi, [agent], {agent.agent: agent}, gh, dry_run=False, repo="test/repo")
        assert n == 1


# ---------------------------------------------------------------------------
# TestRunCommitAfter — orchestrator-driven git commit_after step
# ---------------------------------------------------------------------------

class TestRunCommitAfter:
    """Tests for _run_commit_after covering the no-changes happy path and the
    'workflow files staged without AI_AGILE_BOT_TOKEN' failure branch."""

    def _agent(self) -> AgentDef:
        return AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
            commit_after=True,
        )

    def _work_item(self) -> WorkItem:
        return WorkItem(
            number=42, kind="issue", title="T", labels=set(),
            url="https://github.com/test/repo/issues/42",
        )

    def test_no_working_tree_changes_returns_true(self):
        """Clean working tree (git status --porcelain empty) → True, no commit."""
        import pipeline_orchestrator as orch

        def _run(cmd, *args, **kwargs):
            r = MagicMock()
            if cmd[:2] == ["git", "status"]:
                r.stdout = ""        # clean tree
            else:
                r.stdout = ""
            r.returncode = 0
            return r

        with patch("subprocess.run", side_effect=_run) as mock_run:
            ok = orch._run_commit_after(self._agent(), self._work_item())

        assert ok is True
        # Only the status check should have run — no commit/push.
        commands = [c.args[0][:2] for c in mock_run.call_args_list]
        assert ["git", "status"] in commands
        assert ["git", "commit"] not in commands

    def test_workflow_files_without_bot_token_returns_false(self, monkeypatch):
        """Workflow files staged but AI_AGILE_BOT_TOKEN unset → False (GITHUB_TOKEN
        cannot push workflow files)."""
        import pipeline_orchestrator as orch

        monkeypatch.delenv("AI_AGILE_BOT_TOKEN", raising=False)

        def _run(cmd, *args, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            head = cmd[:2]
            if head == ["git", "status"]:
                r.stdout = " M foo.txt"  # dirty tree
            elif head == ["git", "rev-parse"]:
                r.stdout = "main"
            elif cmd[:3] == ["git", "stash", "show"]:
                r.stdout = ".github/workflows/ci.yml"
            elif cmd[:3] == ["git", "diff", "--cached"] and "--name-only" in cmd:
                # workflow-file detection diff
                r.stdout = ".github/workflows/ci.yml"
            return r

        with patch("subprocess.run", side_effect=_run) as mock_run:
            ok = orch._run_commit_after(self._agent(), self._work_item())

        assert ok is False, (
            "Staging workflow files without AI_AGILE_BOT_TOKEN must fail the "
            "commit_after step (GITHUB_TOKEN lacks the workflow scope)."
        )
        # Must not have attempted a commit after the early failure.
        commands = [c.args[0][:2] for c in mock_run.call_args_list]
        assert ["git", "commit"] not in commands
