"""Conformance tests for coder.md mode detection (issue #310, #467).

After issue #467, the orchestrator determines and injects AI_AGILE_INVOCATION_MODE
so the coder reads it directly instead of inspecting labels or artefacts.

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
    m = re.search(r"## Step 0[^\n]*\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return m.group(1) if m else ""


def _extract_frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return m.group(1) if m else ""


class TestGenuineFirstDispatchRunsModeA:
    """Scenario: A genuine first dispatch runs Mode A even though the dispatch-time counter is non-zero.

    Given coder is dispatched for the first time (no pr-reviewer artefact, no human REQUEST_CHANGES)
    When the orchestrator computes AI_AGILE_INVOCATION_MODE and coder runs Step 0
    Then coder detects Mode A, because the orchestrator injected AI_AGILE_INVOCATION_MODE=initial
    """

    def test_orchestrator_sets_initial_mode_for_first_dispatch(self):
        """The orchestrator sets AI_AGILE_INVOCATION_MODE=initial when rc_cur == 0."""
        text = ORCHESTRATOR_PY.read_text()
        assert "AI_AGILE_INVOCATION_MODE" in text, (
            "pipeline_orchestrator.py must set AI_AGILE_INVOCATION_MODE"
        )
        assert '"initial"' in text, (
            "pipeline_orchestrator.py must set AI_AGILE_INVOCATION_MODE to 'initial' "
            "for a first dispatch"
        )

    def test_orchestrator_initial_mode_uses_review_cycle_check(self):
        """The orchestrator distinguishes first dispatch from re-invocation using
        the review-cycle counter, so the coder does not need to."""
        text = ORCHESTRATOR_PY.read_text()
        assert "_get_review_cycle" in text, (
            "pipeline_orchestrator.py must use _get_review_cycle to determine invocation mode"
        )

    def test_step0_reads_invocation_mode_env_var(self):
        """Step 0 reads AI_AGILE_INVOCATION_MODE instead of inspecting labels."""
        text = _load_coder()
        # PR #517 simplified Step 0 to a brief dispatch table; AI_AGILE_INVOCATION_MODE
        # is defined in the Execution context section, which Step 0 references
        # implicitly by mapping its values (initial/review) to modes.
        assert "AI_AGILE_INVOCATION_MODE" in text, (
            "coder.md must document AI_AGILE_INVOCATION_MODE as the mode-selection mechanism"
        )
        step = _extract_step0(text)
        assert "initial" in step and "review" in step, (
            "coder.md Step 0 must map 'initial' and 'review' to their respective modes"
        )

    def test_step0_does_not_inspect_review_cycle_label(self):
        """Detecting the review-cycle:N label is the orchestrator's job, not the coder's."""
        text = _load_coder()
        step = _extract_step0(text)
        assert "review-cycle" not in step, (
            "coder.md Step 0 must not inspect review-cycle:N labels; "
            "the orchestrator injects the mode via AI_AGILE_INVOCATION_MODE"
        )

    def test_step0_does_not_check_pr_reviewer_artefact(self):
        """Checking for a pr-reviewer artefact is the orchestrator's job, not the coder's."""
        text = _load_coder()
        step = _extract_step0(text)
        assert "pr-reviewer" not in step, (
            "coder.md Step 0 must not check for a pr-reviewer artefact; "
            "the orchestrator injects the mode via AI_AGILE_INVOCATION_MODE"
        )

    def test_step0_identifies_mode_a_as_initial_build(self):
        """Step 0 must map AI_AGILE_INVOCATION_MODE=initial to Mode A."""
        text = _load_coder()
        step = _extract_step0(text)
        lower = step.lower()
        assert "initial" in lower and ("mode a" in lower or "initial build" in lower), (
            "coder.md Step 0 must map AI_AGILE_INVOCATION_MODE=initial to Mode A"
        )


class TestGenuineReInvocationRunsModeB:
    """Scenario: A genuine re-invocation after review feedback still runs Mode B.

    Given pr-reviewer posted REQUEST CHANGES (or a human left an unresolved REQUEST_CHANGES review)
    When the orchestrator computes AI_AGILE_INVOCATION_MODE and coder runs Step 0
    Then coder detects Mode B, because the orchestrator injected AI_AGILE_INVOCATION_MODE=review
    """

    def test_orchestrator_sets_review_mode_for_reinvocation(self):
        """The orchestrator sets AI_AGILE_INVOCATION_MODE=review when rc_cur >= 1."""
        text = ORCHESTRATOR_PY.read_text()
        assert '"review"' in text, (
            "pipeline_orchestrator.py must set AI_AGILE_INVOCATION_MODE to 'review' "
            "for a re-invocation"
        )

    def test_orchestrator_review_mode_covers_human_review_pending(self):
        """The orchestrator sets review mode when HUMAN_REVIEW_PENDING_LABEL is present."""
        text = ORCHESTRATOR_PY.read_text()
        assert "HUMAN_REVIEW_PENDING_LABEL" in text and "review" in text, (
            "pipeline_orchestrator.py must handle HUMAN_REVIEW_PENDING_LABEL "
            "when computing AI_AGILE_INVOCATION_MODE"
        )

    def test_orchestrator_invocation_mode_injected_into_flow_env(self):
        """The orchestrator puts AI_AGILE_INVOCATION_MODE into flow_env so it
        reaches the agent's environment."""
        text = ORCHESTRATOR_PY.read_text()
        assert "_invocation_mode" in text, (
            "pipeline_orchestrator.py must compute _invocation_mode for injection"
        )
        assert '_flow_env["AI_AGILE_INVOCATION_MODE"]' in text, (
            "pipeline_orchestrator.py must inject AI_AGILE_INVOCATION_MODE into _flow_env"
        )

    def test_step0_maps_review_mode_to_mode_b(self):
        """Step 0 must map AI_AGILE_INVOCATION_MODE=review to Mode B."""
        text = _load_coder()
        step = _extract_step0(text)
        lower = step.lower()
        assert "review" in lower and ("mode b" in lower or "address feedback" in lower), (
            "coder.md Step 0 must map AI_AGILE_INVOCATION_MODE=review to Mode B"
        )

    def test_step0_does_not_inspect_human_review_pending(self):
        """Detecting human-review-pending is the orchestrator's job, not the coder's."""
        text = _load_coder()
        step = _extract_step0(text)
        assert "human-review-pending" not in step, (
            "coder.md Step 0 must not check for human-review-pending label; "
            "the orchestrator injects the mode via AI_AGILE_INVOCATION_MODE"
        )

    def test_frontmatter_describes_invocation_mode_env_var(self):
        """Frontmatter description must reference AI_AGILE_INVOCATION_MODE."""
        text = _load_coder()
        fm = _extract_frontmatter(text)
        assert "AI_AGILE_INVOCATION_MODE" in fm, (
            "coder.md frontmatter description must reference AI_AGILE_INVOCATION_MODE "
            "as the mode-selection mechanism"
        )


