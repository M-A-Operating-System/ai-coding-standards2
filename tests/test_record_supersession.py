"""A :complete whose subject has moved is superseded, not stale-and-stuck.

PRODUCT.md, "Correcting the record":

  Superseded is not the same as wrong. When a new commit lands, a record
  describing the previous head has not become false -- it has become about
  something else. The step whose input changed runs again and replaces what
  it recorded.

and:

  A record that can be superseded says what it was about. [...] A step whose
  record names no subject cannot be superseded at all. It can only be
  repeated, or trusted indefinitely.

Before this, a step carrying :complete was skipped unconditionally, so a
record describing a commit that had since moved kept the step from running
rather than prompting it to run again -- the failure that required nine
manual label edits on issue #438.

The fail-safe direction is the one that matters most: not being able to
establish a subject is not evidence that a record is stale, and must never
be read as such.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

from pipeline_orchestrator import (  # noqa: E402
    AgentDef,
    _build_closing_announcement,
    _recorded_subject,
    step_subject,
)

OLD_SHA = "913e407443ded418cac591f68fbfc10dbe101cf4"
NEW_SHA = "fbeeb14d342bb808d251a7256b5e1b4662a98e48"


def _agent(name: str = "03_execute/ci-gate", resolve_pr: bool = True) -> AgentDef:
    return AgentDef(
        agent=name,
        phase=name.split("/")[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
        resolve_pr_number=resolve_pr,
    )


def _work_item(number: int = 438, kind: str = "issue") -> MagicMock:
    wi = MagicMock()
    wi.number = number
    wi.kind = kind
    wi.labels = []
    return wi


def _gh_with_pr(sha: str, pr_number: int = 443) -> MagicMock:
    """A client where the step's PR resolves by either route.

    Both are stubbed because the lookup tries the flow's declared branch
    first and falls back to the source-issue label; which one answers is not
    what these tests are about.
    """
    gh = MagicMock()
    gh.repo = "owner/repo"
    gh.find_pr_by_branch = MagicMock(return_value=pr_number)
    gh.find_pr_by_label = MagicMock(return_value=pr_number)
    gh._get = MagicMock(return_value={"head": {"sha": sha}})
    return gh


def _closing_comment(agent: str, subject: str | None, phase: str = "end") -> str:
    payload = {"agent": agent, "phase": phase, "outcome": "complete"}
    if subject:
        payload["subject"] = subject
    return (
        f"<!-- ai-agile/announcement/v1 by {agent} -->\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```"
    )


class TestTheRecordNamesItsSubject:
    def test_closing_announcement_carries_the_subject(self):
        body = _build_closing_announcement(
            _agent(), _work_item(), "sess-1", "complete", "done", subject=OLD_SHA,
        )
        assert f'"subject": "{OLD_SHA}"' in body

    def test_a_step_with_no_subject_records_none(self):
        """Absent, not null: a record with no subject must not look like one
        whose subject was established as empty."""
        body = _build_closing_announcement(
            _agent(), _work_item(), "sess-1", "complete", "done", subject=None,
        )
        assert "subject" not in body


class TestWhatTheSubjectIs:
    def test_the_subject_is_the_head_of_the_step_s_pr(self):
        gh = _gh_with_pr(OLD_SHA)
        assert step_subject(gh, _agent(), _work_item()) == OLD_SHA

    def test_a_step_that_declares_no_pr_has_no_subject(self):
        """Which steps have a subject is declared in pipeline.json, not by a
        list of step names in orchestrator code (AS-2)."""
        gh = _gh_with_pr(OLD_SHA)
        assert step_subject(gh, _agent(resolve_pr=False), _work_item()) is None
        gh._get.assert_not_called()

    def test_no_pr_in_play_means_no_subject(self):
        gh = _gh_with_pr(OLD_SHA)
        gh.find_pr_by_branch = MagicMock(return_value=None)
        gh.find_pr_by_label = MagicMock(return_value=None)
        assert step_subject(gh, _agent(), _work_item()) is None

    def test_the_source_issue_label_resolves_the_pr_when_the_branch_does_not(self):
        """The fallback the PR lookup already uses, so a rebased branch that
        no longer matches issue-{N} still yields a subject."""
        gh = _gh_with_pr(OLD_SHA)
        gh.find_pr_by_branch = MagicMock(return_value=None)
        assert step_subject(gh, _agent(), _work_item()) == OLD_SHA
        gh.find_pr_by_label.assert_called_once_with("source-issue:438")

    def test_a_pr_kind_item_is_its_own_subject_source(self):
        gh = _gh_with_pr(NEW_SHA)
        assert step_subject(gh, _agent(), _work_item(443, kind="pr")) == NEW_SHA

    def test_an_api_failure_yields_no_subject_rather_than_a_guess(self):
        gh = _gh_with_pr(OLD_SHA)
        gh._get = MagicMock(side_effect=RuntimeError("502"))
        assert step_subject(gh, _agent(), _work_item()) is None


class TestRecoveringWhatWasRecorded:
    def test_reads_the_subject_from_this_step_s_own_closing_record(self):
        gh = MagicMock()
        gh.list_comment_bodies = MagicMock(return_value=[
            _closing_comment("03_execute/ci-gate", OLD_SHA),
        ])
        assert _recorded_subject(gh, _agent(), _work_item()) == OLD_SHA

    def test_another_step_s_record_is_not_this_step_s(self):
        gh = MagicMock()
        gh.list_comment_bodies = MagicMock(return_value=[
            _closing_comment("03_execute/pr-reviewer", NEW_SHA),
        ])
        assert _recorded_subject(gh, _agent(), _work_item()) is None

    def test_an_opening_announcement_is_not_a_conclusion(self):
        gh = MagicMock()
        gh.list_comment_bodies = MagicMock(return_value=[
            _closing_comment("03_execute/ci-gate", OLD_SHA, phase="start"),
        ])
        assert _recorded_subject(gh, _agent(), _work_item()) is None

    def test_the_latest_record_wins(self):
        gh = MagicMock()
        gh.list_comment_bodies = MagicMock(return_value=[
            _closing_comment("03_execute/ci-gate", OLD_SHA),
            _closing_comment("03_execute/ci-gate", NEW_SHA),
        ])
        assert _recorded_subject(gh, _agent(), _work_item()) == NEW_SHA

    def test_a_record_written_before_subjects_existed_has_none(self):
        gh = MagicMock()
        gh.list_comment_bodies = MagicMock(return_value=[
            _closing_comment("03_execute/ci-gate", None),
        ])
        assert _recorded_subject(gh, _agent(), _work_item()) is None

    def test_unreadable_comments_yield_none_rather_than_a_guess(self):
        gh = MagicMock()
        gh.list_comment_bodies = MagicMock(side_effect=RuntimeError("403"))
        assert _recorded_subject(gh, _agent(), _work_item()) is None


class TestSupersessionIsDecidedByComparison:
    """The comparison the eligibility check makes, stated directly.

    Each case says what the pair of subjects means, so the fail-safe
    direction is visible rather than implied by control flow.
    """

    @pytest.mark.parametrize("recorded,current,superseded", [
        (OLD_SHA, NEW_SHA, True),    # the head moved: run again
        (OLD_SHA, OLD_SHA, False),   # same subject: the record still holds
        (None, NEW_SHA, False),      # nothing recorded: not evidence of staleness
        (OLD_SHA, None, False),      # subject unestablished: not evidence either
        (None, None, False),         # no subject at all: never superseded
    ])
    def test_only_two_established_and_differing_subjects_supersede(
        self, recorded, current, superseded,
    ):
        decided = (
            recorded is not None
            and current is not None
            and recorded != current
        )
        assert decided is superseded
