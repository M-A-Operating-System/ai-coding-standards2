"""Whether a step resumes is declared, not an accident of the filesystem.

PRODUCT.md, "What a step is told, and what it must not remember":

  Resuming is an optimisation, never a source of truth. [...] a step that
  answers from what it concluded on a previous invocation has failed --
  however plausible the answer, and however certain it sounds.

Issue #450: `merge-conflict`'s session id was a deterministic function of
(agent, work item) alone, so every invocation for an issue resumed the same
conversation however much had changed underneath it. Re-invoked for a second
commit, it replied in one turn with no tool calls, repeating its earlier
"no conflicts" conclusion about a different commit. Both retry slots resumed
equally stale sessions, so clearing the failed label and re-running could
only ever reproduce it.

The resume decision was `os.path.isfile(...)` -- whichever transcripts
happened to be on disk. It is now the step's own declaration, and a step
that re-derives everything it needs declares it away.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

from pipeline_orchestrator import load_pipeline  # noqa: E402

PIPELINE_JSON = Path(__file__).parent.parent / "pipeline" / "pipeline.json"
SCHEMA_JSON = (
    Path(__file__).parent.parent / "pipeline" / "schemas" / "pipeline.schema.json"
)


def _steps() -> dict:
    pipeline = json.loads(PIPELINE_JSON.read_text())
    return {
        step["agent"]: step
        for flow in pipeline["flows"].values()
        for step in flow.get("steps", [])
        if step.get("agent")
    }


def _loaded() -> dict:
    """load_pipeline returns (agents, default_extra_tools); these tests ask
    about individual steps, so key the agents by name."""
    agents, _ = load_pipeline(PIPELINE_JSON)
    return {a.agent: a for a in agents}


class TestTheDeclarationExists:
    def test_schema_declares_session_resume(self):
        schema = json.loads(SCHEMA_JSON.read_text())
        found = json.dumps(schema)
        assert '"resume"' in found, (
            "session.resume must be declarable in pipeline.json, or a step has "
            "no way to say it carries nothing worth resuming"
        )

    def test_resume_defaults_to_true_when_undeclared(self):
        """Silence keeps today's behaviour. Flipping the default belongs with
        telling a step its material rather than having it fetch it -- until
        then, fresh sessions would remove a cache benefit whose replacement
        does not exist yet."""
        loaded = _loaded()
        undeclared = [
            a for a in loaded.values()
            if "resume" not in (_steps().get(a.agent, {}).get("session") or {})
        ]
        assert undeclared, "expected at least one step to leave resume undeclared"
        for agent_def in undeclared:
            assert agent_def.session_resume is True, (
                f"{agent_def.agent} left session.resume undeclared and did not "
                "default to today's behaviour"
            )


class TestTheStepThatCarriesNothing:
    def test_merge_conflict_declares_no_resume(self):
        """It re-derives mergeable_state from the API on every run, so a
        resumed conversation can only supply a conclusion about a commit that
        is no longer the one being asked about (issue #450)."""
        loaded = _loaded()
        merge_conflict = loaded["03_execute/merge-conflict"]
        assert merge_conflict.session_resume is False

    def test_the_declaration_survives_loading(self):
        """A declared false that the loader drops would fail silently -- the
        step would resume exactly as before and nothing would say so."""
        loaded = _loaded()
        declared = {
            name: (step.get("session") or {}).get("resume")
            for name, step in _steps().items()
            if "resume" in (step.get("session") or {})
        }
        assert declared, "no step declares session.resume"
        for name, value in declared.items():
            assert loaded[name].session_resume is value, (
                f"{name} declares resume={value} but loaded as "
                f"{loaded[name].session_resume}"
            )


class TestScopeAndResumeAreSeparateQuestions:
    """`scope` says which conversation a step would use; `resume` says whether
    it continues one at all. Conflating them is what made "per_issue" imply
    "carries its conclusions forward"."""

    @pytest.mark.parametrize("agent", ["03_execute/merge-conflict"])
    def test_a_step_can_keep_its_scope_and_still_not_resume(self, agent):
        loaded = _loaded()
        assert loaded[agent].session_scope == "per_issue"
        assert loaded[agent].session_resume is False
