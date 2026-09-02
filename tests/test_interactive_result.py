"""Tests for issue #402's --interactive-result apply mode: /maos-{agent}-i's
second phase reads a person-produced result.json instead of spawning a
subprocess, applies it through the exact same _apply_result pipeline a real
run uses, records performed_by=human in the audit trail, and skips the
commit_after pre-dispatch branch checkout (which would otherwise fetch and
hard-reset onto origin, discarding the person's own uncommitted edits).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pipeline_orchestrator as orch
from pipeline_orchestrator import (
    AgentDef, WorkItem,
    _compute_agent_session_id, _scratch_path,
    _run_agent, _apply_result, _emit_terminal_audit,
    AgentRunResult,
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


def _make_work_item(number: int = 777, kind: str = "issue") -> WorkItem:
    return WorkItem(
        number=number, kind=kind, title="Test", labels=set(),
        url=f"https://github.com/test/repo/{kind}s/{number}",
    )


def _scratch_for(agent_def, work_item, repo="test/repo") -> Path:
    session_id = _compute_agent_session_id(agent_def, work_item, repo)
    return Path(_scratch_path(session_id))


@pytest.fixture(autouse=True)
def _no_stray_audit_output(monkeypatch, capsys):
    """Keep audit JSON lines out of captured stdout across every test here."""
    monkeypatch.setattr(orch, "_emit_audit_event", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# _run_agent(interactive_result=True): reads the file, never spawns
# ---------------------------------------------------------------------------

class TestRunAgentInteractiveResultDispatch:
    def _run(self, monkeypatch, agent_def, work_item, *, refuse_subprocess=True):
        gh = MagicMock()
        monkeypatch.setattr(orch, "_acquire_wip_and_announce", lambda *a, **k: None)
        if refuse_subprocess:
            def _boom(*a, **k):
                raise AssertionError("a real subprocess must not be spawned under interactive_result")
            monkeypatch.setattr(orch, "invoke_agent", _boom)
        return _run_agent(
            agent_def, work_item, dry_run=False, repo="test/repo", labels=set(),
            session_id="sess", default_extra_tools=None, concurrency=None,
            gh=gh, pipeline_map={}, interactive_result=True,
        )

    def test_reads_a_valid_result_file_without_spawning_a_subprocess(self, monkeypatch):
        agent_def = _make_agent_def(commit_after=False)
        work_item = _make_work_item()
        scratch = _scratch_for(agent_def, work_item)
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "result.json").write_text(json.dumps({
            "outcome": "complete", "summary": "did the work", "output": "artefact body",
        }))
        try:
            (result, sentinel_status, sentinel_message, pre_branch,
             invoked_at, attempt, exhausted, step_result) = self._run(
                monkeypatch, agent_def, work_item,
            )
            assert result.success is True
            assert sentinel_status == "complete"
            assert step_result is not None
            assert step_result.summary == "did the work"
            assert exhausted is False
            assert pre_branch == ""  # no branch checkout attempted
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_missing_result_file_resolves_as_no_step_result_not_a_crash(self, monkeypatch):
        """Missing/invalid result.json must fail loud via _apply_result's
        existing 'no valid result file' path (:failed) -- never silently
        treated as success."""
        agent_def = _make_agent_def(commit_after=False)
        work_item = _make_work_item(number=778)
        scratch = _scratch_for(agent_def, work_item)
        shutil.rmtree(scratch, ignore_errors=True)  # ensure absent
        (result, sentinel_status, sentinel_message, pre_branch,
         invoked_at, attempt, exhausted, step_result) = self._run(
            monkeypatch, agent_def, work_item,
        )
        assert step_result is None
        assert sentinel_status is None
        assert result.success is False

    def test_invalid_result_file_also_resolves_as_no_step_result(self, monkeypatch):
        agent_def = _make_agent_def(commit_after=False)
        work_item = _make_work_item(number=779)
        scratch = _scratch_for(agent_def, work_item)
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "result.json").write_text("{not valid json")
        try:
            (result, sentinel_status, sentinel_message, pre_branch,
             invoked_at, attempt, exhausted, step_result) = self._run(
                monkeypatch, agent_def, work_item,
            )
            assert step_result is None
            assert result.success is False
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# commit_after checkout is skipped under interactive_result (safety)
# ---------------------------------------------------------------------------

class TestCommitAfterCheckoutSkippedUnderInteractiveResult:
    def test_no_git_subprocess_calls_for_a_commit_after_agent(self, monkeypatch):
        """The pre-dispatch branch checkout (git fetch + checkout -B onto
        origin) must not run here -- it would hard-reset onto origin's copy
        of the branch, discarding a person's own uncommitted edits made
        directly in their session before this apply step runs."""
        agent_def = _make_agent_def(name="03_execute/coder", commit_after=True)
        work_item = _make_work_item(number=780, kind="issue")
        scratch = _scratch_for(agent_def, work_item)
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "result.json").write_text(json.dumps({
            "outcome": "complete", "summary": "ok",
        }))

        def _boom_subprocess(*a, **k):
            raise AssertionError("no subprocess.run call is expected under interactive_result")

        try:
            gh = MagicMock()
            monkeypatch.setattr(orch, "_acquire_wip_and_announce", lambda *a, **k: None)
            monkeypatch.setattr(orch.subprocess, "run", _boom_subprocess)
            result, sentinel_status, *_rest = _run_agent(
                agent_def, work_item, dry_run=False, repo="test/repo", labels=set(),
                session_id="sess", default_extra_tools=None, concurrency=None,
                gh=gh, pipeline_map={}, interactive_result=True,
            )
            assert sentinel_status == "complete"
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_real_spawn_path_is_unaffected_still_checks_out(self, monkeypatch):
        """Guard the guard: interactive_result=False (the default, a real
        subprocess spawn) must still attempt the branch checkout -- this test
        fails if the interactive_result skip is accidentally made the default
        for every commit_after agent."""
        agent_def = _make_agent_def(name="03_execute/coder", commit_after=True)
        work_item = _make_work_item(number=781, kind="issue")

        checkout_attempted = []

        def _record_subprocess(cmd, *a, **k):
            checkout_attempted.append(cmd)
            raise RuntimeError("stop here -- we only care whether checkout was attempted")

        gh = MagicMock()
        monkeypatch.setattr(orch, "_acquire_wip_and_announce", lambda *a, **k: None)
        monkeypatch.setattr(orch.subprocess, "run", _record_subprocess)
        # invoke_agent path would run next; not reached because the checkout
        # itself raises first, which _run_agent catches and logs (see its
        # try/except around the checkout).
        _run_agent(
            agent_def, work_item, dry_run=False, repo="test/repo", labels=set(),
            session_id="sess", default_extra_tools=None, concurrency=None,
            gh=gh, pipeline_map={}, interactive_result=False,
        )
        assert checkout_attempted, "real spawn path must still attempt the commit_after checkout"


# ---------------------------------------------------------------------------
# performed_by attribution reaches the audit event
# ---------------------------------------------------------------------------

class TestPerformedByAttribution:
    def test_interactive_apply_records_performed_by_human(self, monkeypatch):
        events = []
        monkeypatch.setattr(orch, "_emit_audit_event", lambda e: events.append(e))
        _emit_terminal_audit(
            _make_agent_def(), _make_work_item(), orch.STATUS_COMPLETE,
            invoked_at=0.0, session_id="sess", repo="test/repo",
            performed_by="human",
        )
        assert events, "an audit event must be emitted"
        assert "performed_by=human" in events[0]["detail"]

    def test_default_attribution_is_agent(self, monkeypatch):
        events = []
        monkeypatch.setattr(orch, "_emit_audit_event", lambda e: events.append(e))
        _emit_terminal_audit(
            _make_agent_def(), _make_work_item(), orch.STATUS_COMPLETE,
            invoked_at=0.0, session_id="sess", repo="test/repo",
        )
        assert "performed_by=agent" in events[0]["detail"]
