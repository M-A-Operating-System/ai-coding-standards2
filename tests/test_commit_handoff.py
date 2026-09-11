"""The step commits; the orchestrator moves the ref.

PRODUCT.md, "What lands in git":

  An agent's work is not durable because the agent returned successfully. It
  is durable because it was committed. [...] So a step that produces code
  commits it, as it goes, into the isolated worktree it was given. The commit
  is the deliverable, not a side effect of returning cleanly.

and:

  **What this replaces.** Extracting a step's work after the fact -- stash it,
  reset the branch to the remote, replay the stash, commit whatever appears --
  fails in three directions at once [...] Those are not defects in the
  extraction script. They are properties of extracting work from a process
  instead of having the process commit it.

Issue #448 is the second of those three directions, reported from a sibling
repo: a branch that moved between the stash and the replay conflicts with
itself, the pop fails, and the step is reported failed even when its work
already landed. The first direction was hit in the same incident -- a
continuously-drifting submodule gitlink made `git status --porcelain` non-empty
on runs that had produced nothing, dragging no-op runs through the whole path.

These tests exercise the replacement end to end against real git repositories,
because the failures being fixed were all in git's actual behaviour rather than
in any decision the code made.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

import pipeline_orchestrator as po  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path):
    """An origin plus a clone checked out to issue-42, one commit in."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")
    (work / "src").mkdir()
    (work / "src" / "a.py").write_text("code\n")
    _git(work, "checkout", "-q", "-B", "issue-42")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "init")
    _git(work, "push", "-q", "origin", "issue-42")
    return work


def _agent(commit_after=True):
    return po.AgentDef(
        agent="03_execute/coder", phase="03_execute", objects=["issue"],
        trigger={}, dependencies=[], human_gate_after=False,
        human_gate_label=None, description="t", commit_after=commit_after,
        flow="test-flow", flow_naming={"branch": "issue-{number}"},
    )


def _work_item():
    return po.WorkItem(
        number=42, kind="issue", title="T", labels=set(),
        url="https://github.com/test/repo/issues/42",
    )


def _remote_head(work):
    return _git(work, "rev-parse", "origin/issue-42").stdout.strip()


def _local_head(work):
    return _git(work, "rev-parse", "HEAD").stdout.strip()


