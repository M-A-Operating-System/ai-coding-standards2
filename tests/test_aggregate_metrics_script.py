"""Tests for scripts/aggregate-metrics.sh per-bucket commit behaviour (issue #670).

Covers the acceptance scenarios from the issue and docs/features/metrics-aggregator.md:

  R1 (weekly one commit per bucket)  -> TestPerBucketCommits.test_two_missing_weekly_buckets_produce_two_commits
  R2 (daily one commit per bucket)   -> TestPerBucketCommits.test_daily_script_commits_one_bucket_per_catchup
  R3 (crash recovery)                -> TestPerBucketCommits.test_crash_recovery_leaves_committed_buckets_intact
  R5 (single AI_AGILE_STATUS line)   -> TestPerBucketCommits.test_exactly_one_ai_agile_status_line
  R9 (single-bucket one commit)      -> TestPerBucketCommits.test_single_bucket_produces_one_commit
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGG_SCRIPT = REPO_ROOT / "scripts" / "aggregate-metrics.sh"
DAILY_SCRIPT = REPO_ROOT / "scripts" / "aggregate-metrics-daily.sh"
APPEND_SCRIPT = REPO_ROOT / "scripts" / "append-metrics-record.sh"
LIB_DIR = REPO_ROOT / "scripts" / "lib"

BRANCH = "ai-agile/metrics"
RECORDS = "records.jsonl"

# Two consecutive weekly buckets for use in tests.
BUCKET1_START = "2026-09-14T00:00:00Z"
BUCKET1_END   = "2026-09-20T23:59:59Z"
BUCKET2_START = "2026-09-21T00:00:00Z"
BUCKET2_END   = "2026-09-27T23:59:59Z"
BUCKET3_START = "2026-09-28T00:00:00Z"
BUCKET3_END   = "2026-10-04T23:59:59Z"

# A fake metrics_aggregator.py that reads its output from an env-specified file.
# It accepts the same --period / --now flags without error so the shell script
# can call it transparently.
_FAKE_AGGREGATOR = """\
#!/usr/bin/env python3
import os, sys, argparse
parser = argparse.ArgumentParser()
parser.add_argument("--period", default="week")
parser.add_argument("--now", default=None)
args = parser.parse_args()
records_file = os.environ.get("FAKE_AGGREGATOR_RECORDS", "")
if records_file and os.path.isfile(records_file):
    with open(records_file) as fh:
        for line in fh:
            line = line.rstrip()
            if line:
                print(line)
