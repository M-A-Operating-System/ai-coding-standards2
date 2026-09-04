"""Tests for the stale `:wip` reclaim (MI-4, issue #407).

A step can just stop existing -- the machine running it is lost, or the process
is killed outright. Nothing is returned, no signal handler runs, and the `:wip`
it held stays on the item forever. The reclaim is therefore something a LATER
tick does, by looking at the label rather than the run.

Scenarios traced to docs/features/orchestrator.md:
  Scenario: A `:wip` still inside its step's allowance is left alone
  Scenario: A `:wip` past its step's allowance is reclaimed and recorded failed
  Scenario: A reclaim draws from the retry budget
  Scenario: A `:wip` with no readable claim comment is never reclaimed on a guess
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
import pipeline_orchestrator as po  # noqa: E402


NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


def _agent(name="03_execute/coder", *, max_wall_seconds=600, max_retries=1):
    return po.AgentDef(
        agent=name,
        phase=name.split("/", 1)[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test step",
        max_wall_seconds=max_wall_seconds,
        max_retries=max_retries,
    )


def _item(agent_def, number=407, status=po.STATUS_WIP):
    labels = {agent_def.status_label(status)} if status else set()
    return po.WorkItem(
        number=number, kind="issue", title="t",
        labels=labels, url="https://example.invalid/407",
    )


def _claim_comment(agent_def, started_at):
    """An opening announcement, byte-identical in shape to the real one."""
    return (
        f"<!-- ai-agile/announcement/v1 by {agent_def.agent} -->\n"
        "```json\n"
        + json.dumps({
            "session_id": "sid",
            "agent": agent_def.agent,
            "phase": "start",
            "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "intent": "test step",
        }, indent=2)
        + "\n```"
    )


def _gh(comments):
    gh = MagicMock()
    gh.repo = "owner/repo"
    gh.list_comment_bodies.return_value = list(comments)
    return gh


def _reclaim(gh, agent_def, work_item, *, now=NOW):
    return po._reclaim_stale_wip(
        gh, [agent_def], work_item, set(work_item.labels),
        "owner/repo", "sid", now=now,
    )


# ---------------------------------------------------------------------------
# Scenario: A :wip still inside its step's allowance is left alone
# ---------------------------------------------------------------------------

class TestAWipInsideItsAllowance:
    def test_the_lease_covers_every_attempt_not_just_one(self):
        """The mutex is held across the whole retry allowance, so reclaiming on
        a single wall-clock budget would take the lock off a step that is
        legitimately on its second attempt."""
        agent_def = _agent(max_wall_seconds=600, max_retries=1)
        assert po._wip_lease_seconds(agent_def) == \
            2 * 600 + po.WIP_RECLAIM_GRACE_SECONDS

    def test_a_step_with_no_override_uses_the_pipeline_wide_budget(self):
        agent_def = _agent(max_wall_seconds=None, max_retries=0)
        assert po._wip_lease_seconds(agent_def) == \
            po.AGENT_TIMEOUT_SECONDS + po.WIP_RECLAIM_GRACE_SECONDS

    def test_a_fresh_claim_is_not_touched(self):
        agent_def = _agent()
        item = _item(agent_def)
        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=30))])

        labels = _reclaim(gh, agent_def, item)

        assert labels == {agent_def.status_label(po.STATUS_WIP)}
        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()

    def test_a_claim_just_inside_the_allowance_is_not_touched(self):
        agent_def = _agent()
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=lease - 1))])

        _reclaim(gh, agent_def, item)

        gh.add_label.assert_not_called()

    def test_an_item_with_no_wip_is_not_inspected(self):
        agent_def = _agent()
        item = _item(agent_def, status=po.STATUS_COMPLETE)
        gh = _gh([])

        _reclaim(gh, agent_def, item)

        gh.list_comment_bodies.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: A :wip past its step's allowance is reclaimed and recorded failed
# ---------------------------------------------------------------------------

class TestAStrandedWip:
    @pytest.fixture
    def stranded(self):
        agent_def = _agent()
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=lease + 60))])
        labels = _reclaim(gh, agent_def, item)
        return agent_def, item, gh, labels, lease

    def test_the_wip_label_is_taken_back(self, stranded):
        agent_def, _item_, gh, labels, _lease = stranded
        gh.remove_label.assert_any_call(
            407, agent_def.status_label(po.STATUS_WIP),
        )
        assert agent_def.status_label(po.STATUS_WIP) not in labels

    def test_the_step_is_recorded_failed(self, stranded):
        agent_def, _item_, gh, labels, _lease = stranded
        gh.add_label.assert_any_call(407, agent_def.failed_label)
        assert agent_def.failed_label in labels

    def test_the_returned_labels_are_what_the_rest_of_the_tick_sees(self, stranded):
        _agent_def, item, _gh, labels, _lease = stranded
        assert item.labels == labels

    def test_the_orchestrator_says_what_happened_and_what_clears_it(self, stranded):
        agent_def, _item_, gh, _labels, lease = stranded
        posted = "\n\n".join(c.args[1] for c in gh.post_comment.call_args_list)
        assert "stale `:wip` reclaimed" in posted
        assert str(lease) in posted
        assert agent_def.failed_label in posted

    def test_it_posts_the_orchestrators_own_closing_announcement(self, stranded):
        agent_def, _item_, gh, _labels, _lease = stranded
        announcements = [
            c.args[1] for c in gh.post_comment.call_args_list
            if f"<!-- ai-agile/announcement/v1 by {agent_def.agent} -->" in c.args[1]
        ]
        assert announcements, "MI-4: the orchestrator posts the recovery guidance"
        payload = po._announcement_payload(announcements[-1])
        assert payload["phase"] == "end"
        assert payload["outcome"] == po.STATUS_FAILED
        assert "reclaimed" in payload["summary"]

    def test_it_emits_the_lock_reclaimed_audit_event(self, capsys):
        agent_def = _agent()
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=lease + 60))])

        _reclaim(gh, agent_def, item)

        events = [
            json.loads(line) for line in capsys.readouterr().out.splitlines()
            if line.startswith("{")
        ]
        reclaimed = [e for e in events if e["event"] == "lock.reclaimed"]
        assert len(reclaimed) == 1
        assert reclaimed[0]["agent"] == agent_def.agent
        assert reclaimed[0]["issue"] == 407
        assert reclaimed[0]["status"] == "failed"

    def test_the_newest_claim_is_the_one_measured(self):
        """A step re-invoked after an earlier run must not be judged by the
        earlier run's claim."""
        agent_def = _agent()
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([
            _claim_comment(agent_def, NOW - timedelta(seconds=lease * 5)),
            _claim_comment(agent_def, NOW - timedelta(seconds=10)),
        ])

        _reclaim(gh, agent_def, item)

        gh.add_label.assert_not_called()

    def test_another_steps_claim_is_not_borrowed(self):
        agent_def = _agent()
        other = _agent("01_product_docs/prd-writer")
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([_claim_comment(other, NOW - timedelta(seconds=lease + 60))])

        _reclaim(gh, agent_def, item)

        gh.add_label.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: A reclaim draws from the retry budget
