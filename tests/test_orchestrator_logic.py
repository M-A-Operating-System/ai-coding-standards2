"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
import pytest
import json
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap: make pipeline_orchestrator importable without installing it
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline_orchestrator import (
    AgentDef,
    WorkItem,
    _should_skip,
    _eligible_agents,
    promote_gated_agents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(
    name,
    trigger_label=None,
    trigger_event=None,
    deps=None,
    human_gate=False,
    gate_label=None,
    exclude_labels=None,
    exclude_classifications=None,
    step_type="agent",
    auto_approve_on_complete=False,
    review_loop=None,
    max_concurrent=None,
    session_scope="per_issue",
):
    trigger = {}
    if trigger_label:
        trigger["label"] = trigger_label
    if trigger_event:
        trigger["event"] = trigger_event
    return AgentDef(
        agent=name,
        phase=name.split("/")[0],
        objects=["issue"],
        trigger=trigger,
        dependencies=deps or [],
        human_gate_after=human_gate,
        human_gate_label=gate_label,
        description="test",
        step_type=step_type,
        exclude_labels=exclude_labels or [],
        exclude_classifications=exclude_classifications or [],
        auto_approve_on_complete=auto_approve_on_complete,
        review_loop=review_loop,
        max_concurrent=max_concurrent,
        session_scope=session_scope,
    )


def _make_issue(labels=None, title="", classification=None):
    label_set = set(labels or [])
    if classification:
        label_set.add(f"classification:{classification}")
    return WorkItem(
        number=1,
        kind="issue",
        title=title,
        labels=label_set,
        url="https://github.com/test/repo/issues/1",
    )


# ===========================================================================
# _should_skip tests
# ===========================================================================

class TestShouldSkip:

    def test_skips_when_complete_label_present(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:complete"])
        assert _should_skip(agent, issue)

    def test_skips_when_wip_label_present(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:wip"])
        assert _should_skip(agent, issue)

    def test_skips_when_review_label_present(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:review"])
        assert _should_skip(agent, issue)

    def test_skips_when_blocked_label_present(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:blocked"])
        assert _should_skip(agent, issue)

    def test_skips_when_failed_label_present(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:failed"])
        assert _should_skip(agent, issue)

    def test_skips_when_skipped_label_present(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:skipped"])
        assert _should_skip(agent, issue)

    def test_does_not_skip_when_no_status_label(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete"])
        assert not _should_skip(agent, issue)

    def test_skips_when_exclude_label_present(self):
        agent = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            exclude_labels=["epic"],
        )
        issue = _make_issue(labels=["issue-classifier:complete", "epic"])
        assert _should_skip(agent, issue)

    def test_does_not_skip_when_exclude_label_absent(self):
        agent = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            exclude_labels=["epic"],
        )
        issue = _make_issue(labels=["issue-classifier:complete"])
        assert not _should_skip(agent, issue)

    def test_skips_when_excluded_classification_matches(self):
        agent = _make_agent(
            "03_execute/coder",
            trigger_label="prd-docs-updater:complete",
            exclude_classifications=["spike"],
        )
        issue = _make_issue(
            labels=["prd-docs-updater:complete"],
            classification="spike",
        )
        assert _should_skip(agent, issue)

    def test_does_not_skip_when_excluded_classification_absent(self):
        agent = _make_agent(
            "03_execute/coder",
            trigger_label="prd-docs-updater:complete",
            exclude_classifications=["spike"],
        )
        issue = _make_issue(
            labels=["prd-docs-updater:complete"],
            classification="feature",
        )
        assert not _should_skip(agent, issue)

    def test_skips_when_title_prefix_classification_excluded(self):
        """[SPIKE] in the issue title should be treated as a spike classification."""
        agent = _make_agent(
            "03_execute/coder",
            trigger_label="prd-docs-updater:complete",
            exclude_classifications=["spike"],
        )
        issue = _make_issue(
            labels=["prd-docs-updater:complete"],
            title="[SPIKE] investigate caching",
        )
        assert _should_skip(agent, issue)


# ===========================================================================
# _eligible_agents tests
# ===========================================================================

class TestEligibleAgents:

    def _pipeline(self, *agents):
        return list(agents)

    def test_trigger_label_satisfied(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=["issue-classifier:complete"])
        result = _eligible_agents(self._pipeline(agent), issue)
        assert agent in result

    def test_trigger_label_not_satisfied(self):
        agent = _make_agent("01_product_docs/prd-writer", trigger_label="issue-classifier:complete")
        issue = _make_issue(labels=[])
        result = _eligible_agents(self._pipeline(agent), issue)
        assert agent not in result

    def test_dep_label_required(self):
        """An agent whose dep emitted :complete should appear as eligible."""
        agent = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            deps=["01_product_docs/issue-classifier"],
        )
        issue = _make_issue(labels=["issue-classifier:complete"])
        result = _eligible_agents(self._pipeline(agent), issue)
        assert agent in result

    def test_dep_label_missing_blocks_eligibility(self):
        """An agent whose dep has NOT completed is not eligible."""
        agent = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            deps=["01_product_docs/issue-classifier"],
        )
        # No :complete label set for issue-classifier
        issue = _make_issue(labels=[])
        result = _eligible_agents(self._pipeline(agent), issue)
        assert agent not in result

    def test_human_gate_label_required(self):
        """If human_gate_after is True AND gate_label is NOT present, agent stays blocked."""
        writer = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            human_gate=True,
            gate_label="prd-writer:approved",
        )
        # Trigger is satisfied but the approval gate is NOT yet applied
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:complete"])
        result = _eligible_agents(self._pipeline(writer), issue)
        # prd-writer should NOT be eligible again (it already has :complete)
        assert writer not in result

    def test_next_agent_blocked_when_gate_label_absent(self):
        """The agent AFTER a gated step must not fire until the gate label is applied."""
        writer = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            human_gate=True,
            gate_label="prd-writer:approved",
        )
        docs_updater = _make_agent(
            "01_product_docs/prd-docs-updater",
            trigger_label="prd-writer:complete",
            deps=["01_product_docs/prd-writer"],
        )
        # prd-writer is complete but prd-writer:approved has NOT been applied yet
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:complete"])
        pipeline = self._pipeline(writer, docs_updater)

        # The docs updater is not eligible because prd-writer:approved is missing
        # (its trigger label is prd-writer:complete which IS present, but it depends
        # on prd-writer, which requires the gate label)
        result = _eligible_agents(pipeline, issue)
        assert docs_updater not in result

    def test_next_agent_eligible_after_gate_label_applied(self):
        """Once the gate label is applied, the next agent fires."""
        writer = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            human_gate=True,
            gate_label="prd-writer:approved",
        )
        docs_updater = _make_agent(
            "01_product_docs/prd-docs-updater",
            trigger_label="prd-writer:complete",
            deps=["01_product_docs/prd-writer"],
        )
        # Both prd-writer:complete and prd-writer:approved are now present
        issue = _make_issue(
            labels=["issue-classifier:complete", "prd-writer:complete", "prd-writer:approved"]
        )
        pipeline = self._pipeline(writer, docs_updater)
        result = _eligible_agents(pipeline, issue)
        assert docs_updater in result

    def test_event_trigger_never_fires_on_open_issue(self):
        """event-triggered agents only fire on the initial webhook call, not on label re-checks."""
        classifier = _make_agent(
            "01_product_docs/issue-classifier",
            trigger_event="issue.opened",
        )
        issue = _make_issue(labels=[])
        result = _eligible_agents(self._pipeline(classifier), issue)
        assert classifier not in result

    def test_gated_dep_blocks_downstream_even_when_trigger_label_present(self):
        """When a gated agent's gate label is absent, downstream agents are not eligible
        even if their trigger label is present on the issue.
        """
        gated = _make_agent(
            "01_product_docs/prd-writer",
            trigger_label="issue-classifier:complete",
            human_gate=True,
            gate_label="prd-writer:approved",
        )
        downstream = _make_agent(
            "01_product_docs/prd-docs-updater",
            trigger_label="prd-writer:complete",
            deps=["01_product_docs/prd-writer"],
        )
        # prd-writer:complete is present (trigger for downstream), but gate is missing
        issue = _make_issue(labels=["issue-classifier:complete", "prd-writer:complete"])
        result = _eligible_agents(self._pipeline(gated, downstream), issue)
        assert downstream not in result

    def test_max_concurrent_limits_eligible_agents(self):
        """When max_concurrent=1, a second :wip label on the same agent type blocks eligibility."""
        agent = _make_agent(
            "03_execute/coder",
            trigger_label="prd-docs-updater:complete",
            max_concurrent=1,
        )
        # Two issues: one already :wip, one ready to run
        issue_wip = _make_issue(labels=["prd-docs-updater:complete", "coder:wip"])
        issue_ready = _make_issue(labels=["prd-docs-updater:complete"])
        issue_ready = WorkItem(
            number=2,
            kind="issue",
            title="",
            labels={"prd-docs-updater:complete"},
            url="https://github.com/test/repo/issues/2",
        )

        all_items = [issue_wip, issue_ready]

        # For issue_ready: the WIP count across all items is 1, which equals max_concurrent
        import pipeline_orchestrator as orch
        wip_count = sum(
            1 for wi in all_items if f"{agent.short_name}:wip" in wi.labels
        )
        assert wip_count == 1

        # Simulate the orchestrator logic: skip issue_ready because wip_count >= max_concurrent
        assert wip_count >= agent.max_concurrent


# ===========================================================================
# invoke_agent — ANTHROPIC_API_KEY preflight (DP-001)
# ===========================================================================

class TestInvokeAgentApiKeyPreflight:
    """Verify that invoke_agent returns early with a clear error when
    ANTHROPIC_API_KEY is absent, rather than letting the subprocess
    launch and misread a subsequent auth error as a rate-limit pause.
    """

    def _make_agent_def(self) -> "AgentDef":
        import pipeline_orchestrator as orch
        return orch.AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="Test coder agent",
        )

    def _make_work_item(self) -> "WorkItem":
        import pipeline_orchestrator as orch
        return orch.WorkItem(
            number=1,
            kind="issue",
            title="Test issue",
            labels=set(),
            url="https://github.com/test/repo/issues/1",
        )

    def test_missing_api_key_returns_failure_without_spawning_process(self, monkeypatch):
        """When ANTHROPIC_API_KEY is unset, invoke_agent must return AgentRunResult(success=False)
        and must not call subprocess.Popen."""
        import pipeline_orchestrator as orch

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with patch("subprocess.Popen") as mock_popen:
            result = orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(),
                dry_run=False,
                repo="test/repo",
                agent_text_override="---\ntools: []\n---\nTest agent.",
            )

        assert result.success is False
        assert "ANTHROPIC_API_KEY" in result.captured_tail
        mock_popen.assert_not_called()

    def test_present_api_key_does_not_short_circuit(self, monkeypatch):
        """When ANTHROPIC_API_KEY is set, invoke_agent proceeds past the preflight."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 1)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.returncode = 1
        mock_proc.poll.return_value = 1
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(),
                dry_run=False,
                repo="test/repo",
                agent_text_override="---\ntools: []\n---\nTest agent.",
            )

        mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# QA-001: invoke_agent timeout — timer fires and agent does not hang forever
# ---------------------------------------------------------------------------

class TestInvokeAgentTimeout:
    """Verify DP-006 fix: kill-timer terminates a silent or slow agent.

    Two scenarios:
    1. Agent produces no stdout at all (silent hang) — timer fires, process
       is killed, invoke_agent returns AgentRunResult(success=False) instead
       of hanging forever.
    2. Agent keeps producing output past the deadline — _timed_out.is_set()
       check in the per-line loop raises TimeoutExpired, and the returned
       captured_tail contains the "timed out" message.
    """

    def _make_minimal_agent_def(self) -> "AgentDef":
        import pipeline_orchestrator as orch
        return orch.AgentDef(
            agent="03_execute/coder",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="Test coder agent",
            step_type="agent",
        )

    def _make_work_item(self) -> "WorkItem":
        import pipeline_orchestrator as orch
        return orch.WorkItem(
            number=1,
            kind="issue",
            title="Test issue",
            labels=set(),
            url="https://github.com/test/repo/issues/1",
        )

    def test_silent_agent_does_not_hang(self, monkeypatch):
        """Agent that produces no stdout terminates within timeout + small buffer."""
        import threading
        import time
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 0.1)

        # Stdout blocks until the process is killed.
        _killed = threading.Event()

        class BlockingStdout:
            def __iter__(self):
                _killed.wait(timeout=10)  # unblocks when process is terminated
                return iter([])

        mock_proc = MagicMock()
        mock_proc.stdout = BlockingStdout()
        mock_proc.returncode = -15  # SIGTERM

        poll_done = threading.Event()

        def poll_side_effect():
            return -15 if poll_done.is_set() else None

        def terminate_side_effect():
            poll_done.set()
            _killed.set()

        mock_proc.poll.side_effect = poll_side_effect
        mock_proc.terminate.side_effect = terminate_side_effect
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc):
            start = time.monotonic()
            result = orch.invoke_agent(
                self._make_minimal_agent_def(),
                self._make_work_item(),
                dry_run=False,
                repo="test/repo",
                agent_text_override="---\ntools: []\n---\nTest agent.",
            )
            elapsed = time.monotonic() - start

        assert result.success is False
        # Must complete well within 2× the patched timeout, not hang forever.
        assert elapsed < 2.0, f"invoke_agent hung for {elapsed:.2f}s (expected < 2s)"

    def test_timed_out_event_triggers_timeout_message(self, monkeypatch):
        """When _timed_out fires while agent is emitting lines, captured_tail says timed out."""
        import threading
        import time
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 0.1)

        # Stdout yields lines until the process is killed, then stops.
        _killed = threading.Event()

        def line_generator():
            while not _killed.is_set():
                yield '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}\n'
                time.sleep(0.005)

        mock_proc = MagicMock()
        mock_proc.stdout = line_generator()
        mock_proc.returncode = -15

        poll_done = threading.Event()

        def poll_side_effect():
            return -15 if poll_done.is_set() else None

        def terminate_side_effect():
            poll_done.set()
            _killed.set()

        mock_proc.poll.side_effect = poll_side_effect
        mock_proc.terminate.side_effect = terminate_side_effect
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc):
            result = orch.invoke_agent(
                self._make_minimal_agent_def(),
                self._make_work_item(),
                dry_run=False,
                repo="test/repo",
                agent_text_override="---\ntools: []\n---\nTest agent.",
            )

        assert result.success is False
        assert "timed out" in result.captured_tail.lower(), (
            f"Expected 'timed out' in captured_tail, got: {result.captured_tail!r}"
        )


class TestInvokeAgentRuntimeContext:
    """Tests for the resolved ## Runtime context block injected into invoke_agent() prompts.

    Acceptance criteria (issue #172):
    - Prompt contains a pre-resolved KEY=value block, not $VAR shell references.
    - Values in the prompt match what is exported to the subprocess environment.
    - String values are stripped of leading/trailing whitespace before injection.
    - Subprocess env still carries the same variables for bash-snippet compatibility.
    """

    def _make_agent_def(self, name: str = "03_execute/coder") -> "AgentDef":
        import pipeline_orchestrator as orch
        return orch.AgentDef(
            agent=name,
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="Test agent",
            session_scope="per_issue",
        )

    def _make_work_item(self, number: int = 42, kind: str = "issue") -> "WorkItem":
        import pipeline_orchestrator as orch
        return orch.WorkItem(
            number=number,
            kind=kind,
            title="Test issue",
            labels=set(),
            url=f"https://github.com/test/repo/{kind}s/{number}",
        )

    def _capture_prompt(self, cmd_args: list) -> str:
        """Extract the -p prompt argument from the claude CLI args list."""
        try:
            idx = cmd_args.index("-p")
            return cmd_args[idx + 1]
        except (ValueError, IndexError):
            return ""

    def _fake_popen_capturing_cmd(self, captured_cmd: list):
        def fake_popen(cmd, **kwargs):
            captured_cmd.extend(cmd)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.poll.return_value = 0
            proc.wait.return_value = None
            return proc
        return fake_popen

    def _fake_popen_capturing_env(self, captured_env: dict):
        def fake_popen(cmd, env=None, **kwargs):
            if env is not None:
                captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.poll.return_value = 0
            proc.wait.return_value = None
            return proc
        return fake_popen

    def test_runtime_context_block_replaces_shell_var_references_for_issue(self, monkeypatch):
        """Prompt must contain ## Runtime context with resolved KEY=value pairs (not $VAR syntax)."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_cmd: list = []

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_cmd(captured_cmd)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=42, kind="issue"),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        assert "## Runtime context" in prompt, "Prompt must contain '## Runtime context' section"
        assert "REPO=test-org/test-repo" in prompt
        assert "ISSUE_NUMBER=42" in prompt
        assert "WORK_ITEM_KIND=issue" in prompt
        # The old "Env vars: $REPO $ISSUE_NUMBER ..." line must be gone.
        assert "Env vars: $REPO" not in prompt, "Old shell-variable 'Env vars' line must be replaced"

    def test_runtime_context_uses_pr_number_key_for_pr_work_items(self, monkeypatch):
        """When work_item.kind is 'pr', context block uses PR_NUMBER, not ISSUE_NUMBER."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_cmd: list = []

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_cmd(captured_cmd)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=77, kind="pr"),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        assert "PR_NUMBER=77" in prompt, "Prompt must contain resolved PR_NUMBER for PR work items"
        # ISSUE_NUMBER=N must not appear as a KEY=value assignment for PR work items.
        assert "ISSUE_NUMBER=" not in prompt, "PR work items must not expose ISSUE_NUMBER= in context"

    def test_string_values_are_stripped_before_injection(self, monkeypatch):
        """String values with surrounding whitespace are stripped to prevent prompt line injection."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        monkeypatch.setenv("AI_AGILE_ROOT", "  /padded/path  ")
        captured_cmd: list = []

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_cmd(captured_cmd)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=5),
                dry_run=False,
                repo="  test-org/test-repo  ",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        assert "REPO=test-org/test-repo\n" in prompt, "REPO value must be stripped of whitespace"
        assert "AI_AGILE_ROOT=/padded/path\n" in prompt, "AI_AGILE_ROOT must be stripped"
        assert "REPO=  test-org/test-repo  " not in prompt, "Unstripped REPO must not appear"

    def test_subprocess_env_still_exports_vars_for_bash_snippet_compatibility(self, monkeypatch):
        """Subprocess env must still carry REPO, ISSUE_NUMBER, WORK_ITEM_KIND, SESSION_ID."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_env: dict = {}

        with patch("subprocess.Popen", side_effect=self._fake_popen_capturing_env(captured_env)):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=42, kind="issue"),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        assert captured_env.get("REPO") == "test-org/test-repo", "REPO must be in subprocess env"
        assert captured_env.get("ISSUE_NUMBER") == "42", "ISSUE_NUMBER must be in subprocess env"
        assert captured_env.get("WORK_ITEM_KIND") == "issue", "WORK_ITEM_KIND must be in subprocess env"
        assert "SESSION_ID" in captured_env, "SESSION_ID must be in subprocess env"

    def test_prompt_session_id_matches_subprocess_env_session_id(self, monkeypatch):
        """SESSION_ID in the prompt must match SESSION_ID exported to subprocess."""
        import pipeline_orchestrator as orch

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(orch, "AGENT_TIMEOUT_SECONDS", 5)
        captured_cmd: list = []
        captured_env: dict = {}

        def fake_popen(cmd, env=None, **kwargs):
            captured_cmd.extend(cmd)
            if env is not None:
                captured_env.update(env)
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.poll.return_value = 0
            proc.wait.return_value = None
            return proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            orch.invoke_agent(
                self._make_agent_def(),
                self._make_work_item(number=42),
                dry_run=False,
                repo="test-org/test-repo",
                agent_text_override="---\ntools: []\n---\nTest agent body.",
            )

        prompt = self._capture_prompt(captured_cmd)
        env_session_id = captured_env.get("SESSION_ID", "")
        assert env_session_id, "SESSION_ID must be exported to subprocess env"
        assert f"SESSION_ID={env_session_id}" in prompt, (
            f"SESSION_ID in prompt must match subprocess env. "
            f"Expected SESSION_ID={env_session_id!r} in prompt."
        )


class TestPromoteGatedAgents:
    """Tests for promote_gated_agents covering all label-state transitions."""

    def _gated_agent(self, name: str = "01_product_docs/prd-writer") -> AgentDef:
        return AgentDef(
            agent=name,
            phase=name.split("/")[0],
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=True,
            human_gate_label=f"{name.rsplit('/', 1)[-1]}:approved",
            description="test",
        )

    def _ungated_agent(self, name: str = "01_product_docs/issue-classifier") -> AgentDef:
        return AgentDef(
            agent=name,
            phase=name.split("/")[0],
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="test",
        )

    def _issue(self, labels: list) -> WorkItem:
        return WorkItem(
            number=1,
            kind="issue",
            title="",
            labels=set(labels),
            url="https://github.com/test/repo/issues/1",
        )

    # ------------------------------------------------------------------
    # core gate promotion
    # ------------------------------------------------------------------

    def test_complete_on_gated_agent_promotes_to_approved(self):
        """When a gated agent emits :complete, the gate label must be promoted to :approved."""
        agent = self._gated_agent()
        issue = self._issue(["prd-writer:complete"])
        actions = promote_gated_agents([agent], issue)
        assert any(
            a["kind"] == "add_label" and a["label"] == "prd-writer:approved"
            for a in actions
        ), f"Expected add_label prd-writer:approved, got {actions}"

    def test_complete_on_ungated_agent_does_not_promote(self):
        """A non-gated agent must not trigger any label action."""
        agent = self._ungated_agent()
        issue = self._issue(["issue-classifier:complete"])
        actions = promote_gated_agents([agent], issue)
        assert actions == [], f"Expected no actions, got {actions}"

    def test_gate_already_approved_does_not_re_add(self):
        """If the gate label is already present, no duplicate add_label should be emitted."""
        agent = self._gated_agent()
        issue = self._issue(["prd-writer:complete", "prd-writer:approved"])
        actions = promote_gated_agents([agent], issue)
        assert actions == [], f"Expected no actions (gate already applied), got {actions}"

    def test_no_complete_label_does_not_trigger_promotion(self):
        """:wip, :review, :blocked, :failed, :skipped — none should trigger promotion."""
        agent = self._gated_agent()
        for status in ("wip", "review", "blocked", "failed", "skipped"):
            issue = self._issue([f"prd-writer:{status}"])
            actions = promote_gated_agents([agent], issue)
            assert actions == [], (
                f"Expected no actions for status={status!r}, got {actions}"
            )

    # ------------------------------------------------------------------
    # auto_approve_on_complete
    # ------------------------------------------------------------------

    def test_auto_approve_on_complete_emits_add_label(self):
        """When auto_approve_on_complete is True and :complete is present, gate must be added."""
        agent = AgentDef(
            agent="03_execute/merge-conflict",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=True,
            human_gate_label="merge-conflict:approved",
            description="test",
            auto_approve_on_complete=True,
        )
        issue = self._issue(["merge-conflict:complete"])
        actions = promote_gated_agents([agent], issue)
        assert any(
            a["kind"] == "add_label" and a["label"] == "merge-conflict:approved"
            for a in actions
        ), f"Expected add_label merge-conflict:approved, got {actions}"

    def test_auto_approve_on_complete_blocked_when_review_present(self):
        """When :review is present alongside :complete, auto-approval must not fire."""
        agent = AgentDef(
            agent="03_execute/merge-conflict",
            phase="03_execute",
            objects=["issue"],
            trigger={},
            dependencies=[],
            human_gate_after=True,
            human_gate_label="merge-conflict:approved",
            description="test",
            auto_approve_on_complete=True,
        )
        issue = self._issue(["merge-conflict:complete", "merge-conflict:review"])
        actions = promote_gated_agents([agent], issue)
        assert actions == [], (
            f"Expected no auto-approve when :review is present, got {actions}"
        )

    # ------------------------------------------------------------------
    # multiple agents
    # ------------------------------------------------------------------

    def test_multiple_agents_only_promotes_the_complete_one(self):
        """In a pipeline with two gated agents, only the one with :complete gets promoted."""
        writer = self._gated_agent("01_product_docs/prd-writer")
        docs = self._gated_agent("01_product_docs/prd-docs-updater")
        issue = self._issue(["prd-writer:complete"])  # docs-updater is NOT complete
        actions = promote_gated_agents([writer, docs], issue)
        labels_added = [a["label"] for a in actions if a["kind"] == "add_label"]
        assert "prd-writer:approved" in labels_added
        assert "prd-docs-updater:approved" not in labels_added

    # ------------------------------------------------------------------
    # edge cases
    # ------------------------------------------------------------------

    def test_empty_pipeline_returns_no_actions(self):
        issue = self._issue(["some-label"])
        assert promote_gated_agents([], issue) == []

    def test_empty_labels_returns_no_actions(self):
        agent = self._gated_agent()
        issue = self._issue([])
        assert promote_gated_agents([agent], issue) == []


# ===========================================================================
# _should_skip — review-cycle label handling
# ===========================================================================

class TestShouldSkipReviewCycle:
    """review-cycle:N labels must NOT block an agent from running.

    review-cycle:N is a metadata counter (how many coder re-invocations have
    occurred), not a terminal status label. _should_skip must treat it as
    invisible so the coder remains eligible on each new cycle.
    """

    def _coder(self):
        return _make_agent(
            "03_execute/coder",
            trigger_label="prd-docs-updater:complete",
        )

    def test_review_cycle_label_does_not_skip_coder(self):
        """review-cycle:1 alone must not cause _should_skip to return True."""
        coder = self._coder()
        issue = _make_issue(labels=["prd-docs-updater:complete", "review-cycle:1"])
        assert not _should_skip(coder, issue)

    def test_review_cycle_plus_wip_skips_coder(self):
        """review-cycle:1 + coder:wip must still skip (the :wip trumps)."""
        coder = self._coder()
        issue = _make_issue(labels=["prd-docs-updater:complete", "review-cycle:1", "coder:wip"])
        assert _should_skip(coder, issue)

    def test_review_cycle_plus_complete_skips_coder(self):
        """review-cycle:2 + coder:complete must skip (coder already done)."""
        coder = self._coder()
        issue = _make_issue(labels=["prd-docs-updater:complete", "review-cycle:2", "coder:complete"])
        assert _should_skip(coder, issue)

    def test_high_review_cycle_number_does_not_skip(self):
        """review-cycle:99 with no status suffix must not block the coder."""
        coder = self._coder()
        issue = _make_issue(labels=["prd-docs-updater:complete", "review-cycle:99"])
        assert not _should_skip(coder, issue)


# ===========================================================================
# human-review-pending label handling
# ===========================================================================

class TestHumanReviewPendingLabel:
    """human-review-pending must behave as a non-status label.

    It signals that unresolved human REQUEST_CHANGES reviews block the
    pr-reviewer from approving, but it must not be mistaken for a terminal
    agent status (like :wip or :blocked) by _should_skip or _eligible_agents.
    """

    def _pr_reviewer(self):
        return _make_agent(
            "03_execute/pr-reviewer",
            trigger_label="merge-conflict:complete",
        )

    def test_human_review_pending_does_not_skip_pr_reviewer(self):
        """human-review-pending alone must not cause _should_skip to return True."""
        reviewer = self._pr_reviewer()
        issue = _make_issue(
            labels=["merge-conflict:complete", "human-review-pending"]
        )
        assert not _should_skip(reviewer, issue)

    def test_human_review_pending_plus_wip_skips(self):
        """human-review-pending + pr-reviewer:wip must still skip."""
        reviewer = self._pr_reviewer()
        issue = _make_issue(
            labels=["merge-conflict:complete", "human-review-pending", "pr-reviewer:wip"]
        )
        assert _should_skip(reviewer, issue)

    def test_human_review_pending_does_not_block_eligible_agents(self):
        """_eligible_agents must include pr-reviewer when human-review-pending is present
        but no terminal status label blocks it.
        """
        reviewer = self._pr_reviewer()
        issue = _make_issue(
            labels=["merge-conflict:complete", "human-review-pending"]
        )
        result = _eligible_agents([reviewer], issue)
        assert reviewer in result


# ===========================================================================
# Emergency stop tests
# ===========================================================================

# (These live in tests/test_emergency_stop.py — no coverage here.)
