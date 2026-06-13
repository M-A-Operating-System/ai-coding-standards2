"""Tests for _fetch_unresolved_human_review_requests and the human-review
free re-invoke path in _handle_review_loop (issue #100).
"""
import pytest
from unittest.mock import MagicMock

from pipeline.pipeline_orchestrator import (
    _fetch_unresolved_human_review_requests,
    _handle_review_loop,
    HUMAN_REVIEW_PENDING_LABEL,
    STATUS_COMPLETE,
    STATUS_REVIEW,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gh(reviews=None, get_error=None):
    """Return a minimal fake GitHubClient."""
    gh = MagicMock()
    gh.repo = "owner/repo"
    if get_error:
        gh.get_pr_reviews.side_effect = get_error
    else:
        gh.get_pr_reviews.return_value = reviews if reviews is not None else []
    gh.add_label = MagicMock()
    gh.remove_label = MagicMock()
    gh.post_comment = MagicMock()
    return gh


def _review(login, state, submitted_at, user_type="User"):
    return {
        "user": {"login": login, "type": user_type},
        "state": state,
        "submitted_at": submitted_at,
    }


def _make_agent_def(agent_name="03_execute/pr-reviewer", review_loop=None):
    agent_def = MagicMock()
    agent_def.agent = agent_name
    agent_def.review_loop = review_loop or {
        "re_invoke": "03_execute/coder",
        "max_cycles": 3,
        "also_clear": [],
    }
    agent_def.review_label = f"{agent_name}:review"
    agent_def.complete_label = f"{agent_name}:complete"
    return agent_def


def _make_work_item(number=42):
    wi = MagicMock()
    wi.number = number
    return wi


# ---------------------------------------------------------------------------
# _fetch_unresolved_human_review_requests
# ---------------------------------------------------------------------------

class TestFetchUnresolvedHumanReviewRequests:

    def test_returns_empty_list_when_no_reviews(self):
        gh = _make_gh(reviews=[])
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_returns_empty_list_on_api_error(self):
        gh = _make_gh(get_error=Exception("API failure"))
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_returns_empty_list_when_api_returns_non_list(self):
        gh = _make_gh()
        gh._get.return_value = {"error": "not a list"}
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_excludes_bot_accounts(self):
        reviews = [
            _review("dependabot", "CHANGES_REQUESTED", "2024-01-01T10:00:00Z", user_type="Bot"),
            _review("github-actions", "CHANGES_REQUESTED", "2024-01-01T11:00:00Z", user_type="Bot"),
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_returns_single_changes_requested_human_review(self):
        reviews = [
            _review("alice", "CHANGES_REQUESTED", "2024-01-01T10:00:00Z"),
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert len(result) == 1
        assert result[0]["user"]["login"] == "alice"
        assert result[0]["state"] == "CHANGES_REQUESTED"

    def test_excludes_approved_reviews(self):
        reviews = [
            _review("alice", "APPROVED", "2024-01-01T10:00:00Z"),
            _review("bob", "APPROVED", "2024-01-01T11:00:00Z"),
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_excludes_dismissed_reviews(self):
        reviews = [
            _review("alice", "DISMISSED", "2024-01-01T10:00:00Z"),
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_uses_latest_review_per_reviewer(self):
        """Reviewer's latest review supersedes earlier ones — APPROVED after CHANGES_REQUESTED."""
        reviews = [
            _review("alice", "CHANGES_REQUESTED", "2024-01-01T09:00:00Z"),
            _review("alice", "APPROVED", "2024-01-01T10:00:00Z"),
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_changes_requested_supersedes_earlier_approved(self):
        """If reviewer's latest review is CHANGES_REQUESTED, they block even if they approved earlier."""
        reviews = [
            _review("alice", "APPROVED", "2024-01-01T09:00:00Z"),
            _review("alice", "CHANGES_REQUESTED", "2024-01-01T10:00:00Z"),
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert len(result) == 1
        assert result[0]["user"]["login"] == "alice"

    def test_returns_only_reviewers_with_changes_requested(self):
        """Multiple reviewers — only those with latest CHANGES_REQUESTED are returned."""
        reviews = [
            _review("alice", "CHANGES_REQUESTED", "2024-01-01T10:00:00Z"),
            _review("bob", "APPROVED", "2024-01-01T10:00:00Z"),
            _review("charlie", "CHANGES_REQUESTED", "2024-01-01T10:00:00Z"),
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        logins = {r["user"]["login"] for r in result}
        assert logins == {"alice", "charlie"}

    def test_skips_reviews_with_no_login(self):
        reviews = [
            {"user": {"type": "User"}, "state": "CHANGES_REQUESTED", "submitted_at": "2024-01-01T10:00:00Z"},
        ]
        gh = _make_gh(reviews=reviews)
        result = _fetch_unresolved_human_review_requests(gh, 99)
        assert result == []

    def test_uses_correct_api_endpoint(self):
        gh = _make_gh(reviews=[])
        _fetch_unresolved_human_review_requests(gh, 77)
        gh.get_pr_reviews.assert_called_once_with(77)


# ---------------------------------------------------------------------------
# _handle_review_loop — skip_cycle_increment=True (free re-invoke path)
# ---------------------------------------------------------------------------

class TestHandleReviewLoopFreeReInvoke:

    def _run_free_reinvoke(self, labels=None, human_reviews=None):
        """Run _handle_review_loop with skip_cycle_increment=True."""
        gh = _make_gh()
        agent_def = _make_agent_def()

        # Target agent (03_execute/coder)
        coder_def = MagicMock()
        coder_def.complete_label = "03_execute/coder:complete"

        pipeline_map = {
            "03_execute/coder": coder_def,
        }
        wi = _make_work_item()
        labels = set(labels or [])

        updated = _handle_review_loop(
            gh, agent_def, wi, labels, pipeline_map,
            skip_cycle_increment=True,
            human_reviews=human_reviews,
        )
        return gh, updated

    def test_applies_human_review_pending_label(self):
        gh, labels = self._run_free_reinvoke()
        assert HUMAN_REVIEW_PENDING_LABEL in labels
        gh.add_label.assert_any_call(42, HUMAN_REVIEW_PENDING_LABEL)

    def test_does_not_advance_review_cycle_counter(self):
        gh, labels = self._run_free_reinvoke()
        review_cycle_labels = [l for l in labels if l.startswith("review-cycle:")]
        assert review_cycle_labels == []
        for call_args in gh.add_label.call_args_list:
            applied_label = call_args[0][1]
            assert not applied_label.startswith("review-cycle:"), (
                "review-cycle label should not be applied on free re-invoke"
            )

    def test_clears_reviewer_review_label(self):
        gh, labels = self._run_free_reinvoke()
        gh.remove_label.assert_any_call(42, "03_execute/pr-reviewer:review")
        assert "03_execute/pr-reviewer:review" not in labels

    def test_clears_target_complete_label(self):
        gh, labels = self._run_free_reinvoke(labels={"03_execute/coder:complete"})
        gh.remove_label.assert_any_call(42, "03_execute/coder:complete")
        assert "03_execute/coder:complete" not in labels

    def test_posts_comment_with_free_reinvoke_text(self):
        gh, _ = self._run_free_reinvoke()
        comment_text = gh.post_comment.call_args[0][1]
        assert "free re-invoke" in comment_text.lower()
        assert "03_execute/coder" in comment_text

    def test_posts_comment_with_reviewer_names_when_provided(self):
        reviews = [
            {"user": {"login": "alice"}, "state": "CHANGES_REQUESTED"},
            {"user": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
        ]
        gh, _ = self._run_free_reinvoke(human_reviews=reviews)
        comment_text = gh.post_comment.call_args[0][1]
        assert "@alice" in comment_text
        assert "@bob" in comment_text

    def test_does_not_check_max_cycles(self):
        """Free re-invoke bypasses the max_cycles limit entirely."""
        gh = _make_gh()
        agent_def = _make_agent_def()
        agent_def.review_loop = {
            "re_invoke": "03_execute/coder",
            "max_cycles": 1,  # Would normally block at next_cycle=1 >= max_cycles=1
            "also_clear": [],
        }
        coder_def = MagicMock()
        coder_def.complete_label = "03_execute/coder:complete"
        pipeline_map = {"03_execute/coder": coder_def}
        wi = _make_work_item()
        labels = set()

        updated = _handle_review_loop(
            gh, agent_def, wi, labels, pipeline_map,
            skip_cycle_increment=True,
        )
        assert HUMAN_REVIEW_PENDING_LABEL in updated

    def test_does_not_post_escalation_comment(self):
        """Free re-invoke at max_cycles should not post escalation comment."""
        gh = _make_gh()
        agent_def = _make_agent_def()
        agent_def.review_loop = {
            "re_invoke": "03_execute/coder",
            "max_cycles": 1,
            "also_clear": [],
        }
        coder_def = MagicMock()
        coder_def.complete_label = "03_execute/coder:complete"
        pipeline_map = {"03_execute/coder": coder_def}
        wi = _make_work_item()
        labels = set()

        _handle_review_loop(
            gh, agent_def, wi, labels, pipeline_map,
            skip_cycle_increment=True,
        )
        comment_text = gh.post_comment.call_args[0][1]
        assert "human review required" not in comment_text.lower()
        assert "escalat" not in comment_text.lower()

    def test_clears_also_clear_labels(self):
        """also_clear agents' complete labels are removed on free re-invoke."""
        gh = _make_gh()
        agent_def = _make_agent_def()
        agent_def.review_loop = {
            "re_invoke": "03_execute/coder",
            "max_cycles": 3,
            "also_clear": ["03_execute/ci-gate", "03_execute/merge-conflict"],
        }
        coder_def = MagicMock()
        coder_def.complete_label = "03_execute/coder:complete"
        ci_gate_def = MagicMock()
        ci_gate_def.complete_label = "03_execute/ci-gate:complete"
        merge_conflict_def = MagicMock()
        merge_conflict_def.complete_label = "03_execute/merge-conflict:complete"
        pipeline_map = {
            "03_execute/coder": coder_def,
            "03_execute/ci-gate": ci_gate_def,
            "03_execute/merge-conflict": merge_conflict_def,
        }
        wi = _make_work_item()
        labels = {
            "03_execute/ci-gate:complete",
            "03_execute/merge-conflict:complete",
        }

        updated = _handle_review_loop(
            gh, agent_def, wi, labels, pipeline_map,
            skip_cycle_increment=True,
        )
        assert "03_execute/ci-gate:complete" not in updated
        assert "03_execute/merge-conflict:complete" not in updated


# ---------------------------------------------------------------------------
# _handle_review_loop — skip_cycle_increment=False, HUMAN_REVIEW_PENDING_LABEL cleanup
# ---------------------------------------------------------------------------

class TestHandleReviewLoopNormalWithHumanPendingCleanup:

    def test_removes_human_review_pending_label_on_normal_cycle(self):
        """When a normal review cycle runs, the human-review-pending label is removed."""
        gh = _make_gh()
        agent_def = _make_agent_def()

        coder_def = MagicMock()
        coder_def.complete_label = "03_execute/coder:complete"
        pipeline_map = {"03_execute/coder": coder_def}
        wi = _make_work_item()
        labels = {HUMAN_REVIEW_PENDING_LABEL}

        updated = _handle_review_loop(
            gh, agent_def, wi, labels, pipeline_map,
            skip_cycle_increment=False,
        )
        assert HUMAN_REVIEW_PENDING_LABEL not in updated
        gh.remove_label.assert_any_call(42, HUMAN_REVIEW_PENDING_LABEL)

    def test_does_not_apply_human_review_pending_on_normal_cycle(self):
        """Normal review cycle must not add the human-review-pending label."""
        gh = _make_gh()
        agent_def = _make_agent_def()
        coder_def = MagicMock()
        coder_def.complete_label = "03_execute/coder:complete"
        pipeline_map = {"03_execute/coder": coder_def}
        wi = _make_work_item()
        labels = set()

        _handle_review_loop(
            gh, agent_def, wi, labels, pipeline_map,
            skip_cycle_increment=False,
        )
        for c in gh.add_label.call_args_list:
            assert c[0][1] != HUMAN_REVIEW_PENDING_LABEL


# ---------------------------------------------------------------------------
# Backward compatibility: existing _handle_review_loop callers (no new kwargs)
# ---------------------------------------------------------------------------

class TestHandleReviewLoopBackwardCompat:

    def test_existing_call_signature_still_works(self):
        """Calling _handle_review_loop without new kwargs behaves as before."""
        gh = _make_gh()
        agent_def = _make_agent_def()
        coder_def = MagicMock()
        coder_def.complete_label = "03_execute/coder:complete"
        pipeline_map = {"03_execute/coder": coder_def}
        wi = _make_work_item()
        labels = set()

        updated = _handle_review_loop(gh, agent_def, wi, labels, pipeline_map)
        # Should have added review-cycle:1
        assert "review-cycle:1" in updated
        assert HUMAN_REVIEW_PENDING_LABEL not in updated
