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

_ONE_RELEASE = json.dumps({
    "tag_name": "v2.1.0",
    "published_at": "2026-10-01T09:00:00Z",
})
# --paginate --slurp wraps each page in an outer array (one page here).
_NO_PULLS = json.dumps([[]])
_ONE_PULL = json.dumps([[{
    "number": 10,
    "merged_at": "2026-10-15T12:00:00Z",
    "title": "Some fix",
}]])
# --paginate --slurp wraps each page in an outer array (one page here).
_NO_ISSUES = json.dumps([[]])
_ONE_ISSUE = json.dumps([[{
    "number": 20,
    "pull_request": None,
    "closed_at": "2026-10-16T10:00:00Z",
    "title": "Some issue",
}]])


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

    def test_weekly_release_reachable_with_manual_override(self):
        """Scenario R2: --manual-override is the documented escape hatch that
        lets --interactive-result apply a person-produced result for this
        schedule-triggered step to a specific issue (pipeline_orchestrator.py's
        --manual-override CLI flag). Without the override it is unreachable
        (see the sibling test above); with it, eligibility must flip to True."""
        step = self._load_weekly_release_step()
        item = WorkItem(number=1, kind="issue", title="t", labels=set(), url="u")
        assert orch._should_run(
            step, item, item.labels, {}, None, gh=MagicMock(), repo="org/repo",
            manual_override=True,
        ) is True, "weekly-release must be reachable when --manual-override is set"

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

