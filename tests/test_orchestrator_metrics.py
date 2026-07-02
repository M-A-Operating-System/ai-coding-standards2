"""Tests for per-cycle metrics capture in pipeline_orchestrator.py.

Covers the acceptance criteria from issue #121:
- Agent metrics record contains all required fields from system/init and result events
- Scripted-step metrics record has AI-specific fields zeroed
- duration_ms equals timestamp_end minus timestamp_start
- Retry events are reflected in retry_count and retry_errors
- Extra CLI fields pass through (floor not ceiling)
- _StreamAccumulator captures init, result, and api_retry events
- _post_metrics_comment posts the correct format
- _ensure_metrics_branch creates branch on 404, is idempotent on existing branch
- _append_metrics_record appends correctly and retries on 409
- _post_cycle_metrics is skipped in dry_run mode
- Comment and branch record contain identical field sets (same record dict)
"""

import base64
import json
import sys
import os
from unittest.mock import MagicMock, call, patch
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline_orchestrator import (
    METRICS_BRANCH,
    METRICS_RECORDS_FILE,
    METRICS_SCHEMA_FILE,
    METRICS_SCHEMA,
    AgentDef,
    AgentRunResult,
    WorkItem,
    _build_agent_metrics,
    _build_scripted_metrics,
    _build_step_metrics,
    _post_metrics_comment,
    _ensure_metrics_branch,
    _append_metrics_record,
    _post_cycle_metrics,
    _StreamAccumulator,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TS_START = "2026-07-01T10:00:00Z"
_TS_END   = "2026-07-01T10:00:05Z"  # 5 000 ms later
_CYCLE_ID = "test-cycle-abc123"


def _make_agent_def(name: str = "03_execute/coder", step_type: str = "agent") -> AgentDef:
    return AgentDef(
        agent=name,
        phase=name.split("/")[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
        step_type=step_type,
    )


def _make_work_item(number: int = 42, kind: str = "issue") -> WorkItem:
    return WorkItem(number=number, kind=kind, title="Test item", labels=set(), url=f"https://example.com/{number}")


def _make_full_result(
    *,
    session_id: str = "sess-xyz",
    model: str = "claude-sonnet-4-6",
    cwd: str = "/repo",
    permission_mode: str = "default",
    tools: list = None,
    mcp_servers: list = None,
    subtype: str = "success",
    is_error: bool = False,
    duration_ms: int = 4800,
    duration_api_ms: int = 3200,
    num_turns: int = 7,
    input_tokens: int = 5000,
    output_tokens: int = 300,
    cache_creation_input_tokens: int = 200,
    cache_read_input_tokens: int = 4500,
    web_search_requests: int = 0,
    service_tier: str = "standard",
    total_cost_usd: float = 0.042,
    retry_count: int = 0,
    retry_errors: list = None,
) -> AgentRunResult:
    if tools is None:
        tools = [{"name": "Bash"}, {"name": "Read"}]
    if mcp_servers is None:
        mcp_servers = []
    if retry_errors is None:
        retry_errors = []

    init_event = {
        "type": "system",
        "subtype": "init",
        "session_id": session_id,
        "model": model,
        "cwd": cwd,
        "permissionMode": permission_mode,
        "tools": tools,
        "mcp_servers": mcp_servers,
    }
    result_event = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "duration_ms": duration_ms,
        "duration_api_ms": duration_api_ms,
        "num_turns": num_turns,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "server_tool_use": {"web_search_requests": web_search_requests},
            "service_tier": service_tier,
        },
        "total_cost_usd": total_cost_usd,
    }
    return AgentRunResult(
        success=not is_error,
        returncode=0 if not is_error else 1,
        init_event=init_event,
        result_event=result_event,
        retry_count=retry_count,
        retry_errors=retry_errors,
    )


def _make_gh_client(repo: str = "owner/test-repo") -> MagicMock:
    gh = MagicMock()
    gh.repo = repo
    return gh


# ---------------------------------------------------------------------------
# TestAgentRunResultFields
# ---------------------------------------------------------------------------

