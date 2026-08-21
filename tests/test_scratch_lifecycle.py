"""Tests for issue #321: AI_AGILE_SCRATCH lifecycle in invoke_agent.

Scenarios traced to docs/features/agents.md:
- test_agents_md_states_concrete_scratch_convention
- test_orchestrator_creates_empty_scratch_before_agent_run
- test_working_tree_unchanged_by_scratch_files
- test_orchestrator_removes_scratch_on_failure_path
- test_retry_receives_empty_scratch_directory
"""
import re
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
        assert "${AI_AGILE_SCRATCH:-" in text
        assert "never from a bare filename" in text

    def test_agents_md_teaches_body_file_from_scratch(self):
        """Issue #321, corrected. The first fix told agents to avoid files and
        pipe a heredoc into `--body "$(cat <<EOF ...)"`. pr-reviewer ignored it
        across two consecutive ticks, leaking three files each time, because
        its bodies are JSON inside a fenced block and that form needs backticks
        and `$` shielded from the shell twice over -- so it built a file for
        `gh api --input` instead, in the repo root.

        The rule therefore places the file rather than denying it: stage in
        $SCRATCH, post with --body-file, which has no quoting problem at all.
        """
        text = AGENTS_MD.read_text()
        assert "--body-file" in text
        assert '"$SCRATCH/body.md"' in text
        # The fragile form is what the agent routed around; do not teach it.
        assert '--body "$(cat <<' not in text

    def test_pr_reviewer_posts_every_body_from_scratch(self):
        """pr-reviewer is the agent that actually leaked -- three files per run,
        two runs running: ann_rerun/review_v2/ann_close_v2, and before that
        open_announce/review_body/announce_close. Its three posting steps must
        stage into $SCRATCH and post with --body-file, so a regression there
        fails here rather than in a live tick.
        """
        text = (AGENTS_DIR / "03_execute" / "pr-reviewer.md").read_text()
        # Count the command form, not prose mentions of the flag.
        assert text.count('--body-file "$SCRATCH/') == 3, \
            "expected all 3 posting steps to post --body-file from $SCRATCH"
        assert '--body "$(cat <<' not in text, "the fragile quoted-heredoc form is back"
        assert text.count("${AI_AGILE_SCRATCH:-") == 3

    def test_agents_md_documents_orchestrator_manages_lifecycle(self):
        text = AGENTS_MD.read_text()
        assert "orchestrator" in text.lower()
        assert "AI_AGILE_SCRATCH" in text

    def test_orchestrator_creates_empty_scratch_before_agent_run(self, monkeypatch):
        """Debris from a prior run or a crashed retry must not survive into the
        next invocation. This calls invoke_agent for real (the previous version
        called _build_agent_env only, which never touches the filesystem, so its
        fake_popen never ran and the check was vacuous).
        """
        session_id = "ais-v1-coder-issue-321-empty-test"
        scratch = Path("/tmp") / session_id
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        (scratch / "leftover.txt").write_text("debris from prior run")

        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)

        observed = []

        def fake_popen(cmd, **kwargs):
            path = kwargs.get("env", {}).get("AI_AGILE_SCRATCH", "")
            d = Path(path) if path else None
            observed.append({
                "exists": bool(d and d.is_dir()),
                "contents": sorted(x.name for x in d.iterdir()) if d and d.is_dir() else None,
            })
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            return mock_proc

        try:
            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
                 patch("pipeline_orchestrator._compute_agent_session_id", return_value=session_id), \
                 patch("pipeline_orchestrator._resolve_agent_invocation") as mock_resolve, \
                 patch("shutil.rmtree", wraps=shutil.rmtree), \
                 patch("os.makedirs", wraps=os.makedirs):
                mock_resolve.return_value = MagicMock(
                    prompt="test prompt",
                    allowed_tools=["Read"],
                    model=None,
                    max_turns=10,
                    session_id=session_id,
                )
                invoke_agent(_agent_def(), _work_item(), dry_run=False,
                             repo="owner/repo", attempt=0)

            assert observed, "Popen was never called -- invoke_agent did not run"
            assert observed[0]["exists"] is True
            assert observed[0]["contents"] == [], (
                f"scratch not empty at spawn: {observed[0]['contents']}"
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_scratch_dir_path_is_under_tmp(self):
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(),
            agent_session_id="ais-v1-test-session",
            session_scope="per_issue",
        )
        assert env["AI_AGILE_SCRATCH"].startswith("/tmp/")

    def test_invoke_agent_creates_scratch_dir_before_subprocess(self, monkeypatch):
        """The directory must exist on disk by the time Popen fires -- the agent
        cannot write into it otherwise. os.makedirs is wrapped rather than
        replaced so the check observes the real filesystem.
        """
        session_id = "ais-v1-coder-issue-321-create-test"
        scratch_path = Path("/tmp") / session_id
        shutil.rmtree(scratch_path, ignore_errors=True)

        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)

        created_before_popen = []

        def fake_popen(cmd, **kwargs):
            env = kwargs.get("env", {})
            s_path = env.get("AI_AGILE_SCRATCH", "")
            created_before_popen.append(Path(s_path).is_dir() if s_path else False)
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            return mock_proc

        try:
            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
                 patch("pipeline_orchestrator._compute_agent_session_id", return_value=session_id), \
                 patch("pipeline_orchestrator._resolve_agent_invocation") as mock_resolve, \
                 patch("shutil.rmtree", wraps=shutil.rmtree), \
                 patch("os.makedirs", wraps=os.makedirs) as mock_makedirs:
                mock_resolve.return_value = MagicMock(
                    prompt="test prompt",
                    allowed_tools=["Read"],
                    model=None,
                    max_turns=10,
                    session_id=session_id,
                )

                invoke_agent(_agent_def(), _work_item(), dry_run=False,
                             repo="owner/repo", attempt=0)

            assert mock_makedirs.called
            assert str(scratch_path) in str(mock_makedirs.call_args)
            # The load-bearing assertion: the directory was on disk when the
            # agent subprocess was spawned, not merely created at some point.
            assert created_before_popen == [True]
        finally:
            shutil.rmtree(scratch_path, ignore_errors=True)


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


