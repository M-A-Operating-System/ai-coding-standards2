"""Configuration conformance tests for coder agent — human-review-pending mode B trigger.

Covers PRD issue #100: coder must recognise `human-review-pending` label as a
Mode B trigger, fetch unresolved human REQUEST_CHANGES reviews from the REST API,
and classify them as Required feedback.

Gherkin scenarios traced:
  - scenario_coder_reinvoked_with_human_review_context
  - scenario_coder_mode_b_description_updated
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CODER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "coder.md"


def _load_coder_text() -> str:
    assert CODER_MD.exists(), f"coder agent file not found: {CODER_MD}"
    return CODER_MD.read_text()


def _extract_step_0(text: str) -> str:
    match = re.search(r"## Step 0 — Detect mode\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_b1(text: str) -> str:
    match = re.search(r"## Step 9 — Read all review feedback\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_b2(text: str) -> str:
    match = re.search(r"## Step 10 — Categori[sz]e the feedback\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


class TestCoderModeBAwarenessOfHumanReviewPending:
    """Scenario: coder re-invoked with human-review-pending label is in Mode B"""

    def test_step_0_checks_human_review_pending_label(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        assert "human-review-pending" in step, (
            "coder.md Step 0 must check for 'human-review-pending' label. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_0_bash_checks_both_labels(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        assert "HUMAN_REVIEW_PENDING" in step, (
            "coder.md Step 0 bash block must define HUMAN_REVIEW_PENDING variable. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_0_if_condition_includes_human_review_pending(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        if_lines = [l for l in step.splitlines() if l.strip().startswith("if ")]
        assert if_lines, "Step 0 must have an 'if' condition"
        combined_condition = " ".join(if_lines)
        assert "HUMAN_REVIEW_PENDING" in combined_condition, (
            "Step 0 if-condition must include HUMAN_REVIEW_PENDING in the Mode B check. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_0_introductory_text_explains_both_triggers(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        assert "human-review-pending" in step, (
            "Step 0 explanatory text must document the 'human-review-pending' trigger. "
            "Run: python3 scripts/update_agent_files.py"
        )
        assert "review-cycle" in step, (
            "Step 0 explanatory text must still document the 'review-cycle:N' trigger."
        )


class TestCoderB1FetchesHumanBlockReviewers:
    """Scenario: coder reads unresolved human REQUEST_CHANGES reviews"""

    def test_b1_fetches_human_block_reviewers_via_api(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "HUMAN_BLOCK_REVIEWERS" in b1, (
            "coder.md Step 9 must define HUMAN_BLOCK_REVIEWERS. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_b1_uses_gh_api_for_rest_reviews_endpoint(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "gh api" in b1, (
            "coder.md Step 9 must use 'gh api' to fetch the PR reviews endpoint. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_b1_excludes_bots(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "Bot" in b1, (
            "coder.md Step 9 must exclude bot accounts (.user.type != 'Bot'). "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_b1_uses_reviews_endpoint_path(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "reviews" in b1, (
            "coder.md Step 9 must reference the /reviews REST endpoint. "
            "Run: python3 scripts/update_agent_files.py"
        )


class TestCoderB2ClassifiesHumanReviewsAsRequired:
    """Scenario: coder classifies human REQUEST_CHANGES as Required feedback"""

    def test_b2_required_row_includes_human_reviews(self):
        text = _load_coder_text()
        b2 = _extract_b2(text)
        assert b2, "Step 10 (B2) section not found in coder.md"
        required_rows = [l for l in b2.splitlines() if "Required" in l]
        assert required_rows, "Step 10 (B2) must have a Required row in its feedback table"
        combined = " ".join(required_rows)
        assert "HUMAN_BLOCK_REVIEWERS" in combined or "human REQUEST_CHANGES" in combined.lower(), (
            "coder.md Step 10 Required row must include human REQUEST_CHANGES reviews as Required feedback. "
            "Run: python3 scripts/update_agent_files.py"
        )


class TestCoderDescriptionMentionsHumanReviewPending:
    """Scenario: coder description reflects human-review-pending Mode B trigger"""

    def test_frontmatter_description_mentions_human_review_pending(self):
        text = _load_coder_text()
        frontmatter_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert frontmatter_match, "No frontmatter found in coder.md"
        frontmatter = frontmatter_match.group(1)
        assert "human-review-pending" in frontmatter, (
            "coder.md frontmatter description must mention 'human-review-pending' label. "
            "Run: python3 scripts/update_agent_files.py"
        )
