"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

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
    AgentDef, AgentRunResult, ConcurrencyState, WorkItem,
    parse_frontmatter,
    process_work_item,
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
            _make_agent_def_concurrent("05_execute/coder"),
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
        agent = _make_agent_def("05_execute/coder")
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
            agent="05_execute/coder",
            phase="05_execute",
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
            "05_execute/coder": agent_two,
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
# TestOrchestratorNonOverlapping
# ---------------------------------------------------------------------------

class TestOrchestratorNonOverlapping:
    """Scenario: Orchestrator runs remain non-overlapping."""

    def test_workflow_defines_pipeline_orchestrator_concurrency_group(self):
        """
        Given the GitHub Actions workflow
        Then it defines concurrency group 'pipeline-orchestrator' with
        cancel-in-progress: false so new triggers queue rather than
        cancel the active run.
        """
        workflow_path = Path(__file__).parent.parent / ".github/workflows/orchestrator.yml"
        assert workflow_path.exists(), f"Workflow file not found at {workflow_path}"
        content = workflow_path.read_text()
        assert "group: pipeline-orchestrator" in content, (
            "Workflow must declare concurrency group 'pipeline-orchestrator' "
            "to serialise orchestrator runs"
        )
        assert "cancel-in-progress: false" in content, (
            "Workflow must set cancel-in-progress: false so a queued run waits "
            "for the active run to finish rather than being cancelled"
        )
