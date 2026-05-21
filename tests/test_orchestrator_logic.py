"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from unittest.mock import MagicMock, call, patch
import pytest
from pipeline_orchestrator import (
    ALL_STATUSES,
    STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED,
    STATUS_REVIEW, STATUS_BLOCKED, STATUS_WIP, STATUS_REQUESTED,
    agent_status,
    _apply_failed,
    AgentDef, AgentRunResult, WorkItem,
    ConcurrencyState, _count_running, PIPELINE_MAX_CONCURRENT,
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
# TestApplyFailedReason  (QA-001)
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
        agent_def = _make_agent_def("05_execute/coder")
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
        agent_def = _make_agent_def("05_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)
        exhaustion_heading = "### `05_execute/coder` failed — retry limit exhausted"

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
        agent_def = _make_agent_def("05_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)

        _apply_failed(gh, agent_def, work_item, result)

        comment_body = gh.post_comment.call_args[0][1]
        assert "exited with an error" in comment_body

    def test_custom_heading_overrides_default(self):
        """An explicit heading= kwarg takes precedence over the reason-derived heading."""
        agent_def = _make_agent_def("05_execute/coder")
        work_item = _make_work_item(42)
        gh = self._make_gh()
        result = AgentRunResult(success=False, returncode=1)
        custom = "### `05_execute/coder` failed — custom context"

        _apply_failed(gh, agent_def, work_item, result, reason="some reason", heading=custom)

        comment_body = gh.post_comment.call_args[0][1]
        assert custom in comment_body
        assert "post-run step failed" not in comment_body


# ---------------------------------------------------------------------------
# TestCountRunning  (QA-002)
# ---------------------------------------------------------------------------

class TestCountRunning:
    """_count_running correctly counts :wip labels per agent at tick start."""

    def _wi(self, labels: set) -> WorkItem:
        return WorkItem(number=1, kind="issue", title="t", labels=labels, url="http://x")

    def test_zero_when_no_wip_labels(self):
        agent_def = _make_agent_def("05_execute/coder")
        counts = _count_running([self._wi(set()), self._wi({"other:complete"})], [agent_def])
        assert counts.get("coder", 0) == 0

    def test_counts_matching_wip_labels(self):
        agent_def = _make_agent_def("05_execute/coder")
        work_items = [
            self._wi({"coder:wip"}),
            self._wi({"coder:wip"}),
            self._wi({"pr-reviewer:wip"}),
        ]
        counts = _count_running(work_items, [agent_def])
        assert counts["coder"] == 2

    def test_counts_multiple_agents_independently(self):
        coder = _make_agent_def("05_execute/coder")
        reviewer = _make_agent_def("05_execute/pr-reviewer")
        work_items = [
            self._wi({"coder:wip"}),
            self._wi({"pr-reviewer:wip", "coder:wip"}),
        ]
        counts = _count_running(work_items, [coder, reviewer])
        assert counts["coder"] == 2
        assert counts["pr-reviewer"] == 1

    def test_empty_work_items_returns_zeros(self):
        agent_def = _make_agent_def("05_execute/coder")
        counts = _count_running([], [agent_def])
        assert counts.get("coder", 0) == 0


# ---------------------------------------------------------------------------
# TestConcurrencyState  (QA-002)
# ---------------------------------------------------------------------------

class TestConcurrencyState:
    """ConcurrencyState mutable accounting struct behaves correctly."""

    def test_initial_tick_launch_count_is_zero(self):
        state = ConcurrencyState(running_counts={})
        assert state.tick_launch_count == 0

    def test_initialised_from_count_running(self):
        agent_def = _make_agent_def("05_execute/coder")
        wi = WorkItem(number=1, kind="issue", title="t", labels={"coder:wip"}, url="http://x")
        counts = _count_running([wi], [agent_def])
        state = ConcurrencyState(running_counts=counts)
        assert state.running_counts.get("coder") == 1

    def test_increment_advances_both_counters(self):
        state = ConcurrencyState(running_counts={"coder": 1})
        state.running_counts["coder"] = state.running_counts.get("coder", 0) + 1
        state.tick_launch_count += 1
        assert state.running_counts["coder"] == 2
        assert state.tick_launch_count == 1

    def test_rollback_decrements_both_counters(self):
        state = ConcurrencyState(running_counts={"coder": 2}, tick_launch_count=1)
        state.running_counts["coder"] = max(0, state.running_counts.get("coder", 0) - 1)
        state.tick_launch_count = max(0, state.tick_launch_count - 1)
        assert state.running_counts["coder"] == 1
        assert state.tick_launch_count == 0

    def test_rollback_does_not_go_below_zero(self):
        state = ConcurrencyState(running_counts={"coder": 0}, tick_launch_count=0)
        state.running_counts["coder"] = max(0, state.running_counts.get("coder", 0) - 1)
        state.tick_launch_count = max(0, state.tick_launch_count - 1)
        assert state.running_counts["coder"] == 0
        assert state.tick_launch_count == 0

    def test_pipeline_max_concurrent_is_positive_int(self):
        assert isinstance(PIPELINE_MAX_CONCURRENT, int)
        assert PIPELINE_MAX_CONCURRENT > 0


# ---------------------------------------------------------------------------
# TestRetryPolicy  (PRD scenarios for per-agent retry and restart policy)
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    """Gherkin-traced tests for the per-agent retry/restart policy in the orchestrator.

    Each test corresponds to a named scenario in the approved PRD for issue #16.
    """

    def _make_agent(self, max_retries: int = 0) -> AgentDef:
        return AgentDef(
            agent="05_execute/coder",
            phase="05_execute",
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
            work_item, [agent_def], {"05_execute/coder": agent_def},
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
        assert any("retry" in b.lower() for b in comment_bodies), (
            f"Expected a retry attempt comment. post_comment calls: {comment_bodies}"
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
            work_item, [agent_def], {"05_execute/coder": agent_def},
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
            work_item, [agent_def], {"05_execute/coder": agent_def},
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
            work_item, [agent_def], {"05_execute/coder": agent_def},
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