# ---------------------------------------------------------------------------

class TestAReclaimDrawsFromTheRetryBudget:
    def test_it_lands_on_the_failed_a_person_must_clear(self):
        """MI-4: a step that hangs the same way every time must not reclaim and
        hang indefinitely. There is no cross-tick attempt counter -- :failed IS
        where an exhausted budget lands, and only a person clears it -- so a
        reclaim goes straight there rather than silently re-running."""
        agent_def = _agent(max_retries=3)
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=lease + 1))])

        labels = _reclaim(gh, agent_def, item)

        assert agent_def.failed_label in labels
        assert po.STATUS_FAILED in po.TERMINAL_STATUSES, \
            ":failed must be terminal, or a reclaim would re-run on the next tick"

    def test_the_comment_names_the_reclaim_as_an_attempt(self):
        agent_def = _agent()
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=lease + 1))])

        _reclaim(gh, agent_def, item)

        posted = "\n\n".join(c.args[1] for c in gh.post_comment.call_args_list)
        assert "counts as an attempt" in posted

    def test_a_reclaimed_step_is_not_eligible_on_the_same_tick(self):
        agent_def = _agent()
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)
        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=lease + 1))])

        labels = _reclaim(gh, agent_def, item)

        assert po.agent_status(labels, agent_def.label_key) == po.STATUS_FAILED


# ---------------------------------------------------------------------------
# Scenario: A :wip with no readable claim comment is never reclaimed on a guess
# ---------------------------------------------------------------------------