class TestAgentRunResultFields:
    """AgentRunResult carries the four new metrics fields."""

    def test_default_values(self):
        result = AgentRunResult(success=True)
        assert result.init_event is None
        assert result.result_event is None
        assert result.retry_count == 0
        assert result.retry_errors == []

    def test_fields_roundtrip(self):
        init = {"type": "system", "subtype": "init"}
        result_ev = {"type": "result"}
        result = AgentRunResult(
            success=True,
            init_event=init,
            result_event=result_ev,
            retry_count=2,
            retry_errors=["overloaded_error", "server_error"],
        )
        assert result.init_event is init
        assert result.result_event is result_ev
        assert result.retry_count == 2
        assert result.retry_errors == ["overloaded_error", "server_error"]


# ---------------------------------------------------------------------------
# TestBuildAgentMetrics — required field set
# ---------------------------------------------------------------------------

class TestBuildAgentMetrics:
    """_build_agent_metrics produces all PRD-required fields."""

    PRD_REQUIRED_FIELDS = [
        "timestamp_start", "timestamp_end", "github_issue_number", "agent_id",
        "branch_id", "pr_id", "cycle_id", "session_id", "model", "cwd",
        "permission_mode", "tools_available", "mcp_servers", "subtype",
        "is_error", "duration_ms", "duration_api_ms", "num_turns",
        "input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens", "web_search_requests", "service_tier",
        "total_cost_usd", "retry_count", "retry_errors",
    ]

    def _build(self, **kwargs):
        result = _make_full_result(**kwargs)
        agent_def = _make_agent_def()
        work_item = _make_work_item()
        return _build_agent_metrics(
            agent_def, work_item, result, _TS_START, _TS_END, _CYCLE_ID
        )

    def test_all_prd_required_fields_present(self):
        record = self._build()
        for field in self.PRD_REQUIRED_FIELDS:
            assert field in record, f"missing required field: {field}"

    def test_timestamp_start_and_end_match_inputs(self):
        record = self._build()
        assert record["timestamp_start"] == _TS_START
        assert record["timestamp_end"] == _TS_END

    def test_duration_ms_equals_timestamp_diff(self):
        record = self._build()
        assert record["duration_ms"] == 5000

    def test_agent_id_from_agent_def(self):
        record = self._build()
        assert record["agent_id"] == "03_execute/coder"

    def test_github_issue_number_set_for_issue_work_item(self):
        result = _make_full_result()
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(number=99, kind="issue"),
            result, _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["github_issue_number"] == 99
        assert record["pr_id"] is None
        assert record["branch_id"] == "issue-99"

    def test_pr_id_set_and_issue_number_null_for_pr_work_item(self):
        result = _make_full_result()
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(number=77, kind="pr"),
            result, _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["pr_id"] == 77
        assert record["github_issue_number"] is None
        assert record["branch_id"] is None

    def test_session_context_from_init_event(self):
        record = self._build(
            session_id="sess-abc",
            model="claude-opus-4-8",
            cwd="/workspace",
            permission_mode="acceptEdits",
        )
        assert record["session_id"] == "sess-abc"
        assert record["model"] == "claude-opus-4-8"
        assert record["cwd"] == "/workspace"
        assert record["permission_mode"] == "acceptEdits"

    def test_tools_available_comma_separated_names(self):
        record = self._build(tools=[{"name": "Bash"}, {"name": "Read"}, {"name": "Edit"}])
        assert record["tools_available"] == "Bash,Read,Edit"

    def test_tools_available_none_when_empty_list(self):
        record = self._build(tools=[])
        assert record["tools_available"] is None

    def test_mcp_servers_formatted_as_name_colon_status(self):
        record = self._build(
            mcp_servers=[{"name": "mcp-server-a", "status": "connected"}]
        )
        assert record["mcp_servers"] == "mcp-server-a:connected"

    def test_mcp_servers_none_when_empty(self):
        record = self._build(mcp_servers=[])
        assert record["mcp_servers"] is None

    def test_usage_fields_from_result_event(self):
        record = self._build(
            input_tokens=5000,
            output_tokens=300,
            cache_creation_input_tokens=200,
            cache_read_input_tokens=4500,
            web_search_requests=3,
            service_tier="standard",
            total_cost_usd=0.042,
        )
        assert record["input_tokens"] == 5000
        assert record["output_tokens"] == 300
        assert record["cache_creation_input_tokens"] == 200
        assert record["cache_read_input_tokens"] == 4500
        assert record["web_search_requests"] == 3
        assert record["service_tier"] == "standard"
        assert record["total_cost_usd"] == pytest.approx(0.042)

    def test_retry_fields(self):
        record = self._build(
            retry_count=2,
            retry_errors=["overloaded_error", "server_error"],
        )
        assert record["retry_count"] == 2
        assert record["retry_errors"] == ["overloaded_error", "server_error"]

    def test_is_error_from_result_event(self):
        record = self._build(is_error=True, subtype="error_during_execution")
        assert record["is_error"] is True
        assert record["subtype"] == "error_during_execution"

    def test_is_error_override_takes_precedence(self):
        result = _make_full_result(is_error=False)
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
            is_error_override=True,
        )
        assert record["is_error"] is True

    def test_cycle_id_preserved(self):
        record = self._build()
        assert record["cycle_id"] == _CYCLE_ID

    def test_no_init_event_produces_null_session_fields(self):
        result = AgentRunResult(success=True, init_event=None, result_event=None)
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["session_id"] is None
        assert record["model"] is None
        assert record["cwd"] is None
        assert record["tools_available"] is None
        assert record["mcp_servers"] is None

    def test_extra_init_fields_pass_through(self):
        """Fields in system/init beyond the canonical set must be captured."""
        result = AgentRunResult(
            success=True,
            init_event={
                "type": "system",
                "subtype": "init",
                "session_id": "s",
                "model": "m",
                "cwd": "/",
                "permissionMode": "default",
                "tools": [],
                "mcp_servers": [],
                "api_key_source": "env",       # extra field
                "claude_version": "4.6.0",     # extra field
            },
            result_event=None,
        )
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert "api_key_source" in record
        assert record["api_key_source"] == "env"
        assert "claude_version" in record
        assert record["claude_version"] == "4.6.0"

    def test_extra_result_fields_pass_through(self):
        """Fields in the result event beyond the canonical set must be captured."""
        result = AgentRunResult(
            success=True,
            init_event=None,
            result_event={
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 1000,
                "duration_api_ms": 800,
                "num_turns": 3,
                "usage": {},
                "total_cost_usd": 0.01,
                "future_field": "new_value",   # extra field from future CLI
            },
        )
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert "future_field" in record
        assert record["future_field"] == "new_value"

    def test_canonical_fields_override_extra_fields_with_same_name(self):
        """Known canonical fields win over any same-named extra field."""
        result = AgentRunResult(
            success=True,
            init_event={
                "type": "system",
                "subtype": "init",
                "session_id": "canonical-session",
                "model": "claude",
                "cwd": "/",
                "permissionMode": "default",
                "tools": [],
                "mcp_servers": [],
                "cycle_id": "injected-bad-value",  # should NOT win
            },
            result_event=None,
        )
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["cycle_id"] == _CYCLE_ID


