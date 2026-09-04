"""Tests for issue #406's scheduled flows.

A scheduled flow has no work item, so the two things it needs are read from
the record rather than from a label or a table of its own:

  - due-ness: when this flow's steps last appended an entry to the metrics
    branch, with a flow that has never run reading as overdue;
  - its mutex: a claim appended to that same append-only log, where losing the
    push race IS the mutex failure, and a stranded claim expires on age.

No shipped flow declares a schedule yet -- these prove the mechanism.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pipeline_orchestrator as orch
from pipeline_orchestrator import (
    AgentDef,
    cron_matches,
    previous_fire_time,
    schedule_is_due,
    flow_last_run,
    schedule_claim_is_held,
    claim_schedule,
    release_schedule,
    read_metrics_records,
    SCHEDULE_CLAIM_EVENT,
    SCHEDULE_RELEASE_EVENT,
    SCHEDULE_CLAIM_LEASE_SECONDS,
)


def _t(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _record(flow, when, *, event=None, agent="05_continuous/loop"):
    rec = {
        "timestamp_start": when,
        "timestamp_end": when,
        "github_issue_number": None,
        "agent_id": agent,
        "flow": flow,
        "cycle_id": "c",
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "retry_count": 0,
        "retry_errors": [],
    }
    if event:
        rec["event"] = event
    return rec


# ---------------------------------------------------------------------------
# Cron matching
# ---------------------------------------------------------------------------

class TestCronMatching:
    def test_every_minute(self):
        assert cron_matches("* * * * *", _t("2026-09-04T13:07:00")) is True

    def test_hour_and_minute(self):
        assert cron_matches("0 3 * * *", _t("2026-09-04T03:00:00")) is True
        assert cron_matches("0 3 * * *", _t("2026-09-04T04:00:00")) is False

    def test_step_values(self):
        assert cron_matches("*/15 * * * *", _t("2026-09-04T13:30:00")) is True
        assert cron_matches("*/15 * * * *", _t("2026-09-04T13:31:00")) is False

    def test_ranges_and_lists(self):
        assert cron_matches("0 9-17 * * *", _t("2026-09-04T12:00:00")) is True
        assert cron_matches("0 9-17 * * *", _t("2026-09-04T18:00:00")) is False
        assert cron_matches("0 0 1,15 * *", _t("2026-09-15T00:00:00")) is True

    def test_day_of_week(self):
        # 2026-09-07 is a Monday.
        assert cron_matches("0 6 * * 1", _t("2026-09-07T06:00:00")) is True
        assert cron_matches("0 6 * * 1", _t("2026-09-08T06:00:00")) is False

    def test_sunday_is_both_zero_and_seven(self):
        sunday = _t("2026-09-06T06:00:00")
        assert cron_matches("0 6 * * 0", sunday) is True
        assert cron_matches("0 6 * * 7", sunday) is True

    def test_malformed_expression_is_rejected(self):
        with pytest.raises(ValueError):
            cron_matches("0 3 * *", _t("2026-09-04T03:00:00"))

    def test_previous_fire_time_walks_back_to_the_last_firing(self):
        assert previous_fire_time("0 3 * * *", _t("2026-09-04T13:07:00")) == _t("2026-09-04T03:00:00")

    def test_previous_fire_time_crosses_days(self):
        assert previous_fire_time("0 3 * * *", _t("2026-09-04T01:00:00")) == _t("2026-09-03T03:00:00")


# ---------------------------------------------------------------------------
# Due-ness, read from the record
# ---------------------------------------------------------------------------

class TestDueness:
    def test_a_flow_that_has_never_run_is_due(self):
        assert flow_last_run([], "learn-loop") is None
        assert schedule_is_due("0 3 * * *", None, _t("2026-09-04T13:00:00")) is True

    def test_a_flow_that_ran_since_the_last_firing_is_not_due(self):
        last = _t("2026-09-04T03:05:00")
        assert schedule_is_due("0 3 * * *", last, _t("2026-09-04T13:00:00")) is False

    def test_a_flow_that_has_not_run_since_the_last_firing_is_due(self):
        last = _t("2026-09-03T03:05:00")
        assert schedule_is_due("0 3 * * *", last, _t("2026-09-04T13:00:00")) is True

    def test_last_run_is_the_newest_entry_for_that_flow(self):
        records = [
            _record("learn-loop", "2026-09-01T03:00:00Z"),
            _record("other-flow", "2026-09-04T03:00:00Z"),
            _record("learn-loop", "2026-09-02T03:00:00Z"),
        ]
        assert flow_last_run(records, "learn-loop") == _t("2026-09-02T03:00:00")

    def test_claims_are_bookkeeping_and_never_count_as_a_run(self):
        records = [
            _record("learn-loop", "2026-09-01T03:00:00Z"),
            _record("learn-loop", "2026-09-04T03:00:00Z", event=SCHEDULE_CLAIM_EVENT),
            _record("learn-loop", "2026-09-04T03:10:00Z", event=SCHEDULE_RELEASE_EVENT),
        ]
        assert flow_last_run(records, "learn-loop") == _t("2026-09-01T03:00:00")

    def test_there_is_no_last_run_table_anywhere(self):
        """Due-ness is a read of the record and nothing else (AC4)."""
        import inspect
        source = inspect.getsource(orch.flow_last_run) + inspect.getsource(orch.schedule_is_due)
        assert "open(" not in source and "Path(" not in source


# ---------------------------------------------------------------------------
# The claim: a mutex distinct from :wip
# ---------------------------------------------------------------------------

class TestScheduleClaim:
    def test_no_claim_means_free(self):
        assert schedule_claim_is_held([], "learn-loop", _t("2026-09-04T13:00:00")) is False

    def test_a_fresh_claim_is_held(self):
        records = [_record("learn-loop", "2026-09-04T12:59:00Z", event=SCHEDULE_CLAIM_EVENT)]
        assert schedule_claim_is_held(records, "learn-loop", _t("2026-09-04T13:00:00")) is True

    def test_a_released_claim_is_free_again(self):
        records = [
            _record("learn-loop", "2026-09-04T12:50:00Z", event=SCHEDULE_CLAIM_EVENT),
            _record("learn-loop", "2026-09-04T12:55:00Z", event=SCHEDULE_RELEASE_EVENT),
        ]
        assert schedule_claim_is_held(records, "learn-loop", _t("2026-09-04T13:00:00")) is False

    def test_a_stranded_claim_expires_on_age(self):
        """A runner that died mid-flight must not wedge the schedule forever."""
        stale = _t("2026-09-04T13:00:00") - timedelta(seconds=SCHEDULE_CLAIM_LEASE_SECONDS + 60)
        records = [_record(
            "learn-loop", stale.strftime("%Y-%m-%dT%H:%M:%SZ"), event=SCHEDULE_CLAIM_EVENT,
        )]
        assert schedule_claim_is_held(records, "learn-loop", _t("2026-09-04T13:00:00")) is False

    def test_another_flows_claim_is_not_this_ones(self):
        records = [_record("other-flow", "2026-09-04T12:59:00Z", event=SCHEDULE_CLAIM_EVENT)]
        assert schedule_claim_is_held(records, "learn-loop", _t("2026-09-04T13:00:00")) is False

    def test_claiming_appends_a_claim_record_to_the_log(self, monkeypatch):
        appended = []
        monkeypatch.setattr(orch, "read_metrics_records", lambda repo: [])
        monkeypatch.setattr(orch, "_ensure_metrics_branch", lambda gh, repo: None)
        monkeypatch.setattr(
            orch, "_append_metrics_record",
            lambda gh, repo, record, **kw: appended.append((record, kw)),
        )
        assert claim_schedule(MagicMock(), "org/repo", "learn-loop") is True
        record, kwargs = appended[0]
        assert record["event"] == SCHEDULE_CLAIM_EVENT
        assert record["flow"] == "learn-loop"
        assert record["github_issue_number"] is None
        # No retry: a rejected push is the mutex answer, not a transient error.
        assert kwargs["_retries"] == 0

    def test_a_lost_push_race_is_the_mutex_failure(self, monkeypatch):
        """Two runners, one winner: the append is already a compare-and-swap."""
        monkeypatch.setattr(orch, "read_metrics_records", lambda repo: [])
        monkeypatch.setattr(orch, "_ensure_metrics_branch", lambda gh, repo: None)

        pushed = []

        def _append(gh, repo, record, **kw):
            if pushed:
                raise RuntimeError("git push to ai-agile/metrics failed: rejected")
            pushed.append(record)

        monkeypatch.setattr(orch, "_append_metrics_record", _append)
        first = claim_schedule(MagicMock(), "org/repo", "learn-loop")
        second = claim_schedule(MagicMock(), "org/repo", "learn-loop")
        assert (first, second) == (True, False)
        assert len(pushed) == 1

    def test_an_existing_claim_stops_a_second_runner_before_it_pushes(self, monkeypatch):
        held = [_record("learn-loop", "2026-09-04T12:59:00Z", event=SCHEDULE_CLAIM_EVENT)]
        monkeypatch.setattr(orch, "read_metrics_records", lambda repo: held)
        appended = []
        monkeypatch.setattr(orch, "_ensure_metrics_branch", lambda gh, repo: None)
        monkeypatch.setattr(
            orch, "_append_metrics_record",
            lambda gh, repo, record, **kw: appended.append(record),
        )
        assert claim_schedule(
            MagicMock(), "org/repo", "learn-loop", now=_t("2026-09-04T13:00:00"),
        ) is False
        assert appended == []

    def test_release_appends_a_release_record(self, monkeypatch):
        appended = []
        monkeypatch.setattr(
            orch, "_append_metrics_record",
            lambda gh, repo, record, **kw: appended.append(record),
        )
        release_schedule(MagicMock(), "org/repo", "learn-loop")
        assert appended[0]["event"] == SCHEDULE_RELEASE_EVENT

    def test_release_never_raises(self, monkeypatch):
        monkeypatch.setattr(
            orch, "_append_metrics_record",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        release_schedule(MagicMock(), "org/repo", "learn-loop")  # must not raise

    def test_the_claim_is_not_a_wip_label(self):
        """:wip is a label on a work item; a scheduled flow has none (AC4)."""
        import inspect
        source = inspect.getsource(orch.claim_schedule)
        assert "add_label" not in source and "STATUS_WIP" not in source


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------

class TestReadMetricsRecords:
    def test_parses_one_object_per_line(self, monkeypatch):
        lines = "\n".join(json.dumps(_record("f", "2026-09-04T03:00:00Z")) for _ in range(3))
        monkeypatch.setattr(orch.subprocess, "run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=lines),
        ]))
        assert len(read_metrics_records("org/repo")) == 3

    def test_a_missing_records_file_reads_as_nothing_has_happened(self, monkeypatch):
        monkeypatch.setattr(orch.subprocess, "run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=128, stdout=""),
        ]))
        assert read_metrics_records("org/repo") == []

    def test_a_corrupt_line_is_skipped_not_fatal(self, monkeypatch):
        lines = json.dumps(_record("f", "2026-09-04T03:00:00Z")) + "\n{ not json\n"
        monkeypatch.setattr(orch.subprocess, "run", MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=lines),
        ]))
        assert len(read_metrics_records("org/repo")) == 1


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _scheduled_step(flow="learn-loop", cron="0 3 * * *", **overrides):
    kwargs = dict(
        agent="05_continuous/learn-loop",
        phase="05_continuous",
        objects=[],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="a scheduled sweep",
        step_type="script",
        script_path=".github/scripts/learn-loop.sh",
        flow=flow,
        flow_schedule=cron,
        expected_effect={"commits": False, "creates_issues": True},
    )
    kwargs.update(overrides)
    return AgentDef(**kwargs)


def _ctx(agents, dry_run=False):
    return orch.RunContext(
        gh=MagicMock(), agents=agents, pipeline_map={}, work_items=[],
        concurrency=orch.ComponentClaims(), repo="org/repo", session_id="s",
        dry_run=dry_run, default_extra_tools=None,
    )


class TestScheduledDispatch:
    def test_a_scheduled_step_is_never_reached_by_the_per_item_loop(self):
        step = _scheduled_step()
        item = orch.WorkItem(number=1, kind="issue", title="t", labels=set(), url="u")
        assert orch._should_run(step, item, item.labels, {}, None, gh=MagicMock(), repo="org/repo") is False

    def test_a_due_flow_claims_runs_and_releases(self, monkeypatch):
        ctx = _ctx([_scheduled_step()])
        monkeypatch.setattr(orch, "read_metrics_records", lambda repo: [])
        monkeypatch.setattr(orch, "claim_schedule", MagicMock(return_value=True))
        released = []
        monkeypatch.setattr(orch, "release_schedule", lambda gh, repo, flow, **kw: released.append(flow))
        ran = []
        monkeypatch.setattr(orch, "_run_scheduled_step", lambda c, a, w: ran.append(a.agent))

        assert orch._run_scheduled_flows(ctx) == 1
        assert ran == ["05_continuous/learn-loop"]
        assert released == ["learn-loop"]

    def test_a_flow_that_is_not_due_does_not_claim(self, monkeypatch):
        ctx = _ctx([_scheduled_step()])
        monkeypatch.setattr(
            orch, "read_metrics_records",
            lambda repo: [_record("learn-loop", orch._now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"))],
        )
        claimed = MagicMock()
        monkeypatch.setattr(orch, "claim_schedule", claimed)
        monkeypatch.setattr(orch, "_run_scheduled_step", MagicMock())
        assert orch._run_scheduled_flows(ctx) == 0
        claimed.assert_not_called()

    def test_a_flow_whose_claim_is_taken_does_not_run(self, monkeypatch):
        ctx = _ctx([_scheduled_step()])
        monkeypatch.setattr(orch, "read_metrics_records", lambda repo: [])
        monkeypatch.setattr(orch, "claim_schedule", MagicMock(return_value=False))
        run = MagicMock()
        monkeypatch.setattr(orch, "_run_scheduled_step", run)
        assert orch._run_scheduled_flows(ctx) == 0
        run.assert_not_called()

    def test_the_claim_is_released_even_when_a_step_raises(self, monkeypatch):
        ctx = _ctx([_scheduled_step()])
        monkeypatch.setattr(orch, "read_metrics_records", lambda repo: [])
        monkeypatch.setattr(orch, "claim_schedule", MagicMock(return_value=True))
        released = []
        monkeypatch.setattr(orch, "release_schedule", lambda gh, repo, flow, **kw: released.append(flow))
        monkeypatch.setattr(orch, "_run_scheduled_step", MagicMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            orch._run_scheduled_flows(ctx)
        assert released == ["learn-loop"]

    def test_nothing_happens_when_no_flow_declares_a_schedule(self, monkeypatch):
        """The shipped pipeline has no scheduled flow -- and pays nothing for it."""
        read = MagicMock()
        monkeypatch.setattr(orch, "read_metrics_records", read)
        assert orch._run_scheduled_flows(_ctx([])) == 0
        read.assert_not_called()

    def test_a_malformed_cadence_is_reported_not_run(self, monkeypatch):
        ctx = _ctx([_scheduled_step(cron="not a cron")])
        monkeypatch.setattr(orch, "read_metrics_records", lambda repo: [])
        run = MagicMock()
        monkeypatch.setattr(orch, "_run_scheduled_step", run)
        assert orch._run_scheduled_flows(ctx) == 0
        run.assert_not_called()

    def test_a_scheduled_step_has_no_work_item_number(self):
        work_item = orch._schedule_work_item("learn-loop")
        assert work_item.kind == orch.SCHEDULE_WORK_ITEM_KIND
        env = orch._flow_context_env(_scheduled_step(), work_item)
        assert "AI_AGILE_BRANCH" not in env
        assert env["AI_AGILE_FLOW"] == "learn-loop"

    def test_the_run_appends_an_entry_that_makes_the_next_dueness_computable(self, monkeypatch):
        ctx = _ctx([_scheduled_step()])
        step = ctx.agents[0]
        appended = []
        monkeypatch.setattr(orch, "invoke_script", lambda *a, **k: orch.AgentRunResult(success=True))
        monkeypatch.setattr(orch, "_ensure_metrics_branch", lambda gh, repo: None)
        monkeypatch.setattr(
            orch, "_append_metrics_record",
            lambda gh, repo, record, **kw: appended.append(record),
        )
        orch._run_scheduled_step(ctx, step, orch._schedule_work_item("learn-loop"))
        assert appended[0]["flow"] == "learn-loop"
        assert appended[0]["github_issue_number"] is None
        assert flow_last_run(appended, "learn-loop") is not None

    def test_a_scheduled_step_raises_its_findings_as_a_stamped_work_item(self, monkeypatch):
        ctx = _ctx([_scheduled_step(step_type="agent", script_path=None,
                                     model="claude-sonnet-4-6")])
        step = ctx.agents[0]
        ctx.gh.create_issue.return_value = 900
        monkeypatch.setattr(orch, "invoke_agent", lambda *a, **k: orch.AgentRunResult(success=True))
        monkeypatch.setattr(orch, "_scratch_path", lambda sid: "/tmp/none")
        monkeypatch.setattr(orch, "_read_step_result", lambda scratch: (orch.StepResult(
            outcome="complete", summary="swept",
            creates_issue={"title": "Tech debt found", "body": "details"},
        ), ""))
        monkeypatch.setattr(orch, "_ensure_metrics_branch", lambda gh, repo: None)
        monkeypatch.setattr(orch, "_append_metrics_record", lambda *a, **k: None)

        orch._run_scheduled_step(ctx, step, orch._schedule_work_item("learn-loop"))

        title, body, _labels = ctx.gh.create_issue.call_args.args
        assert title == "Tech debt found"
        assert body.startswith(orch.provenance_stamp(step))

    def test_a_tick_scoped_to_one_item_leaves_the_cadences_alone(self, monkeypatch):
        """--issue asks about one work item; a schedule is about the repo."""
        ctx = _ctx([_scheduled_step()])
        ctx.scoped_to_item = True
        read = MagicMock()
        monkeypatch.setattr(orch, "read_metrics_records", read)
        run = MagicMock()
        monkeypatch.setattr(orch, "_run_scheduled_step", run)
        assert orch._run_scheduled_flows(ctx) == 0
        read.assert_not_called()
        run.assert_not_called()
