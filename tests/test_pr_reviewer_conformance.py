"""Configuration conformance tests for pr-reviewer agent — human review hard block.

Covers PRD issue #100: pr-reviewer must check for unresolved human REQUEST_CHANGES
reviews and cannot APPROVE while any exist.

Gherkin scenarios traced:
  - scenario_pr_reviewer_hard_block_on_unresolved_human_feedback
  - scenario_pr_reviewer_reads_human_review_comments
  - scenario_pr_reviewer_description_reflects_human_review_block
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"


def _load_pr_reviewer_text() -> str:
    assert PR_REVIEWER_MD.exists(), f"pr-reviewer agent file not found: {PR_REVIEWER_MD}"
    return PR_REVIEWER_MD.read_text()


def _extract_step_1_5(text: str) -> str:
    match = re.search(
        r"## Step 1\.5 — Check for unresolved human reviews(.+?)(?=\n---\n|\Z)",
        text,
        re.DOTALL,
    )
    return match.group(1) if match else ""


def _extract_verdict_section(text: str) -> str:
    match = re.search(r"## Step 8 — Verdict\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


class TestPrReviewerHumanReviewStep:
    """Scenario: pr-reviewer reads human review comments (Step 1.5 exists)"""

    def test_step_1_5_exists(self):
        text = _load_pr_reviewer_text()
        assert "## Step 1.5" in text, (
            "pr-reviewer.md must contain Step 1.5 — Check for unresolved human reviews. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_1_5_fetches_pr_reviews_via_api(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_1_5(text)
        assert step, "Step 1.5 section is missing"
        assert "gh api" in step, (
            "Step 1.5 must use 'gh api' to fetch PR reviews. "
            "Run: python3 scripts/update_agent_files.py"
        )
        assert "reviews" in step, (
            "Step 1.5 must reference the reviews endpoint. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_1_5_excludes_bots(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_1_5(text)
        assert step, "Step 1.5 section is missing"
        assert "Bot" in step, (
            "Step 1.5 must exclude bot accounts (user.type == 'Bot'). "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_1_5_defines_human_block_variable(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_1_5(text)
        assert step, "Step 1.5 section is missing"
        assert "HUMAN_BLOCK_REVIEWERS" in step, (
            "Step 1.5 must define HUMAN_BLOCK_REVIEWERS variable. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_1_5_sets_verdict_on_block(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_1_5(text)
        assert step, "Step 1.5 section is missing"
        assert "REQUEST CHANGES" in step or "REQUEST_CHANGES" in step, (
            "Step 1.5 must set VERDICT=REQUEST CHANGES when human reviews block. "
            "Run: python3 scripts/update_agent_files.py"
        )


class TestPrReviewerVerdictHumanBlock:
    """Scenario: pr-reviewer hard block on unresolved human feedback (Step 8 updated)"""

    def test_verdict_section_has_human_block_rule(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        assert section, "Step 8 — Verdict section not found"
        assert "HUMAN_BLOCK_REVIEWERS" in section, (
            "Step 8 verdict must check HUMAN_BLOCK_REVIEWERS for the hard block. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_verdict_human_block_listed_before_automated_findings(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        assert section, "Step 8 — Verdict section not found"
        lines = [l.strip() for l in section.splitlines() if l.strip().startswith("-")]
        human_block_idx = next(
            (i for i, l in enumerate(lines) if "HUMAN_BLOCK_REVIEWERS" in l), None
        )
        automated_idx = next(
            (i for i, l in enumerate(lines) if "Critical" in l and "High" in l), None
        )
        assert human_block_idx is not None, (
            "Step 8 must have a rule line checking HUMAN_BLOCK_REVIEWERS"
        )
        assert automated_idx is not None, (
            "Step 8 must have the automated finding rule (Critical/High/Medium)"
        )
        assert human_block_idx < automated_idx, (
            "Human block rule must appear before the automated finding rule in Step 8 "
            "(human block takes priority)"
        )

    def test_approve_requires_empty_human_block_reviewers(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        assert section, "Step 8 — Verdict section not found"
        approve_lines = [l for l in section.splitlines() if "APPROVE" in l]
        assert any("HUMAN_BLOCK_REVIEWERS" in l for l in approve_lines), (
            "The APPROVE rule in Step 8 must require HUMAN_BLOCK_REVIEWERS to be empty. "
            "Run: python3 scripts/update_agent_files.py"
        )


class TestPrReviewerExtraAllowedToolsForApi:
    """pr-reviewer must allow 'gh api *' to fetch PR reviews."""

    def test_frontmatter_allows_gh_api(self):
        text = _load_pr_reviewer_text()
        # Look for gh api in the frontmatter extra_allowedTools line
        frontmatter_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert frontmatter_match, "No frontmatter found in pr-reviewer.md"
        frontmatter = frontmatter_match.group(1)
        assert "gh api" in frontmatter or "Bash(gh api *)" in frontmatter, (
            "pr-reviewer.md frontmatter extra_allowedTools must include Bash(gh api *) "
            "to allow fetching PR reviews. Run: python3 scripts/update_agent_files.py"
        )


class TestPrReviewerDescriptionMentionsHumanBlock:
    """Scenario: Agent description reflects human review hard block"""

    def test_frontmatter_description_mentions_human_review_block(self):
        text = _load_pr_reviewer_text()
        desc_match = re.search(
            r"^description: >(.+?)(?=^\w|\Z)", text, re.MULTILINE | re.DOTALL
        )
        assert desc_match, "description frontmatter not found in pr-reviewer.md"
        desc = desc_match.group(1)
        assert "human" in desc.lower() and (
            "REQUEST_CHANGES" in desc or "REQUEST CHANGES" in desc
        ), (
            "pr-reviewer.md description must mention the human review hard block. "
            "Run: python3 scripts/update_agent_files.py"
        )
