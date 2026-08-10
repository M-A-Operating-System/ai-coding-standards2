"""Conformance tests for the fix-now/defer-ok effort dimension on pr-reviewer findings.

Covers PRD issue #289: pr-reviewer must tag every finding with [fix-now] or
[defer-ok] and force REQUEST CHANGES on any [fix-now] finding; coder must treat
[fix-now] findings as Required feedback regardless of severity.

Gherkin scenarios traced:
  - test_a_trivially_fixable_low_finding_forces_a_fix_cycle
  - test_a_genuinely_subjective_low_finding_does_not_block
  - test_coder_treats_a_fix_now_finding_as_required_not_suggested
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
    m = re.search(r"## Step 10 .* Verdict\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
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
    """Scenario: A trivially-fixable Low finding forces a fix cycle."""

    def test_fix_now_tag_defined_in_consolidate(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert "[fix-now]" in consolidate, (
            "Step 9 Consolidate must define the [fix-now] effort tag"
        )

    def test_fix_now_rule_in_verdict(self):
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        fix_now_lines = [l.strip() for l in verdict.splitlines() if "[fix-now]" in l]
        assert fix_now_lines, (
            "Step 10 Verdict must have a rule line for [fix-now]-tagged findings"
        )

    def test_fix_now_verdict_is_request_changes(self):
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        fix_now_lines = [l.strip() for l in verdict.splitlines() if "[fix-now]" in l]
        assert fix_now_lines, "No [fix-now] rule line in Step 10"
        combined = " ".join(fix_now_lines)
        assert "REQUEST CHANGES" in combined or "REQUEST_CHANGES" in combined, (
            "The [fix-now] rule in Step 10 must map to REQUEST CHANGES; got: "
            f"{combined!r}"
        )

    def test_fix_now_verdict_is_severity_independent(self):
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        fix_now_lines = [l.strip() for l in verdict.splitlines() if "[fix-now]" in l]
        assert fix_now_lines, "No [fix-now] rule line in Step 10"
        combined = " ".join(fix_now_lines)
        assert re.search(r"regardless of severity", combined, re.IGNORECASE), (
            "The [fix-now] rule must state it applies regardless of severity; got: "
            f"{combined!r}"
        )

    def test_fix_now_rule_before_approve_rule(self):
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        lines = [l.strip() for l in verdict.splitlines() if l.strip().startswith("-")]
        fix_now_idx = next((i for i, l in enumerate(lines) if "[fix-now]" in l), None)
        approve_idx = next((i for i, l in enumerate(lines) if "APPROVE" in l), None)
        assert fix_now_idx is not None, "No [fix-now] bullet in Step 10"
        assert approve_idx is not None, "No APPROVE bullet in Step 10"
        assert fix_now_idx < approve_idx, (
            "[fix-now] rule must appear before the APPROVE rule in Step 10"
        )


class TestGenuinelySubjectiveLowFindingDoesNotBlock:
    """Scenario: A genuinely subjective Low finding does not block."""

    def test_defer_ok_tag_defined_in_consolidate(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert "[defer-ok]" in consolidate, (
            "Step 9 Consolidate must define the [defer-ok] effort tag"
        )

    def test_defer_ok_not_in_verdict_as_blocking(self):
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        defer_ok_lines = [l.strip() for l in verdict.splitlines() if "[defer-ok]" in l]
        for line in defer_ok_lines:
            assert "REQUEST CHANGES" not in line and "REQUEST_CHANGES" not in line, (
                "[defer-ok] must not appear on a REQUEST CHANGES verdict line; "
                f"got: {line!r}"
            )

    def test_subjective_findings_documented_as_defer_ok(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert re.search(r"subjective|style prefer", consolidate, re.IGNORECASE), (
            "Step 9 Consolidate must document that subjective/style findings are "
            "[defer-ok]"
        )

    def test_effort_tag_applied_to_every_finding(self):
        text = _load_pr_reviewer()
        consolidate = _extract_consolidate_section(text)
        assert re.search(r"required on every finding|every finding", consolidate, re.IGNORECASE), (
            "Step 9 Consolidate must require the effort tag on every finding"
        )


class TestCoderTreatsFixNowAsRequired:
    """Scenario: coder treats a fix-now finding as Required, not Suggested."""

    def test_fix_now_in_required_row(self):
        text = _load_coder()
        step10 = _extract_coder_step10(text)
        required_rows = [l for l in step10.splitlines() if "Required" in l]
        assert required_rows, "No Required row in coder.md Step 10"
        combined = " ".join(required_rows)
        assert "fix-now" in combined, (
            "coder.md Step 10 Required row must include [fix-now]-tagged findings; "
            f"got: {combined!r}"
        )

    def test_fix_now_not_suggested(self):
        text = _load_coder()
        step10 = _extract_coder_step10(text)
        suggested_rows = [l for l in step10.splitlines() if "Suggested" in l]
        combined = " ".join(suggested_rows)
        assert "fix-now" not in combined, (
            "[fix-now] must not appear in the Suggested row of coder.md Step 10; "
            f"got: {combined!r}"
        )

    def test_fix_now_required_regardless_of_severity(self):
        text = _load_coder()
        step10 = _extract_coder_step10(text)
        assert re.search(r"fix-now.*regardless of.*severity|regardless.*severity.*fix-now",
                         step10, re.IGNORECASE | re.DOTALL), (
            "coder.md Step 10 must state [fix-now] is Required regardless of severity"
        )

    def test_fix_now_cites_std_arch_006(self):
        text = _load_coder()
        step10 = _extract_coder_step10(text)
        assert "STD-ARCH-006" in step10, (
            "coder.md Step 10 must cite STD-ARCH-006 as the basis for [fix-now] Required rule"
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

    def test_fix_now_expressed_only_in_agent_prompts(self):
        pr_text = _load_pr_reviewer()
        coder_text = _load_coder()
        assert "fix-now" in pr_text, "pr-reviewer.md must contain fix-now"
        assert "fix-now" in coder_text, "coder.md must contain fix-now"

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

    def test_fix_now_verdict_rule_has_no_escalation_cap(self):
        text = _load_pr_reviewer()
        verdict = _extract_verdict_section(text)
        fix_now_lines = [l.strip() for l in verdict.splitlines() if "[fix-now]" in l]
        assert fix_now_lines, "No [fix-now] rule in Step 10"
        combined = " ".join(fix_now_lines)
        assert "max_cycles" not in combined and "budget" not in combined.lower(), (
            "[fix-now] verdict rule must not embed its own cycle cap -- "
            "the existing review_loop.max_cycles handles it"
        )
