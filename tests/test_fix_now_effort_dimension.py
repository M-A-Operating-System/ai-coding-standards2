"""Conformance tests for retiring the obsolete fix-now/defer-ok finding
effort dimension. Issue #506 later reintroduced `effort` with different
semantics (simple/medium/complex, scoped to `category: "improvement"`
only) -- these tests guard against the old two-value contract coming back,
not against the field name itself."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
SCHEMA = REPO_ROOT / "pipeline" / "schemas" / "pr-review.schema.json"
OUTCOME = REPO_ROOT / "pipeline" / "review_outcome.py"
CODER = REPO_ROOT / ".claude" / "agents" / "03_execute" / "coder.md"


def test_prompt_does_not_reintroduce_fix_now_defer_ok():
    text = PR_REVIEWER.read_text()
    assert "fix-now" not in text
    assert "defer-ok" not in text


def test_schema_effort_enum_excludes_obsolete_values():
    finding_properties = json.loads(SCHEMA.read_text())["definitions"]["Finding"]["properties"]
    assert set(finding_properties["effort"]["enum"]) == {"simple", "medium", "complex"}


def test_outcome_does_not_reintroduce_fix_now_defer_ok():
    text = OUTCOME.read_text()
    assert "fix-now" not in text
    assert "defer-ok" not in text


def test_coder_uses_orchestrator_computed_blocking_field():
    text = CODER.read_text()
    assert ".blocking == true" in text
    assert "orchestrator" in text and "computed" in text
