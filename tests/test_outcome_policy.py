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

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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
            "id": "RV-001", "title": "t", "category": "defect", "type": "correctness", "severity": "Medium",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding, dict(finding)])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert "duplicate" in failure.lower()
        assert rendered is None


class TestSchemaValidation:
    def test_invalid_severity_fails_closed(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "category": "defect", "type": "correctness", "severity": "Severe",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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
            "id": "RV-001", "title": "merge conflict", "category": "defect",
            "type": "correctness", "severity": "Critical", "confidence": 1.0,
            "evidence": "mergeable_state is dirty", "fix": "resolve the conflict",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert failure == ""
        assert status == STATUS_REVIEW  # Critical finding blocks

    def test_standard_category_without_standard_field_fails_closed(self):
        """A schema-invalid finding: a defect with type "standard" and no
        standard cited. Without this, an ADR exception naming a real
        standard could never match (finding_blocks needs both adr and
        standard set), so a valid exception would silently fail to apply --
        better to reject the finding upfront than let that happen quietly."""
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "category": "defect", "type": "standard", "severity": "High",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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

    def test_resolved_pr_number_is_returned_to_caller(self):
        """When the caller passes pr_number=None, _apply_outcome_policy's
        own fallback resolution must come back in the return tuple, so a
        caller's later _mark_pr_ready_if_requested call reuses this same
        value instead of independently re-resolving to a possibly different
        one (issue #512 Part 3 /code-review fix)."""
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item(number=42)
        step_result = _step_result_with_review()
        gh = _make_gh_mock()
        gh.find_pr_by_branch.return_value = 77

        result = _apply_outcome_policy(gh, agent_def, work_item, step_result, STATUS_COMPLETE)

        assert result[-1] == 77


class TestOutcomeOverride:
    def test_computed_verdict_overrides_model_outcome(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "category": "defect", "type": "correctness", "severity": "Critical",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
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
            "id": "RV-001", "title": "t", "category": "defect", "type": "correctness", "severity": "Critical",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(findings=[finding])
        gh = _make_gh_mock()
        gh.find_pr_by_branch.return_value = 77
        gh.get_pr_reviews.return_value = [
            {"user": {"login": "alice", "type": "User"}, "state": "CHANGES_REQUESTED",
             "submitted_at": "2026-01-01T00:00:00Z"},
        ]

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert status == STATUS_REVIEW
        assert human_only_block is False

    def test_no_human_blocker_is_not_human_only_block(self):
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(findings=[])
        gh = _make_gh_mock()

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE,
        )

        assert status == STATUS_COMPLETE
        assert human_only_block is False


class TestRequireHeadMatch:
    """Issue #512 Part 3: an APPROVE must be about the exact commit
    reviewed, checked against a fresh live-head fetch, never a cached or
    dispatch-time value."""

    def _agent_def_with_head_match(self, **overrides):
        return _pr_reviewer_agent_def(
            outcome_policy={
                "kind": "review_findings",
                "schema": "pipeline/schemas/pr-review.schema.json",
                "require_head_match": True,
            },
            **overrides,
        )

    def test_matching_head_sha_applies_complete_normally(self):
        agent_def = self._agent_def_with_head_match()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(head_sha="abc123")
        gh = _make_gh_mock()
        gh._get.return_value = {"head": {"sha": "abc123"}}

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert stale_head_out is False
        assert status == STATUS_COMPLETE
        assert failure == ""

    def test_mismatched_head_sha_withholds_complete(self):
        """Scenario: Stale review is not approved."""
        agent_def = self._agent_def_with_head_match()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(head_sha="abc123")
        gh = _make_gh_mock()
        gh._get.return_value = {"head": {"sha": "def456"}}

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert stale_head_out is True
        assert failure == "", "a stale head is not a malformed-result failure"
        assert "abc123" in rendered.output
        assert "def456" in rendered.output

    def test_not_checked_when_verdict_is_request_changes(self):
        """A REQUEST CHANGES verdict never reaches _mark_pr_ready_if_requested
        anyway, so a stale head is irrelevant to it -- the issue's own Part 3
        text scopes this check to "before applying complete"."""
        agent_def = self._agent_def_with_head_match()
        work_item = _issue_work_item()
        finding = {
            "id": "RV-001", "title": "t", "category": "defect", "type": "correctness", "severity": "Critical",
            "confidence": 1.0, "evidence": "e", "fix": "f",
        }
        step_result = _step_result_with_review(head_sha="abc123", findings=[finding])
        gh = _make_gh_mock()
        gh._get.return_value = {"head": {"sha": "def456"}}

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert status == STATUS_REVIEW
        assert stale_head_out is False

    def test_not_checked_when_policy_does_not_declare_it(self):
        agent_def = _pr_reviewer_agent_def()  # no require_head_match
        work_item = _issue_work_item()
        step_result = _step_result_with_review(head_sha="abc123")
        gh = _make_gh_mock()
        gh._get.return_value = {"head": {"sha": "def456"}}

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert stale_head_out is False
        assert status == STATUS_COMPLETE

    def test_live_head_fetch_failure_withholds_approval(self):
        """require_head_match exists to prevent a bad approval, so any
        inability to positively confirm a match -- a failed live fetch
        included -- must be treated as "cannot verify, defer", never as
        "check passed, proceed." An API hiccup withholds :complete and lets
        the step re-dispatch next tick rather than silently approving."""
        agent_def = self._agent_def_with_head_match()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(head_sha="abc123")
        gh = _make_gh_mock()
        gh._get.side_effect = RuntimeError("boom")

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert stale_head_out is True
        assert failure == "", "a failed live-head fetch is not a malformed-result failure"

    def test_empty_reviewed_head_sha_withholds_approval(self):
        """review.head_sha empty means the step never confirmed what it
        reviewed (e.g. the "no open PR found" early exit) -- there is
        nothing to compare against the live head, so this must fail closed
        exactly like a genuine mismatch, not skip the check entirely."""
        agent_def = self._agent_def_with_head_match()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(head_sha="")
        gh = _make_gh_mock()
        gh._get.return_value = {"head": {"sha": "def456"}}

        status, rendered, failure, overridden, human_only_block, human_blockers_out, stale_head_out, pr_number_out = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert stale_head_out is True
        assert failure == ""


class TestDeferredFindingsIssueSynthesis:
    """Issue #506: a complex-effort improvement gets bundled into a
    creates_issue request the orchestrator itself computes, never left to
    the model to remember to ask for (P-14) -- gated by the step's own
    expected_effect.creates_issues declaration, same as every other
    creates_issue consumer."""

    _deferred_finding = {
        "id": "RV-001", "title": "large refactor needed", "category": "improvement",
        "effort": "complex", "confidence": 1.0, "evidence": "e", "fix": "f",
    }

    def test_declared_and_deferred_finding_populates_creates_issue(self):
        agent_def = _pr_reviewer_agent_def(
            expected_effect={"commits": False, "creates_issues": True},
        )
        work_item = _issue_work_item()
        step_result = _step_result_with_review(findings=[self._deferred_finding])
        gh = _make_gh_mock()

        _, rendered, failure, *_ = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert failure == ""
        assert rendered.creates_issue
        assert "RV-001" in rendered.creates_issue["body"]

    def test_not_declared_stays_empty_even_with_a_deferred_finding(self):
        """expected_effect.creates_issues defaults False -- a step that
        never opted in gets no synthesized request, matching
        _create_requested_issue's own refuse-not-declared behaviour."""
        agent_def = _pr_reviewer_agent_def()
        work_item = _issue_work_item()
        step_result = _step_result_with_review(findings=[self._deferred_finding])
        gh = _make_gh_mock()

        _, rendered, failure, *_ = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert failure == ""
        assert rendered.creates_issue == {}

    def test_declared_but_nothing_deferred_stays_empty(self):
        agent_def = _pr_reviewer_agent_def(
            expected_effect={"commits": False, "creates_issues": True},
        )
        work_item = _issue_work_item()
        step_result = _step_result_with_review(findings=[])
        gh = _make_gh_mock()

        _, rendered, failure, *_ = _apply_outcome_policy(
            gh, agent_def, work_item, step_result, STATUS_COMPLETE, 77,
        )

        assert failure == ""
        assert rendered.creates_issue == {}
