"""
Tests for the post-agent repo-root sweep (issue #376).

Agents are told to write working files under $AI_AGILE_SCRATCH. When one
writes to a relative path instead, the file lands at the repository root.
`commit-agent-work.sh` already unstages such files, but only for agents with
`git_ops.commit_after: true` -- prd-writer, pr-reviewer and issue-classifier
have none, and all three were observed leaving files there. These tests cover
the sweep that runs for every agent.

Issue #407 moved the sweep out of `pipeline_orchestrator.py` and into two
declared agent-lifecycle scripts (AS-2: the orchestrator only coordinates), so
the same behaviours are asserted here against the scripts and against the
`defaults.agent_lifecycle` wiring that runs them:

    .github/scripts/sweep-repo-root-snapshot.sh   the "before" baseline
    .github/scripts/sweep-repo-root.sh            the "after" removal

The sweep is deliberately conservative: it removes only files that were absent
before the invocation, so a file a human left in the tree is never touched.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

import pipeline_orchestrator as po  # noqa: E402

SNAPSHOT_SCRIPT = REPO_ROOT / ".github" / "scripts" / "sweep-repo-root-snapshot.sh"
SWEEP_SCRIPT = REPO_ROOT / ".github" / "scripts" / "sweep-repo-root.sh"


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway git repo with one tracked file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("tracked\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        cwd=repo, check=True,
    )
    return repo


@pytest.fixture
def scratch(tmp_path):
    """A scratch directory path in the same shape the orchestrator hands out."""
    d = tmp_path / "scratch-376"
    d.mkdir()
    return d


def _run(script, repo, scratch, *, cwd=None, agent="01_product_docs/prd-writer", root=None):
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(repo)),
        "AI_AGILE_SCRATCH": str(scratch),
        "AI_AGILE_ROOT": str(repo) if root is None else root,
        "AGENT_NAME": agent,
    }
    return subprocess.run(
        ["bash", str(script)], env=env, cwd=str(cwd or repo),
        capture_output=True, text=True,
    )


def _snapshot_path(scratch):
    return Path(f"{str(scratch).rstrip('/')}.root-snapshot")


# --- the baseline ("before") ----------------------------------------------


class TestTheBaseline:
    def test_lists_untracked_files_at_the_root(self, git_repo, scratch):
        (git_repo / "leaked.md").write_text("x")
        res = _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        assert res.returncode == 0, res.stderr
        assert "leaked.md" in _snapshot_path(scratch).read_text().split()

    def test_ignores_tracked_files(self, git_repo, scratch):
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        assert "tracked.txt" not in _snapshot_path(scratch).read_text().split()

    def test_ignores_files_in_subdirectories(self, git_repo, scratch):
        (git_repo / "docs").mkdir()
        (git_repo / "docs" / "note.md").write_text("x")
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        assert _snapshot_path(scratch).read_text().split() == [], \
            "only depth-0 files are the agent's residue; subdirectories are real work"

    def test_records_no_baseline_when_git_cannot_be_consulted(self, tmp_path, scratch):
        """No baseline file at all -- the distinction is load-bearing.

        The sweep uses this file as its "before" set. An empty baseline means
        "every untracked root file is new", so writing one on a failed probe
        would turn a transient git error into a delete-everything sweep.
        """
        not_a_repo = tmp_path / "elsewhere"
        not_a_repo.mkdir()
        res = _run(SNAPSHOT_SCRIPT, not_a_repo, scratch, root=str(not_a_repo))
        assert res.returncode != 0
        assert not _snapshot_path(scratch).exists()
        assert "could not resolve the repository root" in res.stderr

    def test_a_retry_keeps_the_first_attempts_baseline(self, git_repo, scratch):
        """scratch-setup.sh empties the scratch dir per attempt; the baseline
        must survive so a file leaked by attempt 1 is still swept after
        attempt 2."""
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        (git_repo / "leaked_by_attempt_1.md").write_text("x")
        res = _run(SNAPSHOT_SCRIPT, git_repo, scratch)  # attempt 2
        assert res.returncode == 0
        assert "leaked_by_attempt_1.md" not in _snapshot_path(scratch).read_text().split()

    def test_a_stale_baseline_is_replaced_not_trusted(self, git_repo, scratch):
        """A snapshot left by a run that died before sweeping is evidence about
        a different run; deleting files against it would be a guess."""
        snap = _snapshot_path(scratch)
        snap.write_text("ancient.md\n")
        os.utime(snap, (0, 0))
        (git_repo / "pre_existing.md").write_text("x")
        res = _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        assert res.returncode == 0
        assert _snapshot_path(scratch).read_text().split() == ["pre_existing.md"]


# --- the sweep ("after") ---------------------------------------------------


class TestTheSweep:
    def test_skips_when_the_baseline_is_unknown(self, git_repo, scratch):
        """A failed probe must lose a cleanup, never delete a file blindly."""
        (git_repo / "not_the_agents.md").write_text("pre-existing")

        res = _run(SWEEP_SCRIPT, git_repo, scratch)

        assert (git_repo / "not_the_agents.md").exists()
        assert res.returncode != 0
        assert "skipping the sweep" in res.stderr

    def test_removes_a_file_the_agent_added(self, git_repo, scratch):
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        (git_repo / "ann_open.md").write_text("announcement")

        res = _run(SWEEP_SCRIPT, git_repo, scratch)

        assert res.returncode == 0, res.stderr
        assert not (git_repo / "ann_open.md").exists()

    def test_removes_every_file_the_agent_added(self, git_repo, scratch):
        """prd-writer left four; pr-reviewer left three."""
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        for name in ("ann_open.md", "ann_close.md", "review_body.md"):
            (git_repo / name).write_text("x")

        _run(SWEEP_SCRIPT, git_repo, scratch, agent="03_execute/pr-reviewer")

        leftovers = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=git_repo, capture_output=True, text=True, check=True,
        ).stdout.split()
        assert leftovers == []

    def test_leaves_a_file_that_existed_before_the_run(self, git_repo, scratch):
        """A human's untracked file must survive an agent invocation."""
        (git_repo / "my_notes.md").write_text("do not delete")
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        (git_repo / "leaked.md").write_text("x")

        _run(SWEEP_SCRIPT, git_repo, scratch)

        assert (git_repo / "my_notes.md").exists(), \
            "the sweep must only remove what the agent itself added"
        assert not (git_repo / "leaked.md").exists()

    def test_leaves_subdirectory_work_untouched(self, git_repo, scratch):
        """The coder writes real files under docs/ and pipeline/; never sweep those."""
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        nested = git_repo / "docs"
        nested.mkdir()
        (nested / "feature.md").write_text("real work")

        _run(SWEEP_SCRIPT, git_repo, scratch, agent="03_execute/coder")

        assert (nested / "feature.md").exists()

    def test_names_the_agent_and_the_files_it_left(self, git_repo, scratch):
        """A silent sweep would hide the bug it exists to contain."""
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        (git_repo / "snapshot_comment.md").write_text("x")

        res = _run(SWEEP_SCRIPT, git_repo, scratch)

        assert "01_product_docs/prd-writer" in res.stderr
        assert "snapshot_comment.md" in res.stderr

    def test_is_silent_when_the_agent_left_nothing(self, git_repo, scratch):
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)

        res = _run(SWEEP_SCRIPT, git_repo, scratch)

        assert res.returncode == 0
        assert res.stderr.strip() == ""

    def test_reports_a_file_that_cannot_be_removed(self, git_repo, scratch):
        """A sweep failure is reported, never hidden -- STD-ARCH-014."""
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        protected = git_repo / "protected"
        protected.mkdir()
        (protected / "keep.md").write_text("x")
        # A non-empty directory at depth 0 cannot be removed by `rm -f`.
        res = _run(SWEEP_SCRIPT, git_repo, scratch)

        # The directory itself is not listed by `git ls-files --others` at
        # depth 0, so nothing is swept and nothing is lost.
        assert (protected / "keep.md").exists()
        assert res.returncode == 0

    def test_consumes_the_baseline_so_a_later_run_cannot_reuse_it(self, git_repo, scratch):
        _run(SNAPSHOT_SCRIPT, git_repo, scratch)
        _run(SWEEP_SCRIPT, git_repo, scratch)
        assert not _snapshot_path(scratch).exists()

    def test_root_is_resolved_from_git_not_the_cwd(self, git_repo, scratch):
        """Started from a subdirectory, the sweep must still act on the repo root.

        AI_AGILE_ROOT is conventionally ".", so reading it directly would leave
        this cwd-relative and the sweep would operate in the wrong directory.
        """
        nested = git_repo / "pipeline"
        nested.mkdir()

        _run(SNAPSHOT_SCRIPT, git_repo, scratch, cwd=nested, root=".")
        (git_repo / "leaked.md").write_text("x")
        _run(SWEEP_SCRIPT, git_repo, scratch, cwd=nested, root=".")

        assert not (git_repo / "leaked.md").exists()


