"""Conformance tests for prd-writer agent -- Step 6e Gherkin backfill.

Covers PRD issue #292: prd-writer must backfill Gherkin coverage in augmentation
mode instead of silently skipping the classification-band minimum.

Gherkin scenarios traced (docs/features/prd-writer.md):
  - A pre-specified issue with the wrong notation gets Gherkin backfilled
  - Existing Gherkin coverage is left alone
  - Backfill never invents requirements
  - Non-behavioural requirements are not padded into scenarios
  - Sizer-created sub-issues are covered
  - Already-approved PRDs are not silently rewritten
  - The derived section is clearly attributed and traceable
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PRD_WRITER_MD = REPO_ROOT / ".claude" / "agents" / "01_product_docs" / "prd-writer.md"


def _load_prd_writer_text() -> str:
    assert PRD_WRITER_MD.exists(), f"prd-writer agent file not found: {PRD_WRITER_MD}"
    return PRD_WRITER_MD.read_text()


def _extract_step_6e(text: str) -> str:
    match = re.search(r"### 6e[^\n]*\n(.*?)(?=\n---\n|\n## Step |\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_step_2(text: str) -> str:
    match = re.search(r"## Step 2 [^\n]*\n(.*?)(?=\n---\n|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_step_3(text: str) -> str:
    match = re.search(r"## Step 3 [^\n]*\n(.*?)(?=\n---\n|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_frontmatter(text: str) -> str:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Scenario: A pre-specified issue with the wrong notation gets Gherkin backfilled
# ---------------------------------------------------------------------------

class TestStep6eBackfillsGherkinForWrongNotation:
    """Step 6e exists and runs during augmentation mode."""

    def test_step_6e_section_exists(self):
        text = _load_prd_writer_text()
        assert "### 6e" in text, (
            "prd-writer.md must contain a '### 6e' subsection implementing Gherkin backfill"
        )

    def test_step_6e_checks_existing_scenario_count(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "Scenario:" in step or "scenario" in step.lower(), (
            "Step 6e must check for existing '#### Scenario:' blocks in the body"
        )

    def test_step_6e_references_classification_band_minimum(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "minimum" in step, (
            "Step 6e must reference the classification band's minimum scenario count"
        )

    def test_step_6e_lists_band_minimums(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "enhancement" in step and "feature" in step, (
            "Step 6e must list the minimum scenario counts per classification band"
        )

    def test_step_3_decision_notes_gherkin_minimum_applies_in_augmentation(self):
        text = _load_prd_writer_text()
        step = _extract_step_3(text)
        assert step, "Step 3 section not found"
        assert "6e" in step, (
            "Step 3 decision note must reference Step 6e so readers understand "
            "the Gherkin minimum still applies in augmentation mode"
        )

    def test_frontmatter_description_mentions_step_6e(self):
        text = _load_prd_writer_text()
        fm = _extract_frontmatter(text)
        assert fm, "Frontmatter not found"
        assert "6e" in fm, (
            "prd-writer.md frontmatter description must mention Step 6e "
            "so the agent's summary is accurate after Gherkin backfill lands"
        )


# ---------------------------------------------------------------------------
# Scenario: Existing Gherkin coverage is left alone
# ---------------------------------------------------------------------------

class TestStep6eIsNoopWhenGherkinSufficient:
    """Step 6e must be a no-op when the minimum is already met."""

    def test_step_6e_has_noop_path_when_minimum_met(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "no-op" in step, (
            "Step 6e must have an explicit no-op path when existing scenario "
            "count already meets the band minimum"
        )

    def test_step_6e_skips_append_when_already_sufficient(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "meets" in step or "exceeds" in step or "meets or exceeds" in step, (
            "Step 6e must skip appending when the existing count meets or exceeds the minimum"
        )


# ---------------------------------------------------------------------------
# Scenario: Backfill never invents requirements
# ---------------------------------------------------------------------------

class TestStep6eNeverInventsRequirements:
    """Step 6e must stop at minimum or when candidates are exhausted."""

    def test_step_6e_stops_at_minimum_or_exhaustion(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "exhausted" in step, (
            "Step 6e must stop when candidates are exhausted (not invent extras)"
        )

    def test_step_6e_does_not_invent_beyond_source_material(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "invent" in step or "source material" in step, (
            "Step 6e must explicitly state it never invents scenarios beyond "
            "what the source material supports"
        )

    def test_step_6e_states_shortfall_with_reason(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "shortfall" in step or "backfill-note" in step, (
            "Step 6e must document the shortfall with a reason when fewer "
            "scenarios are derivable than the band minimum"
        )


# ---------------------------------------------------------------------------
# Scenario: Non-behavioural requirements are not padded into scenarios
# ---------------------------------------------------------------------------

class TestStep6eSkipsNonBehaviouralRequirements:
    """Step 6e must discard non-behavioural items."""

    def test_step_6e_discards_non_behavioural_items(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "non-behavioural" in step, (
            "Step 6e must explicitly discard non-behavioural requirements "
            "(internal structure with no user-observable surface)"
        )

    def test_step_6e_requires_user_observable_surface(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "user-observable" in step, (
            "Step 6e must require user-observable surface as the criterion "
            "for including a requirement as a scenario candidate"
        )


# ---------------------------------------------------------------------------
# Scenario: Sizer-created sub-issues are covered
# ---------------------------------------------------------------------------

class TestStep6eCoversSubIssues:
    """Step 2 must note that Step 6e applies to sizer-created sub-issues."""

    def test_step_2_references_step_6e_for_sub_issues(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert "6e" in step, (
            "Step 2 sub-issue handling must reference Step 6e so sizer-created "
            "sub-issues also get Gherkin backfilled"
        )

    def test_step_2_explains_sub_issue_6e_rationale(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert "Sizer templates" in step or "sizer" in step.lower(), (
            "Step 2 must explain why Step 6e applies to sub-issues "
            "(sizer templates do not generate Gherkin)"
        )

    def test_step_6e_runs_on_sub_issues(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "sub-issue" in step or "augmentation-mode" in step, (
            "Step 6e must state it runs on augmentation-mode issues including sub-issues"
        )


# ---------------------------------------------------------------------------
# Scenario: Already-approved PRDs are not silently rewritten
# ---------------------------------------------------------------------------

class TestStep6eNotRunOnAlreadyApproved:
    """Step 6e must guard against rewriting an already-approved spec."""

    def test_step_6e_has_approved_label_guard(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "ALREADY_APPROVED" in step, (
            "Step 6e must check for the 'prd-writer:approved' label "
            "and skip backfill if it is already present"
        )

    def test_step_6e_guard_uses_prd_writer_approved_label(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "prd-writer:approved" in step, (
            "Step 6e guard must check the exact label 'prd-writer:approved'"
        )

    def test_step_6e_guard_is_noop_on_approved(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        # Guard must skip to Step 8 if approved
        assert "Step 8" in step, (
            "Step 6e guard must skip directly to Step 8 when prd-writer:approved "
            "is already on the issue"
        )


# ---------------------------------------------------------------------------
# Scenario: The derived section is clearly attributed and traceable
# ---------------------------------------------------------------------------

class TestStep6eAttributionAndTraceability:
    """Derived scenarios must be labelled and traced back to source requirements."""

    def test_step_6e_labels_section_as_derived_by_prd_writer(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "Derived by prd-writer" in step, (
            "Step 6e must label the appended section as derived by prd-writer "
            "to distinguish it from human-authored content"
        )

    def test_step_6e_tags_each_scenario_with_source_requirement(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "<!-- R" in step, (
            "Step 6e must tag each derived scenario with a comment citing the "
            "source requirement (e.g. <!-- R24 -->)"
        )

    def test_step_6e_does_not_interleave_with_original_list(self):
        text = _load_prd_writer_text()
        step = _extract_step_6e(text)
        assert step, "Step 6e section not found"
        assert "interleave" in step or "renumber" in step, (
            "Step 6e must explicitly state it does not interleave with or "
            "renumber the original requirements list"
        )
