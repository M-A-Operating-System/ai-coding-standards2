"""Tests for the body-write mechanism added by issue #401: StepResult's
body_write field, the todos-block parse/patch helpers, and _apply_body_write
(replace with auto-snapshot, patch with conflict-retry and checked-item
preservation).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import json
from unittest.mock import MagicMock, call

import pytest
import pipeline_orchestrator as orch
from pipeline_orchestrator import (
    AgentDef, StepResult, WorkItem,
    _read_step_result,
    _todos_subsection_markers,
    _checked_items_would_be_lost,
    _apply_todos_patch,
    _resolve_body_write_target,
    _snapshot_body_if_first_replace,
    _apply_body_write,
)


def _make_agent_def(name: str = "01_product_docs/prd-writer", **overrides) -> AgentDef:
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


def _make_work_item(number: int = 42, kind: str = "issue") -> WorkItem:
    return WorkItem(
        number=number, kind=kind, title="Test", labels=set(),
        url=f"https://github.com/test/repo/{kind}s/{number}",
    )


# ---------------------------------------------------------------------------
# TestBodyWriteValidation
# ---------------------------------------------------------------------------

class TestBodyWriteValidation:
    def _write(self, tmp_path, body_write):
        payload = {"outcome": "review", "summary": "ok", "body_write": body_write}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        return _read_step_result(str(tmp_path))

    def test_empty_body_write_is_valid_default(self, tmp_path):
        payload = {"outcome": "complete", "summary": "ok"}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert reason == ""
        assert result.body_write == {}

    def test_body_write_wrong_type_rejected(self, tmp_path):
        payload = {"outcome": "complete", "summary": "ok", "body_write": "nope"}
        (tmp_path / "result.json").write_text(json.dumps(payload))
        result, reason = _read_step_result(str(tmp_path))
        assert result is None
        assert "body_write" in reason

    def test_missing_target_rejected(self, tmp_path):
        result, reason = self._write(tmp_path, {"mode": "replace", "body": "x"})
        assert result is None
        assert "target" in reason

    def test_bad_target_rejected(self, tmp_path):
        result, reason = self._write(tmp_path, {"target": "wiki", "mode": "replace", "body": "x"})
        assert result is None
        assert "target" in reason

    def test_bad_mode_rejected(self, tmp_path):
        result, reason = self._write(tmp_path, {"target": "issue", "mode": "delete"})
        assert result is None
        assert "mode" in reason

    def test_replace_valid_minimal(self, tmp_path):
        result, reason = self._write(
            tmp_path, {"target": "issue", "mode": "replace", "body": "new body"},
        )
        assert reason == ""
        assert result.body_write["body"] == "new body"

    def test_replace_valid_with_title(self, tmp_path):
        result, reason = self._write(
            tmp_path,
            {"target": "issue", "mode": "replace", "body": "b", "title": "t"},
        )
        assert reason == ""
        assert result.body_write["title"] == "t"

    def test_replace_missing_body_rejected(self, tmp_path):
        result, reason = self._write(tmp_path, {"target": "issue", "mode": "replace"})
        assert result is None
        assert "body" in reason

    def test_replace_title_wrong_type_rejected(self, tmp_path):
        result, reason = self._write(
            tmp_path, {"target": "issue", "mode": "replace", "body": "b", "title": 5},
        )
        assert result is None
        assert "title" in reason

    def test_patch_valid_minimal(self, tmp_path):
        result, reason = self._write(
            tmp_path,
            {"target": "pr", "mode": "patch", "subsection": "build-plan", "content": "- [ ] x"},
        )
        assert reason == ""
        assert result.body_write["subsection"] == "build-plan"

    def test_patch_missing_subsection_rejected(self, tmp_path):
        result, reason = self._write(
            tmp_path, {"target": "issue", "mode": "patch", "content": "x"},
        )
        assert result is None
        assert "subsection" in reason

    def test_patch_empty_subsection_rejected(self, tmp_path):
        result, reason = self._write(
            tmp_path, {"target": "issue", "mode": "patch", "subsection": "", "content": "x"},
        )
        assert result is None
        assert "subsection" in reason

    def test_patch_missing_content_rejected(self, tmp_path):
        result, reason = self._write(
            tmp_path, {"target": "issue", "mode": "patch", "subsection": "build-plan"},
        )
        assert result is None
        assert "content" in reason


# ---------------------------------------------------------------------------
# TestTodosSubsectionMarkers
# ---------------------------------------------------------------------------

class TestTodosSubsectionMarkers:
    def test_markers_are_distinct_and_named(self):
        start, end = _todos_subsection_markers("build-plan")
        assert start == "<!-- ai-agile/todos/build-plan/v1 START -->"
        assert end == "<!-- ai-agile/todos/build-plan/v1 END -->"


# ---------------------------------------------------------------------------
# TestCheckedItemsWouldBeLost
# ---------------------------------------------------------------------------

class TestCheckedItemsWouldBeLost:
    def test_no_checked_items_never_refuses(self):
        assert _checked_items_would_be_lost("- [ ] pending", "anything at all") == ""

    def test_checked_item_preserved_verbatim_ok(self):
        old = "- [x] done thing"
        new = "- [x] done thing\n- [ ] new pending"
        assert _checked_items_would_be_lost(old, new) == ""

    def test_checked_item_dropped_refuses(self):
        old = "- [x] done thing"
        new = "- [ ] some other pending"
        reason = _checked_items_would_be_lost(old, new)
        assert "done thing" in reason
        assert "previously checked" in reason

    def test_checked_item_uncheck_refuses(self):
        old = "- [x] done thing"
        new = "- [ ] done thing"
        assert "previously checked" in _checked_items_would_be_lost(old, new)

    def test_multiple_checked_items_all_preserved_ok(self):
        old = "- [x] one\n- [x] two"
        new = "- [x] one\n- [x] two\n- [ ] three"
        assert _checked_items_would_be_lost(old, new) == ""

    def test_case_insensitive_checkbox_marker(self):
        old = "- [X] done thing"
        new = "- [ ] done thing"
        assert "previously checked" in _checked_items_would_be_lost(old, new)


# ---------------------------------------------------------------------------
# TestApplyTodosPatch
# ---------------------------------------------------------------------------

class TestApplyTodosPatch:
    def test_creates_block_from_scratch(self):
        body = "Human-written prose.\n"
        new_body, err = _apply_todos_patch(body, "acceptance-criteria", "- [ ] item")
        assert err == ""
        assert "Human-written prose." in new_body
        assert orch._TODOS_HEADING in new_body
        assert orch._TODOS_OUTER_START in new_body and orch._TODOS_OUTER_END in new_body
        start, end = _todos_subsection_markers("acceptance-criteria")
        assert start in new_body and end in new_body
        assert "- [ ] item" in new_body

    def test_adds_new_subsection_to_existing_block(self):
        body, _ = _apply_todos_patch("prose\n", "acceptance-criteria", "- [ ] ac1")
        new_body, err = _apply_todos_patch(body, "build-plan", "- [ ] step1")
        assert err == ""
        assert "ac1" in new_body and "step1" in new_body

    def test_patches_existing_subsection_leaves_others_untouched(self):
        body, _ = _apply_todos_patch("prose\n", "acceptance-criteria", "- [ ] ac1")
        body, _ = _apply_todos_patch(body, "build-plan", "- [ ] step1")
        new_body, err = _apply_todos_patch(body, "acceptance-criteria", "- [x] ac1 (done)")
        assert err == ""
        assert "- [x] ac1 (done)" in new_body
        assert "- [ ] ac1" not in new_body  # old content replaced, not appended
        assert "- [ ] step1" in new_body  # untouched subsection survives

    def test_refuses_to_drop_checked_item(self):
        body, _ = _apply_todos_patch("prose\n", "acceptance-criteria", "- [x] done item")
        new_body, err = _apply_todos_patch(body, "acceptance-criteria", "- [ ] different item")
        assert new_body is None
        assert "previously checked" in err

    def test_preserves_human_prose_before_block(self):
        body = "# Issue title\n\nSome human context.\n"
        new_body, err = _apply_todos_patch(body, "build-plan", "- [ ] x")
        assert err == ""
        assert new_body.startswith("# Issue title\n\nSome human context.")

    def test_unterminated_outer_block_errors(self):
        body = f"prose\n\n{orch._TODOS_OUTER_START}\nno end marker"
        new_body, err = _apply_todos_patch(body, "build-plan", "- [ ] x")
        assert new_body is None
        assert "unterminated" in err

    def test_repeated_patch_is_idempotent(self):
        body, _ = _apply_todos_patch("prose\n", "build-plan", "- [ ] x")
        body2, err = _apply_todos_patch(body, "build-plan", "- [ ] x")
        assert err == ""
        assert body == body2


# ---------------------------------------------------------------------------
# TestResolveBodyWriteTarget
# ---------------------------------------------------------------------------

class TestResolveBodyWriteTarget:
    def test_issue_target_on_issue_work_item(self):
        gh = MagicMock()
        wi = _make_work_item(42, "issue")
        assert _resolve_body_write_target(gh, wi, "issue") == 42

    def test_issue_target_on_pr_work_item_returns_none(self):
        gh = MagicMock()
        wi = _make_work_item(42, "pr")
        assert _resolve_body_write_target(gh, wi, "issue") is None

    def test_pr_target_on_pr_work_item(self):
        gh = MagicMock()
        wi = _make_work_item(99, "pr")
        assert _resolve_body_write_target(gh, wi, "pr") == 99

    def test_pr_target_on_issue_work_item_looks_up_by_branch(self):
        gh = MagicMock()
        gh.find_pr_by_branch.return_value = 77
        wi = _make_work_item(42, "issue")
        assert _resolve_body_write_target(gh, wi, "pr") == 77
        gh.find_pr_by_branch.assert_called_once_with("issue-42")

    def test_pr_target_falls_back_to_label_lookup(self):
        gh = MagicMock()
        gh.find_pr_by_branch.return_value = None
        gh.find_pr_by_label.return_value = 88
        wi = _make_work_item(42, "issue")
        assert _resolve_body_write_target(gh, wi, "pr") == 88
        gh.find_pr_by_label.assert_called_once_with("source-issue:42")

    def test_pr_target_returns_none_when_not_found(self):
        gh = MagicMock()
        gh.find_pr_by_branch.return_value = None
        gh.find_pr_by_label.return_value = None
        wi = _make_work_item(42, "issue")
        assert _resolve_body_write_target(gh, wi, "pr") is None

    def test_pr_lookup_exception_returns_none(self):
        gh = MagicMock()
        gh.find_pr_by_branch.side_effect = RuntimeError("boom")
        wi = _make_work_item(42, "issue")
        assert _resolve_body_write_target(gh, wi, "pr") is None


# ---------------------------------------------------------------------------
# TestSnapshotBodyIfFirstReplace
# ---------------------------------------------------------------------------

class TestSnapshotBodyIfFirstReplace:
    def test_posts_snapshot_when_none_exists(self):
        gh = MagicMock()
        gh.list_comment_bodies.return_value = ["some other comment"]
        gh.get_body.return_value = "original body"
        agent_def = _make_agent_def()
        _snapshot_body_if_first_replace(gh, agent_def, 42)
        gh.post_comment.assert_called_once()
        args = gh.post_comment.call_args[0]
        assert args[0] == 42
        assert "ai-agile/snapshot/v1 by 01_product_docs/prd-writer" in args[1]
        assert "original body" in args[1]

    def test_no_op_when_snapshot_already_exists(self):
        gh = MagicMock()
        gh.list_comment_bodies.return_value = [
            "<!-- ai-agile/snapshot/v1 by 01_product_docs/prd-writer -->\nold snapshot",
        ]
        agent_def = _make_agent_def()
        _snapshot_body_if_first_replace(gh, agent_def, 42)
        gh.post_comment.assert_not_called()
        gh.get_body.assert_not_called()


# ---------------------------------------------------------------------------
# TestApplyBodyWrite
# ---------------------------------------------------------------------------

class TestApplyBodyWrite:
    def test_no_op_when_step_result_none(self):
        gh = MagicMock()
        _apply_body_write(gh, _make_agent_def(), _make_work_item(), None)
        gh.update_body.assert_not_called()

    def test_no_op_when_body_write_empty(self):
        gh = MagicMock()
        step_result = StepResult(outcome="complete", summary="ok")
        _apply_body_write(gh, _make_agent_def(), _make_work_item(), step_result)
        gh.update_body.assert_not_called()

    def test_replace_snapshots_then_updates(self):
        gh = MagicMock()
        gh.list_comment_bodies.return_value = []
        gh.get_body.return_value = "original"
        step_result = StepResult(
            outcome="review", summary="ok",
            body_write={"target": "issue", "mode": "replace", "body": "new body", "title": "New Title"},
        )
        _apply_body_write(gh, _make_agent_def(), _make_work_item(42), step_result)
        gh.post_comment.assert_called_once()  # the snapshot
        gh.update_body.assert_called_once_with(42, "new body", title="New Title")

    def test_replace_without_title(self):
        gh = MagicMock()
        gh.list_comment_bodies.return_value = ["<!-- ai-agile/snapshot/v1 by 01_product_docs/prd-writer -->\nx"]
        step_result = StepResult(
            outcome="review", summary="ok",
            body_write={"target": "issue", "mode": "replace", "body": "new body"},
        )
        _apply_body_write(gh, _make_agent_def(), _make_work_item(42), step_result)
        gh.update_body.assert_called_once_with(42, "new body", title=None)

    def test_replace_unresolvable_target_skips(self):
        gh = MagicMock()
        step_result = StepResult(
            outcome="review", summary="ok",
            body_write={"target": "issue", "mode": "replace", "body": "new body"},
        )
        _apply_body_write(gh, _make_agent_def(), _make_work_item(42, "pr"), step_result)
        gh.update_body.assert_not_called()

    def test_patch_succeeds_first_attempt(self):
        gh = MagicMock()
        gh.get_body.side_effect = ["prose\n", "prose\n\n" + orch._TODOS_HEADING]  # pre-write, post-write verify
        step_result = StepResult(
            outcome="complete", summary="ok",
            body_write={"target": "pr", "mode": "patch", "subsection": "build-plan", "content": "- [x] done"},
        )
        # Patch this test's verify check to succeed by controlling get_body's
        # second call to actually contain the expected fragment.
        start, end = _todos_subsection_markers("build-plan")
        expected_fragment = f"{start}\n- [x] done\n{end}"
        gh.get_body.side_effect = ["prose\n", f"prose\n\n{expected_fragment}\n"]
        _apply_body_write(gh, _make_agent_def("03_execute/coder"), _make_work_item(9, "pr"), step_result)
        assert gh.update_body.call_count == 1

    def test_patch_refusal_never_writes(self):
        gh = MagicMock()
        existing, _ = _apply_todos_patch("prose\n", "build-plan", "- [x] done item")
        gh.get_body.return_value = existing
        step_result = StepResult(
            outcome="complete", summary="ok",
            body_write={"target": "issue", "mode": "patch", "subsection": "build-plan", "content": "- [ ] different"},
        )
        _apply_body_write(gh, _make_agent_def("03_execute/coder"), _make_work_item(9), step_result)
        gh.update_body.assert_not_called()

    def test_patch_retries_on_verified_conflict_then_succeeds(self):
        gh = MagicMock()
        start, end = _todos_subsection_markers("build-plan")
        expected_fragment = f"{start}\n- [x] done\n{end}"
        # Attempt 1: read -> patch -> write -> verify read shows a DIFFERENT
        # body (someone else's concurrent write raced in) -> retry.
        # Attempt 2: read -> patch -> write -> verify read shows our content.
        gh.get_body.side_effect = [
            "prose\n",                                   # attempt 1: pre-write read
            "prose\n\nsomeone else's content\n",          # attempt 1: verify (mismatch -> retry)
            "prose\n",                                    # attempt 2: pre-write read
            f"prose\n\n{expected_fragment}\n",             # attempt 2: verify (match -> success)
        ]
        step_result = StepResult(
            outcome="complete", summary="ok",
            body_write={"target": "issue", "mode": "patch", "subsection": "build-plan", "content": "- [x] done"},
        )
        _apply_body_write(gh, _make_agent_def("03_execute/coder"), _make_work_item(9), step_result)
        assert gh.update_body.call_count == 2

    def test_patch_gives_up_after_max_attempts(self):
        gh = MagicMock()
        # Every verify read shows a mismatch -- conflict never resolves.
        gh.get_body.return_value = "prose\n\nsomeone else's content\n"
        step_result = StepResult(
            outcome="complete", summary="ok",
            body_write={"target": "issue", "mode": "patch", "subsection": "build-plan", "content": "- [x] done"},
        )
        _apply_body_write(gh, _make_agent_def("03_execute/coder"), _make_work_item(9), step_result)
        assert gh.update_body.call_count == orch._BODY_WRITE_MAX_ATTEMPTS

    def test_patch_unresolvable_target_skips(self):
        gh = MagicMock()
        gh.find_pr_by_branch.return_value = None
        gh.find_pr_by_label.return_value = None
        step_result = StepResult(
            outcome="complete", summary="ok",
            body_write={"target": "pr", "mode": "patch", "subsection": "build-plan", "content": "- [x] done"},
        )
        _apply_body_write(gh, _make_agent_def("03_execute/coder"), _make_work_item(9, "issue"), step_result)
        gh.update_body.assert_not_called()
        gh.get_body.assert_not_called()

    def test_get_body_exception_during_patch_does_not_raise(self):
        gh = MagicMock()
        gh.get_body.side_effect = RuntimeError("network blip")
        step_result = StepResult(
            outcome="complete", summary="ok",
            body_write={"target": "issue", "mode": "patch", "subsection": "build-plan", "content": "- [x] done"},
        )
        # Must not raise.
        _apply_body_write(gh, _make_agent_def("03_execute/coder"), _make_work_item(9), step_result)
        gh.update_body.assert_not_called()
