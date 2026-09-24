"""Conformance tests for the focused single-pass pr-reviewer prompt."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PROMPT = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
PIPELINE = REPO_ROOT / "pipeline" / "pipeline.json"


def _text() -> str:
    return PROMPT.read_text()


def test_severity_escalation_and_no_escalation_do_not_both_appear():
    """Step 2 once said corroboration escalates severity by one level while
    Step 4 said corroboration does not automatically raise it -- a direct
    contradiction. Severity must be based on technical impact only, and
    corroboration may inform confidence instead."""
    text = _text()
    assert "escalate its severity" not in text
    assert "corroboration across lenses does not" in text or "corroboration does not" in text


def test_review_is_one_integrated_examination_without_personas():
    """The four lenses (Step 2) are coverage criteria applied within a
    single integrated examination -- not a full-diff sweep per lens, no
    separate context per lens, no persona flavor text -- not a return to
    the four-persona structure this PR removed."""
    text = _text()
    assert "one integrated examination" in text or "one integrated pass" in text
    assert "four lenses" in text
    assert "restart the review, refetch the same evidence" in text
    assert "sweep the diff once per lens" not in text
    assert "Defensive Programmer" not in text
    assert "Security Analyst" not in text
    assert "QA Engineer" not in text
    assert "Standards Compliance" not in text


def test_review_includes_a_verification_step():
    """Step 3: a targeted self-check against evidence already gathered --
    not an unrestricted second review of the entire PR -- that a draft
    finding must survive before Step 4 reports it. A genuinely new concrete
    defect surfaced while verifying is recorded, not suppressed."""
    text = _text()
    assert "Verify each draft finding" in text
    assert "drop the finding" in text
    assert "not an\nunrestricted second review of the entire PR" in text or \
        "not an unrestricted second review of the entire PR" in text
    assert "record and verify that defect too rather than suppressing it" in text


def test_prompt_keeps_required_review_inputs():
    text = _text()
    assert "approved PDD" in text
    assert "selected standards" in text
    assert "ADRs" in text
    assert "PR-head" in text


def test_prompt_removes_redundant_state_and_review_work():
    text = _text()
    assert "MERGEABLE=" not in text
    assert "HUMAN_BLOCK_REVIEWERS" not in text
    assert "PRIOR=" not in text
    assert "derive a verdict" in text
    assert "Do not load every standard" in text
    assert "Do not manually reproduce schema validation" in text


def test_prompt_leaves_human_review_state_to_orchestrator():
    text = _text()
    assert "checks current human-review state" in text
    assert "Never edit PR or issue content, labels, review state, or PR state" in text


def test_result_json_remains_required():
    text = _text()
    assert "$AI_AGILE_SCRATCH/result.json" in text
    assert '"review"' in text


def test_permissions_model_is_unchanged_and_still_allows_github_reads():
    pipeline = json.loads(PIPELINE.read_text())
    step = next(
        step
        for flow in pipeline["flows"].values()
        for step in flow["steps"]
        if step["agent"] == "03_execute/pr-reviewer"
    )
    assert "Bash(gh api *)" in step.get("extra_allowedTools", [])
