"""Conformance tests for prd-writer agent -- Step 6e Gherkin backfill.

Covers issue #292: prd-writer must backfill Gherkin coverage in augmentation
mode instead of silently skipping the classification-band minimum.

Gherkin scenarios traced:
  - test_a_pre_specified_issue_with_the_wrong_notation_gets_gherkin_backfilled
  - test_existing_gherkin_coverage_is_left_alone
  - test_backfill_never_invents_requirements
  - test_non_behavioural_requirements_are_not_padded_into_scenarios
  - test_sizer_created_sub_issues_are_covered
  - test_already_approved_prds_are_not_silently_rewritten
  - test_the_derived_section_is_clearly_attributed_and_traceable
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PRD_WRITER_MD = REPO_ROOT / ".claude" / "agents" / "01_product_docs" / "prd-writer.md"


def _load_text() -> str:
    assert PRD_WRITER_MD.exists(), f"prd-writer agent file not found: {PRD_WRITER_MD}"
    return PRD_WRITER_MD.read_text()


def _extract_step_6e(text: str) -> str:
    match = re.search(
        r"### 6e.*?Backfill Gherkin coverage(.+?)(?=\n---\n|\Z)",
        text,
        re.DOTALL,
    )
    return match.group(1) if match else ""


def _extract_step_2(text: str) -> str:
    match = re.search(
        r"## Step 2.*?sub.issue(.+?)(?=\n---\n|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _extract_step_3(text: str) -> str:
    match = re.search(
        r"## Step 3.*?pre.existing(.+?)(?=\n---\n|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match else ""


class TestPreSpecifiedIssueGetsGherkinBackfilled:
    """Scenario: A pre-specified issue with the wrong notation gets Gherkin backfilled"""

    def test_step_6e_exists(self):
        text = _load_text()
        assert "6e" in text, "prd-writer.md must contain Step 6e for Gherkin backfill"

    def test_step_6e_appends_gherkin_section(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing from prd-writer.md"
        assert "Acceptance criteria (Gherkin)" in step, (
            "Step 6e must append an '### Acceptance criteria (Gherkin)' section"
        )

    def test_step_6e_checks_minimum_against_count(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "minimum" in step.lower() or "Minimum" in step, (
            "Step 6e must check existing scenario count against the band minimum"
        )

    def test_step_3_decision_mentions_step_6e(self):
        text = _load_text()
        step = _extract_step_3(text)
        assert step, "Step 3 section is missing"
        assert "6e" in step, (
            "Step 3 decision must mention Step 6e so augmentation-mode issues "
            "know Gherkin backfill applies"
        )


class TestExistingGherkinCoverageIsLeftAlone:
    """Scenario: Existing Gherkin coverage is left alone"""

    def test_step_6e_is_noop_when_count_meets_minimum(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "no-op" in step or "noop" in step.lower(), (
            "Step 6e must state it is a no-op when existing Gherkin count meets minimum"
        )

    def test_step_6e_check_uses_scenario_count(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "Scenario:" in step or "#### Scenario" in step, (
            "Step 6e must count '#### Scenario:' blocks to decide if backfill is needed"
        )


class TestBackfillNeverInventsRequirements:
    """Scenario: Backfill never invents requirements"""

    def test_step_6e_stops_at_exhaustion(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "exhausted" in step or "exhaustion" in step, (
            "Step 6e derivation algorithm must stop when candidates are exhausted, "
            "not invent more to reach the minimum"
        )

    def test_step_6e_forbids_invention(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "Never invent" in step or "never invent" in step, (
            "Step 6e must explicitly forbid inventing scenarios beyond what source "
            "material supports"
        )


class TestNonBehaviouralRequirementsNotPadded:
    """Scenario: Non-behavioural requirements are not padded into scenarios"""

    def test_step_6e_discards_non_behavioural(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "non-behavioural" in step or "non-behavioral" in step, (
            "Step 6e must discard non-behavioural requirements from candidate pool"
        )

    def test_step_6e_honesty_note_for_shortfall(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "backfill-note" in step or "shortfall" in step, (
            "Step 6e must append a note when fewer scenarios than the minimum are "
            "derivable due to non-behavioural requirements"
        )


class TestSizerCreatedSubIssuesCovered:
    """Scenario: Sizer-created sub-issues are covered"""

    def test_step_2_mentions_step_6e_for_sub_issues(self):
        text = _load_text()
        step = _extract_step_2(text)
        assert step, "Step 2 (sub-issue handling) section is missing"
        assert "6e" in step, (
            "Step 2 must state that Step 6e still applies to sizer-created sub-issues"
        )

    def test_step_2_explains_sizer_lacks_gherkin(self):
        text = _load_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section is missing"
        assert "Gherkin" in step or "gherkin" in step.lower(), (
            "Step 2 must explain why Step 6e applies to sub-issues "
            "(sizer templates do not generate Gherkin)"
        )


class TestAlreadyApprovedPrdsNotRewritten:
    """Scenario: Already-approved PRDs are not silently rewritten"""

    def test_step_6e_guards_already_approved(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "prd-writer:approved" in step or "ALREADY_APPROVED" in step, (
            "Step 6e must guard against rewriting already-approved issues "
            "(check for prd-writer:approved label)"
        )

    def test_step_6e_skips_to_step_8_if_approved(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "Step 8" in step, (
            "Step 6e must skip to Step 8 when the issue already has prd-writer:approved"
        )

    def test_frontmatter_describes_step_6e(self):
        text = _load_text()
        desc_match = re.search(
            r"^description: >(.+?)(?=^\w|\Z)", text, re.MULTILINE | re.DOTALL
        )
        assert desc_match, "description frontmatter not found in prd-writer.md"
        desc = desc_match.group(1)
        assert "6e" in desc or "Gherkin" in desc, (
            "prd-writer.md frontmatter description must mention Step 6e or Gherkin "
            "backfill to reflect the updated augmentation-mode behaviour"
        )


class TestDerivedSectionClearlyAttributedAndTraceable:
    """Scenario: The derived section is clearly attributed and traceable"""

    def test_step_6e_labels_section_as_derived(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "Derived by prd-writer" in step or "derived by prd-writer" in step.lower(), (
            "Step 6e appended section must be labelled as derived by prd-writer "
            "so it is not mistaken for human-authored content"
        )

    def test_step_6e_tags_source_requirement(self):
        text = _load_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section is missing"
        assert "<!-- R" in step or "source requirement" in step.lower(), (
            "Step 6e must tag each derived scenario with a comment citing its source "
            "requirement (e.g. <!-- R24 -->) for traceability"
        )