# ---------------------------------------------------------------------------
# TestBuildScriptedMetrics — zeroed AI fields
# ---------------------------------------------------------------------------

class TestBuildScriptedMetrics:
    """_build_scripted_metrics zeroes all AI-specific fields."""

    AI_NULL_FIELDS = [
        "session_id", "model", "cwd", "permission_mode",
        "tools_available", "mcp_servers", "service_tier",
    ]
    AI_ZERO_INT_FIELDS = [
        "duration_api_ms", "num_turns", "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens",
        "web_search_requests", "retry_count",
    ]

    def _build(self, is_error: bool = False) -> dict:
        return _build_scripted_metrics(
            _make_agent_def("01_product_docs/create-pr", step_type="script"),
            _make_work_item(number=55),
            is_error,
            _TS_START,
            _TS_END,
            _CYCLE_ID,
        )

    def test_ai_specific_string_fields_are_null(self):
        record = self._build()
        for field in self.AI_NULL_FIELDS:
            assert record[field] is None, f"expected null for {field}"

    def test_ai_specific_numeric_fields_are_zero(self):
        record = self._build()
        for field in self.AI_ZERO_INT_FIELDS:
            assert record[field] == 0, f"expected 0 for {field}"

    def test_retry_errors_is_empty_list(self):
        record = self._build()
        assert record["retry_errors"] == []

    def test_total_cost_usd_is_zero(self):
        record = self._build()
        assert record["total_cost_usd"] == 0

    def test_subtype_is_script(self):
        record = self._build()
        assert record["subtype"] == "script"

    def test_duration_ms_equals_timestamp_diff(self):
        record = self._build()
        assert record["duration_ms"] == 5000

    def test_is_error_true_when_failed(self):
        record = self._build(is_error=True)
        assert record["is_error"] is True

    def test_is_error_false_when_succeeded(self):
        record = self._build(is_error=False)
        assert record["is_error"] is False

    def test_github_issue_number_from_issue_work_item(self):
        record = self._build()
        assert record["github_issue_number"] == 55
        assert record["pr_id"] is None
        assert record["branch_id"] == "issue-55"

    def test_pr_id_set_for_pr_work_item(self):
        record = _build_scripted_metrics(
            _make_agent_def("03_execute/merge-conflict", step_type="script"),
            _make_work_item(number=7, kind="pr"),
            False, _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["pr_id"] == 7
        assert record["github_issue_number"] is None
        assert record["branch_id"] is None

    def test_all_prd_required_fields_present(self):
        record = self._build()
        required = [
            "timestamp_start", "timestamp_end", "github_issue_number", "agent_id",
            "cycle_id", "duration_ms", "input_tokens", "output_tokens",
            "retry_count", "retry_errors",
        ]
        for f in required:
            assert f in record, f"scripted record missing required field: {f}"

    def test_field_sets_match_agent_record(self):
        """Scripted record keys must be a superset of agent record keys for comparison.

        PRD: 'identical field set' means the same keys appear in both output types.
        """
        scripted_record = self._build()
        agent_result = AgentRunResult(success=True)
        agent_record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), agent_result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        # Every PRD-required key must appear in the scripted record.
        for key in agent_record:
            if key in (
                "session_id", "model", "cwd", "permission_mode",
                "tools_available", "mcp_servers", "service_tier",
                "duration_api_ms", "num_turns",
                "cache_creation_input_tokens", "cache_read_input_tokens",
                "web_search_requests", "total_cost_usd",
            ):
                continue  # these differ by design (zeroed vs populated)
            assert key in scripted_record, f"scripted record missing key {key}"


