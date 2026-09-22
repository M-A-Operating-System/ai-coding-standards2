"""Configuration conformance tests for pr-reviewer agent — human review hard block.

Covers PRD issue #100: pr-reviewer must check for unresolved human REQUEST_CHANGES
reviews and cannot APPROVE while any exist.

Gherkin scenarios traced:
  - scenario_pr_reviewer_hard_block_on_unresolved_human_feedback
  - scenario_pr_reviewer_reads_human_review_comments
  - scenario_pr_reviewer_description_reflects_human_review_block
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"


def _load_pr_reviewer_text() -> str:
    assert PR_REVIEWER_MD.exists(), f"pr-reviewer agent file not found: {PR_REVIEWER_MD}"
    return PR_REVIEWER_MD.read_text()


def _extract_step_2(text: str) -> str:
    match = re.search(
        r"## Step 2 — Check for unresolved human reviews(.+?)(?=\n---\n|\Z)",
        text,
        re.DOTALL,
    )
    return match.group(1) if match else ""


def _extract_verdict_section(text: str) -> str:
    match = re.search(r"## Step 10 — Verdict\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


class TestPrReviewerHumanReviewStep:
    """Scenario: pr-reviewer reads human review comments (Step 2 exists)"""

    def test_step_2_exists(self):
        text = _load_pr_reviewer_text()
        assert "## Step 2" in text, (
            "pr-reviewer.md must contain Step 2 — Check for unresolved human reviews. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_2_fetches_pr_reviews_via_api(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section is missing"
        assert "gh api" in step, (
            "Step 2 must use 'gh api' to fetch PR reviews. "
            "Run: python3 scripts/update_agent_files.py"
        )
        assert "reviews" in step, (
            "Step 2 must reference the reviews endpoint. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_2_excludes_bots(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section is missing"
        assert "Bot" in step, (
            "Step 2 must exclude bot accounts (user.type == 'Bot'). "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_2_defines_human_block_variable(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section is missing"
        assert "HUMAN_BLOCK_REVIEWERS" in step, (
            "Step 2 must define HUMAN_BLOCK_REVIEWERS variable. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_step_2_sets_verdict_on_block(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section is missing"
        assert "REQUEST CHANGES" in step or "REQUEST_CHANGES" in step, (
            "Step 2 must set VERDICT=REQUEST CHANGES when human reviews block. "
            "Run: python3 scripts/update_agent_files.py"
        )


class TestPrReviewerVerdictHumanBlock:
    """Scenario: pr-reviewer hard block on unresolved human feedback (Step 8 updated)"""

    def test_verdict_section_has_human_block_rule(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        assert section, "Step 10 — Verdict section not found"
        assert "HUMAN_BLOCK_REVIEWERS" in section, (
            "Step 8 verdict must check HUMAN_BLOCK_REVIEWERS for the hard block. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_verdict_human_block_listed_before_automated_findings(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        assert section, "Step 10 — Verdict section not found"
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
        assert section, "Step 10 — Verdict section not found"
        approve_lines = [l for l in section.splitlines() if "APPROVE" in l]
        assert any("HUMAN_BLOCK_REVIEWERS" in l for l in approve_lines), (
            "The APPROVE rule in Step 8 must require HUMAN_BLOCK_REVIEWERS to be empty. "
            "Run: python3 scripts/update_agent_files.py"
        )


class TestPrReviewerExtraAllowedToolsForApi:
    """pr-reviewer must allow 'gh api *' to fetch PR reviews."""

    def test_pipeline_json_allows_gh_api(self):
        pipeline = json.loads(PIPELINE_JSON.read_text())
        pr_reviewer = next(
            (
                step
                for flow in pipeline["flows"].values()
                for step in flow["steps"]
                if step["agent"] == "03_execute/pr-reviewer"
            ),
            None,
        )
        assert pr_reviewer is not None, "03_execute/pr-reviewer not found in pipeline.json"
        tools = pr_reviewer.get("extra_allowedTools", [])
        assert "Bash(gh api *)" in tools, (
            "pipeline.json 03_execute/pr-reviewer extra_allowedTools must include "
            "Bash(gh api *) to allow fetching PR reviews"
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


class TestPrReviewerPriorArtefactLookupReadsFromIssueNotPr:
    """Issue #510: _post_artefact_if_present posts every step's artefact to
    work_item.number, which for the issue-kind pr-reviewer step is the
    issue -- never the PR. pr-reviewer's own PRIOR lookup (Step 0) queried
    issues/$PR_NUMBER/comments instead, so it could never find its own prior
    artefact, defeating the re-run detection this lookup exists for.

    Given pr-reviewer.md's Step 0 PRIOR-artefact lookup
    When a reader inspects the gh api call carrying the
    "ai-agile/artefact/v1 by 03_execute/pr-reviewer" marker
    Then it queries issues/$ISSUE_NUMBER/comments, not issues/$PR_NUMBER/comments
    """

    def _artefact_lookup_line(self, text: str) -> str:
        for line in text.splitlines():
            if "ai-agile/artefact/v1 by 03_execute/pr-reviewer" in line:
                return line
        return ""

    def test_prior_lookup_queries_issue_number(self):
        text = _load_pr_reviewer_text()
        line = self._artefact_lookup_line(text)
        assert line, "PRIOR-artefact lookup line not found in pr-reviewer.md"
        assert "issues/$ISSUE_NUMBER/comments" in line, (
            "pr-reviewer.md's PRIOR-artefact lookup must query "
            "issues/$ISSUE_NUMBER/comments -- its own artefact is posted "
            "to the issue, not the PR (issue #510)"
        )

    def test_prior_lookup_does_not_query_pr_number(self):
        text = _load_pr_reviewer_text()
        line = self._artefact_lookup_line(text)
        assert line, "PRIOR-artefact lookup line not found in pr-reviewer.md"
        assert "issues/$PR_NUMBER/comments" not in line, (
            "pr-reviewer.md's PRIOR-artefact lookup must not query "
            "issues/$PR_NUMBER/comments -- that thread never receives its "
            "artefact (issue #510)"
        )


def _extract_step_11(text: str) -> str:
    # Stop at the next real step/section heading, not the first "---" or "##"
    # -- Step 11's own result-body example embeds both inside its fenced
    # blocks ("## PR Review..." and a "---" divider).
    match = re.search(
        r"## Step 11 \u2014 Write the result(.+?)(?=\n## (?:Step \d|Rules)|\Z)",
        text,
        re.DOTALL,
    )
    return match.group(1) if match else ""


class TestPrReviewerStep11OutcomeIsNotHardCodedComplete:
    """Issue #512 Part 1: the result.json example in Step 11 used to hard-code
    "outcome": "complete", so a model that copied the example literally
    reported a failing (REQUEST CHANGES) review as a pass. The example must
    show the outcome as conditional on the verdict, not a literal value.

    Given pr-reviewer.md's Step 11 result.json example
    When a reader inspects the "outcome" field
    Then it is not the literal string "complete"
    And it names both possible outcomes (complete and review)
    """

    def test_step_11_exists(self):
        text = _load_pr_reviewer_text()
        assert _extract_step_11(text), "Step 11 section not found"

    def test_outcome_example_is_not_hard_coded_complete(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_11(text)
        assert step, "Step 11 section is missing"
        assert '"outcome": "complete"' not in step, (
            "Step 11's result.json example must not hard-code "
            '"outcome": "complete" -- a REQUEST CHANGES verdict copied '
            "literally would report a failing review as a pass (issue #512)"
        )

    def test_outcome_example_names_both_outcomes(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_11(text)
        assert step, "Step 11 section is missing"
        assert "complete" in step and "review" in step, (
            "Step 11's result.json example must show outcome as conditional "
            "on the verdict (complete on APPROVE, review on REQUEST CHANGES)"
        )

    def test_result_json_includes_structured_verdict_field(self):
        """Issue #512: the orchestrator cross-checks outcome against a
        structured result.verdict field, never against prose parsed back out
        of `output` (PRODUCT.md, "What a step must return")."""
        text = _load_pr_reviewer_text()
        step = _extract_step_11(text)
        assert step, "Step 11 section is missing"
        assert '"verdict": "$VERDICT"' in step, (
            "Step 11's result.json example must include a structured "
            '"verdict": "$VERDICT" field for the orchestrator to check '
            "outcome against (issue #512)"
        )
