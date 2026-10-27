"""Conformance tests for prd-writer agent.

Traces docs/features/prd-writer.md. Covers:
  - Step 7d: Gherkin backfill in augmentation mode (requirement coverage,
    not classification-band quotas)
  - Step 3/4: substantive-requirements routing and the outstanding-questions
    blocking gate
  - Step 6b/7b: the Release Notes section in both drafting modes
  - Step 7c/8a: the shared title-writing rule and its augmentation-mode
    meaning-preservation constraint
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PRD_WRITER_MD = REPO_ROOT / ".claude" / "agents" / "01_product_docs" / "prd-writer.md"


def _load_prd_writer_text() -> str:
    assert PRD_WRITER_MD.exists(), f"prd-writer agent file not found: {PRD_WRITER_MD}"
    return PRD_WRITER_MD.read_text()


def _extract_section(text: str, heading_pattern: str) -> str:
    """Extract a step/sub-step section's body, stopping at the next heading
    of equal or higher level."""
    match = re.search(
        heading_pattern + r"[^\n]*\n(.*?)(?=\n---\n|\n## Step |\n### \d|\Z)",
        text,
        re.DOTALL,
    )
    return match.group(1) if match else ""


def _extract_step_2(text: str) -> str:
    return _extract_section(text, r"## Step 2 ")


def _extract_step_3(text: str) -> str:
    return _extract_section(text, r"## Step 3 ")


def _extract_step_4(text: str) -> str:
    return _extract_section(text, r"## Step 4 ")


def _extract_step_6a(text: str) -> str:
    return _extract_section(text, r"### 6a")


def _extract_step_6b(text: str) -> str:
    return _extract_section(text, r"### 6b")


def _extract_step_7b(text: str) -> str:
    return _extract_section(text, r"### 7b")


def _extract_step_7c(text: str) -> str:
    return _extract_section(text, r"### 7c")


def _extract_step_7d(text: str) -> str:
    return _extract_section(text, r"### 7d")


def _extract_step_8a(text: str) -> str:
    return _extract_section(text, r"### 8a")


def _extract_frontmatter(text: str) -> str:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Step numbering: every top-level step is an integer; lettered sub-steps are
# always nested (### Na) under their parent step, never a sibling ## heading.
# ---------------------------------------------------------------------------

class TestStepNumbersAreIntegers:
    def test_no_lettered_top_level_steps(self):
        text = _load_prd_writer_text()
        assert not re.search(r"^## Step \d+[a-z]", text, re.MULTILINE), (
            "every top-level '## Step N' heading must use a bare integer -- "
            "a lettered top-level step (e.g. '## Step 3b') is a sibling "
            "numbering scheme the control-flow prose doesn't handle "
            "consistently; nest it as a '### Na' sub-step instead"
        )

    def test_lettered_sub_steps_are_nested_h3(self):
        text = _load_prd_writer_text()
        lettered = re.findall(r"^### (\d+[a-z])", text, re.MULTILINE)
        assert lettered, "expected at least one lettered sub-step (e.g. '### 6a')"

    def test_step_sequence_has_no_gaps_or_duplicates(self):
        text = _load_prd_writer_text()
        numbers = sorted(
            int(n) for n in re.findall(r"^## Step (\d+)", text, re.MULTILINE)
        )
        assert numbers == list(range(numbers[0], numbers[-1] + 1)), (
            f"top-level step numbers must be a contiguous integer sequence, got {numbers}"
        )


# ---------------------------------------------------------------------------
# Scenario: Technical specification without user stories is preserved /
# Scenario: Keywords do not force decomposition
# ---------------------------------------------------------------------------

class TestStep3RoutesOnSubstantiveRequirements:
    """Step 3 routes on substantive solution-level requirements, not on
    formatting signals (Gherkin/user-story presence) or decomposition
    keywords."""

    def test_step_3_defines_substantive_requirements_concretely(self):
        text = _load_prd_writer_text()
        step = _extract_step_3(text)
        assert step, "Step 3 section not found"
        assert "falsifiable constraint" in step, (
            "Step 3 must anchor 'substantive requirements' to a concrete, "
            "checkable test -- not pure judgement -- so routing stays "
            "consistent across runs"
        )

    def test_step_3_forbids_rewriting_on_absent_formatting_signal(self):
        text = _load_prd_writer_text()
        step = _extract_step_3(text)
        assert step, "Step 3 section not found"
        assert "formatting signal is absent" in step, (
            "Step 3 must forbid treating a missing formatting signal "
            "(no Gherkin/user stories) as grounds for a full rewrite"
        )

    def test_step_3_hands_off_explicitly_to_step_4(self):
        text = _load_prd_writer_text()
        step = _extract_step_3(text)
        assert step, "Step 3 section not found"
        assert "go to Step 4" in step, (
            "Step 3's decision must explicitly transition to Step 4 -- "
            "every other step in this prompt uses an explicit 'go to Step N' "
            "and Step 3 must not be the exception, or the blocking-question "
            "gate in Step 4 is never reached"
        )

    def test_step_5_decompose_does_not_use_keyword_list(self):
        text = _load_prd_writer_text()
        step = _extract_section(text, r"## Step 5 ")
        assert step, "Step 5 section not found"
        assert "rebuild" not in step and "redesign" not in step, (
            "Step 5's decompose/proceed decision must not key off specific "
            "keywords like 'rebuild' or 'redesign' in the issue body"
        )
        assert "solely on keywords" in step, (
            "Step 5 must explicitly forbid deciding to decompose solely on keywords"
        )


# ---------------------------------------------------------------------------
# Scenario: Material unanswered questions block the PRD /
# Scenario: Nonblocking questions remain visible /
# Scenario: Question handling uses existing orchestration
# ---------------------------------------------------------------------------

class TestStep4OutstandingQuestions:
    """Step 4 classifies unresolved questions as blocking or nonblocking and
    is reachable from every path through Step 3."""

    def test_step_4_exists(self):
        text = _load_prd_writer_text()
        assert "## Step 4 — Outstanding requirements questions" in text, (
            "prd-writer.md must contain a 'Step 4' section implementing "
            "the outstanding-questions gate"
        )

    def test_step_4_is_mandatory_for_every_path(self):
        text = _load_prd_writer_text()
        step = _extract_step_4(text)
        assert step, "Step 4 section not found"
        assert "Always run this step" in step, (
            "Step 4 must state it always runs regardless of which path "
            "Step 3 selected, or an agent reading literally could skip it"
        )

    def test_step_4_blocking_outcome_has_no_body_write(self):
        text = _load_prd_writer_text()
        step = _extract_step_4(text)
        assert step, "Step 4 section not found"
        assert 'outcome: "blocked"' in step
        assert "Do not include `body_write`" in step, (
            "a blocking question must not be accompanied by a body_write -- "
            "the PRD must not be submitted while a material question is open"
        )

    def test_step_4_nonblocking_outcome_continues_to_review(self):
        text = _load_prd_writer_text()
        step = _extract_step_4(text)
        assert step, "Step 4 section not found"
        assert "Nonblocking" in step
        assert "list it in the review artefact" in step, (
            "a nonblocking question must still surface in the review artefact output"
        )

    def test_step_4_forbids_direct_github_writes(self):
        text = _load_prd_writer_text()
        step = _extract_step_4(text)
        assert step, "Step 4 section not found"
        assert "Do not directly post Question Cards or modify the issue" in step, (
            "Step 4 must forbid the agent from posting comments or editing "
            "the issue directly -- the orchestrator owns all GitHub writes"
        )

    def test_step_4_hands_off_to_the_path_step_3_selected(self):
        text = _load_prd_writer_text()
        step = _extract_step_4(text)
        assert step, "Step 4 section not found"
        assert "proceed now to the path Step 3 selected" in step, (
            "Step 4 must explicitly send execution onward (Step 6 or Step 5) "
            "once no blocking question remains, or the agent has nowhere "
            "defined to go next"
        )

    def test_sub_issues_skip_step_4(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert re.search(r"Skip Steps[^.\n]*\b4\b", step), (
            "Step 2's sub-issue skip list must include Step 4 -- a sizer-"
            "created sub-issue's scope was already human-approved, so it "
            "should not be re-litigated through the outstanding-questions gate"
        )


# ---------------------------------------------------------------------------
# Scenario: Ambiguous feedback is surfaced
# ---------------------------------------------------------------------------

class TestAmbiguousFeedbackIsSurfaced:
    def test_step_0_routes_ambiguous_material_feedback_to_step_4(self):
        text = _load_prd_writer_text()
        step = _extract_section(text, r"## Step 0 ")
        assert step, "Step 0 section not found"
        assert "Step 4 blocked result" in step, (
            "Step 0 must route ambiguous, materially-scope-changing human "
            "feedback through Step 4's blocked result rather than guessing"
        )


# ---------------------------------------------------------------------------
# Scenario: A pre-specified issue with the wrong notation gets Gherkin
# backfilled / Existing Gherkin coverage is left alone / Backfill never
# invents requirements / Scenario count does not drive new requirements /
# Scenario maximum does not suppress missing coverage
# ---------------------------------------------------------------------------

class TestStep7dBackfillsByRequirementCoverage:
    """Step 7d derives Gherkin from requirement coverage, not a
    classification-band scenario count."""

    def test_step_7d_section_exists(self):
        text = _load_prd_writer_text()
        assert "### 7d" in text, (
            "prd-writer.md must contain a '### 7d' subsection implementing "
            "Gherkin backfill"
        )

    def test_step_7d_assesses_against_every_requirement(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "every distinct behavioral requirement" in step

    def test_step_7d_does_not_treat_classification_ranges_as_targets(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "classification ranges are not stopping conditions or generation targets" in step, (
            "Step 7d must explicitly disclaim classification-band minimum/"
            "maximum counts as drivers of how many scenarios it derives"
        )
        assert "Minimum scenarios" not in step and "Maximum scenarios" not in step, (
            "Step 7d must not carry its own classification-band min/max "
            "table -- that was the quota mechanism this redesign removed"
        )

    def test_step_7d_derives_smallest_covering_set(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "Derive only the smallest set of scenarios" in step
        assert "never invent requirements to fill a quota" in step

    def test_step_3_decision_notes_step_7d_applies_in_augmentation(self):
        text = _load_prd_writer_text()
        step = _extract_step_3(text)
        assert step, "Step 3 section not found"
        assert "Step 7" in step, (
            "Step 3's decision must reference Step 7 (augmentation mode) so "
            "readers understand Gherkin backfill still applies there"
        )

    def test_frontmatter_description_mentions_step_7d(self):
        text = _load_prd_writer_text()
        fm = _extract_frontmatter(text)
        assert fm, "Frontmatter not found"
        assert "7d" in fm, (
            "prd-writer.md frontmatter description must mention Step 7d "
            "so the agent's summary stays accurate"
        )


class TestStep7dCoverageSelfCheck:
    """Before signalling review, Step 7d must verify every enumerated
    requirement is cited by at least one scenario or an explicit
    structural/contract check, and run that check unconditionally."""

    def test_step_7d_has_a_coverage_self_check(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert re.search(r"coverage self-check", step, re.IGNORECASE)

    def test_self_check_runs_unconditionally(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert re.search(
            r"coverage\s+self-check\s+\(mandatory.*?run\s+unconditionally",
            step,
            re.IGNORECASE | re.DOTALL,
        ), (
            "the coverage self-check must be explicitly marked mandatory "
            "and unconditional, not implicitly skippable"
        )

    def test_self_check_compares_requirement_tags_to_cited_scenarios(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "requirement tag" in step and "cited" in step

    def test_self_check_requires_deriving_or_stating_gaps(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "derive it now" in step, (
            "a coverable behavioural gap must be derived before finishing, not just noted"
        )
        assert "artefact comment" in step, (
            "an uncoverable gap must be stated explicitly in the artefact comment"
        )

    def test_self_check_forbids_signalling_review_with_a_known_gap(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert re.search(r"do not signal.*outcome.*review.*gap", step, re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# Scenario: Non-behavioural requirements are not padded into scenarios /
# Backfill ... preserves any nonbehavioral requirements as explicit checks
# ---------------------------------------------------------------------------

class TestStep7dPreservesStructuralRequirements:
    """Step 7d must not discard structural/technical requirements, and must
    not force them into artificial user-visible scenarios -- it validates
    them with explicit structural or contract checks instead."""

    def test_step_7d_preserves_rather_than_discards(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "Preserve structural and technical requirements as explicit testable contracts" in step
        assert "Do not discard them" in step

    def test_step_7d_does_not_force_artificial_scenarios(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "force them into artificial user-visible scenarios" in step

    def test_coverage_self_check_covers_structural_requirements_too(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "covered by explicit contract/structural checks and must remain in the issue" in step


# ---------------------------------------------------------------------------
# Scenario: Sizer-created sub-issues are covered
# ---------------------------------------------------------------------------

class TestStep7dCoversSubIssues:
    """Step 2 must note that Step 7d applies to sizer-created sub-issues."""

    def test_step_2_references_step_7d_for_sub_issues(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert "Step 7d" in step, (
            "Step 2 sub-issue handling must reference Step 7d so sizer-"
            "created sub-issues also get Gherkin backfilled"
        )

    def test_step_2_explains_sub_issue_rationale(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert "sizer" in step.lower(), (
            "Step 2 must explain why Step 7d applies to sub-issues "
            "(sizer templates do not generate Gherkin)"
        )

    def test_step_2_sends_sub_issues_to_augmentation_mode(self):
        text = _load_prd_writer_text()
        step = _extract_step_2(text)
        assert step, "Step 2 section not found"
        assert "Step 7 (Augmentation mode)" in step


# ---------------------------------------------------------------------------
# Scenario: Already-approved PRDs are not silently rewritten
# ---------------------------------------------------------------------------

class TestStep7dNotRunOnAlreadyApproved:
    """Step 7d must guard against rewriting an already-approved spec."""

    def test_step_7d_has_approved_label_guard(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "ALREADY_APPROVED" in step

    def test_step_7d_guard_uses_prd_writer_approved_label(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "prd-writer:approved" in step

    def test_step_7d_guard_is_noop_and_skips_to_step_9(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "Step 7d is a no-op" in step
        assert "skip to **Step 9** immediately" in step


# ---------------------------------------------------------------------------
# Scenario: The derived section is clearly attributed and traceable
# ---------------------------------------------------------------------------

class TestStep7dAttributionAndTraceability:
    def test_step_7d_labels_section_as_derived_by_prd_writer(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "Derived by prd-writer" in step

    def test_step_7d_tags_each_scenario_with_source_requirement(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "<!-- R" in step

    def test_step_7d_does_not_interleave_with_original_list(self):
        text = _load_prd_writer_text()
        step = _extract_step_7d(text)
        assert step, "Step 7d section not found"
        assert "interleave" in step or "renumber" in step


# ---------------------------------------------------------------------------
# Scenario: New PRD begins with release-note summary / Existing
# specification gains release notes without losing requirements /
# Existing release notes are not duplicated
# ---------------------------------------------------------------------------

class TestReleaseNotesSection:
    def test_step_6b_places_release_notes_first(self):
        text = _load_prd_writer_text()
        step = _extract_step_6b(text)
        assert step, "Step 6b section not found"
        assert "### Release Notes" in step
        problem_pos = step.find("### Problem")
        notes_pos = step.find("### Release Notes")
        assert 0 <= notes_pos < problem_pos, (
            "Release Notes must come before the Problem section in the "
            "full-draft PRD template"
        )

    def test_step_6b_release_notes_scoped_to_supported_content(self):
        text = _load_prd_writer_text()
        step = _extract_step_6b(text)
        assert step, "Step 6b section not found"
        assert "do not invent requirements or repeat the detailed acceptance criteria" in step

    def test_step_7b_adds_release_notes_to_augmented_body(self):
        text = _load_prd_writer_text()
        step = _extract_step_7b(text)
        assert step, "Step 7b section not found"
        assert "### Release Notes" in step

    def test_step_7b_does_not_duplicate_existing_release_notes(self):
        text = _load_prd_writer_text()
        step = _extract_step_7b(text)
        assert step, "Step 7b section not found"
        assert "preserve it rather than duplicating it" in step


# ---------------------------------------------------------------------------
# Scenario: Issue title communicates the shipped outcome in release notes /
# Both processing modes use the same release-note title rule /
# Existing detailed title may be improved without losing meaning /
# Sizer-generated sub-issue titles remain canonical
# ---------------------------------------------------------------------------

class TestTitleWritingRule:
    def test_step_8a_defines_the_single_title_rule(self):
        text = _load_prd_writer_text()
        step = _extract_step_8a(text)
        assert step, "Step 8a section not found"
        assert "outcome-oriented sentence" in step
        assert "do not invent requirements or benefits" in step

    def test_step_7c_delegates_to_step_8a(self):
        text = _load_prd_writer_text()
        step = _extract_step_7c(text)
        assert step, "Step 7c section not found"
        assert "Step 8a" in step, (
            "augmentation mode's title step must apply the same rule Step 8a "
            "defines for the full-draft path, per the 'both modes share one "
            "title rule' design"
        )

    def test_step_7c_constrains_rewrite_to_preserve_meaning(self):
        text = _load_prd_writer_text()
        step = _extract_step_7c(text)
        assert step, "Step 7c section not found"
        assert re.search(r"may not narrow, broaden, or otherwise change what the title\s+claims", step), (
            "augmentation mode exists to preserve stakeholder content, so "
            "its title rewrite must be constrained to preserve meaning -- "
            "unlike the full-draft path, which is free to write any title"
        )

    def test_step_7c_exempts_sub_issue_titles(self):
        text = _load_prd_writer_text()
        step = _extract_step_7c(text)
        assert step, "Step 7c section not found"
        assert "skip the title change entirely" in step
        assert "canonical" in step


# ---------------------------------------------------------------------------
# Scenario: Material questions are returned without direct comments
# ---------------------------------------------------------------------------

class TestBehaviourRulesCoverQuestions:
    def test_behaviour_rules_reference_step_4(self):
        text = _load_prd_writer_text()
        rules = text.split("## Behaviour rules", 1)[-1]
        assert "Step 4" in rules, (
            "the Behaviour rules section must reference Step 4's "
            "blocking-question mechanism"
        )
