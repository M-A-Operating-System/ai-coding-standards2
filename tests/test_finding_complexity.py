"""Conformance tests for the Low-severity finding complexity dimension
(issue #506) -- STD-ARCH-007's inline-fixable/issue-worthy bar, made
explicit per finding, plus the new middle tier (flagged for a human
decision) STD-ARCH-007 as written does not have.
"""
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
SCHEMA_PATH = REPO_ROOT / "pipeline" / "schemas" / "pr-review.schema.json"
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _finding(**overrides):
    base = {
        "id": "RV-001", "title": "t", "severity": "Low", "category": "correctness",
        "confidence": 1.0, "evidence": "e", "fix": "f",
    }
    base.update(overrides)
    return {"head_sha": "abc123", "findings": [base]}


class TestSchemaRequiresComplexityForLowSeverity:
    def test_complexity_property_accepts_the_three_levels(self):
        properties = _schema()["definitions"]["Finding"]["properties"]
        assert properties["complexity"]["enum"] == ["low", "medium", "high"]

    def test_low_severity_finding_without_complexity_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        review = _finding(severity="Low")
        errors = list(validator.iter_errors(review))
        assert errors, "a Low finding with no complexity must fail schema validation"

    def test_low_severity_finding_with_complexity_validates(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        review = _finding(severity="Low", complexity="medium")
        errors = list(validator.iter_errors(review))
        assert not errors, f"unexpected: {[e.message for e in errors]}"

    def test_non_low_severity_finding_does_not_require_complexity(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        review = _finding(severity="Critical")
        errors = list(validator.iter_errors(review))
        assert not errors, f"unexpected: {[e.message for e in errors]}"

    def test_unrecognised_complexity_value_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        review = _finding(severity="Low", complexity="urgent")
        errors = list(validator.iter_errors(review))
        assert errors

    def test_category_standard_requirement_still_applies_alongside_complexity(self):
        """The allOf composition must not have dropped the pre-existing
        category=="standard" -> requires "standard" rule when the second
        if/then for complexity was added."""
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        review = _finding(severity="Critical", category="standard")
        errors = list(validator.iter_errors(review))
        assert errors, "category: standard must still require the standard field"


class TestPrReviewerDocumentsComplexity:
    def _text(self) -> str:
        return PR_REVIEWER.read_text()

    def test_complexity_field_documented_in_finding_shape(self):
        assert '"complexity"' in self._text()

    def test_rubric_cites_std_arch_007(self):
        assert "STD-ARCH-007" in self._text()

    def test_rubric_defines_all_three_levels(self):
        text = self._text()
        assert "`low`" in text and "`medium`" in text and "`high`" in text

    def test_rubric_states_complexity_required_only_for_low_severity(self):
        text = self._text()
        assert "required only for severity Low" in text or "required only on a `severity: Low`" in text


class TestPipelineDeclaresCreatesIssues:
    def test_pr_reviewer_step_declares_creates_issues(self):
        pipeline = json.loads(PIPELINE_JSON.read_text())
        entry = next(
            step
            for flow in pipeline["flows"].values()
            for step in flow["steps"]
            if step["agent"] == "03_execute/pr-reviewer"
        )
        assert entry["expected_effect"]["creates_issues"] is True
