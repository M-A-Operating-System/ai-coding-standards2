"""Tests for .github/scripts/append-metrics-record.sh (issue #407).

The git plumbing that puts a record on the `ai-agile/metrics` branch used to be
inline Python in `pipeline_orchestrator.py` (`_append_metrics_record`). AS-2
says committing is not coordination, so it is a declared script now. These
tests exercise it against a REAL git repository -- a bare remote plus a working
clone -- so the behaviours the Python carried are asserted end to end:

- creates records.jsonl when the branch does not have it yet
- appends to it when it does, byte for byte, one record per line
- pushes onto the metrics branch, and only that branch
- retries a rejected push against the new tip (the compare-and-swap the
  scheduled-flow mutex relies on)
- fails closed when the retries run out -- a record that did not land is never
  reported as landed (STD-ARCH-014)
- never disturbs the checkout it runs in
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / ".github" / "scripts" / "append-metrics-record.sh"

BRANCH = "ai-agile/metrics"
RECORDS = "records.jsonl"


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), capture_output=True, text=True, check=check,
    )


@pytest.fixture
def remote_and_clone(tmp_path):
    """A bare remote carrying an empty metrics branch, and a clone of it."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(remote)], check=True,
    )

    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-q", "-b", "main", cwd=seed)
    (seed / "README.md").write_text("seed\n")
    _git("add", "README.md", cwd=seed)
    _git("commit", "-qm", "seed", cwd=seed)
    _git("push", "-q", str(remote), f"main:refs/heads/{BRANCH}", cwd=seed)
    _git("push", "-q", str(remote), "main:refs/heads/main", cwd=seed)

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(clone)], check=True,
    )
    _git("config", "user.email", "t@t", cwd=clone)
    _git("config", "user.name", "t", cwd=clone)
    return remote, clone


def _run(clone, record_line, *, message="metrics: test on #1", retries=0):
    record_file = clone.parent / "record.jsonl"
    record_file.write_text(record_line)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(clone)),
        "AI_AGILE_METRICS_BRANCH": BRANCH,
        "AI_AGILE_METRICS_FILE": RECORDS,
        "AI_AGILE_METRICS_COMMIT_MESSAGE": message,
        "AI_AGILE_METRICS_RETRIES": str(retries),
        # No token: the clone's own file:// remote needs no credential, and the
        # script must not require one to work.
    }
    return subprocess.run(
        ["bash", str(SCRIPT), str(record_file)],
        env=env, cwd=str(clone), capture_output=True, text=True,
    )


def _ledger(remote):
    show = subprocess.run(
        ["git", "show", f"{BRANCH}:{RECORDS}"],
        cwd=str(remote), capture_output=True, text=True,
    )
    return show.stdout if show.returncode == 0 else None