# --- the wiring ------------------------------------------------------------


class TestTheSweepIsADeclaredLifecycleHookNotOrchestratorCode:
    def test_pipeline_json_declares_both_halves(self):
        defaults = json.loads(
            (REPO_ROOT / "pipeline" / "pipeline.json").read_text()
        )["defaults"]["agent_lifecycle"]
        assert ".github/scripts/sweep-repo-root-snapshot.sh" in defaults["before"]
        assert ".github/scripts/sweep-repo-root.sh" in defaults["after"]

    def test_the_sweep_runs_before_the_scratch_is_torn_down(self):
        after = json.loads(
            (REPO_ROOT / "pipeline" / "pipeline.json").read_text()
        )["defaults"]["agent_lifecycle"]["after"]
        assert after.index(".github/scripts/sweep-repo-root.sh") < \
            after.index(".github/scripts/scratch-teardown.sh")

    def test_the_orchestrator_holds_no_sweep_code(self):
        """AS-2: nothing that changes an artefact lives inside the orchestrator."""
        for gone in ("_repo_root", "_untracked_root_files", "_sweep_agent_root_files"):
            assert not hasattr(po, gone), (
                f"{gone} still lives in pipeline_orchestrator.py; the sweep "
                "belongs to .github/scripts/sweep-repo-root.sh (AS-2)"
            )

    def test_the_lifecycle_env_carries_what_the_sweep_needs(self):
        assert "AI_AGILE_ROOT" in po._LIFECYCLE_SCRIPT_ENV_VARS
