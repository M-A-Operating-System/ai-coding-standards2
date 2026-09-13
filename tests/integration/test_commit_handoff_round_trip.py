"""The whole handoff against real git: worktree in, branch ref out.

The unit tests around `_push_step_branch` stub git. This one does not, because
every failure the handoff replaces was in git's own behaviour rather than in a
decision the code made (issue #448): a branch that moved between a stash and
its replay, a working tree that was dirty for reasons nothing in the run caused.

So this exercises the sequence end to end -- `_create_run_worktree` checks the
branch out into its own directory, a commit is made there the way a step makes
it, and `_push_step_branch` moves the remote ref -- and then the one case the
unit tests cannot reach at all: a run killed before it returned, whose commits
only survive because the next run's worktree setup pushes a branch left ahead
before resetting it.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "pipeline"))

import pipeline_orchestrator as po  # noqa: E402

BRANCH = "issue-4242"


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
    )


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """An origin plus the orchestrator's own checkout, on the default branch.

    The orchestrator runs git from its process cwd, so the fixture chdirs
    there and points the worktree root at this tmp repo -- otherwise
    `_create_run_worktree` would add a worktree inside the real repository.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")
    (work / "src").mkdir()
    (work / "src" / "a.py").write_text("code\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "initial")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-B", BRANCH)
    _git(work, "push", "-q", "origin", BRANCH)
    _git(work, "checkout", "-q", "main")

    monkeypatch.chdir(work)
    monkeypatch.setattr(po, "_WORKTREE_ROOT", work / ".worktrees")
    return work


def _agent():
    return po.AgentDef(
        agent="03_execute/coder", phase="03_execute", objects=["issue"],
        trigger={}, dependencies=[], human_gate_after=False,
        human_gate_label=None, description="t", commit_after=True,
        flow="test-flow", flow_naming={"branch": "issue-{number}"},
    )


def _work_item():
    return po.WorkItem(
        number=4242, kind="issue", title="T", labels=set(),
        url="https://github.com/test/repo/issues/4242",
    )


def _commit_in(worktree, path, body, message):
    target = Path(worktree) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    _git(worktree, "config", "user.email", "step@example.invalid")
    _git(worktree, "config", "user.name", "step")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", message)
    return _git(worktree, "rev-parse", "HEAD").stdout.strip()


def _remote_head(checkout, branch=BRANCH):
    _git(checkout, "fetch", "-q", "origin", branch)
    return _git(checkout, "rev-parse", f"origin/{branch}").stdout.strip()


def test_a_step_s_commit_reaches_the_remote_through_its_own_worktree(checkout):
    worktree = po._create_run_worktree(BRANCH)
    try:
        assert os.path.isdir(worktree)
        assert worktree != str(checkout), "the step must not share the orchestrator's tree"

        head = _commit_in(worktree, "src/b.py", "the step's work\n", "add b")

        assert po._push_step_branch(_agent(), _work_item(), cwd=worktree) is None
        assert _remote_head(checkout) == head
    finally:
        po._remove_run_worktree(worktree)


def test_the_commit_survives_the_worktree_it_was_made_in(checkout):
    """A commit is durable once the ref moves: the worktree can be removed and
    the objects survive in the shared store."""
    worktree = po._create_run_worktree(BRANCH)
    head = _commit_in(worktree, "src/b.py", "the step's work\n", "add b")
    assert po._push_step_branch(_agent(), _work_item(), cwd=worktree) is None
    po._remove_run_worktree(worktree)

    assert not os.path.exists(worktree)
    assert _remote_head(checkout) == head
    landed = _git(checkout, "ls-tree", "--name-only", "-r", f"origin/{BRANCH}").stdout
    assert "src/b.py" in landed


def test_a_killed_run_s_commits_are_recovered_by_the_next_run(checkout):
    """The case no unit test reaches: the step committed, was killed before it
    returned, so nothing pushed. The next run's worktree setup would reset the
    branch to the remote -- which is exactly where that work would be lost."""
    first = po._create_run_worktree(BRANCH)
    stranded = _commit_in(first, "src/b.py", "committed, never pushed\n", "killed run")
    assert _remote_head(checkout) != stranded
    # A run killed mid-flight leaves its worktree behind; SIGTERM cleanup is
    # best-effort, so the next run finds it and clears it itself.

    second = po._create_run_worktree(BRANCH)
    try:
        assert _remote_head(checkout) == stranded, (
            "the earlier run's commit was discarded by the branch reset"
        )
        assert _git(second, "rev-parse", "HEAD").stdout.strip() == stranded, (
            "the new worktree must start from the recovered commit, not before it"
        )
    finally:
        po._remove_run_worktree(second)


def test_a_second_run_builds_on_what_the_first_one_pushed(checkout):
    """Two invocations of the same step -- the review-cycle path -- accumulate
    on one branch rather than each starting from the base."""
    first = po._create_run_worktree(BRANCH)
    _commit_in(first, "src/b.py", "round one\n", "round one")
    assert po._push_step_branch(_agent(), _work_item(), cwd=first) is None
    po._remove_run_worktree(first)

    second = po._create_run_worktree(BRANCH)
    try:
        assert (Path(second) / "src" / "b.py").read_text() == "round one\n"
        head = _commit_in(second, "src/c.py", "round two\n", "round two")
        assert po._push_step_branch(_agent(), _work_item(), cwd=second) is None
        assert _remote_head(checkout) == head
        landed = _git(checkout, "ls-tree", "--name-only", "-r", f"origin/{BRANCH}").stdout
        assert "src/b.py" in landed and "src/c.py" in landed
    finally:
        po._remove_run_worktree(second)