AGENTS_DIR = Path(__file__).parent.parent / ".claude" / "agents"

# atlas.md is not an AI Agile pipeline agent -- it is not registered in
# pipeline.json and is never invoked by the orchestrator, so the scratch
# contract does not apply to it.
_NON_PIPELINE_AGENTS = {"atlas.md"}


def _agent_prompts():
    return sorted(
        p for p in AGENTS_DIR.rglob("*.md")
        if p.name not in _NON_PIPELINE_AGENTS
    )


class TestAgentPromptsDoNotOwnScratchCleanup:
    """Issue #321: cleanup is the orchestrator's job. The rule itself lives in
    AGENTS.md alone -- duplicating it into every agent prompt was tried and
    reverted, since the failure was the section's worked example teaching
    file-staging, not the rule being insufficiently repeated.
    """

    def test_at_least_one_agent_prompt_is_discovered(self):
        # Guard against the symlink trap: .claude/ is a whole-folder symlink in
        # consuming repos, and a globbing miss would make the tests below pass
        # vacuously on an empty set.
        assert len(_agent_prompts()) > 0

    def test_no_agent_prompt_reintroduces_a_repo_root_cleanup_glob(self):
        # Cleanup is the orchestrator's job since #321; a per-agent glob is the
        # exact mechanism that failed (it only covered stems it anticipated).
        offenders = [
            str(p.relative_to(AGENTS_DIR))
            for p in _agent_prompts()
            if re.search(r"rm -f \.[a-z_]*\*", p.read_text())
        ]
        assert offenders == [], f"agent prompts with a repo-root cleanup glob: {offenders}"
