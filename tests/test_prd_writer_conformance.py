"""Conformance tests for prd-writer agent -- Step 6d Gherkin backfill.

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


def _extract_step_6d(text: str) -> str:
    match = re.search(r"### 6d[^\n]*\n(.*?)(?=\n---\n|\n## Step |\Z)", text, re.DOTALL)
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

class TestStep6dBackfillsGherkinForWrongNotation:
    """Step 6d exists and runs during augmentation mode."""

    def test_step_6d_section_exists(self):
        text = _load_prd_writer_text()
        assert "### 6d" in text, (
            "prd-writer.md must contain a '### 6d' subsection implementing Gherkin backfill"
        )

    def test_step_6d_checks_existing_scenario_count(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "Scenario:" in step or "scenario" in step.lower(), (
            "Step 6d must check for existing '#### Scenario:' blocks in the body"
        )

    def test_step_6d_references_classification_band_minimum(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "minimum" in step, (
            "Step 6d must reference the classification band's minimum scenario count"
        )

    def test_step_6d_lists_band_minimums(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "enhancement" in step and "tech-debt" in step, (
            "Step 6d must list the minimum scenario counts per classification band"
        )

    def test_step_3_decision_notes_gherkin_minimum_applies_in_augmentation(self):
        text = _load_prd_writer_text()
        step = _extract_step_3(text)
        assert step, "Step 3 section not found"
        assert "6d" in step, (
            "Step 3 decision note must reference Step 6d so readers understand "
            "the Gherkin minimum still applies in augmentation mode"
        )

    def test_frontmatter_description_mentions_step_6d(self):
        text = _load_prd_writer_text()
        fm = _extract_frontmatter(text)
        assert fm, "Frontmatter not found"
        assert "6d" in fm, (
            "prd-writer.md frontmatter description must mention Step 6d "
            "so the agent's summary is accurate after Gherkin backfill lands"
        )


# ---------------------------------------------------------------------------
# Scenario: Existing Gherkin coverage is left alone
# ---------------------------------------------------------------------------

class TestStep6dIsNoopWhenGherkinSufficient:
    """Step 6d must be a no-op when the minimum is already met."""

    def test_step_6d_has_noop_path_when_minimum_met(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "no-op" in step, (
            "Step 6d must have an explicit no-op path when existing scenario "
            "count already meets the band minimum"
        )

    def test_step_6d_skips_append_when_already_sufficient(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "meets" in step or "exceeds" in step or "meets or exceeds" in step, (
            "Step 6d must skip appending when the existing count meets or exceeds the minimum"
        )


# ---------------------------------------------------------------------------
# Scenario: Backfill never invents requirements
# ---------------------------------------------------------------------------

class TestStep6dNeverInventsRequirements:
    """Step 6d must stop at minimum or when candidates are exhausted."""

    def test_step_6d_stops_at_minimum_or_exhaustion(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "exhausted" in step, (
            "Step 6d must stop when candidates are exhausted (not invent extras)"
        )

    def test_step_6d_does_not_invent_beyond_source_material(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "invent" in step or "source material" in step, (
            "Step 6d must explicitly state it never invents scenarios beyond "
            "what the source material supports"
        )

    def test_step_6d_states_shortfall_with_reason(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "shortfall" in step or "backfill-note" in step, (
            "Step 6d must document the shortfall with a reason when fewer "
            "scenarios are derivable than the band minimum"
        )


# ---------------------------------------------------------------------------
# Scenario: issue #434 -- the band's minimum is a floor, not a ceiling
# ---------------------------------------------------------------------------

def _extract_step_5a(text: str) -> str:
    match = re.search(r"### 5a[^\n]*\n(.*?)(?=\n### |\n---\n|\n## Step |\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _table_rows(section: str) -> list:
    """Markdown table rows as lists of cell strings, header/separator dropped."""
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= set("- "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    return rows[1:] if rows else rows  # drop header row


class TestStep6dTargetsMaximumNotMinimum:
    """Issue #434: Step 6d's derivation algorithm must derive toward the
    classification band's maximum, using the minimum only as a floor for a
    thinly-specified issue -- never as a stopping condition once reached."""

    def test_step_6d_lists_band_maximums(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "Maximum scenarios" in step, (
            "Step 6d must list the maximum scenario count per classification "
            "band, alongside the minimum"
        )

    def test_step_6d_does_not_stop_at_minimum(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "stop when the minimum is reached" not in step.lower(), (
            "Step 6d must not treat reaching the minimum as a stopping "
            "condition -- it should derive toward the band's maximum"
        )
        assert re.search(r"never a stopping condition|not a stopping condition", step), (
            "Step 6d must explicitly say the minimum is not a stopping condition"
        )

    def test_step_6d_derives_up_to_maximum(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert re.search(r"up to the band'?s[\s\S]{0,20}maximum", step), (
            "Step 6d's derivation rule must derive one scenario per remaining "
            "distinct candidate up to the band's maximum"
        )

    def test_step_6d_and_step_5a_state_the_same_ranges(self):
        """Reproduces the #433 shape: Step 5a's classification table and
        Step 6d's backfill table must agree on every band's scenario count,
        not just on the low end."""
        text = _load_prd_writer_text()
        step_5a = _extract_step_5a(text)
        step_6d = _extract_step_6d(text)
        assert step_5a and step_6d, "Step 5a or Step 6d section not found"

        # Step 5a: | Classification | Problem | Goal | User stories | Gherkin scenarios | ... |
        rows_5a = _table_rows(step_5a)
        gherkin_by_band = {}
        for row in rows_5a:
            if len(row) < 5:
                continue
            band = row[0].strip("`")
            m = re.match(r"(\d+)\D+(\d+)", row[4])
            if m:
                gherkin_by_band[band] = (int(m.group(1)), int(m.group(2)))
        assert gherkin_by_band, "could not parse any band ranges out of Step 5a's table"

        # Step 6d: | Classification | Minimum scenarios | Maximum scenarios |
        rows_6d = _table_rows(step_6d)
        range_by_band_6d = {}
        for row in rows_6d:
            if len(row) < 3:
                continue
            band = row[0].strip("`")
            if not row[1].strip().isdigit() or not row[2].strip().isdigit():
                continue
            range_by_band_6d[band] = (int(row[1]), int(row[2]))
        assert range_by_band_6d, "could not parse any band ranges out of Step 6d's table"

        for band, rng_5a in gherkin_by_band.items():
            assert band in range_by_band_6d, f"Step 6d's table is missing the {band!r} band"
            assert range_by_band_6d[band] == rng_5a, (
                f"{band!r} band: Step 5a says {rng_5a}, Step 6d says "
                f"{range_by_band_6d[band]} -- the two tables must state the same numbers"
            )


class TestStep6dCoverageSelfCheck:
    """Issue #434: before signalling review, Step 6d must verify every
    enumerated requirement is cited by at least one scenario, and either
    derive the gap or state it explicitly -- catching what a human reviewer
    otherwise has to find by inspection (the #433 incident)."""

    def test_step_6d_has_a_coverage_self_check(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert re.search(r"coverage self-check", step, re.IGNORECASE), (
            "Step 6d must contain an explicit coverage self-check before Step 8"
        )

    def test_self_check_compares_requirement_tags_to_cited_scenarios(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "requirement tags" in step or "cited" in step, (
            "the coverage self-check must compare enumerated requirement tags "
            "against the tags actually cited by scenarios in the body"
        )

    def test_self_check_requires_deriving_or_stating_gaps(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "derive it now" in step, (
            "a coverable gap must be derived before finishing, not just noted"
        )
        assert "artefact comment" in step, (
            "an uncoverable gap must be stated explicitly in the artefact comment"
        )

    def test_self_check_forbids_signalling_review_with_a_known_gap(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert re.search(r"do not signal.*outcome.*review.*gap", step, re.IGNORECASE | re.DOTALL), (
            "Step 6d must forbid signalling outcome: review while a known, "
            "unstated coverage gap remains"
        )


# ---------------------------------------------------------------------------
# Scenario: Non-behavioural requirements are not padded into scenarios
# ---------------------------------------------------------------------------

class TestStep6dSkipsNonBehaviouralRequirements:
    """Step 6d must discard non-behavioural items."""

    def test_step_6d_discards_non_behavioural_items(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "non-behavioural" in step, (
            "Step 6d must explicitly discard non-behavioural requirements "
            "(internal structure with no user-observable surface)"
        )

    def test_step_6d_requires_user_observable_surface(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "user-observable" in step, (
            "Step 6d must require user-observable surface as the criterion "
            "for including a requirement as a scenario candidate"
        )


# ---------------------------------------------------------------------------
# Scenario: Sizer-created sub-issues are covered
# ---------------------------------------------------------------------------

class TestStep6dCoversSubIssues:
    """Step 2 must note that Step 6d applies to sizer-created sub-issues."""

    def test_step_2_references_step_6d_for_sub_issues(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert "6d" in step, (
            "Step 2 sub-issue handling must reference Step 6d so sizer-created "
            "sub-issues also get Gherkin backfilled"
        )

    def test_step_2_explains_sub_issue_6d_rationale(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert "Sizer templates" in step or "sizer" in step.lower(), (
            "Step 2 must explain why Step 6d applies to sub-issues "
            "(sizer templates do not generate Gherkin)"
        )

    def test_step_6d_runs_on_sub_issues(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "sub-issue" in step or "augmentation-mode" in step, (
            "Step 6d must state it runs on augmentation-mode issues including sub-issues"
        )


# ---------------------------------------------------------------------------
# Scenario: Already-approved PRDs are not silently rewritten
# ---------------------------------------------------------------------------

class TestStep6dNotRunOnAlreadyApproved:
    """Step 6d must guard against rewriting an already-approved spec."""

    def test_step_6d_has_approved_label_guard(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "ALREADY_APPROVED" in step, (
            "Step 6d must check for the 'prd-writer:approved' label "
            "and skip backfill if it is already present"
        )

    def test_step_6d_guard_uses_prd_writer_approved_label(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "prd-writer:approved" in step, (
            "Step 6d guard must check the exact label 'prd-writer:approved'"
        )

    def test_step_6d_guard_is_noop_on_approved(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        # Guard must skip to Step 8 if approved
        assert "Step 8" in step, (
            "Step 6d guard must skip directly to Step 8 when prd-writer:approved "
            "is already on the issue"
        )


# ---------------------------------------------------------------------------
# Scenario: The derived section is clearly attributed and traceable
# ---------------------------------------------------------------------------

class TestStep6dAttributionAndTraceability:
    """Derived scenarios must be labelled and traced back to source requirements."""

    def test_step_6d_labels_section_as_derived_by_prd_writer(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "Derived by prd-writer" in step, (
            "Step 6d must label the appended section as derived by prd-writer "
            "to distinguish it from human-authored content"
        )

    def test_step_6d_tags_each_scenario_with_source_requirement(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "<!-- R" in step, (
            "Step 6d must tag each derived scenario with a comment citing the "
            "source requirement (e.g. <!-- R24 -->)"
        )

    def test_step_6d_does_not_interleave_with_original_list(self):
        text = _load_prd_writer_text()
        step = _extract_step_6d(text)
        assert step, "Step 6d section not found"
        assert "interleave" in step or "renumber" in step, (
            "Step 6d must explicitly state it does not interleave with or "
            "renumber the original requirements list"
        )
