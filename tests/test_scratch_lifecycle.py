"""Tests for issue #321: AI_AGILE_SCRATCH lifecycle in invoke_agent.

Scenarios traced to docs/features/agents.md, and the classes covering each:

- AGENTS.md states a concrete convention   TestAgentsMdScratchConvention
- The worked example posts from the file   TestAgentsMdScratchConvention
- Empty scratch before each agent run      TestScratchScripts,
                                           TestOrchestratorDelegatesToScripts
- Working tree unchanged by a run          TestAgentPromptsDoNotOwnScratchCleanup,
                                           TestAgentPromptsStayWithinTheirAllowlist
- Scratch removed on the failure path      TestOrchestratorSchedulesTeardownOnEveryPath
- A retry receives an empty directory      TestOrchestratorSchedulesTeardownOnEveryPath
- A killed tick leaves no debris           TestScratchLifecycleIsSelfHealing
"""
import json
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


def _declared_lifecycle():
    """The `defaults.agent_lifecycle` block as pipeline.json actually declares it."""
    from pipeline_orchestrator import load_pipeline
    agents, _ = load_pipeline(Path(__file__).parent.parent / "pipeline" / "pipeline.json")
    agent = next(a for a in agents if a.step_type == "agent")
    return agent.lifecycle_before, agent.lifecycle_after