class TestTheLedgerAppend:
    def test_creates_the_file_when_the_branch_does_not_have_it(self, remote_and_clone):
        remote, clone = remote_and_clone
        record = {"agent_id": "coder", "github_issue_number": 42}

        res = _run(clone, json.dumps(record, separators=(",", ":")) + "\n")

        assert res.returncode == 0, res.stderr
        assert [json.loads(line) for line in _ledger(remote).splitlines()] == [record]

    def test_appends_to_an_existing_file(self, remote_and_clone):
        remote, clone = remote_and_clone
        first = {"agent_id": "prd-writer", "github_issue_number": 10}
        second = {"agent_id": "coder", "github_issue_number": 42}

        _run(clone, json.dumps(first, separators=(",", ":")) + "\n")
        res = _run(clone, json.dumps(second, separators=(",", ":")) + "\n")

        assert res.returncode == 0, res.stderr
        assert [json.loads(line) for line in _ledger(remote).splitlines()] == [first, second]

    def test_uses_the_commit_message_it_was_given(self, remote_and_clone):
        remote, clone = remote_and_clone
        _run(clone, '{"agent_id":"coder"}\n', message="metrics: 03_execute/coder on #55")

        subject = subprocess.run(
            ["git", "log", "-1", "--format=%s", BRANCH],
            cwd=str(remote), capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert subject == "metrics: 03_execute/coder on #55"

    def test_touches_only_the_metrics_branch(self, remote_and_clone):
        remote, clone = remote_and_clone
        main_before = subprocess.run(
            ["git", "rev-parse", "main"], cwd=str(remote),
            capture_output=True, text=True, check=True,
        ).stdout

        _run(clone, '{"agent_id":"coder"}\n')

        main_after = subprocess.run(
            ["git", "rev-parse", "main"], cwd=str(remote),
            capture_output=True, text=True, check=True,
        ).stdout
        assert main_before == main_after

    def test_leaves_the_working_checkout_alone(self, remote_and_clone):
        """A scratch GIT_INDEX_FILE is used, so nothing here disturbs the tick."""
        _remote, clone = remote_and_clone
        (clone / "work_in_progress.txt").write_text("mid-tick edit\n")

        _run(clone, '{"agent_id":"coder"}\n')

        assert (clone / "work_in_progress.txt").read_text() == "mid-tick edit\n"
        status = _git("status", "--porcelain", cwd=clone).stdout
        assert status.strip() == "?? work_in_progress.txt"
        assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone).stdout.strip() == "main"


class TestAConcurrentWriter:
    def _reject_first_push(self, remote, times=1):
        """A pre-receive hook that rejects the first `times` pushes.

        Stands in for another runner landing its own append between our fetch
        and our push -- the case the retry exists for.
        """
        hook = remote / "hooks" / "pre-receive"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(
            "#!/usr/bin/env bash\n"
            f'COUNT_FILE="{remote}/push-count"\n'
            'n=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)\n'
            'echo $(( n + 1 )) > "$COUNT_FILE"\n'
            f'if (( n < {times} )); then echo "rejected by test hook" >&2; exit 1; fi\n'
            "exit 0\n"
        )
        hook.chmod(0o755)

    def test_retries_a_rejected_push_and_lands(self, remote_and_clone):
        remote, clone = remote_and_clone
        self._reject_first_push(remote, times=1)

        res = _run(clone, '{"agent_id":"coder"}\n', retries=1)

        assert res.returncode == 0, res.stderr
        assert "retrying (attempt 1)" in res.stderr
        assert _ledger(remote) is not None

    def test_fails_closed_when_the_retries_run_out(self, remote_and_clone):
        remote, clone = remote_and_clone
        self._reject_first_push(remote, times=5)

        res = _run(clone, '{"agent_id":"coder"}\n', retries=1)

        assert res.returncode != 0, "a record that did not land must not report success"
        assert "git push" in res.stderr
        assert _ledger(remote) is None


class TestItsInputContract:
    def test_refuses_a_missing_record_file(self, remote_and_clone):
        _remote, clone = remote_and_clone
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(clone)),
            "AI_AGILE_METRICS_BRANCH": BRANCH,
            "AI_AGILE_METRICS_FILE": RECORDS,
            "AI_AGILE_METRICS_COMMIT_MESSAGE": "metrics: test on #1",
        }
        res = subprocess.run(
            ["bash", str(SCRIPT), str(clone / "nope.jsonl")],
            env=env, cwd=str(clone), capture_output=True, text=True,
        )
        assert res.returncode != 0
        assert "no record at" in res.stderr

    def test_refuses_to_run_without_a_declared_branch(self, remote_and_clone):
        _remote, clone = remote_and_clone
        record_file = clone.parent / "r.jsonl"
        record_file.write_text('{"a":1}\n')
        res = subprocess.run(
            ["bash", str(SCRIPT), str(record_file)],
            env={"PATH": os.environ["PATH"], "HOME": str(clone)},
            cwd=str(clone), capture_output=True, text=True,
        )
        assert res.returncode != 0
        assert "AI_AGILE_METRICS_BRANCH" in res.stderr
