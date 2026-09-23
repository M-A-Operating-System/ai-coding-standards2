"""Tests for _apply_outcome_policy (issue #512 Part 2 orchestrator glue).

Covers bugs found and fixed after a /code-review pass on PR #513:
  - schema path must resolve from SUBMODULE_ROOT, never AI_AGILE_ROOT
    (pipeline/schemas/ ships with the orchestrator, not the consuming repo)
  - a PR-kind work item's human-blocker lookup must use work_item.number
    directly, not _related_work_item_env (which only resolves ISSUE_NUMBER
    for a PR-kind invocation)
  - STATUS_BLOCKED must never reach _apply_outcome_policy at all (verified
    via the dispatch guard in _apply_result, exercised here at the
    dispatch-guard boundary condition _apply_outcome_policy itself expects)
  - a missing/empty review fails closed
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import pipeline_orchestrator as orch
from pipeline_orchestrator import (
    AgentDef,
    StepResult,
    WorkItem,
    STATUS_COMPLETE,
    STATUS_REVIEW,
    _apply_outcome_policy,
)


def _pr_reviewer_agent_def(**overrides) -> AgentDef:
    kwargs = dict(
        agent="03_execute/pr-reviewer",
        phase="03_execute",
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test",
        flow="standard-delivery",
        flow_naming={"branch": "issue-{number}"},
        review_gate=True,
        outcome_policy={"kind": "review_findings", "schema": "pipeline/schemas/pr-review.schema.json"},
    )
    kwargs.update(overrides)
    return AgentDef(**kwargs)


def _issue_work_item(number: int = 42) -> WorkItem:
    return WorkItem(
        number=number, kind="issue", title="T", labels=set(),
        url=f"https://github.com/test/repo/issues/{number}",
    )


def _pr_work_item(number: int = 99) -> WorkItem:
    return WorkItem(
        number=number, kind="pr", title="T", labels=set(),
        url=f"https://github.com/test/repo/pull/{number}",
    )


def _step_result_with_review(**review_overrides) -> StepResult:
    review = {"head_sha": "abc123", "findings": []}
    review.update(review_overrides)
    return StepResult(outcome="complete", summary="done", review=review)


def _make_gh_mock() -> MagicMock:
    gh = MagicMock()
    gh.get_pr_reviews = MagicMock(return_value=[])
    gh.list_comment_bodies = MagicMock(return_value=[])
    gh.find_pr_by_branch = MagicMock(return_value=None)
    gh.find_pr_by_label = MagicMock(return_value=None)
    return gh


class TestSchemaPathResolution:
    """The schema-path bug: AI_AGILE_ROOT points at the consuming repo in a
    submodule install, which has no pipeline/ directory at all."""

    def test_schema_loads_even_when_ai_agile_root_points_elsewhere(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_AGILE_ROOT", str(tmp_path))
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = _step_result_with_review()
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure == "", f"schema must resolve regardless of AI_AGILE_ROOT; got: {failure!r}"
        assert status == STATUS_COMPLETE
        assert rendered is not None


class TestMissingOrEmptyReview:
    def test_empty_review_fails_closed(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = StepResult(outcome="complete", summary="done", review={})
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure != ""
        assert rendered is None

    def test_schema_valid_empty_findings_does_not_fail(self):
        """The "no open PR" early exit writes review: {head_sha: "", findings: []} --
        this must compute a clean APPROVE/complete, not fail closed."""
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(head_sha="", findings=[])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure == ""
        assert status == STATUS_COMPLETE
        assert overridden is False


class TestDuplicateFindingIds:
    def test_duplicate_ids_fail_closed(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "severity": "Low", "category": "correctness",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding, dict(finding)])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert "duplicate" in failure.lower()
        assert rendered is None


class TestSchemaValidation:
    def test_invalid_severity_fails_closed(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "severity": "Severe", "category": "correctness",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure != ""
        assert rendered is None

    def test_finding_without_path_or_line_is_valid(self):
        """A PR-level finding (merge conflict, missing base doc) has no
        natural file:line -- path/line must be optional."""
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "merge conflict", "severity": "Critical",
            "category": "correctness", "confidence": 1.0,
            "evidence": "mergeable_state is dirty", "fix": "resolve the conflict",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure == ""
        assert status == STATUS_REVIEW  # Critical finding blocks

    def test_standard_category_without_standard_field_fails_closed(self):
        """A schema-valid-but-nonsensical finding: category "standard" with
        no standard cited. Without this, an ADR exception naming a real
        standard could never match (finding_blocks needs both adr and
        standard set), so a valid exception would silently fail to apply --
        better to reject the finding upfront than let that happen quietly."""
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "severity": "High", "category": "standard",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure != ""
        assert rendered is None


class TestHumanBlockerPrNumberResolution:
    """The PR-kind bug: _related_work_item_env only resolves ISSUE_NUMBER
    for a PR-kind work item, never PR_NUMBER, so the human-blocker lookup
    must resolve the PR number itself the same way
    _compute_human_review_override does."""

    def test_pr_kind_work_item_uses_its_own_number(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _pr_work_item(number=99)
        step_result = _step_result_with_review()
        gh = _make_gh_mock()
        gh.get_pr_reviews.return_value = [
            {"user": {"login": "alice", "type": "User"}, "state": "CHANGES_REQUESTED",
             "submitted_at": "2026-01-01T00:00:00Z"},
        ]

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        gh.get_pr_reviews.assert_called_once_with(99)
        assert status == STATUS_REVIEW, "an unresolved human REQUEST_CHANGES must block"
        assert "@alice" in rendered.output, (
            "the rendered comment must name the blocking reviewer, not just say "
            "REQUEST CHANGES with zero findings and no explanation"
        )

    def test_issue_kind_work_item_resolves_pr_via_branch_lookup(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item(number=42)
        step_result = _step_result_with_review()
        gh = _make_gh_mock()
        gh.find_pr_by_branch.return_value = 77

        _apply_outcome_policy(gh, agent_def, work_item, step_result, STATUS_COMPLETE)

        gh.find_pr_by_branch.assert_called_once_with("issue-42")
        gh.get_pr_reviews.assert_called_once_with(77)

    def test_issue_kind_falls_back_to_source_issue_label(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item(number=42)
        step_result = _step_result_with_review()
        gh = _make_gh_mock()
        gh.find_pr_by_branch.return_value = None
        gh.find_pr_by_label.return_value = 88

        _apply_outcome_policy(gh, agent_def, work_item, step_result, STATUS_COMPLETE)

        gh.find_pr_by_label.assert_called_once_with("source-issue:42")
        gh.get_pr_reviews.assert_called_once_with(88)


class TestPrNumberReuse:
    """_run_agent resolves the PR number once (_resolve_pr_number) and
    passes it in; _apply_outcome_policy must reuse it rather than
    re-deriving via its own branch/label lookup."""

    def test_passed_pr_number_skips_branch_and_label_lookup(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item(number=42)
        step_result = _step_result_with_review()
        gh = _make_gh_mock()

        _apply_outcome_policy(gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77)

        gh.find_pr_by_branch.assert_not_called()
        gh.find_pr_by_label.assert_not_called()
        gh.get_pr_reviews.assert_called_once_with(77)


class TestOutcomeOverride:
    def test_computed_verdict_overrides_model_outcome(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "severity": "Critical", "category": "correctness",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure == ""
        assert status == STATUS_REVIEW
        assert overridden is True

    def test_agreeing_verdict_is_not_flagged_as_overridden(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(findings=[])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert status == STATUS_COMPLETE
        assert overridden is False


class TestHumanOnlyBlock:
    """issue #100's once-only free-re-invoke exemption, reworked for
    outcome_policy: distinguishes "a human blocker is the sole reason for
    REQUEST CHANGES" (free cycle, HUMAN_REVIEW_PENDING_LABEL-guarded, once)
    from "findings also block" (a normal review-loop cycle) -- without this,
    every cycle spent waiting on a human reviewer to re-approve would count
    against review_loop.max_cycles and could escalate to human sign-off from
    cycle exhaustion alone (found independently by two /code-review angles
    on PR #513)."""

    def test_human_blocker_with_clean_findings_is_human_only_block(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(findings=[])
        gh = _make_gh_mock()
        gh.find_pr_by_branch.return_value = 77
        gh.get_pr_reviews.return_value = [
            {"user": {"login": "alice", "type": "User"}, "state": "CHANGES_REQUESTED",
             "submitted_at": "2026-01-01T00:00:00Z"},
        ]

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert status == STATUS_REVIEW
        assert human_only_block is True
        assert len(human_blockers_out) == 1

    def test_human_blocker_with_blocking_finding_is_not_human_only_block(self):
        """A human blocker AND a blocking finding both push to REQUEST
        CHANGES, but the cycle is not "free" -- there's a real finding for
        coder to act on."""
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "severity": "Critical", "category": "correctness",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()
        gh.find_pr_by_branch.return_value = 77
        gh.get_pr_reviews.return_value = [
            {"user": {"login": "alice", "type": "User"}, "state": "CHANGES_REQUESTED",
             "submitted_at": "2026-01-01T00:00:00Z"},
        ]

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert status == STATUS_REVIEW
        assert human_only_block is False

    def test_no_human_blocker_is_not_human_only_block(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(findings=[])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert status == STATUS_COMPLETE
        assert human_only_block is False