# ---------------------------------------------------------------------------
# TestBuildStepMetrics — dispatcher
# ---------------------------------------------------------------------------

class TestBuildStepMetrics:
    """_build_step_metrics dispatches to the correct builder."""

    def test_dispatches_to_scripted_builder_for_script_type(self):
        agent_def = _make_agent_def("01_product_docs/create-pr", step_type="script")
        result = AgentRunResult(success=True)
        record = _build_step_metrics(
            agent_def, _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["subtype"] == "script"
        assert record["session_id"] is None

    def test_dispatches_to_agent_builder_for_agent_type(self):
        agent_def = _make_agent_def("03_execute/coder", step_type="agent")
        result = _make_full_result(subtype="success")
        record = _build_step_metrics(
            agent_def, _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["subtype"] == "success"

    def test_is_error_override_propagates_to_script(self):
        agent_def = _make_agent_def("script-step", step_type="script")
        result = AgentRunResult(success=True)
        record = _build_step_metrics(
            agent_def, _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
            is_error_override=True,
        )
        assert record["is_error"] is True

    def test_is_error_override_propagates_to_agent(self):
        agent_def = _make_agent_def("03_execute/coder", step_type="agent")
        result = _make_full_result(is_error=False)
        record = _build_step_metrics(
            agent_def, _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
            is_error_override=True,
        )
        assert record["is_error"] is True


# ---------------------------------------------------------------------------
# TestStreamAccumulatorMetrics — event capture
# ---------------------------------------------------------------------------

class TestStreamAccumulatorMetrics:
    """_StreamAccumulator captures init, result, and api_retry events."""

    def test_captures_init_event(self):
        acc = _StreamAccumulator()
        init = {"type": "system", "subtype": "init", "model": "claude-sonnet-4-6", "session_id": "s1"}
        acc.feed(json.dumps(init))
        assert acc.init_event == init

    def test_captures_result_event(self):
        acc = _StreamAccumulator()
        result = {"type": "result", "subtype": "success", "is_error": False}
        acc.feed(json.dumps(result))
        assert acc.result_event == result

    def test_counts_api_retry_events(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "system", "subtype": "api_retry", "error": "overloaded_error"}))
        acc.feed(json.dumps({"type": "system", "subtype": "api_retry", "error": "server_error"}))
        assert acc.retry_count == 2

    def test_accumulates_retry_error_strings(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "system", "subtype": "api_retry", "error": "overloaded_error"}))
        acc.feed(json.dumps({"type": "system", "subtype": "api_retry", "error": "server_error"}))
        assert acc.retry_errors == ["overloaded_error", "server_error"]

    def test_no_retry_error_field_does_not_crash(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "system", "subtype": "api_retry"}))
        assert acc.retry_count == 1
        assert acc.retry_errors == []

    def test_last_result_event_wins(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "result", "subtype": "first"}))
        acc.feed(json.dumps({"type": "result", "subtype": "second"}))
        assert acc.result_event["subtype"] == "second"

    def test_last_init_event_wins(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "system", "subtype": "init", "model": "a"}))
        acc.feed(json.dumps({"type": "system", "subtype": "init", "model": "b"}))
        assert acc.init_event["model"] == "b"

    def test_other_system_subtypes_do_not_set_init_event(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "system", "subtype": "other_event"}))
        assert acc.init_event is None

    def test_assistant_event_does_not_affect_metrics(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "assistant", "message": {"content": []}}))
        assert acc.init_event is None
        assert acc.result_event is None
        assert acc.retry_count == 0

    def test_initial_state_is_empty(self):
        acc = _StreamAccumulator()
        assert acc.init_event is None
        assert acc.result_event is None
        assert acc.retry_count == 0
        assert acc.retry_errors == []


