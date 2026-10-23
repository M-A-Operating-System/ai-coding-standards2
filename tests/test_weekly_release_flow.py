"""Tests for issue #619: orchestrator scheduling and dispatch for the weekly
release flow.

Covers:
- Scenario R1 (weekly cron trigger): weekly-release flow is in pipeline.json
  with a schedule trigger and a Wednesday cron expression.
- Scenario R2 (manual dispatch): the flow is a scheduled flow dispatched by
  _run_scheduled_flows, which is also the manual-override path.
- Scenario R3/R4 (no-change run): run-release-flow.sh exits with
  AI_AGILE_STATUS: complete and emits a structured no-change JSON to stderr
  when gh reports no merged PRs or closed issues since the last release.
- Scenario R5/R6 (retry without residual state): the script makes no writes,
  so a re-run leaves no residual state.
- Scenario R7 (stub leaves no GitHub Release): the stub path emits a
  structured JSON to stderr without calling gh release create.
"""
import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

import pipeline_orchestrator as orch
from pipeline_orchestrator import AgentDef, WorkItem, cron_matches, load_pipeline
from datetime import datetime, timezone


def _t(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

_PIPELINE_PATH = Path(__file__).parent.parent / "pipeline" / "pipeline.json"
_SCRIPT = Path(__file__).parent.parent / "scripts" / "run-release-flow.sh"

_EMPTY_RELEASES = json.dumps({"message": "Not Found"})
_ONE_RELEASE = json.dumps({
    "tag_name": "v2.1.0",
    "published_at": "2026-10-01T09:00:00Z",
})
_NO_PULLS = json.dumps([])
_ONE_PULL = json.dumps([{
    "number": 10,
    "merged_at": "2026-10-15T12:00:00Z",
    "title": "Some fix",
}])
_NO_ISSUES = json.dumps([])
_ONE_ISSUE = json.dumps([{
    "number": 20,
    "pull_request": None,
    "closed_at": "2026-10-16T10:00:00Z",
    "title": "Some issue",
}])


# ---------------------------------------------------------------------------
# Pipeline.json shape tests (Scenario R1, R2)
# ---------------------------------------------------------------------------

class TestWeeklyReleaseFlowPipelineShape:
    """The weekly-release flow must be a scheduled script step on a Wednesday
    cron, not reachable by the per-item work loop."""

    def _load_weekly_release_step(self):
        agents, _ = load_pipeline(_PIPELINE_PATH)
        matches = [a for a in agents if a.flow == "weekly-release"]
        assert matches, "weekly-release flow not found in pipeline.json"
        assert len(matches) == 1, "expected exactly one step in weekly-release flow"
        return matches[0]

    def test_weekly_release_flow_has_schedule_trigger(self):
        """Scenario R1: the flow is configured with a schedule trigger."""
        step = self._load_weekly_release_step()
        assert step.flow_schedule is not None, (
            "weekly-release flow must declare a schedule trigger"
        )

    def test_weekly_release_fires_on_wednesday(self):
        """Scenario R1: the cron expression must include Wednesday (field 5 = 3)."""
        step = self._load_weekly_release_step()
        # A Wednesday in 2026 at 09:00 Eastern.
        # 2026-10-21 is a Wednesday still in EDT (UTC-4); 09:00 EDT = 13:00 UTC.
        when_est = _t("2026-10-21T13:00:00")  # 09:00 EDT (UTC-4)
        assert cron_matches(
            step.flow_schedule, when_est, tz=step.flow_schedule_timezone
        ), (
            f"weekly-release schedule {step.flow_schedule!r} must fire at "
            f"09:00 Eastern on a Wednesday"
        )

    def test_weekly_release_does_not_fire_on_monday(self):
        """The release flow must not fire on Monday (that is the metrics cadence)."""
        step = self._load_weekly_release_step()
        # 2026-10-19 is a Monday (still EDT, UTC-4). 09:00 EDT = 13:00 UTC.
        when_monday = _t("2026-10-19T13:00:00")  # Monday
        assert not cron_matches(
            step.flow_schedule, when_monday, tz=step.flow_schedule_timezone
        ), "weekly-release must not fire on Monday"

    def test_weekly_release_is_script_type(self):
        step = self._load_weekly_release_step()
        assert step.step_type == "script", (
            "weekly-release step must be type 'script'"
        )

    def test_weekly_release_has_no_label_trigger(self):
        step = self._load_weekly_release_step()
        assert step.trigger.get("label") is None, (
            "weekly-release step must not have a label trigger"
        )
        assert step.trigger.get("event") == "schedule", (
            "weekly-release step trigger must be {event: schedule}"
        )

    def test_weekly_release_is_not_reachable_by_work_item_loop(self):
        """Scenario R2: the step must never be triggered by a work item -- it
        is only dispatched by _run_scheduled_flows (including the manual path)."""
        step = self._load_weekly_release_step()
        item = WorkItem(number=1, kind="issue", title="t", labels=set(), url="u")
        assert orch._should_run(
            step, item, item.labels, {}, None, gh=MagicMock(), repo="org/repo"
        ) is False, "weekly-release must never be triggered by a work item"

    def test_weekly_release_schedule_does_not_collide_with_other_flows(self):
        """The cron expression must not duplicate an existing scheduled flow."""
        step = self._load_weekly_release_step()
        agents, _ = load_pipeline(_PIPELINE_PATH)
        other_crons = {
            a.flow_schedule for a in agents
            if a.flow_schedule and a.flow != "weekly-release"
        }
        assert step.flow_schedule not in other_crons, (
            f"weekly-release schedule {step.flow_schedule!r} collides with "
            f"another scheduled flow's cron"
        )

    def test_weekly_release_inherits_eastern_timezone(self):
        """All scheduled flows inherit defaults.schedule_timezone = America/New_York."""
        step = self._load_weekly_release_step()
        assert step.flow_schedule_timezone == "America/New_York", (
            "weekly-release flow must inherit defaults.schedule_timezone"
        )

    def test_weekly_release_script_path_exists(self):
        """The declared script must exist on disk."""
        step = self._load_weekly_release_step()
        script_file = Path(__file__).parent.parent / step.script_path
        assert script_file.exists(), (
            f"weekly-release script {step.script_path!r} not found at {script_file}"
        )


# ---------------------------------------------------------------------------
# Script behavior tests (Scenarios R3/R4, R5/R6, R7)
# ---------------------------------------------------------------------------

def _fake_gh(tmp_path, responses: dict[str, str]) -> Path:
    """Write a fake gh binary that echoes canned responses for each API path.

    responses: {path_fragment: json_string}.  The fake gh looks for the first
    key that appears in the argument list and prints the matching response.
    If no key matches, it prints '[]' and exits 0 so callers that do --jq
    still get a parseable result.
    """
    lines = ["#!/usr/bin/env bash", "ARGS=\"$*\""]
    for fragment, body in responses.items():
        safe_fragment = fragment.replace("'", "'\\''")
        safe_body = body.replace("'", "'\\''").replace("\n", "\\n")
        lines.append(f"if [[ \"$ARGS\" == *'{safe_fragment}'* ]]; then")
        lines.append(f"  printf '%s' '{safe_body}'")
        lines.append(f"  exit 0")
        lines.append("fi")
    lines.append("printf '%s' '[]'")
    lines.append("exit 0")
    script = tmp_path / "gh"
    script.write_text("\n".join(lines) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return tmp_path


def _run_script(tmp_path, fake_bin_dir: Path, repo="org/repo",
                *, gh_token="fake-token"):
    """Run run-release-flow.sh with a fake gh binary."""
    env = {
        "PATH": str(fake_bin_dir) + ":" + os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "REPO": repo,
        "GH_TOKEN": gh_token,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


class TestRunReleaseFlowNoChange:
    """Scenario R3/R4: when no merged PRs or closed issues exist since the last
    release, the script exits complete and records a structured no-change JSON
    to stderr."""

    def test_no_change_exits_complete(self, tmp_path):
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "issues?state=closed": _NO_ISSUES,
        })
        result = _run_script(tmp_path, fake_bin)
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: complete" in result.stdout

    def test_no_change_records_structured_outcome_in_stderr(self, tmp_path):
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "issues?state=closed": _NO_ISSUES,
        })
        result = _run_script(tmp_path, fake_bin)
        # Structured JSON must appear in stderr.
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "no-change" in line),
            None,
        )
        assert json_line is not None, (
            f"expected no-change JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "no-change"
        assert "last_release_date" in record
        assert "timestamp" in record

    def test_no_change_when_no_prior_release(self, tmp_path):
        """When there is no prior release (404), epoch date is used and an
        empty PR/issue list still triggers no-change."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _EMPTY_RELEASES,
            "pulls?state=closed": _NO_PULLS,
            "issues?state=closed": _NO_ISSUES,
        })
        result = _run_script(tmp_path, fake_bin)
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: complete" in result.stdout
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "no-change" in line),
            None,
        )
        assert json_line is not None
        record = json.loads(json_line)
        assert record["outcome"] == "no-change"


class TestRunReleaseFlowStub:
    """Scenario R7: when changes exist the stub path exits complete without
    creating a GitHub Release."""

    def test_stub_path_exits_complete(self, tmp_path):
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "issues?state=closed": _NO_ISSUES,
        })
        result = _run_script(tmp_path, fake_bin)
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: complete" in result.stdout

    def test_stub_path_does_not_call_release_create(self, tmp_path):
        """Scenario R7: the stub must never call gh release create."""
        # Record all gh invocations by appending args to a log file.
        log_file = tmp_path / "gh_calls.txt"
        gh_lines = [
            "#!/usr/bin/env bash",
            f"echo \"$@\" >> '{log_file}'",
            "# Route canned responses.",
            "ARGS=\"$*\"",
            f"if [[ \"$ARGS\" == *'releases/latest'* ]]; then printf '%s' '{_ONE_RELEASE}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'pulls?state=closed'* ]]; then printf '%s' '{_ONE_PULL}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'issues?state=closed'* ]]; then printf '%s' '{_NO_ISSUES}'; exit 0; fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        gh_script = tmp_path / "gh"
        gh_script.write_text("\n".join(gh_lines) + "\n")
        gh_script.chmod(gh_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        result = _run_script(tmp_path, tmp_path)
        assert result.returncode == 0
        calls = log_file.read_text() if log_file.exists() else ""
        assert "release create" not in calls, (
            f"stub must not call 'gh release create'; calls were:\n{calls}"
        )

    def test_stub_records_structured_outcome_in_stderr(self, tmp_path):
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "issues?state=closed": _ONE_ISSUE,
        })
        result = _run_script(tmp_path, fake_bin)
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "stub" in line),
            None,
        )
        assert json_line is not None, (
            f"expected stub JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "stub"
        assert "merged_prs" in record
        assert "closed_issues" in record


class TestRunReleaseFlowRetry:
    """Scenario R5/R6: a failed run leaves no residual state so re-triggering
    starts cleanly."""

    def test_no_change_path_makes_no_writes(self, tmp_path):
        """The no-change path must not write to any file (idempotent)."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "issues?state=closed": _NO_ISSUES,
        })
        before = set(tmp_path.rglob("*"))
        _run_script(tmp_path, fake_bin)
        after = set(tmp_path.rglob("*"))
        new_files = {p for p in after - before if p.is_file() and p.name != "gh"}
        assert not new_files, (
            f"no-change path must not create files; found: {new_files}"
        )

    def test_stub_path_makes_no_writes(self, tmp_path):
        """The stub path must not write to any file (idempotent)."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "issues?state=closed": _NO_ISSUES,
        })
        before = set(tmp_path.rglob("*"))
        _run_script(tmp_path, fake_bin)
        after = set(tmp_path.rglob("*"))
        new_files = {p for p in after - before if p.is_file() and p.name != "gh"}
        assert not new_files, (
            f"stub path must not create files; found: {new_files}"
        )

    def test_two_consecutive_runs_produce_same_outcome(self, tmp_path):
        """A re-trigger produces the same outcome as the first run."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "issues?state=closed": _NO_ISSUES,
        })
        r1 = _run_script(tmp_path, fake_bin)
        r2 = _run_script(tmp_path, fake_bin)
        assert r1.returncode == r2.returncode == 0
        assert "AI_AGILE_STATUS: complete" in r1.stdout
        assert "AI_AGILE_STATUS: complete" in r2.stdout


class TestRunReleaseFlowMissingEnv:
    """The script must exit blocked when required env vars are absent."""

    def test_missing_repo_exits_blocked(self, tmp_path):
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(tmp_path)),
            "GH_TOKEN": "fake-token",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        result = subprocess.run(
            ["bash", str(_SCRIPT)],
            env=env, capture_output=True, text=True,
        )
        assert result.returncode != 0 or "REPO" in result.stderr

    def test_missing_token_exits_blocked(self, tmp_path):
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(tmp_path)),
            "REPO": "org/repo",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        result = subprocess.run(
            ["bash", str(_SCRIPT)],
            env=env, capture_output=True, text=True,
        )
        # Either exits non-zero or emits AI_AGILE_STATUS: blocked
        assert result.returncode != 0 or "AI_AGILE_STATUS: blocked" in result.stdout
