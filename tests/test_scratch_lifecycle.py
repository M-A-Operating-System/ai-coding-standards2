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
import pytest
import shutil
import subprocess
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


AGENTS_DIR = Path(__file__).parent.parent / ".claude" / "agents"
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

# atlas.md is not an AI Agile pipeline agent -- not registered in pipeline.json
# and never orchestrator-invoked, so the scratch contract does not apply to it.
_NON_PIPELINE_AGENTS = {"atlas.md"}


def _agent_prompts():
    return sorted(
        p for p in AGENTS_DIR.rglob("*.md")
        if p.name not in _NON_PIPELINE_AGENTS
    )


class TestAgentsMdScratchConvention:
    def test_agents_md_states_concrete_scratch_convention(self):
        text = AGENTS_MD.read_text()
        assert "AI_AGILE_SCRATCH" in text
        assert "${AI_AGILE_SCRATCH:-" in text
        assert "never from a bare filename" in text

    def test_agents_md_teaches_writing_into_scratch(self):
        """Issue #321, third correction. Two earlier rules failed in practice:
        "avoid files" (pr-reviewer routed around it, leaking 3 files a run) and
        then a `SCRATCH=...; mkdir -p` preamble, which pr-reviewer cannot run at
        all -- it starts with an assignment (matching no allowlist pattern) and
        mkdir is not among its 31 granted tools. Worse, when that line is denied
        the next one expands to `cat > "/body.md"` -- a write to the filesystem
        root.

        The rule now creates nothing: the orchestrator provides the directory,
        and ${AI_AGILE_SCRATCH:-/tmp} falls back to a path that always exists.
        """
        text = AGENTS_MD.read_text()
        assert '${AI_AGILE_SCRATCH:-/tmp}/' in text
        assert "do not create it yourself" in text
        # No preamble the agent has to execute before it can write. The word
        # may appear in prose explaining why not to; a command must not.
        assert "mkdir -p" not in text
        assert 'SCRATCH="${AI_AGILE_SCRATCH' not in text

    def test_pr_reviewer_posts_every_body_from_scratch(self):
        """pr-reviewer is the agent that leaked -- three files per run, twice
        running. Its three posting steps must write into the scratch directory
        and post from there, using tools it is actually granted.
        """
        text = (AGENTS_DIR / "03_execute" / "pr-reviewer.md").read_text()
        assert text.count('cat > "${AI_AGILE_SCRATCH:-/tmp}/') == 3
        # REST, not `gh pr comment`: the latter is GraphQL and 403s in a
        # restricted session. Bash(gh api --method * repos/*/issues*) is granted
        # to every agent, so this form works on both paths.
        assert text.count('gh api --method POST "repos/$REPO/issues/$PR_NUMBER/comments"') == 3
        assert "mkdir -p" not in text
        assert 'SCRATCH="${AI_AGILE_SCRATCH' not in text

    def test_agents_md_documents_orchestrator_manages_lifecycle(self):
        text = AGENTS_MD.read_text()
        assert "orchestrator" in text.lower()
        assert "AI_AGILE_SCRATCH" in text

    def test_scratch_dir_path_is_under_tmp(self):
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(),
            agent_session_id="ais-v1-test-session",
            session_scope="per_issue",
        )
        assert env["AI_AGILE_SCRATCH"].startswith("/tmp/")


# ---------------------------------------------------------------------------
# STD-ARCH-035: the lifecycle is implemented in scripts, not in the orchestrator
# ---------------------------------------------------------------------------

SCRIPTS = Path(__file__).parent.parent / ".github" / "scripts"


def _run_script(name, scratch):
    return subprocess.run(
        ["bash", str(SCRIPTS / name)],
        env={"PATH": os.environ["PATH"], "AI_AGILE_SCRATCH": str(scratch)},
        capture_output=True, text=True, timeout=30,
    )


class TestScratchScripts:
    """The work lives in .github/scripts/, so it is testable standalone."""

    def test_setup_creates_the_directory_empty(self):
        d = Path("/tmp/ais-test-setup-empty")
        shutil.rmtree(d, ignore_errors=True)
        try:
            assert _run_script("scratch-setup.sh", d).returncode == 0
            assert d.is_dir() and list(d.iterdir()) == []
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_setup_clears_debris_from_a_prior_run(self):
        """This is what makes the lifecycle self-healing: a tick killed before
        teardown leaves files behind, and the next run clears them. It is why
        no signal handler needs to clean up.
        """
        d = Path("/tmp/ais-test-setup-debris")
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        (d / "leftover.txt").write_text("debris")
        try:
            assert _run_script("scratch-setup.sh", d).returncode == 0
            assert list(d.iterdir()) == []
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_teardown_removes_the_directory(self):
        d = Path("/tmp/ais-test-teardown")
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        (d / "f.txt").write_text("x")
        assert _run_script("scratch-teardown.sh", d).returncode == 0
        assert not d.exists()

    @pytest.mark.parametrize("bad", ["", "relative/path", "/home/user/repo", "/", "/tmp"])
    def test_scripts_refuse_a_path_outside_tmp(self, bad):
        """Both scripts run rm -rf. A relative path, the repo, or a bare /tmp
        must be refused rather than deleted.
        """
        for name in ("scratch-setup.sh", "scratch-teardown.sh"):
            assert _run_script(name, bad).returncode != 0, f"{name} accepted {bad!r}"


class TestOrchestratorDelegatesToScripts:
    """STD-ARCH-035: the orchestrator schedules the scripts; it does not do the
    filesystem work itself.
    """

    def test_orchestrator_holds_no_scratch_filesystem_calls(self):
        src = (Path(__file__).parent.parent / "pipeline" / "pipeline_orchestrator.py").read_text()
        assert "_CURRENT_SCRATCH" not in src, "module global for in-flight scratch is back"
        assert "os.makedirs(scratch" not in src
        assert "shutil.rmtree(scratch" not in src

    def test_agent_receives_an_empty_scratch_directory_at_spawn(self, monkeypatch):
        """End-to-end through the real scripts: by the time Popen fires, the
        directory exists and is empty even if a prior run left debris.
        """
        session_id = "ais-v1-test-delegates"
        scratch = Path("/tmp") / session_id
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        (scratch / "leftover.txt").write_text("debris from prior run")

        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)
        observed = []

        real_popen = subprocess.Popen

        def fake_popen(cmd, **kwargs):
            # The orchestrator runs the scratch scripts via subprocess.run,
            # which is itself built on Popen -- let those through untouched or
            # the hooks silently no-op and this test asserts nothing.
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "bash":
                return real_popen(cmd, **kwargs)
            path = kwargs.get("env", {}).get("AI_AGILE_SCRATCH", "")
            d = Path(path) if path else None
            observed.append({
                "exists": bool(d and d.is_dir()),
                "contents": sorted(x.name for x in d.iterdir()) if d and d.is_dir() else None,
            })
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.wait.return_value = 0
            return proc

        try:
            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
                 patch("pipeline_orchestrator._compute_agent_session_id", return_value=session_id), \
                 patch("pipeline_orchestrator._resolve_agent_invocation") as mock_resolve:
                mock_resolve.return_value = MagicMock(
                    prompt="p", allowed_tools=["Read"], model=None,
                    max_turns=10, session_id=session_id,
                )
                invoke_agent(_agent_def(), _work_item(), dry_run=False,
                             repo="owner/repo", attempt=0)

            assert observed, "Popen was never called"
            assert observed[0]["exists"] is True
            assert observed[0]["contents"] == [], (
                f"scratch not empty at spawn: {observed[0]['contents']}"
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


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
