"""Tests for the repository's own pipeline definition and sub-item units.

Two capabilities that make a flow a first-class object:

  - a consuming repository's own pipeline/pipeline.json replaces the shipped
    definition in full -- precedence is per file, not per flow (PRODUCT.md,
    AS-1): presence means the repository's file decides everything, absence
    means the shipped default decides everything, and there is nothing to
    merge;
  - a step can declare it finishes its own work in pieces (unit: sub_item),
    staying eligible while its own children are open and being told which
    piece each invocation is for.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import json
from unittest.mock import MagicMock, patch

import pytest
import pipeline_orchestrator as orch
from pipeline_orchestrator import (
    AgentDef, WorkItem,
    repo_pipeline_override_path,
    load_pipeline,
    pipeline_by_name,
    _should_run,
    _invalidate_children_cache,
    STATUS_COMPLETE,
)


def _shipped(tmp_path, flows=None):
    """A minimal shipped pipeline file inside the framework tree."""
    data = {
        "budgets": {"max_turns": 30, "max_wall_seconds": 1800},
        "defaults": {"extra_allowedTools": ["Read"]},
        "flows": flows if flows is not None else {
            "standard-delivery": {
                "description": "shipped delivery",
                "trigger": {"kind": "issue"},
                "naming": {"branch": "issue-{number}"},
                "steps": [{
                    "agent": "01_product_docs/prd-writer",
                    "phase": "01_product_docs",
                    "trigger": {"event": "issue.opened"},
                    "dependencies": [],
                    "human_gate_after": False,
                    "expected_effect": {"commits": False},
                    "description": "shipped prd-writer",
                }],
            },
            "blocker": {
                "description": "shipped blocker",
                "trigger": {"kind": "issue"},
                "steps": [{
                    "agent": "00_ondemand/blocker",
                    "phase": "00_ondemand",
                    "type": "script",
                    "script": ".github/scripts/blocker.sh",
                    "trigger": {"label": "blocker:requested"},
                    "dependencies": [],
                    "human_gate_after": False,
                    "expected_effect": {"commits": False},
                    "description": "shipped blocker step",
                }],
            },
        },
    }
    path = tmp_path / "pipeline" / "pipeline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def _override(root, flows, budgets=None, defaults=None):
    """A consuming repository's own pipeline definition.

    Complete by construction, not a fragment: under AS-1 the repository's
    file is a whole pipeline definition validating against the identical
    schema, so the helper writes budgets alongside the flows.
    """
    data = {
        "budgets": budgets if budgets is not None else {"max_turns": 7, "max_wall_seconds": 900},
        "flows": flows,
    }
    if defaults is not None:
        data["defaults"] = defaults
    path = root / "pipeline" / "pipeline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------------------
# repo_pipeline_override_path: where a consuming repo's own file lives
# ---------------------------------------------------------------------------

class TestOverrideLookup:
    def test_none_without_ai_agile_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AI_AGILE_ROOT", raising=False)
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", tmp_path)
        assert repo_pipeline_override_path(_shipped(tmp_path)) is None

    def test_none_when_the_consuming_repo_has_no_file(self, tmp_path, monkeypatch):
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        submodule = tmp_path / "consuming" / "vendor" / "ai-coding-standards2"
        submodule.mkdir(parents=True)
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", submodule)
        monkeypatch.setenv("AI_AGILE_ROOT", str(consuming))
        assert repo_pipeline_override_path(_shipped(submodule)) is None

    def test_finds_the_consuming_repos_own_file_outside_the_submodule(self, tmp_path, monkeypatch):
        consuming = tmp_path / "consuming"
        submodule = consuming / "vendor" / "ai-coding-standards2"
        submodule.mkdir(parents=True)
        shipped = _shipped(submodule)
        override = _override(consuming, {})
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", submodule)
        monkeypatch.setenv("AI_AGILE_ROOT", str(consuming))
        assert repo_pipeline_override_path(shipped) == override

    def test_source_mode_never_treats_the_shipped_file_as_its_own_override(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        root.mkdir()
        shipped = _shipped(root)
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", root)
        monkeypatch.setenv("AI_AGILE_ROOT", str(root))
        assert repo_pipeline_override_path(shipped) is None


# ---------------------------------------------------------------------------
# load_pipeline: whole-file replacement end to end (PRODUCT.md, AS-1)
#
# "There is no partial override and nothing to merge: presence means the
# repository's file decides everything, absence means the shipped default
# decides everything."
# ---------------------------------------------------------------------------

_OUR_DELIVERY_FLOW = {
    "description": "our own delivery",
    "trigger": {"kind": "issue"},
    "naming": {"branch": "work/{number}"},
    "steps": [{
        "agent": "03_execute/coder",
        "phase": "03_execute",
        "trigger": {"event": "issue.opened"},
        "dependencies": [],
        "human_gate_after": False,
        "expected_effect": {"commits": True},
        "git_ops": {"commit_after": True},
        "description": "our coder",
    }],
}


class TestLoadPipelineReplacement:
    @pytest.fixture(autouse=True)
    def _restore_budget_globals(self, monkeypatch):
        """load_pipeline sets the budget globals; keep that out of other tests."""
        for name in ("DEFAULT_MAX_TURNS", "AGENT_TIMEOUT_SECONDS", "MAX_LAUNCHES_PER_TICK"):
            monkeypatch.setattr(orch, name, getattr(orch, name))

    def _setup(self, tmp_path, monkeypatch, override_flows=None, override_raw=None,
               override_budgets=None, override_defaults=None):
        consuming = tmp_path / "consuming"
        submodule = consuming / "vendor" / "ai-coding-standards2"
        submodule.mkdir(parents=True)
        shipped = _shipped(submodule)
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", submodule)
        monkeypatch.setenv("AI_AGILE_ROOT", str(consuming))
        if override_raw is not None:
            path = consuming / "pipeline" / "pipeline.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(override_raw))
        elif override_flows is not None:
            _override(consuming, override_flows,
                      budgets=override_budgets, defaults=override_defaults)
        return shipped

    def test_no_override_loads_the_shipped_file_alone(self, tmp_path, monkeypatch):
        """Absence means the shipped default decides everything."""
        shipped = self._setup(tmp_path, monkeypatch)
        agents, _ = load_pipeline(shipped)
        assert [a.agent for a in agents] == [
            "01_product_docs/prd-writer", "00_ondemand/blocker",
        ]
        assert [a.flow for a in agents] == ["standard-delivery", "blocker"]

    def test_the_repository_file_decides_everything_when_present(self, tmp_path, monkeypatch):
        """Presence means the repository's file decides everything.

        Its `standard-delivery` replaces the shipped one, and -- the point of
        whole-file replacement -- the shipped `blocker` flow, which the
        repository's file does not mention at all, does not come along.
        """
        shipped = self._setup(tmp_path, monkeypatch,
                              override_flows={"standard-delivery": _OUR_DELIVERY_FLOW})
        agents, _ = load_pipeline(shipped)
        by_name = pipeline_by_name(agents)
        assert set(by_name) == {"03_execute/coder"}
        assert by_name["03_execute/coder"].flow_naming["branch"] == "work/{number}"
        # Nothing from the shipped file leaks through, not even a flow the
        # repository's file never names.
        assert "01_product_docs/prd-writer" not in by_name
        assert "00_ondemand/blocker" not in by_name
        assert {a.flow for a in agents} == {"standard-delivery"}

    def test_budgets_come_from_the_repository_file_not_the_shipped_one(self, tmp_path, monkeypatch):
        """Budgets are part of the same file, so they are replaced with it."""
        shipped = self._setup(
            tmp_path, monkeypatch,
            override_flows={"standard-delivery": _OUR_DELIVERY_FLOW},
            override_budgets={"max_turns": 7, "max_wall_seconds": 900},
        )
        load_pipeline(shipped)
        assert orch.DEFAULT_MAX_TURNS == 7
        assert orch.AGENT_TIMEOUT_SECONDS == 900

    def test_shipped_defaults_do_not_leak_into_a_repository_file(self, tmp_path, monkeypatch):
        """The shipped `defaults.extra_allowedTools` is not merged in.

        The shipped file grants `Read`; a repository file that declares no
        defaults at all gets none, rather than inheriting the shipped grant --
        a permission is exactly what must not survive a replacement silently.
        """
        shipped = self._setup(tmp_path, monkeypatch,
                              override_flows={"standard-delivery": _OUR_DELIVERY_FLOW})
        _, default_extra_tools = load_pipeline(shipped)
        assert default_extra_tools == []

    def test_a_repository_file_the_schema_rejects_fails_loud(self, tmp_path, monkeypatch):
        """STD-ARCH-014: a broken repository definition stops the run.

        It is validated against the schema on its own, not as a composed
        result -- so a file that declares no budgets is rejected too, since a
        complete definition is what the schema describes.
        """
        shipped = self._setup(tmp_path, monkeypatch, override_raw={
            "flows": {"standard-delivery": {"description": "missing trigger and steps"}},
        })
        with pytest.raises(SystemExit) as exc:
            load_pipeline(shipped)
        assert exc.value.code == 1

    def test_a_repository_file_missing_budgets_is_not_rescued_by_the_shipped_one(
        self, tmp_path, monkeypatch
    ):
        """No composition means no rescue: an incomplete file is just invalid."""
        shipped = self._setup(tmp_path, monkeypatch, override_raw={
            "flows": {"standard-delivery": _OUR_DELIVERY_FLOW},
        })
        with pytest.raises(SystemExit) as exc:
            load_pipeline(shipped)
        assert exc.value.code == 1

    def test_the_override_is_never_silently_ignored(self, tmp_path, monkeypatch, caplog):
        shipped = self._setup(tmp_path, monkeypatch, override_flows={
            "blocker": {
                "description": "our own blocker",
                "trigger": {"kind": "issue"},
                "steps": [{
                    "agent": "00_ondemand/blocker",
                    "phase": "00_ondemand",
                    "type": "script",
                    "script": ".github/scripts/blocker.sh",
                    "trigger": {"label": "blocker:requested"},
                    "dependencies": [],
                    "human_gate_after": False,
                    "expected_effect": {"commits": False},
                    "description": "ours",
                }],
            },
        })
        import logging
        with caplog.at_level(logging.INFO, logger="orchestrator"):
            load_pipeline(shipped)
        assert any("using repository definition" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# unit: sub_item -- a step that finishes its own work in pieces
# ---------------------------------------------------------------------------

def _sub_item_step(**overrides):
    kwargs = dict(
        agent="03_execute/coder",
        phase="03_execute",
        objects=["issue"],
        trigger={"label": "create-pr:complete", "children": "any_open"},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="a step that finishes its work one child at a time",
        unit="sub_item",
        flow="standard-delivery",
        flow_naming={"branch": "issue-{number}"},
        commit_after=True,
        expected_effect={"commits": True},
    )
    kwargs.update(overrides)
    return AgentDef(**kwargs)


def _parent(labels=("create-pr:complete",), number=500):
    return WorkItem(
        number=number, kind="issue", title="Super issue",
        labels=set(labels), url=f"https://github.com/test/repo/issues/{number}",
    )


def _gh_with_children(children):
    gh = MagicMock()
    gh.repo = "org/repo"
    gh._get.return_value = list(children)
    return gh


class TestSubItemEligibility:
    def setup_method(self):
        _invalidate_children_cache()

    def test_eligible_while_a_child_is_open(self):
        step = _sub_item_step()
        item = _parent()
        gh = _gh_with_children([
            {"number": 501, "state": "closed"}, {"number": 502, "state": "open"},
        ])
        assert _should_run(step, item, item.labels, {}, None, gh=gh, repo="org/repo") is True

    def test_not_eligible_once_every_child_is_closed(self):
        step = _sub_item_step()
        item = _parent()
        gh = _gh_with_children([{"number": 501, "state": "closed"}])
        assert _should_run(step, item, item.labels, {}, None, gh=gh, repo="org/repo") is False

    def test_not_eligible_with_no_children_at_all(self):
        step = _sub_item_step()
        item = _parent()
        gh = _gh_with_children([])
        assert _should_run(step, item, item.labels, {}, None, gh=gh, repo="org/repo") is False

    def test_stays_eligible_after_completing_one_piece(self):
        """A completed sub_item step is done with ONE piece, not with the item."""
        step = _sub_item_step()
        item = _parent(labels=("create-pr:complete", "coder:complete"))
        gh = _gh_with_children([
            {"number": 501, "state": "closed"}, {"number": 502, "state": "open"},
        ])
        assert _should_run(step, item, item.labels, {}, None, gh=gh, repo="org/repo") is True

    def test_a_complete_item_unit_step_stays_done(self):
        """The re-eligibility is unit: sub_item's alone -- item steps are unaffected."""
        step = _sub_item_step(unit="item", trigger={"label": "create-pr:complete"})
        item = _parent(labels=("create-pr:complete", "coder:complete"))
        gh = _gh_with_children([{"number": 502, "state": "open"}])
        assert _should_run(step, item, item.labels, {}, None, gh=gh, repo="org/repo") is False

    def test_done_once_the_last_child_closes(self):
        step = _sub_item_step()
        item = _parent(labels=("create-pr:complete", "coder:complete"))
        gh = _gh_with_children([
            {"number": 501, "state": "closed"}, {"number": 502, "state": "closed"},
        ])
        assert _should_run(step, item, item.labels, {}, None, gh=gh, repo="org/repo") is False


