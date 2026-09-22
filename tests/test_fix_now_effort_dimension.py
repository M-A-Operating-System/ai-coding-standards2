"""Conformance tests for the fix-now/defer-ok effort dimension on pr-reviewer findings.

Originally covered PRD issue #289: pr-reviewer must tag every finding
[fix-now]/[defer-ok] and Step 10's rule table must force REQUEST CHANGES on
any [fix-now] finding; coder must treat a [fix-now] finding as Required
regardless of severity, read off that same rule table.

Issue #512 Part 2 moves the actual enforcement into code
(review_outcome.finding_blocks: a defer-ok finding blocks unless it is Low
or Informational severity -- tested in
tests/test_review_outcome.py::TestFindingBlocks::test_defer_ok_*). Step 10
is advisory prose now, not a rule table, so pr-reviewer.md still defines the
`effort` field but no longer states a REQUEST CHANGES rule for it; coder.md
no longer reads `effort` at all -- it reads the orchestrator-computed
`blocking` field the rendered artefact already carries (see
tests/test_review_outcome.py::TestRenderReviewComment::
test_json_block_findings_carry_blocking_field). These tests were rewritten
accordingly.

Gherkin scenarios traced:
  - test_a_trivially_fixable_low_finding_forces_a_fix_cycle (now: code, not prompt)
  - test_a_genuinely_subjective_low_finding_does_not_block (now: code, not prompt)
  - test_coder_treats_a_blocking_finding_as_required_not_suggested
  - test_no_new_pipeline_machinery_is_introduced
  - test_cycle_budget_is_not_abused
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
CODER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "coder.md"
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"
ORCHESTRATOR_PY = REPO_ROOT / "pipeline" / "pipeline_orchestrator.py"


def _load_pr_reviewer() -> str:
    assert PR_REVIEWER_MD.exists(), f"not found: {PR_REVIEWER_MD}"
    return PR_REVIEWER_MD.read_text()


def _load_coder() -> str:
    assert CODER_MD.exists(), f"not found: {CODER_MD}"
    return CODER_MD.read_text()


# Duplicates test_pr_reviewer_verdict._extract_verdict_section to keep this
# module self-contained and independent of sibling test module internals.
def _extract_verdict_section(text: str) -> str:
    m = re.search(r"## Step 10 .* Verdict[^\n]*\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    assert m, "Step 10 Verdict section not found in pr-reviewer.md"
    return m.group(1)


def _extract_consolidate_section(text: str) -> str:
    m = re.search(r"## Step 9 .* Consolidate\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    assert m, "Step 9 Consolidate section not found in pr-reviewer.md"
    return m.group(1)


def _extract_coder_step10(text: str) -> str:
    m = re.search(r"## Step 10 .* Categori.e the feedback\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    assert m, "Step 10 Categorise section not found in coder.md"
    return m.group(1)


class TestTriviallyFixableLowFindingForcesFixCycle:
    """Scenario: A trivially-fixable Low finding forces a fix cycle.

    Enforced in code now (issue #512): review_outcome.finding_blocks blocks
    a fix-now finding unless one of its other escapes applies (improvement
    category, verified ADR exception, non-Critical below 0.8 confidence) --
    see test_review_outcome.py::TestFindingBlocks. This class checks only
    that pr-reviewer.md still defines the effort field the rule reads.
    """

    def test_fix_now_tag_defined_in_consolidate(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert "fix-now" in consolidate, (
            "Step 9 Consolidate must define the fix-now effort value"
        )

    def test_fix_now_documented_as_severity_independent(self):
        """The historical guarantee (fix-now forces a cycle regardless of
        severity) is now implicit in finding_blocks's rule shape -- a
        defer-ok finding is the ONLY effort value with a severity-gated
        exemption, so fix-now has none. Check Step 9 documents that shape."""
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert re.search(r"defer-ok.*severity|severity.*defer-ok", consolidate,
                         re.IGNORECASE | re.DOTALL), (
            "Step 9 must document that only defer-ok findings get a "
            "severity-gated exemption -- fix-now findings have none"
        )


class TestGenuinelySubjectiveLowFindingDoesNotBlock:
    """Scenario: A genuinely subjective Low finding does not block.

    Enforced in code now (issue #512): a defer-ok finding at Low or
    Informational severity is non-blocking (review_outcome.finding_blocks;
    test_defer_ok_low_severity_does_not_block). This class checks only that
    pr-reviewer.md still defines the effort field and category the rule
    reads.
    """

    def test_defer_ok_tag_defined_in_consolidate(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert "defer-ok" in consolidate, (
            "Step 9 Consolidate must define the defer-ok effort value"
        )

    def test_subjective_findings_documented_as_improvement_category(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert re.search(r"subjective|style prefer", consolidate, re.IGNORECASE), (
            "Step 9 Consolidate must document that subjective/style findings "
            "are category: improvement (never block, issue #512)"
        )

    def test_effort_field_documented_on_every_finding(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert '"effort"' in consolidate, (
            "Step 9 Consolidate's finding object must include the effort field"
        )


class TestCoderTreatsBlockingFindingAsRequired:
    """Scenario: coder treats a blocking finding as Required, not Suggested.

    Issue #512 Part 2: coder.md no longer reads the effort tag at all --
    it reads the orchestrator-computed `blocking` field the rendered
    artefact already carries (test_review_outcome.py::TestRenderReviewComment::
    test_json_block_findings_carry_blocking_field), so Required is never
    something coder re-derives from severity or effort itself.
    """

    def test_blocking_in_required_row(self):
        text = _load_coder()
        step10 = _extract_coder_step10(text)
        required_rows = [l for l in step10.splitlines() if "Required" in l]
        assert required_rows, "No Required row in coder.md Step 10"
        combined = " ".join(required_rows)
        assert "blocking" in combined, (
            "coder.md Step 10 Required row must include findings the "
            f"orchestrator marked blocking; got: {combined!r}"
        )

    def test_blocking_true_not_suggested(self):
        text = _load_coder()
        step10 = _extract_coder_step10(text)
        suggested_rows = [l for l in step10.splitlines() if "Suggested" in l]
        combined = " ".join(suggested_rows)
        assert "blocking: true" not in combined, (
            "'blocking: true' must not appear in the Suggested row of coder.md "
            f"Step 10; got: {combined!r}"
        )

    def test_step10_states_blocking_is_orchestrator_computed(self):
        text = _load_coder()
        step10 = _extract_coder_step10(text)
        assert re.search(r"orchestrator.*comput", step10, re.IGNORECASE), (
            "coder.md Step 10 must state that the blocking field is the "
            "orchestrator's own computation, not something coder re-derives"
        )

    def test_step9_parses_blocking_field_from_json_block(self):
        text = _load_coder()
        step9_match = re.search(r"## Step 9 .* Read all review feedback(.+?)(?=\n## Step 9a|\Z)",
                                text, re.DOTALL)
        assert step9_match, "Step 9 section not found in coder.md"
        step9 = step9_match.group(1)
        assert '.blocking == true' in step9, (
            "coder.md Step 9 must filter the parsed review JSON on "
            "blocking == true, not re-derive it from severity or effort"
        )


class TestNoNewPipelineMachineryIntroduced:
    """Scenario: No new pipeline machinery is introduced."""

    def test_pipeline_json_unchanged(self):
        pipeline_text = PIPELINE_JSON.read_text()
        assert "fix-now" not in pipeline_text and "fix_now" not in pipeline_text, (
            "pipeline.json must not contain fix-now/fix_now machinery -- "
            "the fix-now mechanism is expressed in agent prompts only"
        )

    def test_orchestrator_unchanged(self):
        if not ORCHESTRATOR_PY.exists():
            pytest.skip("pipeline_orchestrator.py not found")
        orch_text = ORCHESTRATOR_PY.read_text()
        assert "fix-now" not in orch_text and "fix_now" not in orch_text, (
            "pipeline_orchestrator.py must not contain fix-now/fix_now machinery"
        )

    def test_fix_now_expressed_only_in_pr_reviewer_prompt(self):
        """coder.md no longer needs to know about the fix-now/defer-ok effort
        tag at all (issue #512) -- it reads the orchestrator-computed
        `blocking` field instead, so only pr-reviewer.md (which produces
        `effort`) still mentions it."""
        pr_text = _load_pr_reviewer()
        assert "fix-now" in pr_text, "pr-reviewer.md must contain fix-now"

    def test_pipeline_json_max_cycles_present(self):
        pipeline = json.loads(PIPELINE_JSON.read_text())
        raw = json.dumps(pipeline)
        assert "max_cycles" in raw, (
            "pipeline.json must still contain max_cycles -- the existing review_loop "
            "is reused unchanged"
        )


class TestCycleBudgetIsNotAbused:
    """Scenario: Cycle budget is not abused."""

    def test_no_new_cycle_counter_in_pr_reviewer(self):
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        assert "fix_now_count" not in verdict and "fix_now_cycles" not in verdict, (
            "Step 10 must not introduce a new fix-now cycle counter"
        )

    def test_consolidate_dedup_mechanism_still_present(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert re.search(r"cross-persona agreement|merge into one entry", consolidate,
                         re.IGNORECASE), (
            "Step 9 Consolidate dedup (cross-persona merge) must still be present -- "
            "it handles re-review idempotency"
        )

    def test_verdict_section_has_no_escalation_cap(self):
        """Step 10 is advisory prose now (issue #512) -- it must not embed
        its own cycle cap either; the existing review_loop.max_cycles in
        pipeline.json handles it, unchanged."""
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        assert "max_cycles" not in verdict and "budget" not in verdict.lower(), (
            "Step 10 must not embed its own cycle cap -- "
            "the existing review_loop.max_cycles handles it"
        )
