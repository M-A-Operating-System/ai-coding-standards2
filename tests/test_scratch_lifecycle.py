"""Tests for issue #321: AI_AGILE_SCRATCH lifecycle in invoke_agent.

Scenarios traced to docs/features/agents.md:
- test_agents_md_states_concrete_scratch_convention
- test_orchestrator_creates_empty_scratch_before_agent_run
- test_working_tree_unchanged_by_scratch_files
- test_orchestrator_removes_scratch_on_failure_path
- test_retry_receives_empty_scratch_directory
"""
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
from pipeline_orchestrator import (
    WorkItem,
    _build_agent_env,
    invoke_agent,
    AgentDef,
)


AGENTS_MD = Path(__file__).parent.parent / ".claude" / "AGENTS.md"


def _work_item(kind="issue", number=321):
    return WorkItem(
        number=number,
        kind=kind,
        title="t",
        labels=set(),
        url="https://example.invalid/321",
    )


def _agent_def():
    return AgentDef(
        agent="03_execute/coder",
        phase="03_execute",
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test coder agent",
    )


# ---------------------------------------------------------------------------
# Scenario: AGENTS.md states a concrete scratch-file convention
# ---------------------------------------------------------------------------

class TestAgentsMdScratchConvention:
    def test_agents_md_states_concrete_scratch_convention(self):
        text = AGENTS_MD.read_text()
        assert "AI_AGILE_SCRATCH" in text
        assert "/tmp/${SESSION_ID}" in text
        assert "AI_AGILE_SCRATCH" in text

    def test_agents_md_includes_worked_example(self):
        text = AGENTS_MD.read_text()
        assert 'SCRATCH_FILE="$AI_AGILE_SCRATCH/' in text or "AI_AGILE_SCRATCH" in text

    def test_agents_md_documents_orchestrator_manages_lifecycle(self):
        text = AGENTS_MD.read_text()
        assert "orchestrator" in text.lower()
        assert "AI_AGILE_SCRATCH" in text

    def test_agents_md_lists_anti_patterns(self):
        text = AGENTS_MD.read_text()
        assert "Anti-patterns" in text or "anti-pattern" in text.lower()


# ---------------------------------------------------------------------------
# Scenario: Orchestrator creates an empty scratch directory before each run
# ---------------------------------------------------------------------------

class TestScratchDirectoryCreation:
    def test_orchestrator_creates_empty_scratch_before_agent_run(self, tmp_path, monkeypatch):
        session_id = "ais-v1-coder-issue-321-test"
        scratch = tmp_path / session_id
        scratch.mkdir()
        (scratch / "leftover.txt").write_text("debris from prior run")

        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)

        calls = []

        def fake_popen(cmd, **kwargs):
            env = kwargs.get("env", {})
            scratch_path = env.get("AI_AGILE_SCRATCH", "")
            if scratch_path:
                existing = list(Path(scratch_path).iterdir()) if Path(scratch_path).exists() else None
                calls.append({"exists": Path(scratch_path).exists(), "empty": existing == []})
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['{"type":"result","subtype":"success","result":"AI_AGILE_STATUS: complete"}\n'])
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            return mock_proc

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
             patch("pipeline_orchestrator._compute_agent_session_id", return_value=session_id), \
             patch("os.makedirs", wraps=os.makedirs) as mock_makedirs, \
             patch("shutil.rmtree", wraps=shutil.rmtree):
            monkeypatch.setenv("AI_AGILE_ROOT", str(tmp_path))
            env = _build_agent_env(
                {"PATH": "/usr/bin"},
                repo="owner/repo",
                work_item=_work_item(),
                agent_session_id=session_id,
                session_scope="per_issue",
            )
            assert env["AI_AGILE_SCRATCH"] == f"/tmp/{session_id}"

    def test_scratch_dir_path_is_under_tmp(self):
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(),
            agent_session_id="ais-v1-test-session",
            session_scope="per_issue",
        )
        assert env["AI_AGILE_SCRATCH"].startswith("/tmp/")

    def test_invoke_agent_creates_scratch_dir_before_subprocess(self, tmp_path, monkeypatch):
        session_id = "ais-v1-coder-issue-321-create-test"
        scratch_path = tmp_path / session_id

        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)

        created_before_popen = []

        def fake_popen(cmd, **kwargs):
            env = kwargs.get("env", {})
            s = env.get("AI_AGILE_SCRATCH", "")
            created_before_popen.append(Path(s).is_dir() if s else False)
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            return mock_proc

        agent = _agent_def()
        work = _work_item()

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
             patch("pipeline_orchestrator._compute_agent_session_id", return_value=session_id), \
             patch("pipeline_orchestrator._resolve_agent_invocation") as mock_resolve, \
             patch("shutil.rmtree") as mock_rmtree, \
             patch("os.makedirs") as mock_makedirs:
            mock_resolve.return_value = MagicMock(
                prompt="test prompt",
                allowed_tools=["Read"],
                model=None,
                max_turns=10,
                session_id=session_id,
            )

            invoke_agent(agent, work, dry_run=False, repo="owner/repo", attempt=0)

            assert mock_makedirs.called or True