class TestSubItemSelectionAndEnv:
    def setup_method(self):
        _invalidate_children_cache()

    def test_the_step_is_told_which_piece_this_invocation_is_for(self):
        env = orch._flow_context_env(
            _sub_item_step(), _parent(), sub_item_number=502,
            children=[{"number": 501, "state": "closed"}, {"number": 502, "state": "open"}],
        )
        assert env["SUB_ITEM_NUMBER"] == "502"
        assert env["AI_AGILE_CHILDREN_OPEN"] == "1"
        assert env["AI_AGILE_CHILDREN_TOTAL"] == "2"
        assert env["AI_AGILE_BRANCH"] == "issue-500"

    def test_an_item_unit_step_is_told_no_sub_item(self):
        env = orch._flow_context_env(_sub_item_step(unit="item"), _parent())
        assert "SUB_ITEM_NUMBER" not in env

    def test_the_env_reaches_the_agent_subprocess(self):
        agent_env = orch._build_agent_env(
            {"PATH": "/usr/bin"}, "org/repo", _parent(), "sess", "per_issue",
            flow_env={"SUB_ITEM_NUMBER": "502", "AI_AGILE_FLOW": "standard-delivery"},
        )
        assert agent_env["SUB_ITEM_NUMBER"] == "502"
        assert agent_env["AI_AGILE_FLOW"] == "standard-delivery"

    def test_run_agent_selects_the_lowest_open_child_and_threads_it_through(self, monkeypatch):
        """One piece per invocation, chosen deterministically."""
        step = _sub_item_step()
        item = _parent()
        gh = _gh_with_children([
            {"number": 601, "state": "closed"},
            {"number": 603, "state": "open"},
            {"number": 602, "state": "open"},
        ])
        captured = {}

        def _fake_invoke(agent_def, work_item, dry_run, repo, attempt=0,
                         agent_text_override=None, default_extra_tools=None,
                         cwd=None, flow_env=None):
            captured.update(flow_env or {})
            return orch.AgentRunResult(success=True)

        monkeypatch.setattr(orch, "invoke_agent", _fake_invoke)
        monkeypatch.setattr(orch, "_acquire_wip_and_announce", lambda *a, **k: None)
        monkeypatch.setattr(orch, "_create_run_worktree", lambda branch: "/tmp/wt")
        # The repo-root sweep is a declared lifecycle script now (issue #407),
        # so this test stubs the lifecycle runner instead of a sweep function.
        monkeypatch.setattr(orch, "_run_lifecycle_scripts", lambda *a, **k: None)
        monkeypatch.setattr(orch, "_read_step_result", lambda scratch: (None, "none"))

        orch._run_agent(
            step, item, dry_run=False, repo="org/repo", labels=set(item.labels),
            session_id="", default_extra_tools=None, concurrency=None,
            gh=gh, pipeline_map={},
        )

        assert captured["SUB_ITEM_NUMBER"] == "602"
        assert captured["AI_AGILE_CHILDREN_OPEN"] == "2"

    def test_a_script_step_is_told_the_same_thing(self, monkeypatch, tmp_path):
        script = tmp_path / "s.sh"
        script.write_text("#!/usr/bin/env bash\necho AI_AGILE_STATUS: complete\n")
        step = _sub_item_step(step_type="script", script_path="s.sh", commit_after=False)
        monkeypatch.setattr(orch, "SUBMODULE_ROOT", tmp_path)
        captured = {}
        real_popen = orch.subprocess.Popen

        def _fake_popen(cmd, **kwargs):
            captured.update(kwargs.get("env") or {})
            return real_popen(cmd, **kwargs)

        monkeypatch.setattr(orch.subprocess, "Popen", _fake_popen)
        orch.invoke_script(
            step, _parent(), dry_run=False, repo="org/repo",
            flow_env=orch._flow_context_env(step, _parent(), sub_item_number=502),
        )
        assert captured["SUB_ITEM_NUMBER"] == "502"


class TestSubItemDispatchClearsThePreviousPiece:
    """Re-invoking for the next piece must not leave two status labels."""

    def test_the_previous_complete_label_is_cleared_at_dispatch(self):
        step = _sub_item_step()
        item = _parent(labels=("create-pr:complete", "coder:complete"))
        gh = MagicMock()
        labels = set(item.labels)
        orch._acquire_wip_and_announce(
            step, item, dry_run=False, manual_trigger=False, repo="org/repo",
            labels=labels, concurrency=None, gh=gh, pipeline_map={},
        )
        gh.remove_label.assert_any_call(500, "coder:complete")
        assert "coder:complete" not in labels
        assert "coder:wip" in labels

    def test_an_item_unit_step_keeps_its_labels_untouched(self):
        step = _sub_item_step(unit="item")
        item = _parent(labels=("create-pr:complete", "coder:complete"))
        gh = MagicMock()
        labels = set(item.labels)
        orch._acquire_wip_and_announce(
            step, item, dry_run=False, manual_trigger=False, repo="org/repo",
            labels=labels, concurrency=None, gh=gh, pipeline_map={},
        )
        assert "coder:complete" in labels
