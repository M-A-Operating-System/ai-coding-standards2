"""Conformance tests for pr-reviewer's structured findings contract."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PROMPT = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
PIPELINE = REPO_ROOT / "pipeline" / "pipeline.json"


def _text() -> str:
    return PROMPT.read_text()


def _entry() -> dict:
    pipeline = json.loads(PIPELINE.read_text())
    return next(
        step
        for flow in pipeline["flows"].values()
        for step in flow["steps"]
        if step["agent"] == "03_execute/pr-reviewer"
    )


def test_pipeline_keeps_code_computed_outcome_policy():
    policy = _entry()["outcome_policy"]
    assert policy["kind"] == "review_findings"
    assert policy["require_head_match"] is True
    assert (REPO_ROOT / policy["schema"]).exists()


def test_prompt_uses_pr_head_evidence():
    text = _text()
    assert "$PR_HEAD_SHA" in text
    assert "read_pr_file" in text
    assert "only sources of truth" in text


def test_prompt_defines_structured_findings():
    text = _text()
    for field in ("RV-001", '"severity"', '"category"', '"confidence"',
                  '"evidence"', '"fix"'):
        assert field in text


def test_prompt_writes_review_result_without_advisory_verdict():
    text = _text()
    assert '"review"' in text and '"head_sha"' in text and '"findings"' in text
    assert '"verdict"' not in text
    assert '"output"' not in text


def test_prompt_does_not_reintroduce_fix_now_defer_ok():
    text = _text()
    assert "fix-now" not in text
    assert "defer-ok" not in text