def _agent_def():
    before, after = _declared_lifecycle()
    return AgentDef(
        agent="03_execute/coder",
        phase="03_execute",
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test coder agent",
        lifecycle_before=before,
        lifecycle_after=after,
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

    @pytest.mark.parametrize("bad", [
        "", "relative/path", "/home/user/repo", "/", "/tmp",
        # Traversal: a literal prefix test passes these, because `?` consumes
        # the dot and `*` takes the rest. Found by pr-reviewer as SA-001 on
        # PR #360 and confirmed by deleting a real file before the fix; the
        # guard now resolves with readlink -m before testing.
        "/tmp/../etc",
        "/tmp/../home/user/ai-coding-standards2",
        "/var/tmp/../../etc",
    ])
    def test_scripts_refuse_a_path_outside_tmp(self, bad):
        """Both scripts run rm -rf. A relative path, the repo, a bare /tmp, or
        anything that *resolves* outside /tmp must be refused rather than
        deleted.
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

    def test_the_orchestrator_does_not_name_the_lifecycle_scripts(self):
        """STD-ARCH-035: the pipeline describes itself. Hardcoding the paths as
        Python constants made pipeline.json an incomplete description of the
        pipeline -- reading the config no longer told you what ran."""
        src = (Path(__file__).parent.parent / "pipeline" / "pipeline_orchestrator.py").read_text()
        code = "\n".join(
            line for line in src.split("\n") if not line.lstrip().startswith("#")
        )
        for name in ["scratch-setup.sh", "scratch-teardown.sh"]:
            assert name not in code, (
                f"{name} is named in orchestrator code; declare it in "
                f"pipeline.json defaults.agent_lifecycle instead"
            )

    def test_the_lifecycle_scripts_are_declared_in_pipeline_json(self):
        raw = json.loads(
            (Path(__file__).parent.parent / "pipeline" / "pipeline.json").read_text()
        )
        lifecycle = raw["defaults"]["agent_lifecycle"]
        assert lifecycle["before"] == [".github/scripts/scratch-setup.sh"]
        assert lifecycle["after"] == [".github/scripts/scratch-teardown.sh"]

    def test_every_declared_lifecycle_script_exists_and_runs(self):
        """A declared path that does not exist is skipped with a warning, so a
        typo would be silent. Assert the declaration resolves."""
        root = Path(__file__).parent.parent
        raw = json.loads((root / "pipeline" / "pipeline.json").read_text())
        lifecycle = raw["defaults"]["agent_lifecycle"]
        for script in lifecycle["before"] + lifecycle["after"]:
            path = root / script
            assert path.is_file(), f"declared lifecycle script missing: {script}"
            result = subprocess.run(
                ["bash", "-n", str(path)], capture_output=True, text=True
            )
            assert result.returncode == 0, f"{script} does not parse: {result.stderr}"

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


class TestAgentPromptsStayWithinTheirAllowlist:
    """Issue #321, review round 2. AGENTS.md and pr-reviewer.md were changed to
    open every posting step with `SCRATCH=...; mkdir -p "$SCRATCH"`. It looked
    correct and shipped CI-green, but pr-reviewer is not granted mkdir -- only
    coder is -- so the line could never run, and with SCRATCH unset the next
    line expanded to `cat > "/body.md"`: a write to the filesystem root.

    Reading the diff did not catch it; running the agent did. This is the
    generalisable guard.

    Deliberately narrow. It checks only filesystem-mutating utilities, because
    those are unambiguous: if an agent is not granted `mkdir` it cannot create
    a directory, whatever the matcher's view of assignments or pipelines. It
    does NOT try to model command-line matching in general -- the enforcement
    hook is stricter than Claude Code's own matcher (see #362), so a test built
    on hook semantics would fail on prompts that run correctly in production.
    """

    MUTATORS = ("mkdir", "rm", "cp", "mv", "touch", "chmod", "ln")

    @staticmethod
    def _bash_command_words(md_text):
        """Leading words of command positions inside ```bash fences.

        Heredoc bodies are skipped -- their contents are data, not commands.
        """
        words, in_bash, heredoc = [], False, None
        for line in md_text.splitlines():
            st = line.strip()
            if st.startswith("```"):
                in_bash = st.startswith("```bash")
                heredoc = None
                continue
            if not in_bash:
                continue
            if heredoc:
                if st.strip("'\"") == heredoc:
                    heredoc = None
                continue
            m = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?", line)
            if m:
                heredoc = m.group(1)
            if not st or st.startswith("#"):
                continue
            # A utility is in command position at the start of the line or
            # directly after a separator.
            for seg in re.split(r"(?:&&|\|\||;|\|)", st):
                seg = seg.strip()
                if seg:
                    words.append(seg.split()[0])
        return words

    def test_no_agent_prompt_uses_a_filesystem_command_it_lacks(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
        import pipeline_orchestrator as po

        agents, defaults = po.load_pipeline(
            str(Path(__file__).parent.parent / "pipeline" / "pipeline.json")
        )[:2]
        wi = po.WorkItem(number=1, kind="issue", title="t", labels=set(), url="u")

        offenders = []
        for ad in agents:
            f = AGENTS_DIR / f"{ad.agent}.md"
            if not f.is_file():
                continue
            resolved = po._resolve_agent_invocation(
                ad, wi, repo="o/r", default_extra_tools=defaults
            )
            if resolved is None:
                continue
            granted = {
                t[5:-1].split()[0]
                for t in resolved.allowed_tools
                if t.startswith("Bash(") and t[5:-1].split()
            }
            for word in self._bash_command_words(f.read_text()):
                if word in self.MUTATORS and word not in granted:
                    offenders.append(f"{ad.agent}: `{word}` used but not granted")

        assert offenders == [], (
            "agent prompts invoke filesystem commands their allowlist denies:\n  "
            + "\n  ".join(sorted(set(offenders)))
        )


# ---------------------------------------------------------------------------
# Scenario: Orchestrator removes the scratch directory on the failure path
# Scenario: A retry receives an empty scratch directory
#
# TestScratchScripts covers the two scripts standing alone. These cover the
# other half: that the orchestrator actually schedules them, on the path where
# it matters most. Cleanup that only runs on the happy path leaks precisely the
# runs most likely to leave debris.
# ---------------------------------------------------------------------------


class TestOrchestratorSchedulesTeardownOnEveryPath:

    def _run_agent_with(self, monkeypatch, session_id, invoke_side_effect):
        """Drive _run_agent with the agent invocation stubbed out.

        Everything before and after the invocation is the real code path, so
        the scratch hooks run for real against a real directory.
        """
        import pipeline_orchestrator as po

        monkeypatch.setattr(po, "_HEADLESS", True)
        monkeypatch.setattr(po, "_compute_agent_session_id",
                            lambda *a, **k: session_id)
        monkeypatch.setattr(po, "_acquire_wip_and_announce",
                            lambda *a, **k: None)
        monkeypatch.setattr(po, "_emit_audit_event", lambda *a, **k: None)
        monkeypatch.setattr(po, "invoke_agent", invoke_side_effect)

        return po._run_agent(
            _agent_def(), _work_item(), dry_run=False, repo="owner/repo",
            labels=set(), session_id=session_id, default_extra_tools=None,
            concurrency=None, gh=MagicMock(), pipeline_map={},
        )

    def test_scratch_is_removed_after_an_agent_crashes_without_a_sentinel(
        self, monkeypatch
    ):
        """The failure path, which is where debris actually accumulates."""
        session_id = "ais-v1-test-teardown-failure"
        scratch = Path("/tmp") / session_id
        shutil.rmtree(scratch, ignore_errors=True)

        def crashing_invoke(*args, **kwargs):
            scratch.mkdir(parents=True, exist_ok=True)
            (scratch / "half-written.json").write_text("{")
            from pipeline_orchestrator import AgentRunResult
            return AgentRunResult(success=False, captured_tail="boom")

        try:
            self._run_agent_with(monkeypatch, session_id, crashing_invoke)
            assert not scratch.exists(), (
                "scratch survived a crash with no sentinel -- the same teardown "
                "must run as on the success path"
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_scratch_is_removed_after_a_successful_run(self, monkeypatch):
        session_id = "ais-v1-test-teardown-success"
        scratch = Path("/tmp") / session_id
        shutil.rmtree(scratch, ignore_errors=True)

        def completing_invoke(*args, **kwargs):
            scratch.mkdir(parents=True, exist_ok=True)
            (scratch / "body.md") .write_text("posted already")
            from pipeline_orchestrator import AgentRunResult
            return AgentRunResult(success=True,
                                  captured_tail="AI_AGILE_STATUS: complete")

        try:
            self._run_agent_with(monkeypatch, session_id, completing_invoke)
            assert not scratch.exists()
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_a_retry_cannot_read_the_previous_attempt_s_files(self, monkeypatch):
        """SESSION_ID is stable across retries (the retry suffix goes into
        session_uuid_seed), so attempt 2 gets the same directory attempt 1 used.
        It must still start empty, or a failed attempt's half-written state
        becomes attempt 2's input."""
        session_id = "ais-v1-test-retry-clean"
        scratch = Path("/tmp") / session_id
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        (scratch / "attempt-1-leftover.json").write_text("{")

        seen_at_spawn = []
        real_popen = subprocess.Popen

        def fake_popen(cmd, **kwargs):
            # The scratch hooks run via subprocess.run, which is built on
            # Popen -- let them through or they silently no-op.
            if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "bash":
                return real_popen(cmd, **kwargs)
            path = kwargs.get("env", {}).get("AI_AGILE_SCRATCH", "")
            directory = Path(path) if path else None
            seen_at_spawn.append(
                sorted(x.name for x in directory.iterdir())
                if directory and directory.is_dir() else None
            )
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.wait.return_value = 0
            return proc

        monkeypatch.setattr("pipeline_orchestrator._HEADLESS", True)
        try:
            with patch("subprocess.Popen", side_effect=fake_popen), \
                 patch("pipeline_orchestrator._claude_cli_usable", return_value=True), \
                 patch("pipeline_orchestrator._compute_agent_session_id",
                       return_value=session_id), \
                 patch("pipeline_orchestrator._resolve_agent_invocation") as mock_resolve:
                mock_resolve.return_value = MagicMock(
                    prompt="p", allowed_tools=["Read"], model=None,
                    max_turns=10, session_id=session_id,
                )
                # attempt=1 is the retry: same work item, same SESSION_ID.
                invoke_agent(_agent_def(), _work_item(), dry_run=False,
                             repo="owner/repo", attempt=1)

            assert seen_at_spawn, "Popen was never called"
            assert seen_at_spawn[0] == [], (
                f"the retry could read the previous attempt's files: "
                f"{seen_at_spawn[0]}"
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


class TestScratchLifecycleIsSelfHealing:

    def test_setup_clearing_removes_the_need_for_a_signal_handler(self):
        """#321's resolved design asked for teardown on the SIGTERM path that
        clears :wip. That is not implementable: the kill that ends a background
        tick is uncatchable, so a handler would not run anyway. Setup clearing
        before it creates covers the same case without one -- pin the property
        the design actually wanted, not the mechanism it named."""
        src = (Path(__file__).parent.parent / "pipeline"
               / "pipeline_orchestrator.py").read_text()
        assert "_clear_scratch_on_signal" not in src
        setup = (Path(__file__).parent.parent / ".github" / "scripts"
                 / "scratch-setup.sh").read_text()
        rm_at = setup.index("rm -rf")
        mkdir_at = setup.index("mkdir -p")
        assert rm_at < mkdir_at, (
            "setup must clear before it creates, or a tick killed mid-run "
            "hands its debris to the next one"
        )


# ---------------------------------------------------------------------------
# Review findings on PR #360 (DP-002, QA-005, SC-001).
# ---------------------------------------------------------------------------


class TestInteractivePathGetsARealScratchDirectory:
    """DP-002: the orchestrator path exported AI_AGILE_SCRATCH and created the
    directory; the interactive path did neither, so every hand-run agent fell
    through `${AI_AGILE_SCRATCH:-/tmp}` to a shared directory with fixed
    filenames. AGENTS.md promises the agent a per-run directory either way.
    """

    def test_resolve_only_prints_the_scratch_path(self):
        from pipeline_orchestrator import PRINT_PROMPT_ENV_KEYS
        assert "AI_AGILE_SCRATCH" in PRINT_PROMPT_ENV_KEYS, (
            "/run-agent reads the agent's env from --print-prompt; a key absent "
            "from this list cannot reach the agent"
        )

    def test_the_printed_scratch_path_is_per_session_not_bare_tmp(self):
        from pipeline_orchestrator import _build_agent_env, PRINT_PROMPT_ENV_KEYS
        session_id = "ais-v1-03-execute-pr-reviewer-issue-321"
        env = _build_agent_env(
            {"PATH": "/usr/bin"}, repo="owner/repo",
            work_item=_work_item(kind="issue", number=321),
            agent_session_id=session_id, session_scope="per_issue",
        )
        printable = {k: env[k] for k in PRINT_PROMPT_ENV_KEYS if k in env}
        assert printable["AI_AGILE_SCRATCH"] == f"/tmp/{session_id}"

    def test_the_scratch_path_carries_no_credential(self):
        """PRINT_PROMPT_ENV_KEYS is an allowlist precisely so a new entry cannot
        start leaking. The path is derived from SESSION_ID; assert it stays a
        path and nothing else joined the list alongside it."""
        from pipeline_orchestrator import PRINT_PROMPT_ENV_KEYS
        for key in PRINT_PROMPT_ENV_KEYS:
            assert not any(
                marker in key for marker in ("TOKEN", "KEY", "SECRET", "PASSWORD")
            ), f"{key} looks like a credential and must not be printed"

    def test_run_agent_creates_the_directory_before_writing_the_scope_file(self):
        """Order matters: once the scope file exists the hook denies `bash` to
        every agent that lacks the grant, which is most of them."""
        text = (Path(__file__).parent.parent / ".claude" / "commands"
                / "run-agent.md").read_text()
        setup_at = text.index("scratch-setup.sh")
        scope_at = text.index(".run-agent-scope.json")
        assert setup_at < scope_at, (
            "scratch-setup.sh must run before the scope file is written"
        )

    def test_run_agent_removes_the_directory_at_the_end(self):
        text = (Path(__file__).parent.parent / ".claude" / "commands"
                / "run-agent.md").read_text()
        assert "scratch-teardown.sh" in text


class TestTeardownIsPairedWithSetup:
    """QA-005: setup runs inside invoke_agent, so only agent steps get a
    directory. Tearing down for a script step pairs a teardown with no setup.
    """

    def test_script_steps_are_not_torn_down(self, monkeypatch):
        import pipeline_orchestrator as po

        torn_down = []
        monkeypatch.setattr(po, "_HEADLESS", True)
        monkeypatch.setattr(po, "_acquire_wip_and_announce", lambda *a, **k: None)
        monkeypatch.setattr(po, "_emit_audit_event", lambda *a, **k: None)
        monkeypatch.setattr(po, "invoke_script",
                            lambda *a, **k: po.AgentRunResult(success=True, captured_tail=""))
        monkeypatch.setattr(
            po, "_run_lifecycle_scripts",
            lambda scripts, path: torn_down.extend((s, path) for s in scripts),
        )

        # A real script step out of pipeline.json, not an agent step with its
        # type flipped: the pairing is enforced by load_pipeline leaving the
        # lifecycle lists empty for script steps, so the step has to come from
        # the same loader the orchestrator uses or the test proves nothing.
        agents, _ = po.load_pipeline(
            Path(__file__).parent.parent / "pipeline" / "pipeline.json"
        )
        agent_def = next(a for a in agents if a.step_type == "script")
        assert agent_def.lifecycle_before == [], (
            "load_pipeline must not give a script step lifecycle scripts"
        )

        po._run_agent(
            agent_def, _work_item(), dry_run=False, repo="owner/repo",
            labels=set(), session_id="sid", default_extra_tools=None,
            concurrency=None, gh=MagicMock(), pipeline_map={},
        )
        assert torn_down == [], (
            f"a script step was given a teardown it never had a setup for: {torn_down}"
        )

    def test_agent_steps_are_still_torn_down(self, monkeypatch):
        import pipeline_orchestrator as po

        torn_down = []
        monkeypatch.setattr(po, "_HEADLESS", True)
        monkeypatch.setattr(po, "_acquire_wip_and_announce", lambda *a, **k: None)
        monkeypatch.setattr(po, "_emit_audit_event", lambda *a, **k: None)
        monkeypatch.setattr(
            po, "invoke_agent",
            lambda *a, **k: po.AgentRunResult(success=True,
                                              captured_tail="AI_AGILE_STATUS: complete"),
        )
        monkeypatch.setattr(
            po, "_run_lifecycle_scripts",
            lambda scripts, path: torn_down.extend((s, path) for s in scripts),
        )

        po._run_agent(
            _agent_def(), _work_item(), dry_run=False, repo="owner/repo",
            labels=set(), session_id="sid", default_extra_tools=None,
            concurrency=None, gh=MagicMock(), pipeline_map={},
        )
        assert len(torn_down) == 1
        assert torn_down[0][0].endswith("scratch-teardown.sh")


class TestShippedFilesAreAscii:
    """SC-001: CLAUDE.md -- "Never write emoji or non-ASCII characters inside
    code, configuration, or workflow files. This includes Python source files,
    shell scripts, GitHub Actions workflow YAML files, and JSON files."

    Scoped to the trees this PR touches and that are already clean. Several
    older scripts and pipeline/*.json carry non-ASCII from before this rule was
    written; widening the scope is a separate cleanup, not this issue's work.
    """

    REPO_ROOT = Path(__file__).parent.parent

    def _offenders(self, path):
        text = path.read_text(encoding="utf-8")
        return sorted({c for c in text if ord(c) > 127})

    @pytest.mark.parametrize("name", [
        "architecture.json", "data.json", "documentation.json", "process.json",
        "security.json", "adrs.json", "ux-design.json", "testing.json",
    ])
    def test_standards_json_is_ascii(self, name):
        path = self.REPO_ROOT / "standards" / name
        assert self._offenders(path) == [], (
            f"{name} contains non-ASCII; use the \\uXXXX escape in JSON"
        )

    @pytest.mark.parametrize("name", ["scratch-setup.sh", "scratch-teardown.sh"])
    def test_scratch_scripts_are_ascii(self, name):
        path = self.REPO_ROOT / ".github" / "scripts" / name
        assert self._offenders(path) == [], f"{name} contains non-ASCII"


class TestCommitSweepRefusesNewRootFiles:
    """The enforcement half of #321.

    Every agent prompt carries the scratch rule, and the rule is still only an
    instruction: a bare filename resolves against the repo root because that is
    the working directory, so a leak is one invented filename away. That is how
    `pr_review_328.txt` reached a commit on issue-316 and how
    `artefact_comment.txt` reached `d0471f1`.

    commit-agent-work.sh now unstages new root-level files before the commit is
    written, which closes the harm without depending on agent compliance.
    """

    SCRIPT = (Path(__file__).parent.parent / ".github" / "scripts"
              / "commit-agent-work.sh")

    def _repo(self, tmp_path):
        """A repo with an `origin` the script can fetch and push, on issue-999."""
        origin = tmp_path / "origin.git"
        work = tmp_path / "work"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)

        def git(*args):
            subprocess.run(["git", *args], cwd=work, check=True,
                           capture_output=True, text=True)

        git("config", "user.email", "t@example.invalid")
        git("config", "user.name", "t")
        (work / "src").mkdir()
        (work / "README.md").write_text("readme\n")
        (work / "src" / "a.py").write_text("code\n")
        git("checkout", "-q", "-B", "issue-999")
        git("add", "-A")
        git("commit", "-qm", "init")
        git("push", "-q", "origin", "issue-999")
        return work

    def _run_sweep(self, work):
        env = {
            **os.environ,
            "AGENT_NAME": "03_execute/pr-reviewer",
            "ISSUE_NUMBER": "999",
            "BRANCH_SUFFIX": "",
        }
        env.pop("GITHUB_TOKEN", None)
        env.pop("GH_TOKEN", None)
        return subprocess.run(
            ["bash", str(self.SCRIPT)], cwd=work, env=env,
            capture_output=True, text=True, timeout=60,
        )

    def _committed_files(self, work):
        out = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
            cwd=work, capture_output=True, text=True, check=True,
        )
        return sorted(f for f in out.stdout.split("\n") if f.strip())

    def test_a_leaked_root_file_never_reaches_the_commit(self, tmp_path):
        work = self._repo(tmp_path)
        # The exact filenames pr-reviewer invented on issue #348.
        (work / "review_body.json").write_text('{"body": "leak"}')
        (work / "announce_close.json").write_text('{"body": "leak"}')

        result = self._run_sweep(work)
        assert result.returncode == 0, result.stderr

        committed = self._committed_files(work)
        assert "review_body.json" not in committed
        assert "announce_close.json" not in committed
        assert "created new file(s) at the repo root" in result.stderr

    def test_the_agent_s_real_work_still_lands(self, tmp_path):
        """The guard must not cost the agent its actual output."""
        work = self._repo(tmp_path)
        (work / "README.md").write_text("readme\nedited by the agent\n")
        (work / "src" / "b.py").write_text("new module\n")
        (work / "review_body.json").write_text('{"body": "leak"}')

        result = self._run_sweep(work)
        assert result.returncode == 0, result.stderr

        committed = self._committed_files(work)
        assert "README.md" in committed, "a modified tracked root file is legitimate"
        assert "src/b.py" in committed, "a new nested file is legitimate"
        assert "review_body.json" not in committed

    def test_the_leaked_file_is_left_on_disk_not_destroyed(self, tmp_path):
        """Unstage, do not delete -- nothing an agent produced is thrown away,
        and the violation stays visible to whoever looks."""
        work = self._repo(tmp_path)
        (work / "src" / "b.py").write_text("new module\n")
        (work / "review_body.json").write_text('{"body": "leak"}')

        self._run_sweep(work)
        assert (work / "review_body.json").exists()
        assert (work / "review_body.json").read_text() == '{"body": "leak"}'

    def test_a_run_that_leaks_only_root_files_commits_nothing(self, tmp_path):
        """pr-reviewer writes no source. A run whose entire output is leaks must
        produce no commit at all, rather than an empty or leak-only one."""
        work = self._repo(tmp_path)
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work,
                                capture_output=True, text=True, check=True).stdout
        (work / "review_body.json").write_text('{"body": "leak"}')

        result = self._run_sweep(work)
        assert result.returncode == 0, result.stderr

        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work,
                               capture_output=True, text=True, check=True).stdout
        assert before == after, "a leak-only run must not create a commit"

