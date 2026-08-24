"""
Tests for the post-agent repo-root sweep (issue #376).

Agents are told to write working files under $AI_AGILE_SCRATCH. When one
writes to a relative path instead, the file lands at the repository root.
`commit-agent-work.sh` already unstages such files, but only for agents with
`git_ops.commit_after: true` -- prd-writer, pr-reviewer and issue-classifier
have none, and all three were observed leaving files there. These tests cover
the orchestrator-side sweep that runs for every agent.

The sweep is deliberately conservative: it removes only files that were absent
before the invocation, so a file a human left in the tree is never touched.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

import pipeline_orchestrator as po  # noqa: E402


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A throwaway git repo, with cwd pointed at it."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("tracked\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        cwd=tmp_path, check=True,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_AGILE_ROOT", str(tmp_path))
    return tmp_path


def _agent(name="01_product_docs/prd-writer"):
    return po.AgentDef(
        agent=name,
        phase=name.split("/", 1)[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
    )


# --- _untracked_root_files -------------------------------------------------


def test_lists_untracked_files_at_the_root(git_repo):
    (git_repo / "leaked.md").write_text("x")
    assert "leaked.md" in po._untracked_root_files()


def test_ignores_tracked_files(git_repo):
    assert "tracked.txt" not in po._untracked_root_files()


def test_ignores_files_in_subdirectories(git_repo):
    nested = git_repo / "docs"
    nested.mkdir()
    (nested / "note.md").write_text("x")
    assert po._untracked_root_files() == set(), \
        "only depth-0 files are the agent's residue; subdirectories are real work"


def test_returns_none_when_git_cannot_be_consulted(tmp_path, monkeypatch):
    """None, not an empty set -- the distinction is load-bearing.

    The result is used as the "before" baseline. An empty baseline means
    "every untracked root file is new", so returning set() on a failed probe
    would turn a transient git error into a delete-everything sweep.
    """
    monkeypatch.setattr(po, "_repo_root", lambda: tmp_path)
    assert po._untracked_root_files() is None


def test_sweep_skips_when_the_baseline_is_unknown(git_repo, caplog):
    """A failed probe must lose a cleanup, never delete a file blindly."""
    (git_repo / "not_the_agents.md").write_text("pre-existing")

    with caplog.at_level("WARNING"):
        po._sweep_agent_root_files(_agent(), None)

    assert (git_repo / "not_the_agents.md").exists()
    assert "skipping the sweep" in caplog.text


# --- _sweep_agent_root_files ----------------------------------------------


def test_removes_a_file_the_agent_added(git_repo):
    before = po._untracked_root_files()
    (git_repo / "ann_open.md").write_text("announcement")

    po._sweep_agent_root_files(_agent(), before)

    assert not (git_repo / "ann_open.md").exists()


def test_removes_every_file_the_agent_added(git_repo):
    """prd-writer left four; pr-reviewer left three."""
    before = po._untracked_root_files()
    for name in ("ann_open.md", "ann_close.md", "review_body.md"):
        (git_repo / name).write_text("x")

    po._sweep_agent_root_files(_agent("03_execute/pr-reviewer"), before)

    assert po._untracked_root_files() == set()


def test_leaves_a_file_that_existed_before_the_run(git_repo):
    """A human's untracked file must survive an agent invocation."""
    (git_repo / "my_notes.md").write_text("do not delete")
    before = po._untracked_root_files()
    (git_repo / "leaked.md").write_text("x")

    po._sweep_agent_root_files(_agent(), before)

    assert (git_repo / "my_notes.md").exists(), \
        "the sweep must only remove what the agent itself added"
    assert not (git_repo / "leaked.md").exists()


def test_leaves_subdirectory_work_untouched(git_repo):
    """The coder writes real files under docs/ and pipeline/; never sweep those."""
    before = po._untracked_root_files()
    nested = git_repo / "docs"
    nested.mkdir()
    (nested / "feature.md").write_text("real work")

    po._sweep_agent_root_files(_agent("03_execute/coder"), before)

    assert (nested / "feature.md").exists()


def test_names_the_agent_and_the_files_it_left(git_repo, caplog):
    """A silent sweep would hide the bug it exists to contain."""
    before = po._untracked_root_files()
    (git_repo / "snapshot_comment.md").write_text("x")

    with caplog.at_level("WARNING"):
        po._sweep_agent_root_files(_agent(), before)

    logged = caplog.text
    assert "01_product_docs/prd-writer" in logged
    assert "snapshot_comment.md" in logged


def test_is_silent_when_the_agent_left_nothing(git_repo, caplog):
    before = po._untracked_root_files()

    with caplog.at_level("WARNING"):
        po._sweep_agent_root_files(_agent(), before)

    assert caplog.text == ""


def test_survives_a_file_that_cannot_be_removed(git_repo, caplog, monkeypatch):
    """A sweep failure is logged, never raised -- it must not fail the run."""
    before = po._untracked_root_files()
    (git_repo / "leaked.md").write_text("x")

    def boom(self):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "unlink", boom)

    with caplog.at_level("WARNING"):
        po._sweep_agent_root_files(_agent(), before)

    assert "could not remove" in caplog.text


def test_root_is_resolved_from_git_not_the_cwd(git_repo, monkeypatch):
    """Started from a subdirectory, the sweep must still act on the repo root.

    AI_AGILE_ROOT is conventionally ".", so reading it directly would leave
    this cwd-relative and the sweep would operate in the wrong directory.
    """
    nested = git_repo / "pipeline"
    nested.mkdir()
    monkeypatch.chdir(nested)
    monkeypatch.setenv("AI_AGILE_ROOT", ".")

    assert po._repo_root() == git_repo.resolve()

    before = po._untracked_root_files()
    (git_repo / "leaked.md").write_text("x")
    po._sweep_agent_root_files(_agent(), before)

    assert not (git_repo / "leaked.md").exists()