"""


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), capture_output=True, text=True, check=check,
    )


@pytest.fixture
def agg_env(tmp_path):
    """Set up fake repo layout + metrics branch for testing aggregate-metrics.sh.

    Layout mirrors what the script expects:
      {root}/scripts/aggregate-metrics.sh   (copied from real)
      {root}/scripts/append-metrics-record.sh
      {root}/scripts/lib/github-identity.sh
      {root}/pipeline/metrics_aggregator.py  (fake, reads FAKE_AGGREGATOR_RECORDS)
    Plus a bare remote and a clone pointing at it.
    """
    scripts_dir = tmp_path / "scripts"
    pipeline_dir = tmp_path / "pipeline"
    scripts_dir.mkdir()
    pipeline_dir.mkdir()

    shutil.copy(AGG_SCRIPT, scripts_dir / "aggregate-metrics.sh")
    shutil.copy(DAILY_SCRIPT, scripts_dir / "aggregate-metrics-daily.sh")
    shutil.copy(APPEND_SCRIPT, scripts_dir / "append-metrics-record.sh")
    shutil.copytree(LIB_DIR, scripts_dir / "lib")

    (pipeline_dir / "metrics_aggregator.py").write_text(_FAKE_AGGREGATOR)

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
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    _git("config", "user.email", "t@t", cwd=clone)
    _git("config", "user.name", "t", cwd=clone)

    return {
        "remote": remote,
        "clone": clone,
        "tmp": tmp_path,
        "scripts_dir": scripts_dir,
    }


def _blended_row(ts_start, ts_end):
    return json.dumps({
        "agent_id": "metrics-aggregator",
        "period": "week",
        "timestamp_start": ts_start,
        "timestamp_end": ts_end,
    }, separators=(",", ":"))


def _make_records(*buckets):
    """JSONL string with one blended row per bucket."""
    return "\n".join(_blended_row(s, e) for s, e in buckets) + "\n"


def _run_agg(env, records_content, period="week", extra_args=None):
    records_file = env["tmp"] / "fake_records.jsonl"
    records_file.write_text(records_content)
    script_env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(env["clone"])),
        "FAKE_AGGREGATOR_RECORDS": str(records_file),
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
    }
    cmd = ["bash", str(env["scripts_dir"] / "aggregate-metrics.sh"), "--period", period]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd, env=script_env, cwd=str(env["clone"]), capture_output=True, text=True,
    )


def _run_daily(env, records_content):
    records_file = env["tmp"] / "fake_records_daily.jsonl"
    records_file.write_text(records_content)
    script_env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(env["clone"])),
        "FAKE_AGGREGATOR_RECORDS": str(records_file),
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
    }
    return subprocess.run(
        ["bash", str(env["scripts_dir"] / "aggregate-metrics-daily.sh")],
        env=script_env, cwd=str(env["clone"]), capture_output=True, text=True,
    )


def _ledger(remote):
    show = subprocess.run(
        ["git", "show", f"{BRANCH}:{RECORDS}"],
        cwd=str(remote), capture_output=True, text=True,
    )
    return show.stdout if show.returncode == 0 else None


def _commit_subjects(remote):
    result = subprocess.run(
        ["git", "log", "--format=%s", BRANCH],
        cwd=str(remote), capture_output=True, text=True, check=True,
    )
    return [l for l in result.stdout.splitlines() if l.strip()]


def _commit_count(remote):
    return len(_commit_subjects(remote))


class TestPerBucketCommits:
    def test_two_missing_weekly_buckets_produce_two_commits(self, agg_env):
        """R1: Two missing weekly buckets -> two separate commits."""
        records = _make_records(
            (BUCKET1_START, BUCKET1_END),
            (BUCKET2_START, BUCKET2_END),
        )
        res = _run_agg(agg_env, records)

        assert res.returncode == 0, res.stderr
        assert "AI_AGILE_STATUS: complete" in res.stdout
        # seed commit + 2 bucket commits
        assert _commit_count(agg_env["remote"]) == 3

    def test_daily_script_commits_one_bucket_per_catchup(self, agg_env):
        """R2: aggregate-metrics-daily.sh also commits one bucket per catch-up period."""
        records = _make_records(
            (BUCKET1_START, BUCKET1_END),
            (BUCKET2_START, BUCKET2_END),
        )
        res = _run_daily(agg_env, records)

        assert res.returncode == 0, res.stderr
        assert "AI_AGILE_STATUS: complete" in res.stdout
        assert _commit_count(agg_env["remote"]) == 3

    def test_crash_recovery_leaves_committed_buckets_intact(self, agg_env):
        """R3: First bucket committed; second fails. Re-run with only second succeeds."""
        hook = agg_env["remote"] / "hooks" / "pre-receive"
        hook.parent.mkdir(exist_ok=True)
        # Allow the first push only (n=0 passes, n>=1 is rejected).
        hook.write_text(
            "#!/usr/bin/env bash\n"
            f'COUNT_FILE="{agg_env["remote"]}/push-count"\n'
            'n=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)\n'
            'echo $(( n + 1 )) > "$COUNT_FILE"\n'
            'if (( n >= 1 )); then echo "hook: rejected" >&2; exit 1; fi\n'
            "exit 0\n"
        )
        hook.chmod(0o755)

        records_two = _make_records(
            (BUCKET1_START, BUCKET1_END),
            (BUCKET2_START, BUCKET2_END),
        )
        res = _run_agg(agg_env, records_two)

        assert "AI_AGILE_STATUS: blocked" in res.stdout, res.stdout
        ledger = _ledger(agg_env["remote"])
        assert ledger is not None
        assert BUCKET1_START in ledger
        assert BUCKET2_START not in ledger

        hook.unlink()

        records_one = _make_records((BUCKET2_START, BUCKET2_END))
        res2 = _run_agg(agg_env, records_one)

        assert "AI_AGILE_STATUS: complete" in res2.stdout
        ledger2 = _ledger(agg_env["remote"])
        assert BUCKET1_START in ledger2
        assert BUCKET2_START in ledger2
        # seed + bucket1 + bucket2
        assert _commit_count(agg_env["remote"]) == 3

    def test_exactly_one_ai_agile_status_line(self, agg_env):
        """R5: Exactly one AI_AGILE_STATUS line regardless of bucket count."""
        records = _make_records(
            (BUCKET1_START, BUCKET1_END),
            (BUCKET2_START, BUCKET2_END),
            (BUCKET3_START, BUCKET3_END),
        )
        res = _run_agg(agg_env, records)

        status_lines = [l for l in res.stdout.splitlines() if l.startswith("AI_AGILE_STATUS:")]
        assert len(status_lines) == 1

    def test_single_bucket_produces_one_commit(self, agg_env):
        """R9: Single missing bucket -> exactly one commit."""
        records = _make_records((BUCKET1_START, BUCKET1_END))
        res = _run_agg(agg_env, records)

        assert res.returncode == 0, res.stderr
        assert "AI_AGILE_STATUS: complete" in res.stdout
        # seed + 1 bucket
        assert _commit_count(agg_env["remote"]) == 2

    def test_three_buckets_committed_oldest_first(self, agg_env):
        """Three buckets are committed in chronological order (oldest first)."""
        records = _make_records(
            (BUCKET1_START, BUCKET1_END),
            (BUCKET2_START, BUCKET2_END),
            (BUCKET3_START, BUCKET3_END),
        )
        res = _run_agg(agg_env, records)

        assert res.returncode == 0, res.stderr
        # git log is newest-first; BUCKET3 is at the top, BUCKET1 at the bottom
        subjects = _commit_subjects(agg_env["remote"])
        # subjects[0] = newest commit (BUCKET3), subjects[-1] = seed
        assert BUCKET3_START in subjects[0]
        assert BUCKET2_START in subjects[1]
        assert BUCKET1_START in subjects[2]

    def test_no_records_produces_no_commit(self, agg_env):
        """Empty aggregator output -> no commit, complete status."""
        res = _run_agg(agg_env, "")

        assert res.returncode == 0, res.stderr
        assert "AI_AGILE_STATUS: complete" in res.stdout
        # only seed commit remains
        assert _commit_count(agg_env["remote"]) == 1

    def test_dry_run_produces_no_commit(self, agg_env):
        """--dry-run produces no commit and reports complete."""
        records = _make_records(
            (BUCKET1_START, BUCKET1_END),
            (BUCKET2_START, BUCKET2_END),
        )
        res = _run_agg(agg_env, records, extra_args=["--dry-run"])

        assert res.returncode == 0, res.stderr
        assert "AI_AGILE_STATUS: complete" in res.stdout
        assert "DRY RUN" in res.stderr
        # no new commits
        assert _commit_count(agg_env["remote"]) == 1
