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

Gherkin scenarios (docs/features/pipeline.md):
- stateless step re-checks PR state after commit change
- retry after stale-session failure reaches an unused session
"""
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

from pipeline_orchestrator import load_pipeline, AgentDef, WorkItem  # noqa: E402

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

    def test_pr_reviewer_declares_no_resume(self):
        """It re-reads the PR diff, standards, and ADRs from scratch on every
        invocation, so a resumed conversation can only answer from a prior
        cycle's cached conclusion about a diff that has since changed (issue
        #500, the same failure mode as issue #450)."""
        loaded = _loaded()
        pr_reviewer = loaded["03_execute/pr-reviewer"]
        assert pr_reviewer.session_resume is False

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

    @pytest.mark.parametrize("agent", ["03_execute/merge-conflict", "03_execute/pr-reviewer"])
    def test_a_step_can_keep_its_scope_and_still_not_resume(self, agent):
        loaded = _loaded()
        assert loaded[agent].session_scope == "per_issue"
        assert loaded[agent].session_resume is False


def _make_no_resume_agent() -> AgentDef:
    return AgentDef(
        agent="03_execute/merge-conflict",
        phase="03_execute",
        objects=["issue"],
        trigger={"label": "ci-gate:complete"},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="checks merge conflicts",
        session_scope="per_issue",
        session_resume=False,
    )


def _make_work_item(number: int = 42) -> WorkItem:
    return WorkItem(
        number=number,
        kind="issue",
        title="Test issue",
        labels=set(),
        url=f"https://github.com/test/repo/issues/{number}",
    )


def _fake_popen():
    proc = MagicMock()
    proc.stdout = iter([])
    proc.returncode = 0
    proc.poll.return_value = 0
    proc.wait.return_value = None
    return proc


def _extract_session_uuid(cmd: list) -> str:
    for flag in ("--session-id", "--resume"):
        if flag in cmd:
            idx = cmd.index(flag)
            return cmd[idx + 1]
    raise AssertionError(f"no session flag in cmd: {cmd}")


class TestStatelessStepReChecksPrStateAfterCommitChange:
    """Gherkin: stateless step re-checks PR state after commit change.

    Given merge-conflict has previously been invoked for issue N and produced
    outcome "complete" for commit C1
    When the orchestrator invokes merge-conflict again for issue N with a new head commit C2
    Then the agent calls the GitHub API to check the current mergeable_state and writes
    result.json based on that fresh check, not the prior session's conclusion.

    Mechanism: session.resume=false causes each invocation to get a random UUID via
    uuid4(), so the second invocation cannot resume the first's conversation.
    """

    def test_stateless_step_re_checks_pr_state_after_commit_change(self, monkeypatch):
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        monkeypatch.setattr(orch, "_claude_cli_usable", lambda env: True)

        agent_def = _make_no_resume_agent()
        work_item = _make_work_item(number=438)

        uuids = []

        def fake_popen(cmd, **kwargs):
            uuids.append(_extract_session_uuid(cmd))
            return _fake_popen()

        with patch("subprocess.Popen", side_effect=fake_popen):
            orch.invoke_agent(
                agent_def, work_item,
                dry_run=False, repo="test/repo",
                agent_text_override="---\ntools: []\n---\ntest",
            )
        with patch("subprocess.Popen", side_effect=fake_popen):
            orch.invoke_agent(
                agent_def, work_item,
                dry_run=False, repo="test/repo",
                agent_text_override="---\ntools: []\n---\ntest",
            )

        assert len(uuids) == 2
        assert uuids[0] != uuids[1], (
            "Two invocations of a session.resume=false step must receive "
            "distinct session UUIDs so the second cannot continue the first's "
            "conversation (issue #450)"
        )
        for u in uuids:
            assert len(u) == 36, f"Expected a UUID, got {u!r}"


class TestRetryAfterStaleSessionFailureReachesAnUnusedSession:
    """Gherkin: retry after stale-session failure reaches an unused session.

    Given merge-conflict has failed because a resumed session replied without any fresh API calls
    When the orchestrator re-drives the step for the same issue in a subsequent run
    Then the step uses a session that has not previously concluded for this issue-step combination.

    Mechanism: session.resume=false causes each attempt (including retries) to get a
    random UUID, so no attempt can resume a session used by a previous attempt.
    """

    def test_retry_after_stale_session_failure_reaches_an_unused_session(self, monkeypatch):
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        monkeypatch.setattr(orch, "_claude_cli_usable", lambda env: True)

        agent_def = _make_no_resume_agent()
        work_item = _make_work_item(number=438)

        uuids = []

        def fake_popen(cmd, **kwargs):
            uuids.append(_extract_session_uuid(cmd))
            return _fake_popen()

        for attempt in range(3):
            with patch("subprocess.Popen", side_effect=fake_popen):
                orch.invoke_agent(
                    agent_def, work_item,
                    dry_run=False, repo="test/repo",
                    attempt=attempt,
                    agent_text_override="---\ntools: []\n---\ntest",
                )

        assert len(uuids) == 3
        assert len(set(uuids)) == 3, (
            "Each attempt for a session.resume=false step must receive a distinct "
            "session UUID so retries cannot resume a stale exhausted session (issue #450). "
            f"Got: {uuids}"
        )
        for u in uuids:
            deterministic_seed_0 = str(uuid.uuid5(
                orch._SESSION_NAMESPACE,
                "ais-v1-03-execute-merge-conflict-issue-438",
            ))
            deterministic_seed_1 = str(uuid.uuid5(
                orch._SESSION_NAMESPACE,
                "ais-v1-03-execute-merge-conflict-issue-438-r1",
            ))
            assert u != deterministic_seed_0, (
                f"Attempt UUID {u!r} must not match the deterministic attempt-0 seed"
            )
            assert u != deterministic_seed_1, (
                f"Attempt UUID {u!r} must not match the deterministic attempt-1 seed"
            )