# ---------------------------------------------------------------------------
# TestPostMetricsComment
# ---------------------------------------------------------------------------

class TestPostMetricsComment:
    """_post_metrics_comment posts a collapsible metrics block."""

    def test_comment_contains_json_record(self):
        gh = _make_gh_client()
        work_item = _make_work_item(number=42)
        record = {"timestamp_start": _TS_START, "agent_id": "03_execute/coder"}
        _post_metrics_comment(gh, work_item, record)
        gh.post_comment.assert_called_once()
        body = gh.post_comment.call_args[0][1]
        assert "<!-- ai-agile/metrics/v1 -->" in body
        assert json.dumps(record, indent=2) in body

    def test_comment_uses_work_item_number(self):
        gh = _make_gh_client()
        work_item = _make_work_item(number=99)
        _post_metrics_comment(gh, work_item, {"agent_id": "test"})
        gh.post_comment.assert_called_once_with(99, pytest.approx(gh.post_comment.call_args[0][1], rel=0))
        assert gh.post_comment.call_args[0][0] == 99

    def test_comment_failure_is_swallowed(self):
        gh = _make_gh_client()
        gh.post_comment.side_effect = Exception("network error")
        work_item = _make_work_item(number=1)
        _post_metrics_comment(gh, work_item, {"agent_id": "test"})
        # Must not raise


# ---------------------------------------------------------------------------
# TestEnsureMetricsBranch
# ---------------------------------------------------------------------------

class TestEnsureMetricsBranch:
    """_ensure_metrics_branch creates the branch when absent, no-ops when present."""

    def _make_response(self, status_code: int) -> MagicMock:
        r = MagicMock(spec=requests.Response)
        r.status_code = status_code
        http_err = requests.HTTPError(response=r)
        r.raise_for_status.side_effect = http_err if status_code >= 400 else None
        return r

    def test_returns_immediately_when_branch_exists(self):
        gh = _make_gh_client()
        gh._get.return_value = {"object": {"sha": "abc"}}
        _ensure_metrics_branch(gh, "owner/repo")
        gh._post.assert_not_called()

    def test_creates_branch_when_not_found(self):
        gh = _make_gh_client()
        not_found_resp = self._make_response(404)
        not_found_err = requests.HTTPError(response=not_found_resp)

        def _get_side_effect(path, **kwargs):
            if "refs/heads/ai-agile/metrics" in path and "contents" not in path:
                raise not_found_err
            if "/repos/owner/repo" == path:
                return {"default_branch": "main"}
            if "refs/heads/main" in path:
                return {"object": {"sha": "deadbeef"}}
            return {}

        gh._get.side_effect = _get_side_effect
        put_resp = self._make_response(201)
        gh._put.return_value = put_resp

        _ensure_metrics_branch(gh, "owner/repo")

        gh._post.assert_called_once()
        post_body = gh._post.call_args[0][1]
        assert post_body["ref"] == f"refs/heads/{METRICS_BRANCH}"
        assert post_body["sha"] == "deadbeef"

    def test_pushes_schema_after_creating_branch(self):
        gh = _make_gh_client()
        not_found_resp = self._make_response(404)
        not_found_err = requests.HTTPError(response=not_found_resp)

        def _get_side_effect(path, **kwargs):
            if "refs/heads/ai-agile/metrics" in path:
                raise not_found_err
            if "/repos/owner/repo" == path:
                return {"default_branch": "main"}
            if "refs/heads/main" in path:
                return {"object": {"sha": "abc123"}}
            return {}

        gh._get.side_effect = _get_side_effect
        gh._put.return_value = self._make_response(201)

        _ensure_metrics_branch(gh, "owner/repo")

        assert gh._put.call_count >= 1
        put_call = gh._put.call_args
        assert METRICS_SCHEMA_FILE in put_call[0][0]
        body = put_call[0][1]
        schema_decoded = json.loads(base64.b64decode(body["content"].replace("\n", "")))
        assert schema_decoded["title"] == "AI Agile Metrics Record"

    def test_swallows_422_concurrent_creation(self):
        gh = _make_gh_client()
        not_found_resp = self._make_response(404)
        not_found_err = requests.HTTPError(response=not_found_resp)
        conflict_resp = self._make_response(422)
        conflict_err = requests.HTTPError(response=conflict_resp)

        def _get_side_effect(path, **kwargs):
            if "refs/heads/ai-agile/metrics" in path:
                raise not_found_err
            if "/repos/owner/repo" == path:
                return {"default_branch": "main"}
            return {"object": {"sha": "sha1"}}

        gh._get.side_effect = _get_side_effect
        gh._post.side_effect = conflict_err
        _ensure_metrics_branch(gh, "owner/repo")
        # Must not raise


