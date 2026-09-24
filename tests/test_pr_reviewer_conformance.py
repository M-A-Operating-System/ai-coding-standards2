"""Conformance tests for the focused single-pass pr-reviewer prompt."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PROMPT = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
PIPELINE = REPO_ROOT / "pipeline" / "pipeline.json"


def _text() -> str:
    return PROMPT.read_text()


def test_review_is_one_pass_across_lenses_without_personas():
    """The four lenses (Step 2) are checkpoints within a single model
    invocation -- no separate context per lens, no persona flavor text --
    not a return to the four-persona structure this PR removed."""
    text = _text()
    assert "in one pass" in text
    assert "four lenses" in text
    assert "do not re-fetch evidence or\nrestart between lenses" in text
    assert "Defensive Programmer" not in text
    assert "Security Analyst" not in text
    assert "QA Engineer" not in text
    assert "Standards Compliance" not in text


def test_review_includes_a_verification_step():
    """Step 3: a cheap, single-context self-check against the same evidence
    -- not a second independent reviewer, not new research -- that a draft
    finding must survive before Step 4 reports it."""
    text = _text()
    assert "Verify each draft finding" in text
    assert "drop the finding" in text
    assert "introduce no new findings here" in text


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
