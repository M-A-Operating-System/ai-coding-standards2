"""Conformance tests for the defect/improvement finding taxonomy (issue
#506) -- category is the fundamental classification; `type` narrows a
defect's technical area, `effort` narrows an improvement's disposition.
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


def _review(finding: dict) -> dict:
    return {"head_sha": "abc123", "findings": [finding]}


def _defect(**overrides):
    base = {
        "id": "RV-001", "title": "t", "category": "defect", "type": "correctness",
        "severity": "High", "confidence": 1.0, "evidence": "e", "fix": "f",
    }
    base.update(overrides)
    return base


def _improvement(**overrides):
    base = {
        "id": "RV-002", "title": "t", "category": "improvement", "effort": "simple",
        "confidence": 1.0, "evidence": "e", "fix": "f",
    }
    base.update(overrides)
    return base


class TestSchemaEnforcesDefectImprovementShapes:
    def test_category_enum_is_defect_or_improvement(self):
        properties = _schema()["definitions"]["Finding"]["properties"]
        assert properties["category"]["enum"] == ["defect", "improvement"]

    def test_type_enum_covers_technical_areas(self):
        properties = _schema()["definitions"]["Finding"]["properties"]
        assert properties["type"]["enum"] == [
            "correctness", "spec", "security", "tests", "standard", "consistency",
        ]

    def test_effort_enum_has_three_levels(self):
        properties = _schema()["definitions"]["Finding"]["properties"]
        assert properties["effort"]["enum"] == ["simple", "medium", "complex"]

    def test_valid_defect_validates(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors(_review(_defect())))
        assert not errors, f"unexpected: {[e.message for e in errors]}"

    def test_valid_improvement_validates(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors(_review(_improvement())))
        assert not errors, f"unexpected: {[e.message for e in errors]}"

    def test_defect_without_type_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        f = _defect()
        del f["type"]
        errors = list(validator.iter_errors(_review(f)))
        assert errors, "a defect without type must fail schema validation"

    def test_defect_without_severity_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        f = _defect()
        del f["severity"]
        errors = list(validator.iter_errors(_review(f)))
        assert errors, "a defect without severity must fail schema validation"

    def test_defect_with_effort_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors(_review(_defect(effort="simple"))))
        assert errors, "a defect must not carry effort"

    def test_improvement_without_effort_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        f = _improvement()
        del f["effort"]
        errors = list(validator.iter_errors(_review(f)))
        assert errors, "an improvement without effort must fail schema validation"

    def test_improvement_with_severity_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors(_review(_improvement(severity="Critical"))))
        assert errors, "an improvement must not carry severity"

    def test_improvement_with_type_fails_validation(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors(_review(_improvement(type="correctness"))))
        assert errors, "an improvement must not carry type"

    def test_obsolete_category_values_are_rejected(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        for old_category in ("correctness", "spec", "security", "tests", "standard", "consistency"):
            f = _defect(category=old_category)
            errors = list(validator.iter_errors(_review(f)))
            assert errors, f"obsolete top-level category {old_category!r} must be rejected"

    def test_obsolete_complexity_field_is_rejected(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors(_review(_defect(severity="Low", complexity="low"))))
        assert errors, "the obsolete complexity field must be rejected"

    def test_defect_type_standard_requires_standard_field(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        f = _defect(type="standard")
        errors = list(validator.iter_errors(_review(f)))
        assert errors, "type: standard must still require the standard field"

    def test_defect_type_standard_with_standard_field_validates(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        f = _defect(type="standard", standard="STD-ARCH-001")
        errors = list(validator.iter_errors(_review(f)))
        assert not errors, f"unexpected: {[e.message for e in errors]}"


class TestPrReviewerDocumentsDefectImprovement:
    def _text(self) -> str:
        return PR_REVIEWER.read_text()

    def test_category_defect_and_improvement_documented(self):
        text = self._text()
        assert '"category": "defect"' in text
        assert '"category": "improvement"' in text

    def test_effort_levels_documented(self):
        text = self._text()
        assert "`simple`" in text and "`medium`" in text and "`complex`" in text

    def test_defect_never_carries_effort_stated(self):
        text = self._text()
        assert "never apply `effort` to a defect" in text

    def test_no_obsolete_complexity_field(self):
        assert '"complexity"' not in self._text()


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