class TestTheStepsCommitBecomesDurable:
    def test_the_ref_moves_to_what_the_step_committed(self, repo):
        (repo / "src" / "b.py").write_text("new\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "the step's own commit")

        assert po._push_step_branch(_agent(), _work_item(), cwd=str(repo)) is None
        assert _remote_head(repo) == _local_head(repo)

    def test_partial_work_lands_when_the_step_committed_more_than_once(self, repo):
        """A step killed at its budget ceiling leaves behind whatever it had
        committed by then. Every commit it made is pushed, not just the last."""
        for n in range(3):
            (repo / "src" / f"part{n}.py").write_text("x\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", f"part {n}")

        assert po._push_step_branch(_agent(), _work_item(), cwd=str(repo)) is None
        landed = _git(repo, "ls-tree", "--name-only", "-r", "origin/issue-42").stdout
        for n in range(3):
            assert f"src/part{n}.py" in landed


class TestTheFailuresOfExtractingWorkAfterTheFact:
    """Issue #448's three directions, each now a non-event."""

    def test_unrelated_dirt_does_not_drag_a_no_op_run_anywhere(self, repo):
        """The first direction: a continuously-drifting submodule gitlink made
        `git status --porcelain` non-empty, so a run that produced nothing
        still entered the stash/checkout/pop path. Nothing here reads the
        working tree to decide whether to act -- only what was committed."""
        (repo / "noise.txt").write_text("dirt from somewhere else\n")
        before = _remote_head(repo)

        reason = po._push_step_branch(_agent(), _work_item(), cwd=str(repo))

        assert reason is not None and "uncommitted" in reason, (
            "uncommitted content must be reported, since it dies with the worktree"
        )
        assert _remote_head(repo) == before, "no commits means no ref movement"

    def test_a_branch_that_moved_underneath_is_a_plain_rejection(self, repo):
        """The second direction, #448 itself: the extraction reset the branch
        to the remote between stashing and replaying, so a branch that had
        moved conflicted with itself and the step was reported failed even
        when its work had landed.

        Nothing is replayed now. A remote that genuinely moved is an ordinary
        non-fast-forward rejection, reported with git's own message, and the
        step's commits are still in its worktree.
        """
        other = repo.parent / "other"
        subprocess.run(
            ["git", "clone", "-q", str(repo.parent / "origin.git"), str(other)],
            check=True,
        )
        _git(other, "config", "user.email", "o@example.invalid")
        _git(other, "config", "user.name", "o")
        _git(other, "checkout", "-q", "issue-42")
        (other / "src" / "elsewhere.py").write_text("someone else\n")
        _git(other, "add", "-A")
        _git(other, "commit", "-qm", "a push from elsewhere")
        _git(other, "push", "-q", "origin", "issue-42")

        (repo / "src" / "b.py").write_text("new\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "the step's own commit")
        head = _local_head(repo)

        reason = po._push_step_branch(_agent(), _work_item(), cwd=str(repo))

        assert reason is not None and "push to issue-42" in reason
        assert _local_head(repo) == head, "the step's commit is still in its worktree"

    def test_a_step_that_did_not_return_cleanly_still_had_its_work_committed(self, repo):
        """The third direction: a step returning anything but success never
        reached the extraction at all, so its edits were discarded. Committing
        is the step's own act now, so the work exists before any outcome is
        decided -- and a "review" outcome is pushed like any other.
        """
        (repo / "src" / "b.py").write_text("written before the step gated\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "work done on a run that ends in review")

        assert po._push_step_branch(_agent(), _work_item(), cwd=str(repo)) is None
        assert _remote_head(repo) == _local_head(repo)


class TestRecoveringABranchLeftAhead:
    """A step killed mid-run never returns, so nothing pushes what it
    committed. The next run's worktree setup resets the branch to the remote,
    which is precisely where that work would be lost."""

    def test_commits_from_a_killed_run_are_pushed_before_the_branch_is_reset(self, repo, monkeypatch):
        monkeypatch.chdir(repo)
        (repo / "src" / "b.py").write_text("committed but never pushed\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "a killed run's commit")
        stranded = _local_head(repo)
        assert _remote_head(repo) != stranded

        po._recover_unpushed_commits("issue-42")

        assert _remote_head(repo) == stranded

    def test_a_branch_level_with_its_remote_is_left_alone(self, repo, monkeypatch):
        monkeypatch.chdir(repo)
        before = _remote_head(repo)
        po._recover_unpushed_commits("issue-42")
        assert _remote_head(repo) == before

    def test_a_branch_that_cannot_be_pushed_does_not_fail_the_run(self, repo, monkeypatch):
        """Best-effort: failing the whole run over a previous run's leftovers
        would strand the branch rather than rescue it."""
        (repo / "src" / "b.py").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "unpushed")
        _git(repo, "remote", "set-url", "origin", str(repo.parent / "nonexistent.git"))

        monkeypatch.chdir(repo)
        po._recover_unpushed_commits("issue-42")  # must not raise


class TestWhatTheStepIsAndIsNotToldItMayDo:
    def test_every_committing_step_is_granted_the_commands_to_commit(self):
        """A step whose deliverable is a commit and whose allowlist omits
        `git commit` fails in a way no reader of pipeline.json could predict.
        The declaration and the capability must agree (AS-1)."""
        agents, defaults = po.load_pipeline(po.PIPELINE_PATH)
        committing = [a for a in agents if a.commit_after]
        assert committing, "no step declares git_ops.commit_after"
        for agent_def in committing:
            granted = set(defaults) | set(agent_def.extra_allowedTools)
            for needed in ("Bash(git add *)", "Bash(git commit *)"):
                assert needed in granted, (
                    f"{agent_def.agent} declares git_ops.commit_after but is not "
                    f"granted {needed}"
                )

    # PRODUCT.md names this as unfinished target-state work in as many words:
    # "one step, merge-conflict, both pushes and force-pushes in its rebase
    # path, which this section and the history rule below already disallow."
    # Naming it here keeps the guard live for every other step and makes the
    # exception something a reader can see, rather than a hole in the check.
    _KNOWN_PUSHING_STEP = "03_execute/merge-conflict"

    def test_no_step_but_the_one_known_exception_is_granted_a_push(self):
        """Pushing is the orchestrator's. The allowlist says what the step is
        meant to do; the credential decides what it can do."""
        agents, defaults = po.load_pipeline(po.PIPELINE_PATH)
        offenders = {
            agent_def.agent
            for agent_def in agents
            for tool in set(defaults) | set(agent_def.extra_allowedTools)
            if tool.startswith("Bash(git push")
        }
        assert offenders <= {self._KNOWN_PUSHING_STEP}, (
            f"{sorted(offenders - {self._KNOWN_PUSHING_STEP})} granted git push; "
            "the orchestrator owns the branch ref (PRODUCT.md, 'What lands in git')"
        )

    def test_the_one_exception_is_still_outstanding_rather_than_forgotten(self):
        """When merge-conflict's rebase moves to the orchestrator, this test is
        what says so: it fails, and the exception above comes out with it."""
        agents, _ = po.load_pipeline(po.PIPELINE_PATH)
        by_name = {a.agent: a for a in agents}
        assert "Bash(git push *)" in set(
            by_name[self._KNOWN_PUSHING_STEP].extra_allowedTools
        ), (
            f"{self._KNOWN_PUSHING_STEP} no longer pushes -- drop it from "
            "_KNOWN_PUSHING_STEP and delete this test"
        )

    def test_the_pushing_credential_is_kept_out_of_a_step_s_environment(self):
        """The worktree a step runs in shares the repository's config, so a
        credential stored there would be one the step could push with. The
        orchestrator clears it and keeps the header in its own process env,
        which agents never inherit."""
        assert not any(
            k.startswith("GIT_CONFIG") for k in po.AGENT_ENV_PASSTHROUGH
        ), "GIT_CONFIG_* embeds the push token and must never reach an agent"
        source = Path(po.__file__).read_text()
        assert '"http.https://github.com/.extraHeader"' in source
        assert '"--unset-all"' in source, (
            "the checkout's stored auth header must be cleared, or every step's "
            "worktree holds a credential that can push"
        )
