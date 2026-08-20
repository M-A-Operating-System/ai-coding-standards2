"""Conformance tests for coder.md Step 0 mode detection fix (issue #310).

Verifies that coder.md Step 0 correctly distinguishes a genuine first dispatch
(Mode A) from a genuine re-invocation after review feedback (Mode B), and that
max_cycles enforcement is not changed.

Gherkin scenarios traced:
  - a_genuine_first_dispatch_runs_mode_a_even_though_the_dispatch_time_counter_is_non_zero
  - a_genuine_re_invocation_after_review_feedback_still_runs_mode_b
  - max_cycles_enforcement_is_unaffected
"""
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CODER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "coder.md"
ORCHESTRATOR_PY = REPO_ROOT / "pipeline" / "pipeline_orchestrator.py"


def _load_coder() -> str:
    assert CODER_MD.exists(), f"coder.md not found at {CODER_MD}"
    return CODER_MD.read_text()


def _extract_step0(text: str) -> str:
    m = re.search(r"## Step 0 — Detect mode\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return m.group(1) if m else ""


def _extract_frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return m.group(1) if m else ""


class TestGenuineFirstDispatchRunsModeA:
    """Scenario: A genuine first dispatch runs Mode A even though the dispatch-time counter is non-zero.

    Given coder is dispatched for the first time (no pr-reviewer artefact, no human REQUEST_CHANGES)
    When coder runs Step 0
    Then it detects Mode A regardless of whether review-cycle:1 was applied at dispatch
    """

    def test_step0_documents_dispatch_time_counter_caveat(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "dispatch" in step.lower(), (
            "Step 0 must document that review-cycle:N is applied at dispatch time"
        )

    def test_step0_review_cycle_not_sufficient_alone(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "not a reliable" in step.lower() or "alone is not" in step.lower(), (
            "Step 0 must state that review-cycle:N presence alone is not a reliable Mode B signal"
        )

    def test_step0_checks_pr_reviewer_artefact(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "pr-reviewer" in step and "artefact" in step.lower(), (
            "Step 0 must check for a pr-reviewer artefact comment on the PR"
        )

    def test_step0_bash_fetches_pr_comments_for_artefact(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "PR_REVIEWER_ARTEFACT" in step, (
            "Step 0 bash block must define PR_REVIEWER_ARTEFACT to hold the artefact check result"
        )

    def test_step0_bash_checks_artefact_marker_string(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "ai-agile/artefact/v1 by 03_execute/pr-reviewer" in step, (
            "Step 0 must search for the canonical pr-reviewer artefact marker in PR comments"
        )

    def test_step0_falls_through_to_mode_a_when_no_artefact(self):
        text = _load_coder()
        step = _extract_step0(text)
        lower = step.lower()
        assert "mode a" in lower or 'mode=a' in lower or '"mode=a"' in lower, (
            "Step 0 must fall through to Mode A when review-cycle:N is present but no artefact found"
        )

    def test_step0_human_review_pending_is_always_mode_b(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "HUMAN_REVIEW_PENDING" in step, (
            "Step 0 must still handle the human-review-pending label as a reliable Mode B trigger"
        )


class TestGenuineReInvocationRunsModeB:
    """Scenario: A genuine re-invocation after review feedback still runs Mode B.

    Given pr-reviewer posted REQUEST CHANGES (or a human left an unresolved REQUEST_CHANGES review)
    When coder runs Step 0
    Then it detects Mode B and reads the actual feedback
    """

    def test_step0_still_handles_review_cycle_label(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "review-cycle" in step, (
            "Step 0 must still recognise review-cycle:N as input to Mode B detection"
        )

    def test_step0_mode_b_when_artefact_present(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "MODE=B" in step or "mode=b" in step.lower(), (
            "Step 0 bash block must set Mode B when the pr-reviewer artefact is found"
        )

    def test_step0_human_review_pending_triggers_mode_b_unconditionally(self):
        text = _load_coder()
        step = _extract_step0(text)
        # human-review-pending must set MODE=B without an artefact check
        lines = step.splitlines()
        hrp_lines = [i for i, l in enumerate(lines) if "HUMAN_REVIEW_PENDING" in l and "MODE=B" in l]
        # Also acceptable: separate lines where HUMAN_REVIEW_PENDING check sets MODE=B
        hrp_check_idx = next((i for i, l in enumerate(lines) if '"$HUMAN_REVIEW_PENDING"' in l or '[ -n "$HUMAN_REVIEW_PENDING" ]' in l), None)
        assert hrp_check_idx is not None, (
            "Step 0 bash block must check HUMAN_REVIEW_PENDING"
        )
        # MODE=B must appear after the human-review-pending check and before any artefact check
        artefact_idx = next((i for i, l in enumerate(lines) if "PR_REVIEWER_ARTEFACT" in l), len(lines))
        modeb_before_artefact = any("MODE=B" in l for l in lines[hrp_check_idx:artefact_idx])
        assert modeb_before_artefact, (
            "human-review-pending must set MODE=B without requiring a pr-reviewer artefact check"
        )

    def test_frontmatter_description_reflects_new_mode_b_triggers(self):
        text = _load_coder()
        fm = _extract_frontmatter(text)
        assert "human-review-pending" in fm, (
            "Frontmatter description must mention human-review-pending as a Mode B trigger"
        )
        assert "pr-reviewer" in fm and "artefact" in fm.lower(), (
            "Frontmatter description must mention the pr-reviewer artefact check"
        )


class TestMaxCyclesEnforcementIsUnaffected:
    """Scenario: max_cycles enforcement is unaffected.

    Given pr-reviewer requests changes 3 times in a row (the configured max_cycles)
    When the review loop runs its course
    Then the cycle limit still triggers human sign-off at the same point as before
    """

    def test_orchestrator_review_cycle_increment_unchanged(self):
        text = ORCHESTRATOR_PY.read_text()
        # The dispatch-time increment logic must still exist
        assert "_get_review_cycle" in text, (
            "pipeline_orchestrator.py must still define _get_review_cycle"
        )
        assert "_rc_next = _rc_cur + 1" in text, (
            "Dispatch-time review-cycle increment logic must be unchanged in the orchestrator"
        )

    def test_orchestrator_handle_review_loop_max_cycles_check_unchanged(self):
        text = ORCHESTRATOR_PY.read_text()
        # max_cycles check in _handle_review_loop must still exist
        assert "next_cycle > max_cycles" in text, (
            "max_cycles escalation check in _handle_review_loop must be unchanged"
        )

    def test_coder_step0_does_not_alter_review_cycle_label(self):
        text = _load_coder()
        step = _extract_step0(text)
        # Step 0 must not add or remove review-cycle labels
        assert "gh label" not in step.lower(), (
            "Step 0 must not create or delete labels"
        )
        assert "add_label" not in step, (
            "Step 0 must not call add_label"
        )

    def test_coder_step0_fix_is_read_only_detection(self):
        text = _load_coder()
        step = _extract_step0(text)
        # The fix must only READ state (gh api GET), not mutate it
        mutating_patterns = ["--method POST", "--method PATCH", "--method DELETE", "gh pr review"]
        for pattern in mutating_patterns:
            assert pattern not in step, (
                f"Step 0 must not make mutating API calls ({pattern!r} found)"
            )
