"""Tests for issue #197: issue branches created from, and kept current with,
latest main.

Covers:
  - check-branch-freshness.sh flags stale / no-merge-base branches (AC #4, and
    the "flagged" form of AC #2).
  - create-pr.sh cuts new branches from origin/main so they share the current
    merge base (AC #1), and wires in the freshness flag.
  - ai_orchestrator.yml's orchestrate job checks out full history (AC #3).
"""
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
FRESHNESS = REPO_ROOT / ".github" / "scripts" / "check-branch-freshness.sh"
CREATE_PR = REPO_ROOT / ".github" / "scripts" / "create-pr.sh"
ORCH_YML = REPO_ROOT / ".github" / "workflows" / "ai_orchestrator.yml"


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check, capture_output=True, text=True
    )


# ---------------------------------------------------------------------------
# check-branch-freshness.sh (behavioral)
# ---------------------------------------------------------------------------

class TestCheckBranchFreshness:
    def _repo(self, tmp_path):
        """A bare origin plus a work clone with git identity configured."""
        origin = tmp_path / "origin.git"
        _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
        work = tmp_path / "work"
        _git(tmp_path, "clone", str(origin), str(work))
        _git(work, "config", "user.email", "t@t")
        _git(work, "config", "user.name", "t")
        return work

    def _commit(self, work, msg):
        (work / "f.txt").write_text(msg)
        _git(work, "add", "-A")
        _git(work, "commit", "-m", msg)

    def _run(self, work, branch, *extra):
        return subprocess.run(
            ["bash", str(FRESHNESS), branch, *extra],
            cwd=str(work), capture_output=True, text=True,
        )

    def test_fresh_branch_exits_0(self, tmp_path):
        work = self._repo(tmp_path)
        self._commit(work, "c1")
        _git(work, "push", "origin", "main")
        _git(work, "checkout", "-b", "issue-1")
        _git(work, "push", "origin", "issue-1")

        r = self._run(work, "issue-1")
        assert r.returncode == 0, r.stderr
        assert "FRESH" in r.stdout

    def test_behind_beyond_threshold_is_stale(self, tmp_path):
        work = self._repo(tmp_path)
        self._commit(work, "c1")
        _git(work, "push", "origin", "main")
        _git(work, "checkout", "-b", "issue-2")
        _git(work, "push", "origin", "issue-2")
        # main advances 3 commits; the branch stays put.
        _git(work, "checkout", "main")
        for i in range(3):
            self._commit(work, f"m{i}")
        _git(work, "push", "origin", "main")

        r = self._run(work, "issue-2", "2")  # threshold 2 < behind 3
        assert r.returncode == 1, (r.stdout, r.stderr)
        assert "STALE" in r.stderr
        assert "3 commit" in r.stderr

    def test_behind_within_threshold_is_fresh(self, tmp_path):
        work = self._repo(tmp_path)
        self._commit(work, "c1")
        _git(work, "push", "origin", "main")
        _git(work, "checkout", "-b", "issue-3")
        _git(work, "push", "origin", "issue-3")
        _git(work, "checkout", "main")
        for i in range(3):
            self._commit(work, f"m{i}")
        _git(work, "push", "origin", "main")

        r = self._run(work, "issue-3", "5")  # threshold 5 > behind 3
        assert r.returncode == 0, r.stderr
        assert "FRESH" in r.stdout

    def test_no_merge_base_is_stale(self, tmp_path):
        work = self._repo(tmp_path)
        self._commit(work, "c1")
        _git(work, "push", "origin", "main")
        # An orphan branch has no common ancestor with main.
        _git(work, "checkout", "--orphan", "issue-4")
        _git(work, "rm", "-rf", ".", check=False)
        (work / "other.txt").write_text("unrelated")
        _git(work, "add", "-A")
        _git(work, "commit", "-m", "orphan root")
        _git(work, "push", "origin", "issue-4")

        r = self._run(work, "issue-4")
        assert r.returncode == 1, (r.stdout, r.stderr)
        assert "no merge base" in r.stderr.lower()

    def test_bad_threshold_is_usage_error(self, tmp_path):
        work = self._repo(tmp_path)
        self._commit(work, "c1")
        _git(work, "push", "origin", "main")
        _git(work, "checkout", "-b", "issue-5")
        _git(work, "push", "origin", "issue-5")

        r = self._run(work, "issue-5", "notanumber")
        assert r.returncode == 2

    def test_missing_branch_is_env_error(self, tmp_path):
        work = self._repo(tmp_path)
        self._commit(work, "c1")
        _git(work, "push", "origin", "main")

        r = self._run(work, "issue-does-not-exist")
        assert r.returncode == 2


# ---------------------------------------------------------------------------
# create-pr.sh (static: cuts from origin/main, wires the freshness flag)
# ---------------------------------------------------------------------------

class TestCreatePrCutsFromOriginMain:
    def test_new_branch_cut_from_origin_default_branch(self):
        text = CREATE_PR.read_text()
        assert 'checkout -B "${BRANCH}" "origin/${DEFAULT_BRANCH}"' in text, (
            "create-pr.sh must cut the issue branch from origin/${DEFAULT_BRANCH}, "
            "not the (possibly stale) local default branch"
        )

    def test_no_longer_branches_from_local_default(self):
        text = CREATE_PR.read_text()
        # The buggy plain `checkout -b "${BRANCH}"` (from a local checkout of
        # the default branch) must be gone -- regression guard for #197.
        assert 'checkout -b "${BRANCH}"' not in text

    def test_invokes_freshness_check(self):
        text = CREATE_PR.read_text()
        assert "check-branch-freshness.sh" in text, (
            "create-pr.sh must flag a stale branch before the coder runs"
        )


# ---------------------------------------------------------------------------
# ai_orchestrator.yml (static: orchestrate job checks out full history)
# ---------------------------------------------------------------------------

class TestOrchestrateFullHistory:
    def test_orchestrate_checkout_uses_fetch_depth_0(self):
        data = yaml.safe_load(ORCH_YML.read_text())
        steps = data["jobs"]["orchestrate"]["steps"]
        checkout = next(
            s for s in steps if "actions/checkout" in str(s.get("uses", ""))
        )
        assert checkout.get("with", {}).get("fetch-depth") == 0, (
            "orchestrate job must checkout with fetch-depth: 0 so main...HEAD "
            "and merge-base operations work (no phantom 'no merge base')"
        )