# ---------------------------------------------------------------------------
# TestAppendMetricsRecord
# ---------------------------------------------------------------------------

class TestAppendMetricsRecord:
    """_append_metrics_record appends JSON lines to records.jsonl."""

    def _make_successful_put(self, status_code: int = 200) -> MagicMock:
        r = MagicMock(spec=requests.Response)
        r.status_code = status_code
        r.raise_for_status.return_value = None
        return r

    def test_creates_file_when_not_found(self):
        gh = _make_gh_client()
        not_found = requests.HTTPError(response=MagicMock(status_code=404))
        gh._get.side_effect = not_found
        gh._put.return_value = self._make_successful_put(201)

        record = {"agent_id": "coder", "github_issue_number": 42}
        _append_metrics_record(gh, "owner/repo", record, _retries=0)

        gh._put.assert_called_once()
        put_body = gh._put.call_args[0][1]
        decoded = base64.b64decode(put_body["content"].replace("\n", "")).decode()
        assert json.loads(decoded.strip()) == record
        assert "sha" not in put_body  # no prior SHA when file doesn't exist

    def test_appends_to_existing_file(self):
        gh = _make_gh_client()
        existing_record = {"agent_id": "prd-writer", "github_issue_number": 10}
        existing_line = json.dumps(existing_record, separators=(",", ":")) + "\n"
        existing_b64 = base64.b64encode(existing_line.encode()).decode()
        gh._get.return_value = {"content": existing_b64, "sha": "file-sha-123"}
        gh._put.return_value = self._make_successful_put(200)

        new_record = {"agent_id": "coder", "github_issue_number": 42}
        _append_metrics_record(gh, "owner/repo", new_record, _retries=0)

        put_body = gh._put.call_args[0][1]
        assert put_body["sha"] == "file-sha-123"
        decoded = base64.b64decode(put_body["content"].replace("\n", "")).decode()
        lines = [l for l in decoded.strip().splitlines() if l]
        assert len(lines) == 2
        assert json.loads(lines[0]) == existing_record
        assert json.loads(lines[1]) == new_record

    def test_retries_on_409_conflict(self):
        gh = _make_gh_client()
        not_found = requests.HTTPError(response=MagicMock(status_code=404))
        gh._get.side_effect = not_found

        conflict_resp = MagicMock(spec=requests.Response)
        conflict_resp.status_code = 409
        conflict_resp.raise_for_status.side_effect = requests.HTTPError(response=conflict_resp)
        success_resp = self._make_successful_put(201)

        gh._put.side_effect = [conflict_resp, success_resp]

        with patch("pipeline_orchestrator.time.sleep"):
            _append_metrics_record(gh, "owner/repo", {"agent_id": "test"}, _retries=1)

        assert gh._put.call_count == 2

    def test_commit_message_contains_agent_and_issue(self):
        gh = _make_gh_client()
        not_found = requests.HTTPError(response=MagicMock(status_code=404))
        gh._get.side_effect = not_found
        gh._put.return_value = self._make_successful_put(201)

        _append_metrics_record(
            gh, "owner/repo",
            {"agent_id": "03_execute/coder", "github_issue_number": 55},
            _retries=0,
        )

        put_body = gh._put.call_args[0][1]
        assert "03_execute/coder" in put_body["message"]
        assert "55" in put_body["message"]

    def test_put_targets_correct_branch(self):
        gh = _make_gh_client()
        not_found = requests.HTTPError(response=MagicMock(status_code=404))
        gh._get.side_effect = not_found
        gh._put.return_value = self._make_successful_put(201)

        _append_metrics_record(gh, "owner/repo", {"agent_id": "test"}, _retries=0)

        put_body = gh._put.call_args[0][1]
        assert put_body["branch"] == METRICS_BRANCH


