"""Configuration conformance tests for pr-reviewer verdict threshold.

Covers PRD issue #99: REQUEST_CHANGES threshold lowered to include Medium findings.
Gherkin scenarios traced:
  - scenario_medium_triggers_request_changes
  - scenario_only_low_or_informational_yields_approve
  - scenario_critical_high_continue_to_trigger_request_changes
  - scenario_verdict_present_in_closing_announcement
  - scenario_agent_description_reflects_updated_threshold
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER_MD = REPO_ROOT / ".claude" / "agents" / "05_execute" / "pr-reviewer.md"
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"

VERDICT_APPROVE = "APPROVE"
VERDICT_REQUEST_CHANGES = "REQUEST_CHANGES"
THRESHOLD_SEVERITIES = ("Critical", "High", "Medium")
PASS_THROUGH_SEVERITIES = ("Low", "Informational")


def _load_pr_reviewer_text() -> str:
    assert PR_REVIEWER_MD.exists(), f"pr-reviewer agent file not found: {PR_REVIEWER_MD}"
    return PR_REVIEWER_MD.read_text()


def _load_pipeline_json() -> dict:
    assert PIPELINE_JSON.exists(), f"pipeline.json not found: {PIPELINE_JSON}"
    with open(PIPELINE_JSON) as f:
        return json.load(f)


def _find_pr_reviewer_entry(pipeline: dict) -> dict:
    def search(obj):
        if isinstance(obj, dict):
            if obj.get("agent") == "05_execute/pr-reviewer":
                return obj
            for v in obj.values():
                result = search(v)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = search(item)
                if result is not None:
                    return result
        return None
    entry = search(pipeline)
    assert entry is not None, "05_execute/pr-reviewer not found in pipeline.json"
    return entry


def _extract_verdict_section(text: str) -> str:
    match = re.search(r"## Step 8 — Verdict\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    assert match, "Step 8 — Verdict section not found in pr-reviewer.md"
    return match.group(1)


def _extract_frontmatter_description(text: str) -> str:
    match = re.search(r"^description: >(.+?)(?=^\w|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "description frontmatter not found in pr-reviewer.md"
    return match.group(1)


class TestScenarioMediumTriggersRequestChanges:
    """Scenario: Medium finding triggers REQUEST_CHANGES"""

    def test_verdict_section_includes_medium_in_request_changes(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        assert "Medium" in section, (
            "Step 8 verdict section must mention Medium in the REQUEST_CHANGES rule"
        )
        lines = [l.strip() for l in section.splitlines() if "REQUEST CHANGES" in l or "REQUEST_CHANGES" in l]
        assert lines, "No REQUEST CHANGES line found in Step 8"
        combined = " ".join(lines)
        assert "Medium" in combined, (
            f"REQUEST CHANGES rule must include Medium; got: {combined!r}"
        )

    def test_medium_not_in_approve_rule(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        approve_lines = [l.strip() for l in section.splitlines() if "APPROVE" in l]
        assert approve_lines, "No APPROVE line found in Step 8"
        for line in approve_lines:
            assert "Medium" not in line, (
                f"APPROVE rule must not include Medium; offending line: {line!r}"
            )


class TestScenarioOnlyLowOrInformationalYieldsApprove:
    """Scenario: Only Low or Informational findings yield APPROVE"""

    def test_verdict_section_approve_includes_low(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        approve_lines = [l.strip() for l in section.splitlines() if "APPROVE" in l]
        assert approve_lines, "No APPROVE line found in Step 8"
        combined = " ".join(approve_lines)
        assert "Low" in combined, (
            f"APPROVE rule must include Low severity; got: {combined!r}"
        )

    def test_verdict_section_approve_includes_informational(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        approve_lines = [l.strip() for l in section.splitlines() if "APPROVE" in l]
        combined = " ".join(approve_lines)
        assert "Informational" in combined, (
            f"APPROVE rule must include Informational severity; got: {combined!r}"
        )

    def test_low_not_in_request_changes_rule(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        rc_lines = [l.strip() for l in section.splitlines() if "REQUEST CHANGES" in l or "REQUEST_CHANGES" in l]
        for line in rc_lines:
            assert "Low" not in line, (
                f"REQUEST CHANGES rule must not include Low; offending line: {line!r}"
            )


class TestScenarioCriticalHighContinueTrigger:
    """Scenario: Critical and High findings continue to trigger REQUEST_CHANGES"""

    def test_critical_in_request_changes_rule(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        rc_lines = [l.strip() for l in section.splitlines() if "REQUEST CHANGES" in l or "REQUEST_CHANGES" in l]
        assert rc_lines, "No REQUEST CHANGES line found in Step 8"
        combined = " ".join(rc_lines)
        assert "Critical" in combined, (
            f"REQUEST CHANGES rule must include Critical; got: {combined!r}"
        )

    def test_high_in_request_changes_rule(self):
        text = _load_pr_reviewer_text()
        section = _extract_verdict_section(text)
        rc_lines = [l.strip() for l in section.splitlines() if "REQUEST CHANGES" in l or "REQUEST_CHANGES" in l]
        combined = " ".join(rc_lines)
        assert "High" in combined, (
            f"REQUEST CHANGES rule must include High; got: {combined!r}"
        )


class TestScenarioVerdictInClosingAnnouncement:
    """Scenario: Verdict is present in the structured closing announcement"""

    def test_verdict_field_present_in_step10(self):
        text = _load_pr_reviewer_text()
        step10_match = re.search(r"## Step 10 — Close(.+?)(?=\n---|\Z)", text, re.DOTALL)
        assert step10_match, "Step 10 — Close section not found in pr-reviewer.md"
        step10 = step10_match.group(1)
        assert '"verdict"' in step10, (
            'Step 10 closing JSON must contain a "verdict" field'
        )

    def test_verdict_field_uses_verdict_variable(self):
        text = _load_pr_reviewer_text()
        step10_match = re.search(r"## Step 10 — Close(.+?)(?=\n---|\Z)", text, re.DOTALL)
        assert step10_match
        step10 = step10_match.group(1)
        assert '"verdict": "$VERDICT"' in step10, (
            'verdict field must be set to "$VERDICT" in Step 10 JSON'
        )


class TestScenarioAgentDescriptionReflectsThreshold:
    """Scenario: Agent description reflects updated threshold"""

    def test_frontmatter_description_mentions_request_changes_for_medium(self):
        text = _load_pr_reviewer_text()
        desc = _extract_frontmatter_description(text)
        assert "Medium" in desc, (
            "Frontmatter description must mention Medium in context of REQUEST_CHANGES"
        )
        assert "REQUEST_CHANGES" in desc or "REQUEST CHANGES" in desc, (
            "Frontmatter description must mention REQUEST_CHANGES"
        )

    def test_frontmatter_description_mentions_approve_for_low_or_informational(self):
        text = _load_pr_reviewer_text()
        desc = _extract_frontmatter_description(text)
        assert "Low" in desc or "Informational" in desc, (
            "Frontmatter description must mention Low or Informational in context of APPROVE"
        )

    def test_pipeline_json_description_mentions_threshold(self):
        pipeline = _load_pipeline_json()
        entry = _find_pr_reviewer_entry(pipeline)
        desc = entry.get("description", "")
        assert "Medium" in desc, (
            "pipeline.json pr-reviewer description must mention Medium severity"
        )
        assert "REQUEST_CHANGES" in desc or "REQUEST CHANGES" in desc, (
            "pipeline.json pr-reviewer description must mention REQUEST_CHANGES"
        )
        assert "Low" in desc or "Informational" in desc, (
            "pipeline.json pr-reviewer description must mention Low or Informational for APPROVE"
        )