class TestMaxCyclesEnforcementIsUnaffected:
    """Scenario: max_cycles enforcement is unaffected.

    Given pr-reviewer requests changes 3 times in a row (the configured max_cycles)
    When the review loop runs its course
    Then the cycle limit still triggers human sign-off at the same point as before
    """

    def test_orchestrator_review_cycle_increment_unchanged(self):
        text = ORCHESTRATOR_PY.read_text()
        assert "_get_review_cycle" in text, (
            "pipeline_orchestrator.py must still define _get_review_cycle"
        )
        assert "_rc_next = _rc_cur + 1" in text, (
            "Dispatch-time review-cycle increment logic must be unchanged in the orchestrator"
        )

    def test_orchestrator_handle_review_loop_max_cycles_check_unchanged(self):
        text = ORCHESTRATOR_PY.read_text()
        assert "next_cycle > max_cycles" in text, (
            "max_cycles escalation check in _handle_review_loop must be unchanged"
        )

    def test_coder_step0_does_not_alter_review_cycle_label(self):
        text = _load_coder()
        step = _extract_step0(text)
        assert "gh label" not in step.lower(), (
            "Step 0 must not create or delete labels"
        )
        assert "add_label" not in step, (
            "Step 0 must not call add_label"
        )

    def test_coder_step0_fix_is_read_only_detection(self):
        text = _load_coder()
        step = _extract_step0(text)
        mutating_patterns = ["--method POST", "--method PATCH", "--method DELETE", "gh pr review"]
        for pattern in mutating_patterns:
            assert pattern not in step, (
                f"Step 0 must not make mutating API calls ({pattern!r} found)"
            )