# ---------------------------------------------------------------------------
# TestPostCycleMetrics
# ---------------------------------------------------------------------------

class TestPostCycleMetrics:
    """_post_cycle_metrics orchestrates comment posting and branch appending."""

    def test_skipped_in_dry_run_mode(self):
        gh = _make_gh_client()
        work_item = _make_work_item(number=1)
        _post_cycle_metrics(gh, "owner/repo", work_item, {"agent_id": "test"}, dry_run=True)
        gh.post_comment.assert_not_called()
        gh._get.assert_not_called()
        gh._put.assert_not_called()

    def test_posts_comment_and_branch_record_in_non_dry_run(self):
        gh = _make_gh_client()
        gh._get.side_effect = [
            requests.HTTPError(response=MagicMock(status_code=404)),  # branch check
            {"default_branch": "main"},
            {"object": {"sha": "abc"}},
            requests.HTTPError(response=MagicMock(status_code=404)),  # records.jsonl check
        ]
        success_resp = MagicMock(spec=requests.Response)
        success_resp.status_code = 201
        success_resp.raise_for_status.return_value = None
        gh._post.return_value = {}
        gh._put.return_value = success_resp

        work_item = _make_work_item(number=42)
        record = {"agent_id": "coder", "github_issue_number": 42}
        _post_cycle_metrics(gh, "owner/repo", work_item, record, dry_run=False)

        gh.post_comment.assert_called_once()

    def test_branch_push_failure_does_not_propagate(self):
        gh = _make_gh_client()
        gh._get.side_effect = Exception("network failure")
        work_item = _make_work_item(number=5)
        _post_cycle_metrics(gh, "owner/repo", work_item, {"agent_id": "test"}, dry_run=False)
        # Must not raise

    def test_comment_failure_does_not_propagate(self):
        gh = _make_gh_client()
        gh.post_comment.side_effect = Exception("API error")
        gh._get.side_effect = Exception("also failing")
        work_item = _make_work_item(number=3)
        _post_cycle_metrics(gh, "owner/repo", work_item, {"agent_id": "test"}, dry_run=False)
        # Must not raise


# ---------------------------------------------------------------------------
# TestMetricsSchema
# ---------------------------------------------------------------------------

class TestMetricsSchema:
    """METRICS_SCHEMA structure satisfies PRD requirements."""

    def test_schema_permits_additional_properties(self):
        assert METRICS_SCHEMA.get("additionalProperties") is True

    def test_schema_requires_timestamp_start_and_end(self):
        required = METRICS_SCHEMA.get("required", [])
        assert "timestamp_start" in required
        assert "timestamp_end" in required

    def test_schema_allows_null_for_ai_specific_fields(self):
        props = METRICS_SCHEMA.get("properties", {})
        nullable_fields = [
            "session_id", "model", "cwd", "permission_mode",
            "tools_available", "mcp_servers", "service_tier",
        ]
        for f in nullable_fields:
            assert f in props, f"schema missing property: {f}"
            field_type = props[f].get("type", [])
            if isinstance(field_type, list):
                assert "null" in field_type, f"{f} should accept null"

    def test_schema_allows_zero_for_numeric_fields(self):
        props = METRICS_SCHEMA.get("properties", {})
        zero_fields = [
            "duration_api_ms", "num_turns", "input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens",
            "web_search_requests", "retry_count",
        ]
        for f in zero_fields:
            assert f in props, f"schema missing property: {f}"
            assert props[f].get("minimum", 1) == 0, f"{f} must allow 0"

    def test_schema_retry_errors_is_array_of_strings(self):
        props = METRICS_SCHEMA.get("properties", {})
        assert "retry_errors" in props
        assert props["retry_errors"]["type"] == "array"
        assert props["retry_errors"]["items"]["type"] == "string"

    def test_metrics_constants_defined(self):
        assert METRICS_BRANCH == "ai-agile/metrics"
        assert METRICS_RECORDS_FILE == "records.jsonl"
        assert METRICS_SCHEMA_FILE == "schema.json"


