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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"

VERDICT_APPROVE = "APPROVE"
VERDICT_REQUEST_CHANGES = "REQUEST_CHANGES"
THRESHOLD_SEVERITIES = ("Critical", "High", "Medium")
PASS_THROUGH_SEVERITIES = ("Low", "Informational")

# The severity → verdict partition under test. Critical/High/Medium must drive
# REQUEST_CHANGES; Low/Informational must drive APPROVE. Tested as a whole so the
# partition can never silently lose a severity.
SEVERITY_VERDICT_MAP = (
    [(sev, VERDICT_REQUEST_CHANGES) for sev in THRESHOLD_SEVERITIES]
    + [(sev, VERDICT_APPROVE) for sev in PASS_THROUGH_SEVERITIES]
)


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
            if obj.get("agent") == "03_execute/pr-reviewer":
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
    assert entry is not None, "03_execute/pr-reviewer not found in pipeline.json"
    return entry


def _extract_verdict_section(text: str) -> str:
    match = re.search(r"## Step 10 — Verdict\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    assert match, "Step 10 — Verdict section not found in pr-reviewer.md"
    return match.group(1)


def _extract_frontmatter_description(text: str) -> str:
    match = re.search(r"^description: >(.+?)(?=^\w|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "description frontmatter not found in pr-reviewer.md"
    return match.group(1)


def _request_changes_rule_line(section: str) -> str:
    """Return the single REQUEST CHANGES rule line from the verdict section."""
    lines = [
        l.strip()
        for l in section.splitlines()
        if "REQUEST CHANGES" in l or "REQUEST_CHANGES" in l
    ]
    assert lines, "No REQUEST CHANGES line found in Step 10"
    # The threshold rule is the line that enumerates the blocking severities; pick
    # the one mentioning the highest severity so we test the rule, not prose.
    rule = next((l for l in lines if "Critical" in l), lines[0])
    return rule


def _approve_rule_line(section: str) -> str:
    """Return the single APPROVE rule line from the verdict section."""
    lines = [l.strip() for l in section.splitlines() if "APPROVE" in l]
    assert lines, "No APPROVE line found in Step 10"
    rule = next(
        (l for l in lines if "Low" in l or "Informational" in l),
        lines[0],
    )
    return rule


class TestVerdictRuleOrderedStructure:
    """The verdict rules must enumerate severities in order before the arrow.

    Substring presence (``"Medium" in section``) passes for the wrong reason —
    the word could appear anywhere. These assert the ordered shape of each rule:
    severities listed (in canonical order) before the verdict they map to.
    """

    def test_request_changes_rule_lists_severities_before_arrow(self):
        section = _extract_verdict_section(_load_pr_reviewer_text())
        rule = _request_changes_rule_line(section)
        assert re.search(r"Critical.*High.*Medium.*REQUEST", rule), (
            "REQUEST CHANGES rule must list Critical, High, AND Medium (in that "
            f"order) before the verdict; got: {rule!r}"
        )

    def test_approve_rule_lists_severities_before_arrow(self):
        section = _extract_verdict_section(_load_pr_reviewer_text())
        rule = _approve_rule_line(section)
        assert re.search(r"Low.*Informational.*APPROVE", rule), (
            "APPROVE rule must list Low AND Informational (in that order) before "
            f"the verdict; got: {rule!r}"
        )

    def test_request_changes_rule_excludes_pass_through_severities(self):
        section = _extract_verdict_section(_load_pr_reviewer_text())
        rule = _request_changes_rule_line(section)
        for sev in PASS_THROUGH_SEVERITIES:
            assert sev not in rule, (
                f"REQUEST CHANGES rule must not include {sev}; got: {rule!r}"
            )

    def test_approve_rule_excludes_threshold_severities(self):
        section = _extract_verdict_section(_load_pr_reviewer_text())
        rule = _approve_rule_line(section)
        for sev in THRESHOLD_SEVERITIES:
            assert sev not in rule, (
                f"APPROVE rule must not include {sev}; got: {rule!r}"
            )


class TestSeverityVerdictPartition:
    """The severity → verdict partition, exercised as a mapping table.

    Each severity must appear on the rule line for exactly the verdict it maps
    to, and be absent from the opposite rule. Parametrizing over
    ``SEVERITY_VERDICT_MAP`` tests the partition as a whole rather than one
    severity at a time.
    """

    @pytest.mark.parametrize("severity,verdict", SEVERITY_VERDICT_MAP)
    def test_severity_maps_to_expected_verdict(self, severity, verdict):
        section = _extract_verdict_section(_load_pr_reviewer_text())
        if verdict == VERDICT_REQUEST_CHANGES:
            target = _request_changes_rule_line(section)
            other = _approve_rule_line(section)
        else:
            target = _approve_rule_line(section)
            other = _request_changes_rule_line(section)
        assert severity in target, (
            f"{severity} must appear on the {verdict} rule; got: {target!r}"
        )
        assert severity not in other, (
            f"{severity} must not appear on the opposing rule; got: {other!r}"
        )


class TestAdrDowngradeCarveOut:
    """The trickiest verdict branch: ADR-downgraded findings never block APPROVE.

    pr-reviewer.md Step 10 carries a carve-out line stating that findings an ADR
    downgrades to Informational do not count toward the REQUEST_CHANGES
    threshold. This branch is otherwise untested.
    """

    def test_adr_downgrade_does_not_block_approve(self):
        section = _extract_verdict_section(_load_pr_reviewer_text())
        adr_lines = [
            l.strip()
            for l in section.splitlines()
            if "ADR" in l and "Informational" in l
        ]
        assert adr_lines, (
            "Step 10 must carry an ADR-downgrade carve-out line mentioning "
            "Informational (e.g. 'ADR-covered findings downgraded to "
            "Informational never block APPROVE')"
        )
        combined = " ".join(adr_lines)
        assert "APPROVE" in combined, (
            "ADR carve-out must state the downgrade never blocks APPROVE; got: "
            f"{combined!r}"
        )
        assert re.search(r"never block", combined, re.IGNORECASE), (
            "ADR carve-out must state downgraded findings 'never block' APPROVE; "
            f"got: {combined!r}"
        )


class TestScenarioVerdictInClosingAnnouncement:
    """Scenario: Verdict is present in the structured result the step writes.

    Since issue #400, pr-reviewer no longer posts its own closing
    announcement — it writes one result to $AI_AGILE_SCRATCH/result.json and
    the orchestrator posts the closing announcement on its behalf. The
    verdict must still be traceable from that result (in summary/message),
    bound to a shell variable rather than hardcoded.
    """

    def test_verdict_field_present_in_result_write(self):
        text = _load_pr_reviewer_text()
        step_match = re.search(r"## Step 11 — Write the result(.+?)(?=\n---|\Z)", text, re.DOTALL)
        assert step_match, "Step 11 — Write the result section not found in pr-reviewer.md"
        step = step_match.group(1)
        assert "Verdict:" in step, (
            "the result.json write must include the verdict (e.g. in summary/message)"
        )

    def test_verdict_field_bound_to_a_variable(self):
        # Presence of the verdict text is covered by the test above.
        # Here we only assert it is bound to *some* shell variable, without
        # coupling to the exact variable name (which is an implementation detail).
        text = _load_pr_reviewer_text()
        step_match = re.search(r"## Step 11 — Write the result(.+?)(?=\n---|\Z)", text, re.DOTALL)
        assert step_match
        step = step_match.group(1)
        assert re.search(r"Verdict:\s*\$\{?\w+\}?", step), (
            "the verdict must be bound to a shell variable (e.g. $VERDICT), "
            "not hardcoded, in the Step 11 result.json write"
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
