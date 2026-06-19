"""Integration tests for commit-agent-work.sh — exercises real git I/O.

These tests create temporary local git repositories and invoke the shell
script directly. They are excluded from the default pytest run
(see pytest.ini) because they perform real filesystem and subprocess I/O.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "pipeline"))
import pipeline_orchestrator as orch

_SCRIPT_PATH = orch.SUBMODULE_ROOT / ".github" / "scripts" / "commit-agent-work.sh"

_GIT_ENV_BASE = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _make_git_env() -> dict:
    return {**os.environ, **_GIT_ENV_BASE}


def _bootstrap_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    """Create a bare origin and a working clone with an issue-42 branch.

    Returns (origin_path, work_path, default_branch_name).
    The working clone is left on the default branch so the script can
    switch to issue-42 as expected.
    """
    git_env = _make_git_env()

    origin = tmp_path / "origin.git"
    origin.mkdir()
    subprocess.run(
        ["git", "init", "--bare", str(origin)],
        check=True, capture_output=True, env=git_env,
    )

    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", str(work)], check=True, capture_output=True, env=git_env)
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)],
        cwd=str(work), check=True, capture_output=True, env=git_env,
    )

    (work / "init.txt").write_text("init")
    subprocess.run(["git", "add", "init.txt"], cwd=str(work), check=True, capture_output=True, env=git_env)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(work), check=True, capture_output=True, env=git_env)

    default_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(work), check=True, capture_output=True, text=True, env=git_env,
    ).stdout.strip()

    subprocess.run(
        ["git", "push", "origin", f"HEAD:{default_branch}"],
        cwd=str(work), check=True, capture_output=True, env=git_env,
    )
    subprocess.run(
        ["git", "checkout", "-b", "issue-42"],
        cwd=str(work), check=True, capture_output=True, env=git_env,
    )
    subprocess.run(
        ["git", "push", "origin", "issue-42:issue-42"],
        cwd=str(work), check=True, capture_output=True, env=git_env,
    )
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=str(work), check=True, capture_output=True, env=git_env,
    )

    return origin, work, default_branch


def test_commit_agent_work_script_creates_correct_commit_message(tmp_path):
    """Scenario: New script stages, commits, and pushes agent work.

    Given a local git repo with branch issue-42 tracking a local bare origin,
    And a dirty working tree with an untracked file,
    When commit-agent-work.sh is invoked with AGENT_NAME=03_execute/coder
         and ISSUE_NUMBER=42,
    Then a commit is created on issue-42 with message
         '[agent] 03_execute/coder — issue #42'
    And that commit is present in the origin bare repo.
    """
    git_env = _make_git_env()
    origin, work, _ = _bootstrap_repo(tmp_path)

    (work / "agent_output.txt").write_text("agent wrote this")

    result = subprocess.run(
        ["bash", str(_SCRIPT_PATH)],
        cwd=str(work),
        env={**git_env, "AGENT_NAME": "03_execute/coder", "ISSUE_NUMBER": "42"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"commit-agent-work.sh exited {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    log_result = subprocess.run(
        ["git", "log", "--format=%s", "issue-42", "-1"],
        cwd=str(origin),
        capture_output=True, text=True, check=True, env=git_env,
    )
    assert log_result.stdout.strip() == "[agent] 03_execute/coder — issue #42", (
        f"Unexpected commit message: {log_result.stdout.strip()!r}"
    )


def test_clean_working_tree_exits_zero_with_no_commit(tmp_path):
    """Scenario: commit-agent-work.sh exits 0 without creating a commit when working tree is clean.

    Given a local git repo with branch issue-42 tracking a local bare origin,
    And a clean working tree (no untracked or modified files),
    When commit-agent-work.sh is invoked with AGENT_NAME=03_execute/coder
         and ISSUE_NUMBER=42,
    Then the script exits 0
    And git log on issue-42 in the bare origin contains no '[agent]' commit.
    """
    git_env = _make_git_env()
    origin, work, _ = _bootstrap_repo(tmp_path)

    result = subprocess.run(
        ["bash", str(_SCRIPT_PATH)],
        cwd=str(work),
        env={**git_env, "AGENT_NAME": "03_execute/coder", "ISSUE_NUMBER": "42"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"commit-agent-work.sh exited {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    log_result = subprocess.run(
        ["git", "log", "--format=%s", "issue-42"],
        cwd=str(origin),
        capture_output=True, text=True, check=True, env=git_env,
    )
    assert "[agent]" not in log_result.stdout, (
        f"Expected no [agent] commit on issue-42 but found:\n{log_result.stdout}"
    )


def test_workflow_files_without_bot_token_exits_nonzero(tmp_path):
    """Scenario: staging .github/workflows/ files without AI_AGILE_BOT_TOKEN causes exit 1.

    Given a local git repo with branch issue-42 tracking a local bare origin,
    And .github/workflows/ci.yml present in the working tree,
    When commit-agent-work.sh is invoked with AI_AGILE_BOT_TOKEN unset,
    Then the script exits 1
    And stderr contains 'AI_AGILE_BOT_TOKEN'.
    """
    git_env = _make_git_env()
    origin, work, _ = _bootstrap_repo(tmp_path)

    # Create a workflows directory and file to trigger the bot-token guard.
    workflows_dir = work / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "ci.yml").write_text("name: CI\n")

    # Build a filtered env with AI_AGILE_BOT_TOKEN explicitly absent.
    filtered_env = {
        k: v for k, v in git_env.items()
        if k not in ("AI_AGILE_BOT_TOKEN",)
    }
    filtered_env["AGENT_NAME"] = "03_execute/coder"
    filtered_env["ISSUE_NUMBER"] = "42"

    result = subprocess.run(
        ["bash", str(_SCRIPT_PATH)],
        cwd=str(work),
        env=filtered_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"Expected exit 1 when AI_AGILE_BOT_TOKEN is unset but got {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "AI_AGILE_BOT_TOKEN" in result.stderr, (
        f"Expected 'AI_AGILE_BOT_TOKEN' in stderr but got:\n{result.stderr!r}"
    )