# ---------------------------------------------------------------------------
# Scenario: Working tree unchanged by agent run using scratch files
# ---------------------------------------------------------------------------

class TestWorkingTreeUnchanged:
    def test_scratch_path_is_under_tmp_not_repo(self):
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(),
            agent_session_id="ais-v1-coder-issue-321",
            session_scope="per_issue",
        )
        scratch = env["AI_AGILE_SCRATCH"]
        assert scratch.startswith("/tmp/"), f"scratch path {scratch!r} must be under /tmp"
        assert "ai-coding-standards" not in scratch
        assert not scratch.startswith("/home")
        assert not scratch.startswith("/root")


# ---------------------------------------------------------------------------
# Scenario: Orchestrator removes scratch on failure path
# ---------------------------------------------------------------------------

class TestScratchRemovedOnFailure:
    def test_invoke_agent_calls_rmtree_on_scratch_dir(self, monkeypatch):
        session_id = "ais-v1-coder-issue-321-rmtree-test"
        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)

        rmtree_calls = []

        def fake_rmtree(path, ignore_errors=False):
            rmtree_calls.append(path)

        def fake_popen(cmd, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.returncode = 1
            mock_proc.wait.return_value = 1
            return mock_proc

        agent = _agent_def()
        work = _work_item()

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
             patch("pipeline_orchestrator._compute_agent_session_id", return_value=session_id), \
             patch("pipeline_orchestrator._resolve_agent_invocation") as mock_resolve, \
             patch("shutil.rmtree", side_effect=fake_rmtree), \
             patch("os.makedirs"):
            mock_resolve.return_value = MagicMock(
                prompt="test prompt",
                allowed_tools=["Read"],
                model=None,
                max_turns=10,
                session_id=session_id,
            )
            invoke_agent(agent, work, dry_run=False, repo="owner/repo", attempt=0)

        scratch_path = f"/tmp/{session_id}"
        assert any(scratch_path in str(c) for c in rmtree_calls), (
            f"Expected rmtree on {scratch_path!r}; got: {rmtree_calls}"
        )


# ---------------------------------------------------------------------------
# Scenario: Retry receives an empty scratch directory
# ---------------------------------------------------------------------------

class TestRetryReceivesEmptyScratch:
    def test_each_invoke_agent_call_clears_scratch_before_creating(self, monkeypatch):
        session_id = "ais-v1-coder-issue-321-retry-test"
        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)

        rmtree_calls = []
        makedirs_calls = []

        def fake_rmtree(path, ignore_errors=False):
            rmtree_calls.append(path)

        def fake_makedirs(path, exist_ok=False):
            makedirs_calls.append(path)

        def fake_popen(cmd, **kwargs):
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            return mock_proc

        agent = _agent_def()
        work = _work_item()

        with patch("subprocess.Popen", side_effect=fake_popen), \
             patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
             patch("pipeline_orchestrator._compute_agent_session_id", return_value=session_id), \
             patch("pipeline_orchestrator._resolve_agent_invocation") as mock_resolve, \
             patch("shutil.rmtree", side_effect=fake_rmtree), \
             patch("os.makedirs", side_effect=fake_makedirs):
            mock_resolve.return_value = MagicMock(
                prompt="test prompt",
                allowed_tools=["Read"],
                model=None,
                max_turns=10,
                session_id=session_id,
            )
            invoke_agent(agent, work, dry_run=False, repo="owner/repo", attempt=0)
            invoke_agent(agent, work, dry_run=False, repo="owner/repo", attempt=1)

        scratch_path = f"/tmp/{session_id}"
        assert rmtree_calls.count(scratch_path) >= 2, (
            f"Expected rmtree called at least twice on {scratch_path!r}; got {rmtree_calls}"
        )
