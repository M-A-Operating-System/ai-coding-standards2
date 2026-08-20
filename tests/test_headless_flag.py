"""Tests for --headless flag, audit actor, axis-B env mode, and resolve-only path.

Covers all 8 Gherkin scenarios in docs/features/orchestrator.md that were
introduced with issue #316.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import pipeline_orchestrator
from pipeline_orchestrator import (
    _make_audit_event,
    _run_print_prompt,
    PRINT_PROMPT_ENV_KEYS,
    _build_agent_env,
    _resolve_agent_invocation,
    BASE_AGENT_TOOLS,
    WorkItem,
    AgentDef,
)


def _make_args(**kwargs):
    args = MagicMock()
    args.clear_pause = False
    args.clear_stop = False
    args.repo = "test/repo"
    args.verbose = False
    args.dry_run = False
    args.issue = None
    args.pipeline = Path("pipeline/pipeline.json")
    args.headless = False
    args.print_prompt = False
    args.agent = None
    args.kind = None
    for k, v in kwargs.items():
        setattr(args, k, v)
    return args


def _make_work_item(number=1, kind="issue"):
    return WorkItem(
        number=number,
        kind=kind,
        title="Test issue",
        labels=set(),
        url=f"https://github.com/test/repo/{kind}s/{number}",
    )


def _make_agent_def(agent="test/agent", extra_tools=None):
    return AgentDef(
        agent=agent,
        phase="03_execute",
        objects=[],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="",
        extra_allowedTools=extra_tools or [],
    )


# ---------------------------------------------------------------------------
# TestAuditActorHeadless
# ---------------------------------------------------------------------------

class TestAuditActorHeadless:
    """Audit trail actor fields vary with --headless."""

    def test_scheduled_tick_audit_trail_correctly_identifies_itself_as_unattended(
        self, monkeypatch
    ):
        """Given --headless, actor.id is 'github-actions' and actor.human is None."""
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)
        event = _make_audit_event("session-1", "system.tick", "test/repo")
        assert event["actor"]["id"] == "github-actions"
        assert event["actor"]["human"] is None

    def test_a_human_triggered_ticks_audit_trail_correctly_identifies_a_human_trigger(
        self, monkeypatch
    ):
        """Without --headless, actor.id is 'interactive' and actor.human is True."""
        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", False)
        event = _make_audit_event("session-1", "system.tick", "test/repo")
        assert event["actor"]["id"] == "interactive"
        assert event["actor"]["human"] is True


# ---------------------------------------------------------------------------
# TestAxisBHeadlessEnv
# ---------------------------------------------------------------------------

class TestAxisBHeadlessEnv:
    """AI_AGILE_EXECUTION_MODE is always 'headless' for orchestrator-spawned subprocesses."""

    def test_an_orchestrator_spawned_agent_subprocess_is_always_axis_b_headless_regardless_of_trigger(
        self, monkeypatch
    ):
        """_build_agent_env sets AI_AGILE_EXECUTION_MODE='headless' in both headless and
        interactive ticks, so agent subprocesses are never influenced by the trigger mode."""
        wi = _make_work_item()
        base = {"GITHUB_TOKEN": "tok", "ANTHROPIC_API_KEY": "key"}

        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", True)
        env_when_headless = _build_agent_env(base, "test/repo", wi, "session-A", "per_issue")
        assert env_when_headless["AI_AGILE_EXECUTION_MODE"] == "headless", (
            "AI_AGILE_EXECUTION_MODE must be 'headless' when orchestrator ran with --headless"
        )

        monkeypatch.setattr(pipeline_orchestrator, "_HEADLESS", False)
        env_when_interactive = _build_agent_env(base, "test/repo", wi, "session-B", "per_issue")
        assert env_when_interactive["AI_AGILE_EXECUTION_MODE"] == "headless", (
            "AI_AGILE_EXECUTION_MODE must still be 'headless' when orchestrator ran without --headless"
        )


# ---------------------------------------------------------------------------
# TestStopMarkerHeadlessGating
# ---------------------------------------------------------------------------

class TestStopMarkerHeadlessGating:
    """.pipeline-stop gating on --headless."""

    def test_pipeline_stop_halts_the_scheduled_headless_path(self, tmp_path, monkeypatch):
        """Given --headless and .pipeline-stop, main() must not load the pipeline."""
        marker = tmp_path / ".pipeline-stop"
        marker.write_text(json.dumps({
            "stopped_at": "2026-01-01T00:00:00Z",
            "reason": "test stop",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker)

        loaded = []

        def fake_load(path):
            loaded.append(True)
            return [], []

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=_make_args(headless=True)), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused",
                          return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load), \
             patch.object(pipeline_orchestrator, "_emit_audit_event"), \
             patch.object(pipeline_orchestrator, "GitHubClient"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert not loaded, "load_pipeline must not be called when headless and stop marker is set"

    def test_pipeline_stop_does_not_block_an_interactive_tick(self, tmp_path, monkeypatch):
        """Given .pipeline-stop but no --headless, main() proceeds to load the pipeline."""
        marker = tmp_path / ".pipeline-stop"
        marker.write_text(json.dumps({
            "stopped_at": "2026-01-01T00:00:00Z",
            "reason": "test stop",
            "stopped_by": "github-actions",
        }))
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", marker)

        loaded = []

        def fake_load(path):
            loaded.append(True)
            return [], []

        gh_mock = MagicMock()
        gh_mock.list_open_issues.return_value = []

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=_make_args(headless=False)), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused",
                          return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load), \
             patch.object(pipeline_orchestrator, "_emit_audit_event"), \
             patch.object(pipeline_orchestrator, "GitHubClient", return_value=gh_mock), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert loaded, "load_pipeline must be called for interactive runs even with stop marker"

    def test_a_human_triggered_tick_still_performs_real_work(self, tmp_path, monkeypatch):
        """Without --headless and no stop marker, main() evaluates the pipeline normally."""
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")

        loaded = []

        def fake_load(path):
            loaded.append(True)
            return [], []

        gh_mock = MagicMock()
        gh_mock.list_open_issues.return_value = []

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=_make_args(headless=False)), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused",
                          return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "load_pipeline", side_effect=fake_load), \
             patch.object(pipeline_orchestrator, "_emit_audit_event"), \
             patch.object(pipeline_orchestrator, "GitHubClient", return_value=gh_mock), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert loaded, "load_pipeline must be called when orchestrator runs without --headless"


# ---------------------------------------------------------------------------
# TestResolveAgentInvocation
# ---------------------------------------------------------------------------

class TestResolveAgentInvocation:
    """/run-agent obtains tool allowlist from orchestrator, not hand-parsing."""

    def test_run_agent_obtains_its_tool_allowlist_from_the_orchestrator_instead_of_hand_parsing_frontmatter(self):
        """_resolve_agent_invocation is the authoritative source for allowed_tools,
        and includes all BASE_AGENT_TOOLS plus any extra tools from the agent definition."""
        wi = _make_work_item()
        agent_text = "---\nextra_allowedTools:\n  - Write\n---\nDo some work.\n"
        agent_def = _make_agent_def(extra_tools=["Write"])

        resolved = _resolve_agent_invocation(
            agent_def, wi, "test/repo",
            agent_text_override=agent_text,
        )

        assert resolved is not None
        for tool in BASE_AGENT_TOOLS:
            assert tool in resolved.allowed_tools, f"BASE_AGENT_TOOLS entry missing: {tool}"
        assert "Write" in resolved.allowed_tools, "Extra tool from agent def must appear in allowlist"

    def test_resolve_returns_none_for_missing_agent_file(self):
        """_resolve_agent_invocation returns None (not an exception) for a missing agent file."""
        wi = _make_work_item()
        agent_def = _make_agent_def(agent="nonexistent/agent-xyz-does-not-exist")

        resolved = _resolve_agent_invocation(agent_def, wi, "test/repo")

        assert resolved is None, "Must return None for a missing agent file, not raise"


# ---------------------------------------------------------------------------
# TestResolveOnlyMode
# ---------------------------------------------------------------------------

class TestResolveOnlyMode:
    """Resolve-only mode (--print-prompt) must mutate no GitHub state."""

    def test_resolve_only_mode_mutates_no_github_state(self, tmp_path, monkeypatch):
        """When --print-prompt is set, _run_print_prompt runs and no GitHub writes occur."""
        monkeypatch.setattr(pipeline_orchestrator, "STOP_MARKER_PATH", tmp_path / ".pipeline-stop")

        print_prompt_called = []
        gh_write_calls = []

        def fake_print_prompt(args):
            print_prompt_called.append(True)

        gh_mock = MagicMock()
        gh_mock.add_label.side_effect = lambda *a, **kw: gh_write_calls.append(("add_label", a))
        gh_mock.remove_label.side_effect = lambda *a, **kw: gh_write_calls.append(("remove_label", a))
        gh_mock.post_comment.side_effect = lambda *a, **kw: gh_write_calls.append(("post_comment", a))

        with patch.object(pipeline_orchestrator, "parse_args",
                          return_value=_make_args(
                              print_prompt=True, headless=False,
                              agent="03_execute/coder", issue=1,
                          )), \
             patch.object(pipeline_orchestrator, "is_pipeline_paused",
                          return_value=(False, None, None)), \
             patch.object(pipeline_orchestrator, "_run_print_prompt",
                          side_effect=fake_print_prompt), \
             patch.object(pipeline_orchestrator, "GitHubClient", return_value=gh_mock), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
            pipeline_orchestrator.main()

        assert print_prompt_called, "_run_print_prompt must be called when --print-prompt is set"
        assert not gh_write_calls, (
            f"No GitHub write calls expected in resolve-only mode; got {gh_write_calls}"
        )


class TestResolveOnlyModeExportsOnlyNamedEnvKeys:
    """Resolve-only output is captured into an interactive session's transcript,
    so its env is built from an explicit allowlist (PRINT_PROMPT_ENV_KEYS) rather
    than by subtracting known-bad keys. AGENT_ENV_PASSTHROUGH forwards
    ANTHROPIC_API_KEY / GH_TOKEN / GITHUB_TOKEN to the real subprocess env, and
    _run_print_prompt prints that same env."""

    SECRETS = {
        "ANTHROPIC_API_KEY": "canary-anthropic-key",
        "GH_TOKEN": "canary-gh-token",
        "GITHUB_TOKEN": "canary-github-token",
    }

    def _run(self, capsys, tmp_path, extra_env=None, extra_passthrough=()):
        agent_dir = tmp_path / ".claude" / "agents" / "03_execute"
        agent_dir.mkdir(parents=True)
        (agent_dir / "coder.md").write_text(
            "---\nname: 03_execute/coder\nmodel: claude-sonnet-4-6\n---\n\nDo the work.\n"
        )

        gh_mock = MagicMock()
        gh_mock._get.return_value = {
            "number": 1,
            "title": "Test issue",
            "labels": [],
            "html_url": "https://github.com/test/repo/issues/1",
        }

        env = dict(self.SECRETS)
        env.update(extra_env or {})
        passthrough = pipeline_orchestrator.AGENT_ENV_PASSTHROUGH + tuple(extra_passthrough)

        with patch.object(pipeline_orchestrator, "SUBMODULE_ROOT", tmp_path), \
             patch.object(pipeline_orchestrator, "AI_AGILE_CONTEXT", tmp_path / "AGENTS.md"), \
             patch.object(pipeline_orchestrator, "AGENT_ENV_PASSTHROUGH", passthrough), \
             patch.object(pipeline_orchestrator, "GitHubClient", return_value=gh_mock), \
             patch.object(pipeline_orchestrator, "_discover_github_token",
                          return_value="canary-github-token"), \
             patch.dict(os.environ, env):
            _run_print_prompt(_make_args(
                print_prompt=True, agent="03_execute/coder", issue=1, repo="test/repo",
            ))
        return capsys.readouterr().out

    def test_no_credential_value_appears_in_output(self, capsys, tmp_path):
        out = self._run(capsys, tmp_path)
        for name, value in self.SECRETS.items():
            assert value not in out, f"{name}'s value leaked into --print-prompt output"

    def test_a_newly_added_passthrough_secret_is_omitted_by_default(self, capsys, tmp_path):
        """The reason this is an allowlist: a credential added to
        AGENT_ENV_PASSTHROUGH later must not start leaking on its own. A denylist
        naming only today's three secrets would fail this."""
        out = self._run(
            capsys, tmp_path,
            extra_env={"SOME_FUTURE_API_TOKEN": "canary-future-token"},
            extra_passthrough=("SOME_FUTURE_API_TOKEN",),
        )
        assert "canary-future-token" not in out
        payload = json.loads(out)
        assert "SOME_FUTURE_API_TOKEN" not in payload["env"]
        assert "SOME_FUTURE_API_TOKEN" in payload["env_omitted_keys"]

    def test_omitted_keys_are_reported_not_silently_dropped(self, capsys, tmp_path):
        payload = json.loads(self._run(capsys, tmp_path))
        for key in self.SECRETS:
            assert key not in payload["env"]
            assert key in payload["env_omitted_keys"], (
                "an omitted key must still be named so a consumer can tell "
                "'not needed' from 'not shown'"
            )

    def test_env_contains_nothing_outside_the_allowlist(self, capsys, tmp_path):
        payload = json.loads(self._run(capsys, tmp_path))
        assert set(payload["env"]) <= set(PRINT_PROMPT_ENV_KEYS)

    def test_agent_facing_context_is_still_printed(self, capsys, tmp_path):
        """The allowlist must not gut the env the spec asks resolve-only mode to emit."""
        payload = json.loads(self._run(capsys, tmp_path))
        assert payload["env"]["AI_AGILE_EXECUTION_MODE"] == "interactive"
        assert payload["env"]["REPO"] == "test/repo"
        assert payload["env"]["ISSUE_NUMBER"] == "1"
        assert payload["env"]["WORK_ITEM_KIND"] == "issue"

    def test_real_subprocess_env_still_carries_credentials(self):
        """The restriction is print-only -- a real spawn still needs the values."""
        with patch.dict(os.environ, self.SECRETS):
            env = _build_agent_env(
                os.environ, "test/repo", _make_work_item(), "session-X", "per_issue"
            )
        for name, value in self.SECRETS.items():
            assert env[name] == value, f"{name} must still reach the spawned agent"
        assert not set(PRINT_PROMPT_ENV_KEYS) & set(self.SECRETS), (
            "no credential key may appear in the print allowlist"
        )