def _fake_gh(tmp_path, responses: dict[str, str | None]) -> Path:
    """Write a fake gh binary that echoes canned responses for each API path.

    responses: {path_fragment: json_string}.  The fake gh looks for the first
    key that appears in the argument list and prints the matching response.
    A value of None simulates gh's real behavior on a 404 (e.g. no prior
    GitHub Release): nothing on stdout, non-zero exit, matching the bare
    `gh api ... 2>/dev/null` error path the script guards with `if ...; then`.
    If no key matches, it prints '[]' and exits 0 so callers that do --jq
    still get a parseable result.
    """
    lines = ["#!/usr/bin/env bash", "ARGS=\"$*\""]
    for fragment, body in responses.items():
        safe_fragment = fragment.replace("'", "'\\''")
        lines.append(f"if [[ \"$ARGS\" == *'{safe_fragment}'* ]]; then")
        if body is None:
            lines.append(f"  exit 1")
        else:
            safe_body = body.replace("'", "'\\''").replace("\n", "\\n")
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
                *, gh_token="fake-token", extra_env=None):
    """Run run-release-flow.sh with a fake gh binary."""
    env = {
        "PATH": str(fake_bin_dir) + ":" + os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "REPO": repo,
        "GH_TOKEN": gh_token,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


def _make_notes_file(tmp_path):
    """Write a minimal canned release-notes file and return its path."""
    f = tmp_path / "canned-notes.md"
    f.write_text("# Release Notes\n\nTest content.\n")
    return f


class TestRunReleaseFlowNoChange:
    """Scenario R3/R4: when no merged PRs or closed issues exist since the last
    release, the script exits complete and records a structured no-change JSON
    to stderr."""

    def test_no_change_exits_complete(self, tmp_path):
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "repos/org/repo/issues": _NO_ISSUES,
        })
        result = _run_script(tmp_path, fake_bin)
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: complete" in result.stdout

    def test_no_change_records_structured_outcome_in_stderr(self, tmp_path):
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "repos/org/repo/issues": _NO_ISSUES,
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
        """When there is no prior release (404, real gh exits non-zero with
        no stdout), epoch date is used and an empty PR/issue list still
        triggers no-change."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": None,
            "pulls?state=closed": _NO_PULLS,
            "repos/org/repo/issues": _NO_ISSUES,
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


class TestRunReleaseFlowPublish:
    """When merged PRs exist and gates pass, the flow creates a GitHub Release
    and exits complete (issue #620)."""

    def test_publish_path_exits_complete(self, tmp_path):
        """Scenario: passing validation and all gates publishes a GitHub Release."""
        notes = _make_notes_file(tmp_path)
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "repos/org/repo/issues": _NO_ISSUES,
            # git/refs/tags returns [] by default -> next tag v2.1.0
            "releases/tags/v2.1.0": None,    # no duplicate
            "release create": "",             # publish succeeds
        })
        result = _run_script(tmp_path, fake_bin,
                             extra_env={"RELEASE_NOTES_FILE_OVERRIDE": str(notes)})
        assert result.returncode == 0, f"script failed:\n{result.stderr}"
        assert "AI_AGILE_STATUS: complete" in result.stdout

    def test_publish_path_calls_release_create(self, tmp_path):
        """Scenario: the publish path calls gh release create with the new tag."""
        notes = _make_notes_file(tmp_path)
        log_file = tmp_path / "gh_calls.txt"
        gh_lines = [
            "#!/usr/bin/env bash",
            f"echo \"$@\" >> '{log_file}'",
            "ARGS=\"$*\"",
            f"if [[ \"$ARGS\" == *'releases/latest'* ]]; then printf '%s' '{_ONE_RELEASE}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'pulls?state=closed'* ]]; then printf '%s' '{_ONE_PULL}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'repos/org/repo/issues'* ]]; then printf '%s' '{_NO_ISSUES}'; exit 0; fi",
            # releases/tags/<tag> returns nothing (404) -> no duplicate
            f"if [[ \"$ARGS\" == *'releases/tags/'* ]]; then exit 1; fi",
            # release create succeeds
            f"if [[ \"$ARGS\" == *'release create'* ]]; then exit 0; fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        gh_script = tmp_path / "gh"
        gh_script.write_text("\n".join(gh_lines) + "\n")
        gh_script.chmod(gh_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        result = _run_script(tmp_path, tmp_path,
                             extra_env={"RELEASE_NOTES_FILE_OVERRIDE": str(notes)})
        assert result.returncode == 0, f"script failed:\n{result.stderr}"
        calls = log_file.read_text() if log_file.exists() else ""
        assert "release create" in calls, (
            f"expected 'gh release create' to be called; calls were:\n{calls}"
        )

    def test_publish_records_structured_outcome_in_stderr(self, tmp_path):
        """Scenario: release metadata, status, and outcome are in orchestrator logs."""
        notes = _make_notes_file(tmp_path)
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "repos/org/repo/issues": _ONE_ISSUE,
            "releases/tags/v2.1.0": None,
            "release create": "",
        })
        result = _run_script(tmp_path, fake_bin,
                             extra_env={"RELEASE_NOTES_FILE_OVERRIDE": str(notes)})
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "published" in line),
            None,
        )
        assert json_line is not None, (
            f"expected published JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "published"
        assert "tag" in record
        assert "merged_prs" in record
        assert "timestamp" in record


class TestRunReleaseFlowGates:
    """Publication gates: coverage threshold and duplicate-release prevention
    (issue #620 acceptance criteria R3)."""

    def test_coverage_threshold_gate_blocks_publication(self, tmp_path):
        """Scenario: coverage threshold gate blocks publication when below threshold."""
        # MERGED_PRS=1 but threshold=5 -> gate-failed, no release created
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "repos/org/repo/issues": _NO_ISSUES,
            "releases/tags/v2.1.0": None,
        })
        result = _run_script(tmp_path, fake_bin,
                             extra_env={"RELEASE_COVERAGE_THRESHOLD": "5"})
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: complete" in result.stdout
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "gate-failed" in line),
            None,
        )
        assert json_line is not None, (
            f"expected gate-failed JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "gate-failed"
        assert record["coverage_threshold"] == 5
        assert record["merged_prs"] == 1

    def test_coverage_threshold_gate_does_not_call_release_create(self, tmp_path):
        """Coverage gate failure must not call gh release create."""
        log_file = tmp_path / "gh_calls.txt"
        gh_lines = [
            "#!/usr/bin/env bash",
            f"echo \"$@\" >> '{log_file}'",
            "ARGS=\"$*\"",
            f"if [[ \"$ARGS\" == *'releases/latest'* ]]; then printf '%s' '{_ONE_RELEASE}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'pulls?state=closed'* ]]; then printf '%s' '{_ONE_PULL}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'repos/org/repo/issues'* ]]; then printf '%s' '{_NO_ISSUES}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'releases/tags/'* ]]; then exit 1; fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        gh_script = tmp_path / "gh"
        gh_script.write_text("\n".join(gh_lines) + "\n")
        gh_script.chmod(gh_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        _run_script(tmp_path, tmp_path,
                    extra_env={"RELEASE_COVERAGE_THRESHOLD": "5"})
        calls = log_file.read_text() if log_file.exists() else ""
        assert "release create" not in calls, (
            f"gate failure must not call 'gh release create'; calls were:\n{calls}"
        )

    def test_duplicate_release_skips_without_creating(self, tmp_path):
        """Scenario: a rerun does not create a duplicate tag or release."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "repos/org/repo/issues": _NO_ISSUES,
            # The release for the computed tag already exists -> skipped
            "releases/tags/v2.1.0": json.dumps(
                {"tag_name": "v2.1.0", "published_at": "2026-10-28T09:00:00Z"}
            ),
        })
        result = _run_script(tmp_path, fake_bin)
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: complete" in result.stdout
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "skipped" in line),
            None,
        )
        assert json_line is not None, (
            f"expected skipped JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "skipped"

    def test_duplicate_release_does_not_call_release_create(self, tmp_path):
        """A duplicate release detected must not call gh release create."""
        existing = json.dumps(
            {"tag_name": "v2.1.0", "published_at": "2026-10-28T09:00:00Z"}
        )
        log_file = tmp_path / "gh_calls.txt"
        gh_lines = [
            "#!/usr/bin/env bash",
            f"echo \"$@\" >> '{log_file}'",
            "ARGS=\"$*\"",
            f"if [[ \"$ARGS\" == *'releases/latest'* ]]; then printf '%s' '{_ONE_RELEASE}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'pulls?state=closed'* ]]; then printf '%s' '{_ONE_PULL}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'repos/org/repo/issues'* ]]; then printf '%s' '{_NO_ISSUES}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'releases/tags/'* ]]; then printf '%s' '{existing}'; exit 0; fi",
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
            f"duplicate detection must not call 'gh release create'; calls:\n{calls}"
        )


class TestRunReleaseFlowRetry:
    """Scenario R5/R6: retry and idempotency behavior."""

    def test_no_change_path_makes_no_writes(self, tmp_path):
        """The no-change path must not write to any file (idempotent)."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "repos/org/repo/issues": _NO_ISSUES,
        })
        before = set(tmp_path.rglob("*"))
        _run_script(tmp_path, fake_bin)
        after = set(tmp_path.rglob("*"))
        new_files = {p for p in after - before if p.is_file() and p.name != "gh"}
        assert not new_files, (
            f"no-change path must not create files; found: {new_files}"
        )

    def test_two_consecutive_no_change_runs_produce_same_outcome(self, tmp_path):
        """A re-trigger on the no-change path produces the same outcome."""
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _NO_PULLS,
            "repos/org/repo/issues": _NO_ISSUES,
        })
        r1 = _run_script(tmp_path, fake_bin)
        r2 = _run_script(tmp_path, fake_bin)
        assert r1.returncode == r2.returncode == 0
        assert "AI_AGILE_STATUS: complete" in r1.stdout
        assert "AI_AGILE_STATUS: complete" in r2.stdout

    def test_duplicate_detection_makes_rerun_idempotent(self, tmp_path):
        """A rerun after a published release exits complete via duplicate detection."""
        existing = json.dumps(
            {"tag_name": "v2.1.0", "published_at": "2026-10-28T09:00:00Z"}
        )
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "repos/org/repo/issues": _NO_ISSUES,
            "releases/tags/v2.1.0": existing,
        })
        r1 = _run_script(tmp_path, fake_bin)
        r2 = _run_script(tmp_path, fake_bin)
        assert r1.returncode == r2.returncode == 0
        assert "AI_AGILE_STATUS: complete" in r1.stdout
        assert "AI_AGILE_STATUS: complete" in r2.stdout


