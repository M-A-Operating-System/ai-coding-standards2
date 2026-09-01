"""Tests for the step-result-file mechanism added by issue #400.

Covers _read_step_result (validation), _is_exhausted, the allowed_labels
filter/apply helpers, _post_artefact_if_present, the closing announcement's
expected_effect field, and the "exhausted is never retried" invariant in
_invoke_with_retries.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import json
from unittest.mock import MagicMock, patch

import pytest
import pipeline_orchestrator as orch
from pipeline_orchestrator import (
    AgentDef, AgentRunResult, StepResult, WorkItem,
    _read_step_result,
    _is_exhausted,
    _label_pattern_matches,
    _filter_allowed_label_requests,
    _apply_label_requests,
    _post_artefact_if_present,
    _build_closing_announcement,
    _invoke_with_retries,
    STATUS_COMPLETE, STATUS_REVIEW, STATUS_BLOCKED,
)


def _make_agent_def(name: str = "03_execute/coder", **overrides) -> AgentDef:
    kwargs = dict(
        agent=name,
        phase=name.split("/")[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
    )
    kwargs.update(overrides)
    return AgentDef(**kwargs)


def _make_work_item(number: int = 42) -> WorkItem:
    return WorkItem(
        number=number, kind="issue", title="Test issue",
        labels=set(), url=f"https://github.com/test/repo/issues/{number}",
    )


# ---------------------------------------------------------------------------
# TestReadStepResult
# ---------------------------------------------------------------------------

class TestReadStepResult:
    def test_missing_file_returns_none_with_reason(self, tmp_path):
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "no result file" in reason

    def test_no_scratch_dir_returns_none(self):
        result, reason = _read_step_result("")
        assert result is None
        assert reason

    def test_malformed_json_returns_none(self, tmp_path):
        (tmp_path / "result.json").write_text("{not json")
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "could not be read/parsed" in reason

    def test_non_object_json_returns_none(self, tmp_path):
        (tmp_path / "result.json").write_text("[1, 2, 3]")
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "not a JSON object" in reason

    @pytest.mark.parametrize("outcome", ["failed", "exhausted", "invented", "", None])
    def test_invalid_outcome_rejected(self, tmp_path, outcome):
        payload = {"outcome": outcome, "summary": "did stuff"}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "outcome" in reason

    @pytest.mark.parametrize("outcome", ["complete", "review", "blocked"])
    def test_valid_outcomes_accepted(self, tmp_path, outcome):
        payload = {"outcome": outcome, "summary": "did stuff"}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert reason == ""
        assert result.outcome == outcome
        assert result.summary == "did stuff"

    def test_missing_summary_rejected(self, tmp_path):
        payload = {"outcome": "complete"}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "summary" in reason

    def test_summary_wrong_type_rejected(self, tmp_path):
        payload = {"outcome": "complete", "summary": 123}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "summary" in reason

    @pytest.mark.parametrize("field", ["undone", "message", "output"])
    def test_optional_string_fields_wrong_type_rejected(self, tmp_path, field):
        payload = {"outcome": "complete", "summary": "ok", field: 42}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert field in reason

    def test_optional_fields_default_when_omitted(self, tmp_path):
        payload = {"outcome": "complete", "summary": "ok"}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, _ = _read_step_result(str(tmp_path))
        assert result.undone == ""
        assert result.message == ""
        assert result.output == ""
        assert result.expected_effect == {}
        assert result.label_requests == []

    def test_expected_effect_wrong_type_rejected(self, tmp_path):
        payload = {"outcome": "complete", "summary": "ok", "expected_effect": "yes"}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "expected_effect" in reason

    def test_label_requests_not_array_rejected(self, tmp_path):
        payload = {"outcome": "complete", "summary": "ok", "label_requests": {}}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "label_requests" in reason

    def test_label_requests_entry_not_object_rejected(self, tmp_path):
        payload = {"outcome": "complete", "summary": "ok", "label_requests": ["oops"]}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "label_requests" in reason

    def test_label_requests_issue_wrong_type_rejected(self, tmp_path):
        payload = {
            "outcome": "complete", "summary": "ok",
            "label_requests": [{"issue": "42", "add": [], "remove": []}],
        }
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "issue" in reason

    def test_label_requests_issue_null_accepted(self, tmp_path):
        payload = {
            "outcome": "complete", "summary": "ok",
            "label_requests": [{"issue": None, "add": ["x"], "remove": []}],
        }
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert reason == ""
        assert result.label_requests[0]["issue"] is None

    def test_label_requests_add_not_list_of_strings_rejected(self, tmp_path):
        payload = {
            "outcome": "complete", "summary": "ok",
            "label_requests": [{"issue": None, "add": [1, 2], "remove": []}],
        }
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "add" in reason

    def test_fully_populated_result_round_trips(self, tmp_path):
        payload = {
            "outcome": "review",
            "summary": "reviewed the PR",
            "undone": "nothing left",
            "message": "please look at DP-001",
            "output": "## PR Review\n\nfindings...",
            "expected_effect": {"commits": False},
            "label_requests": [{"issue": 7, "add": ["a"], "remove": ["b"]}],
        }
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert reason == ""
        assert result == StepResult(**payload)


# ---------------------------------------------------------------------------
# TestIsExhausted
# ---------------------------------------------------------------------------

class TestIsExhausted:
    def test_timed_out_flag_is_exhausted(self):
        result = AgentRunResult(success=False, timed_out=True)
        assert _is_exhausted(result) is True

    def test_error_max_turns_subtype_is_exhausted(self):
        result = AgentRunResult(success=True, result_event={"subtype": "error_max_turns"})
        assert _is_exhausted(result) is True

    def test_normal_success_is_not_exhausted(self):
        result = AgentRunResult(success=True, result_event={"subtype": "success"})
        assert _is_exhausted(result) is False

    def test_no_result_event_is_not_exhausted(self):
        result = AgentRunResult(success=False)
        assert _is_exhausted(result) is False

    def test_crash_is_not_exhausted(self):
        result = AgentRunResult(success=False, returncode=1, result_event={"subtype": "error_during_execution"})
        assert _is_exhausted(result) is False


# ---------------------------------------------------------------------------
# TestLabelPatternMatching
# ---------------------------------------------------------------------------

class TestLabelPatternMatching:
    def test_exact_match(self):
        assert _label_pattern_matches("epic", "epic") is True

    def test_no_match(self):
        assert _label_pattern_matches("epic", "blocked") is False

    def test_glob_star_matches(self):
        assert _label_pattern_matches("classification: *", "classification: bug") is True

    def test_glob_star_does_not_match_unrelated_prefix(self):
        assert _label_pattern_matches("classification: *", "priority: high") is False

    def test_case_sensitive(self):
        assert _label_pattern_matches("Epic", "epic") is False


# ---------------------------------------------------------------------------
# TestFilterAllowedLabelRequests
# ---------------------------------------------------------------------------

class TestFilterAllowedLabelRequests:
    def _agent_def_with_allowed(self, add=None, remove=None):
        return _make_agent_def(allowed_labels={"add": add or [], "remove": remove or []})

    def test_matching_add_clears(self):
        agent_def = self._agent_def_with_allowed(add=["classification: *"])
        requests = [{"issue": None, "add": ["classification: bug"], "remove": []}]
        cleared = _filter_allowed_label_requests(agent_def, requests)
        assert cleared == [(None, "add", "classification: bug")]

    def test_non_matching_add_silently_dropped(self):
        agent_def = self._agent_def_with_allowed(add=["classification: *"])
        requests = [{"issue": None, "add": ["priority: high"], "remove": []}]
        cleared = _filter_allowed_label_requests(agent_def, requests)
        assert cleared == []

    def test_matching_remove_clears(self):
        agent_def = self._agent_def_with_allowed(remove=["blocked"])
        requests = [{"issue": None, "add": [], "remove": ["blocked"]}]
        cleared = _filter_allowed_label_requests(agent_def, requests)
        assert cleared == [(None, "remove", "blocked")]

    def test_add_pattern_does_not_permit_remove(self):
        agent_def = self._agent_def_with_allowed(add=["blocked"])
        requests = [{"issue": None, "add": [], "remove": ["blocked"]}]
        cleared = _filter_allowed_label_requests(agent_def, requests)
        assert cleared == []

    def test_no_allowed_labels_declared_clears_nothing(self):
        agent_def = _make_agent_def()  # allowed_labels defaults to {}
        requests = [{"issue": None, "add": ["anything"], "remove": []}]
        cleared = _filter_allowed_label_requests(agent_def, requests)
        assert cleared == []

    def test_request_targeting_another_issue_preserved(self):
        agent_def = self._agent_def_with_allowed(add=["blocked"])
        requests = [{"issue": 999, "add": ["blocked"], "remove": []}]
        cleared = _filter_allowed_label_requests(agent_def, requests)
        assert cleared == [(999, "add", "blocked")]

    def test_mixed_requests_only_matching_survive(self):
        agent_def = self._agent_def_with_allowed(add=["epic", "blocked"])
        requests = [
            {"issue": None, "add": ["epic", "not-allowed"], "remove": []},
            {"issue": 5, "add": ["blocked"], "remove": []},
        ]
        cleared = _filter_allowed_label_requests(agent_def, requests)
        assert cleared == [(None, "add", "epic"), (5, "add", "blocked")]


# ---------------------------------------------------------------------------
# TestApplyLabelRequests
# ---------------------------------------------------------------------------

class TestApplyLabelRequests:
    def test_applies_only_cleared_requests(self):
        agent_def = _make_agent_def(allowed_labels={"add": ["epic"], "remove": []})
        work_item = _make_work_item(1)
        gh = MagicMock()
        _apply_label_requests(gh, agent_def, work_item, [
            {"issue": None, "add": ["epic", "nope"], "remove": []},
        ])
        gh.add_label.assert_called_once_with(1, "epic")

    def test_targets_named_issue_not_work_item(self):
        agent_def = _make_agent_def(allowed_labels={"add": ["epic"], "remove": []})
        work_item = _make_work_item(1)
        gh = MagicMock()
        _apply_label_requests(gh, agent_def, work_item, [
            {"issue": 77, "add": ["epic"], "remove": []},
        ])
        gh.add_label.assert_called_once_with(77, "epic")

    def test_swallows_add_label_exception(self):
        agent_def = _make_agent_def(allowed_labels={"add": ["epic"], "remove": []})
        work_item = _make_work_item(1)
        gh = MagicMock()
        gh.add_label.side_effect = RuntimeError("boom")
        # Must not raise.
        _apply_label_requests(gh, agent_def, work_item, [
            {"issue": None, "add": ["epic"], "remove": []},
        ])

    def test_empty_requests_calls_nothing(self):
        agent_def = _make_agent_def(allowed_labels={"add": ["epic"], "remove": []})
        work_item = _make_work_item(1)
        gh = MagicMock()
        _apply_label_requests(gh, agent_def, work_item, [])
        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()


# ---------------------------------------------------------------------------
# TestPostArtefactIfPresent
# ---------------------------------------------------------------------------

class TestPostArtefactIfPresent:
    def test_posts_output_with_marker(self):
        agent_def = _make_agent_def("03_execute/pr-reviewer")
        work_item = _make_work_item(5)
        gh = MagicMock()
        step_result = StepResult(outcome="complete", summary="ok", output="## Review\n\nfindings")
        _post_artefact_if_present(gh, agent_def, work_item, step_result)
        gh.post_comment.assert_called_once()
        args = gh.post_comment.call_args[0]
        assert args[0] == 5
        assert "<!-- ai-agile/artefact/v1 by 03_execute/pr-reviewer -->" in args[1]
        assert "## Review" in args[1]

    def test_no_op_when_step_result_none(self):
        agent_def = _make_agent_def()
        work_item = _make_work_item(5)
        gh = MagicMock()
        _post_artefact_if_present(gh, agent_def, work_item, None)
        gh.post_comment.assert_not_called()

    def test_no_op_when_output_empty(self):
        agent_def = _make_agent_def()
        work_item = _make_work_item(5)
        gh = MagicMock()
        step_result = StepResult(outcome="complete", summary="ok", output="")
        _post_artefact_if_present(gh, agent_def, work_item, step_result)
        gh.post_comment.assert_not_called()

    def test_swallows_post_comment_exception(self):
        agent_def = _make_agent_def()
        work_item = _make_work_item(5)
        gh = MagicMock()
        gh.post_comment.side_effect = RuntimeError("boom")
        step_result = StepResult(outcome="complete", summary="ok", output="content")
        # Must not raise.
        _post_artefact_if_present(gh, agent_def, work_item, step_result)


# ---------------------------------------------------------------------------
# TestClosingAnnouncementExpectedEffect
# ---------------------------------------------------------------------------

class TestClosingAnnouncementExpectedEffect:
    def test_expected_effect_included_when_present(self):
        agent_def = _make_agent_def()
        work_item = _make_work_item(5)
        body = _build_closing_announcement(
            agent_def, work_item, "sess-1", STATUS_COMPLETE, "done",
            expected_effect={"commits": True},
        )
        payload = json.loads(body.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        assert payload["expected_effect"] == {"commits": True}

    def test_expected_effect_omitted_when_empty(self):
        agent_def = _make_agent_def()
        work_item = _make_work_item(5)
        body = _build_closing_announcement(
            agent_def, work_item, "sess-1", STATUS_COMPLETE, "done",
            expected_effect={},
        )
        payload = json.loads(body.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        assert "expected_effect" not in payload


# ---------------------------------------------------------------------------
# TestExhaustionNeverRetried
# ---------------------------------------------------------------------------

class TestExhaustionNeverRetried:
    @patch("pipeline_orchestrator.invoke_agent")
    def test_wall_clock_timeout_invokes_exactly_once_despite_max_retries(self, mock_invoke, tmp_path, monkeypatch):
        monkeypatch.setattr(orch, "_scratch_path", lambda session_id: str(tmp_path))
        agent_def = _make_agent_def(max_retries=3)
        work_item = _make_work_item(9)
        gh = MagicMock()
        mock_invoke.return_value = AgentRunResult(success=False, timed_out=True, captured_tail="timed out")

        result, step_result, exhausted, attempt = _invoke_with_retries(
            agent_def, work_item, dry_run=False, repo="test/repo", gh=gh,
            default_extra_tools=None, agent_text_snapshot=None,
        )

        assert mock_invoke.call_count == 1, "an exhausted run must never be retried"
        assert exhausted is True
        assert step_result is None
        assert attempt == 0

    @patch("pipeline_orchestrator.invoke_agent")
    def test_max_turns_subtype_invokes_exactly_once(self, mock_invoke, tmp_path, monkeypatch):
        monkeypatch.setattr(orch, "_scratch_path", lambda session_id: str(tmp_path))
        agent_def = _make_agent_def(max_retries=2)
        work_item = _make_work_item(9)
        gh = MagicMock()
        mock_invoke.return_value = AgentRunResult(
            success=True, result_event={"subtype": "error_max_turns"},
        )

        result, step_result, exhausted, attempt = _invoke_with_retries(
            agent_def, work_item, dry_run=False, repo="test/repo", gh=gh,
            default_extra_tools=None, agent_text_snapshot=None,
        )

        assert mock_invoke.call_count == 1
        assert exhausted is True

    @patch("pipeline_orchestrator.invoke_agent")
    def test_crash_with_no_result_still_retries_up_to_max(self, mock_invoke, tmp_path, monkeypatch):
        """Sanity check: a plain crash (not exhaustion) keeps the pre-#400 retry behaviour."""
        monkeypatch.setattr(orch, "_scratch_path", lambda session_id: str(tmp_path))
        agent_def = _make_agent_def(max_retries=2)
        work_item = _make_work_item(9)
        gh = MagicMock()
        mock_invoke.return_value = AgentRunResult(success=False, returncode=1, captured_tail="boom")

        result, step_result, exhausted, attempt = _invoke_with_retries(
            agent_def, work_item, dry_run=False, repo="test/repo", gh=gh,
            default_extra_tools=None, agent_text_snapshot=None,
        )

        assert mock_invoke.call_count == 3  # initial + 2 retries
        assert exhausted is False
        assert step_result is None
        assert attempt == 2
