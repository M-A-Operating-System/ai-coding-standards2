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
import re
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

    def test_every_committing_step_is_told_to_commit(self):
        """The grant is necessary and not sufficient.

        A step can hold `Bash(git commit *)` and never be told to use it. That
        is not a smaller version of the same defect -- it is the whole defect:
        the step writes its files, commits nothing, and the orchestrator
        reports it failed for having delivered nothing, discarding the work
        with the worktree. Exactly the loss this arrangement exists to stop.

        Caught `00_ondemand/new-agent`, whose prompt was the one of three not
        updated when committing moved into the step.
        """
        agents, _ = po.load_pipeline(po.PIPELINE_PATH)
        prompts = Path(po.__file__).parent.parent / ".claude" / "agents"
        for agent_def in (a for a in agents if a.commit_after):
            path = prompts / f"{agent_def.agent}.md"
            assert path.is_file(), f"{agent_def.agent} has no prompt at {path}"
            text = " ".join(path.read_text().split())
            assert "git commit" in text, (
                f"{agent_def.agent} declares git_ops.commit_after but its prompt "
                "never tells it to commit; it will deliver nothing"
            )
            assert "git push" in text, (
                f"{agent_def.agent} commits but its prompt never says pushing is "
                "the orchestrator's"
            )

    # The claim being guarded against is "something other than this step does
    # the committing". Matched as whole phrases naming that actor, rather than
    # on any appearance of the words: a prompt may legitimately say "you do not
    # need to commit generated files", and a test that fails on a true sentence
    # gets deleted rather than fixed.
    #
    # Each pattern is a phrasing that was actually in coder.md after #443
    # merged, or a near neighbour of one, and each asserts the orchestrator or
    # some other party commits on the step's behalf. Every one of them is
    # load-bearing: the test below pins at least one sentence that only that
    # pattern catches, so none can be dropped as redundant without a failure
    # saying what was lost.
    _CONTRADICTIONS = (
        # Bare "will commit"/"will stage", no object -- the object-bearing
        # pattern further down cannot see these.
        r"orchestrator will commit",
        r"orchestrator owns all git",
        r"orchestrator will stage",
        # The orchestrator named as the committer of the step's own output.
        # The object is required: without it this would also reject the true
        # sentence "The orchestrator commits nothing".
        r"orchestrator (?:will |does )?(?:stage(?:s)?,? (?:and )?)?commits? (?:all )?(?:your |the )?(?:changes|work|files)",
        # Same claim with a pronoun subject ("It will stage, commit and push"),
        # which the pattern above misses because it anchors on "orchestrator".
        r"will stage,? (?:and )?commits?",
        # "you do not need to commit" only contradicts when it is about the
        # step's own work, not about some particular category of file. Allow
        # words between the verb and the qualifier ("commit your work between
        # sub-issues"), but never across a sentence boundary -- hence [^.].
        r"do not need to commit\b(?:[^.]{0,30}?\b(?:between|at all|anything)\b|\s*[.;])",
        r"do not run any git commands",
    )

    def test_no_committing_step_is_also_told_the_orchestrator_commits(self):
        """Presence is not agreement.

        The test above passes on a prompt that says both "commit your own
        work" and "the orchestrator will commit all changes when you signal
        completion" -- which is what `coder.md` said after #443 merged, with
        the contradicting lines sitting at the end of Mode A and Mode B,
        exactly where the step decides what to do. A step reading that does
        not commit, and is then failed for delivering nothing.

        So the prompt must not merely mention committing; it must not also
        tell the step someone else will do it.
        """
        agents, _ = po.load_pipeline(po.PIPELINE_PATH)
        prompts = Path(po.__file__).parent.parent / ".claude" / "agents"
        for agent_def in (a for a in agents if a.commit_after):
            text = " ".join((prompts / f"{agent_def.agent}.md").read_text().split())
            found = [
                pat for pat in self._CONTRADICTIONS
                if re.search(pat, text, re.IGNORECASE)
            ]
            assert not found, (
                f"{agent_def.agent} tells the step to commit and also says "
                f"{found!r}; the step will believe the second"
            )

    # Sentences a committing step's prompt must never contain, each asserting
    # that someone other than the step does the committing. The first three
    # are what coder.md actually carried after #443; the rest are the near
    # neighbours that an earlier substring version of _CONTRADICTIONS caught
    # and its first regex rewrite silently stopped catching.
    _MUST_FAIL = (
        "The orchestrator will commit all changes when you signal completion",
        "The orchestrator owns all git operations (branch, commit, push)",
        "you do not need to commit between sub-issues.",
        "It will stage, commit and push for you.",
        "you do not need to commit your work between sub-issues",
        "You do not need to commit; the orchestrator handles it.",
        "The orchestrator commits all changes on your behalf.",
        "The orchestrator will commit.",
        "The orchestrator will stage your files before pushing.",
        "Do not run any git commands.",
    )

    # True sentences a prompt may legitimately contain. A guard that rejects
    # these is worse than no guard: it gets deleted rather than fixed.
    _MUST_PASS = (
        "Commit your own work; the orchestrator owns the branch and the push.",
        "You do not need to commit generated files -- they are gitignored.",
        "Commit as you go. The orchestrator pushes the branch after you return.",
        "The orchestrator commits nothing; the step commits its own work.",
        "You do not need to commit generated files. Between runs they are rebuilt.",
    )

    def test_the_contradiction_patterns_catch_what_they_were_written_for(self):
        """Both directions of the guard, pinned by example.

        Without this, narrowing the patterns to stop false positives could
        quietly stop catching the real thing -- which is exactly what happened
        once: replacing the substring "will stage, commit" with a regex
        anchored on "orchestrator" stopped catching "It will stage, commit and
        push for you", and nothing failed.
        """
        for sentence in self._MUST_FAIL:
            assert any(
                re.search(p, sentence, re.IGNORECASE) for p in self._CONTRADICTIONS
            ), f"no pattern catches {sentence!r}, which a prompt must not say"
        for sentence in self._MUST_PASS:
            hit = [
                p for p in self._CONTRADICTIONS
                if re.search(p, sentence, re.IGNORECASE)
            ]
            assert not hit, f"{hit!r} falsely flags {sentence!r}"

    def test_every_contradiction_pattern_is_load_bearing(self):
        """No pattern may be dropped as redundant without something failing.

        Each pattern must be the only one catching at least one sentence in
        _MUST_FAIL. A pattern that catches nothing on its own is either dead
        weight or -- the case that matters -- a replacement that was assumed
        to cover a deleted pattern and does not.
        """
        for pattern in self._CONTRADICTIONS:
            others = [p for p in self._CONTRADICTIONS if p != pattern]
            covered_only_by_this = [
                s for s in self._MUST_FAIL
                if re.search(pattern, s, re.IGNORECASE)
                and not any(re.search(o, s, re.IGNORECASE) for o in others)
            ]
            assert covered_only_by_this, (
                f"{pattern!r} catches nothing that another pattern does not; "
                f"either drop it or add the sentence only it catches to "
                f"_MUST_FAIL"
            )

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