class TestRunReleaseFlowErrors:
    """Error paths: gh release create failure, empty notes file, tag discovery
    failure.  All error outcomes must exit 0 and emit AI_AGILE_STATUS: blocked
    (issue #620 RV-003, RV-004)."""

    def test_release_create_failure_exits_zero_with_blocked_status(self, tmp_path):
        """Scenario: gh release create failure must exit 0 with AI_AGILE_STATUS: blocked."""
        notes = _make_notes_file(tmp_path)
        log_file = tmp_path / "gh_calls.txt"
        gh_lines = [
            "#!/usr/bin/env bash",
            f"echo \"$@\" >> '{log_file}'",
            "ARGS=\"$*\"",
            f"if [[ \"$ARGS\" == *'releases/latest'* ]]; then printf '%s' '{_ONE_RELEASE}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'pulls?state=closed'* ]]; then printf '%s' '{_ONE_PULL}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'repos/org/repo/issues'* ]]; then printf '%s' '{_NO_ISSUES}'; exit 0; fi",
            # git/refs/tags returns [] -> NEXT_TAG = v2.1.0
            f"if [[ \"$ARGS\" == *'git/refs/tags'* ]]; then printf '%s' '[[]]'; exit 0; fi",
            # no duplicate for this tag
            f"if [[ \"$ARGS\" == *'releases/tags/'* ]]; then exit 1; fi",
            # release create fails
            f"if [[ \"$ARGS\" == *'release create'* ]]; then exit 1; fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        gh_script = tmp_path / "gh"
        gh_script.write_text("\n".join(gh_lines) + "\n")
        gh_script.chmod(gh_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        result = _run_script(tmp_path, tmp_path,
                             extra_env={"RELEASE_NOTES_FILE_OVERRIDE": str(notes)})
        assert result.returncode == 0, (
            f"script must exit 0 on release create failure; got {result.returncode};\n{result.stderr}"
        )
        assert "AI_AGILE_STATUS: blocked" in result.stdout

    def test_release_create_failure_records_error_outcome(self, tmp_path):
        """gh release create failure must record outcome: error in stderr."""
        notes = _make_notes_file(tmp_path)
        gh_lines = [
            "#!/usr/bin/env bash",
            "ARGS=\"$*\"",
            f"if [[ \"$ARGS\" == *'releases/latest'* ]]; then printf '%s' '{_ONE_RELEASE}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'pulls?state=closed'* ]]; then printf '%s' '{_ONE_PULL}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'repos/org/repo/issues'* ]]; then printf '%s' '{_NO_ISSUES}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'git/refs/tags'* ]]; then printf '%s' '[[]]'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'releases/tags/'* ]]; then exit 1; fi",
            f"if [[ \"$ARGS\" == *'release create'* ]]; then exit 1; fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        gh_script = tmp_path / "gh"
        gh_script.write_text("\n".join(gh_lines) + "\n")
        gh_script.chmod(gh_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        result = _run_script(tmp_path, tmp_path,
                             extra_env={"RELEASE_NOTES_FILE_OVERRIDE": str(notes)})
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "error" in line),
            None,
        )
        assert json_line is not None, (
            f"expected outcome: error JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "error"

    def test_empty_notes_file_exits_zero_with_blocked_status(self, tmp_path):
        """Scenario: empty notes file must exit 0 with AI_AGILE_STATUS: blocked."""
        empty_notes = tmp_path / "empty-notes.md"
        empty_notes.write_text("")
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "repos/org/repo/issues": _NO_ISSUES,
            "releases/tags/v2.1.0": None,
        })
        result = _run_script(tmp_path, fake_bin,
                             extra_env={"RELEASE_NOTES_FILE_OVERRIDE": str(empty_notes)})
        assert result.returncode == 0, (
            f"script must exit 0 on empty notes; got {result.returncode};\n{result.stderr}"
        )
        assert "AI_AGILE_STATUS: blocked" in result.stdout

    def test_empty_notes_file_records_error_outcome(self, tmp_path):
        """Empty notes file must record outcome: error in stderr."""
        empty_notes = tmp_path / "empty-notes.md"
        empty_notes.write_text("")
        fake_bin = _fake_gh(tmp_path, {
            "releases/latest": _ONE_RELEASE,
            "pulls?state=closed": _ONE_PULL,
            "repos/org/repo/issues": _NO_ISSUES,
            "releases/tags/v2.1.0": None,
        })
        result = _run_script(tmp_path, fake_bin,
                             extra_env={"RELEASE_NOTES_FILE_OVERRIDE": str(empty_notes)})
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "error" in line),
            None,
        )
        assert json_line is not None, (
            f"expected outcome: error JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "error"

    def test_tag_discovery_failure_exits_zero_with_blocked_status(self, tmp_path):
        """Scenario: tag discovery API failure must exit 0 with AI_AGILE_STATUS: blocked
        rather than silently falling back to a hardcoded version string (RV-001)."""
        gh_lines = [
            "#!/usr/bin/env bash",
            "ARGS=\"$*\"",
            f"if [[ \"$ARGS\" == *'releases/latest'* ]]; then printf '%s' '{_ONE_RELEASE}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'pulls?state=closed'* ]]; then printf '%s' '{_ONE_PULL}'; exit 0; fi",
            f"if [[ \"$ARGS\" == *'repos/org/repo/issues'* ]]; then printf '%s' '{_NO_ISSUES}'; exit 0; fi",
            # tag discovery fails
            "if [[ \"$ARGS\" == *'git/refs/tags'* ]]; then exit 1; fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        gh_script = tmp_path / "gh"
        gh_script.write_text("\n".join(gh_lines) + "\n")
        gh_script.chmod(gh_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        result = _run_script(tmp_path, tmp_path)
        assert result.returncode == 0, (
            f"script must exit 0 on tag discovery failure; got {result.returncode};\n{result.stderr}"
        )
        assert "AI_AGILE_STATUS: blocked" in result.stdout
        json_line = next(
            (line for line in result.stderr.splitlines()
             if line.startswith("{") and "error" in line),
            None,
        )
        assert json_line is not None, (
            f"expected outcome: error JSON in stderr; got:\n{result.stderr}"
        )
        record = json.loads(json_line)
        assert record["outcome"] == "error"
        assert "tag discovery" in record["reason"]


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