class TestMissingEvidenceFailsClosed:
    def _assert_left_alone(self, gh, agent_def, item, caplog):
        with caplog.at_level("WARNING"):
            labels = _reclaim(gh, agent_def, item)
        assert labels == {agent_def.status_label(po.STATUS_WIP)}
        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()
        assert "not reclaiming on a guess" in caplog.text
        return caplog.text

    def test_no_claim_comment_at_all(self, caplog):
        agent_def = _agent()
        self._assert_left_alone(_gh([]), agent_def, _item(agent_def), caplog)

    def test_an_unparseable_claim_comment(self, caplog):
        agent_def = _agent()
        broken = (
            f"<!-- ai-agile/announcement/v1 by {agent_def.agent} -->\n"
            "```json\n{ not json at all\n```"
        )
        self._assert_left_alone(_gh([broken]), agent_def, _item(agent_def), caplog)

    def test_a_claim_comment_with_no_timestamp(self, caplog):
        agent_def = _agent()
        undated = (
            f"<!-- ai-agile/announcement/v1 by {agent_def.agent} -->\n"
            "```json\n"
            + json.dumps({"agent": agent_def.agent, "phase": "start"})
            + "\n```"
        )
        self._assert_left_alone(_gh([undated]), agent_def, _item(agent_def), caplog)

    def test_comments_that_cannot_be_read(self, caplog):
        agent_def = _agent()
        gh = MagicMock()
        gh.repo = "owner/repo"
        gh.list_comment_bodies.side_effect = RuntimeError("502")
        self._assert_left_alone(gh, agent_def, _item(agent_def), caplog)

    def test_the_warning_names_the_manual_exit(self, caplog):
        """MI-4: nothing gets stuck with no way out. Failing closed on THIS tick
        is not a permanent stall -- eligibility is re-evaluated every tick, so a
        transient read failure resolves itself. If the claim comment is
        genuinely gone the warning repeats every tick, and it names the label a
        person removes by hand."""
        agent_def = _agent()
        text = self._assert_left_alone(_gh([]), agent_def, _item(agent_def), caplog)
        assert agent_def.status_label(po.STATUS_WIP) in text
        assert "by hand" in text

    def test_it_is_re_evaluated_on_the_next_tick(self, caplog):
        """The same item, read successfully a tick later, is reclaimed."""
        agent_def = _agent()
        item = _item(agent_def)
        lease = po._wip_lease_seconds(agent_def)

        with caplog.at_level("WARNING"):
            _reclaim(_gh([]), agent_def, item)  # tick 1: unreadable
        assert agent_def.status_label(po.STATUS_WIP) in item.labels

        gh = _gh([_claim_comment(agent_def, NOW - timedelta(seconds=lease + 60))])
        labels = _reclaim(gh, agent_def, item)  # tick 2: readable
        assert agent_def.failed_label in labels


# ---------------------------------------------------------------------------
# The tick runs it
# ---------------------------------------------------------------------------

class TestTheTickReclaimsBeforeItEvaluatesEligibility:
    def test_process_work_item_calls_the_reclaim(self, monkeypatch):
        called = {}
        monkeypatch.setattr(po, "_check_controls", lambda repo: "run")
        monkeypatch.setattr(po, "promote_gated_agents", lambda labels, *a, **k: labels)
        monkeypatch.setattr(po, "_clear_satisfied_blocks", lambda gh, wi, labels: labels)
        monkeypatch.setattr(po, "_is_blocked_from_starting", lambda gh, labels: False)
        monkeypatch.setattr(po, "_work_item_has_started", lambda labels, agents: True)

        def _spy(gh, agents, work_item, labels, repo, session_id, **kw):
            called["yes"] = True
            return labels

        monkeypatch.setattr(po, "_reclaim_stale_wip", _spy)

        agent_def = _agent()
        po.process_work_item(
            _item(agent_def), [], {}, MagicMock(), dry_run=False, repo="owner/repo",
        )
        assert called.get("yes")

    def test_a_dry_run_never_writes_a_label(self, monkeypatch):
        called = {}
        monkeypatch.setattr(po, "_check_controls", lambda repo: "run")
        monkeypatch.setattr(po, "_work_item_has_started", lambda labels, agents: True)
        monkeypatch.setattr(
            po, "_reclaim_stale_wip",
            lambda *a, **k: called.setdefault("yes", True),
        )

        agent_def = _agent()
        po.process_work_item(
            _item(agent_def), [], {}, MagicMock(), dry_run=True, repo="owner/repo",
        )
        assert "yes" not in called