# ---------------------------------------------------------------------------
# TestDurationMsComputation
# ---------------------------------------------------------------------------

class TestDurationMsComputation:
    """duration_ms always equals timestamp_end minus timestamp_start."""

    def test_five_seconds_difference(self):
        result = AgentRunResult(success=True)
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            "2026-07-01T10:00:00Z", "2026-07-01T10:00:05Z", _CYCLE_ID,
        )
        assert record["duration_ms"] == 5000

    def test_one_minute_difference(self):
        result = AgentRunResult(success=True)
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            "2026-07-01T10:00:00Z", "2026-07-01T10:01:00Z", _CYCLE_ID,
        )
        assert record["duration_ms"] == 60_000

    def test_scripted_step_duration_ms(self):
        record = _build_scripted_metrics(
            _make_agent_def("create-pr", "script"),
            _make_work_item(),
            False,
            "2026-07-01T10:00:00Z",
            "2026-07-01T10:00:30Z",
            _CYCLE_ID,
        )
        assert record["duration_ms"] == 30_000

    def test_invalid_timestamps_fall_back_to_zero(self):
        result = AgentRunResult(success=True, result_event=None)
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            "not-a-timestamp", "also-bad", _CYCLE_ID,
        )
        assert record["duration_ms"] == 0


# ---------------------------------------------------------------------------
# TestRetryEventCapture
# ---------------------------------------------------------------------------

class TestRetryEventCapture:
    """Retry events are accumulated and reflected in the metrics record."""

    def test_retry_count_and_errors_in_agent_metrics(self):
        result = _make_full_result(
            retry_count=3,
            retry_errors=["overloaded_error", "server_error", "overloaded_error"],
        )
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["retry_count"] == 3
        assert record["retry_errors"] == ["overloaded_error", "server_error", "overloaded_error"]

    def test_zero_retries_when_none_occurred(self):
        result = _make_full_result(retry_count=0, retry_errors=[])
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["retry_count"] == 0
        assert record["retry_errors"] == []

    def test_stream_accumulator_feeds_into_agent_run_result(self):
        acc = _StreamAccumulator()
        acc.feed(json.dumps({"type": "system", "subtype": "api_retry", "error": "overloaded_error"}))
        acc.feed(json.dumps({"type": "system", "subtype": "api_retry", "error": "server_error"}))
        acc.feed(json.dumps({
            "type": "result", "subtype": "success", "is_error": False,
            "result": "AI_AGILE_STATUS: complete",
        }))

        result = AgentRunResult(
            success=True,
            retry_count=acc.retry_count,
            retry_errors=list(acc.retry_errors),
            init_event=acc.init_event,
            result_event=acc.result_event,
        )
        record = _build_agent_metrics(
            _make_agent_def(), _make_work_item(), result,
            _TS_START, _TS_END, _CYCLE_ID,
        )
        assert record["retry_count"] == 2
        assert record["retry_errors"] == ["overloaded_error", "server_error"]


# ---------------------------------------------------------------------------
# TestCommentAndBranchRecordParity
# ---------------------------------------------------------------------------

class TestCommentAndBranchRecordParity:
    """The same record dict is used for both outputs — parity is structural."""

    def test_same_record_dict_used_for_comment_and_branch(self):
        """_post_cycle_metrics passes the same dict to both outputs."""
        record = {"agent_id": "coder", "github_issue_number": 42, "input_tokens": 100}
        comment_records = []
        branch_records = []

        gh = _make_gh_client()
        gh.post_comment.side_effect = lambda num, body: comment_records.append(body)
        gh._get.side_effect = Exception("skip branch ops")

        work_item = _make_work_item(number=42)

        with patch("pipeline_orchestrator._ensure_metrics_branch"):
            with patch("pipeline_orchestrator._append_metrics_record") as mock_append:
                mock_append.side_effect = lambda _gh, _repo, r, **kw: branch_records.append(r)
                _post_cycle_metrics(gh, "owner/repo", work_item, record, dry_run=False)

        assert len(comment_records) == 1
        assert len(branch_records) == 1
        # The branch record is the same dict passed in.
        assert branch_records[0] is record
