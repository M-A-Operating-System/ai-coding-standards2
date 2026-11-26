"""Tests for pipeline/issue_audit_outcome.py (issue #743).

Gherkin scenarios traced (issue #743):
  - Valid audit object passes schema validation
  - Non-unverifiable evidence item without citation fails schema validation
  - Unverifiable evidence item without citation passes schema validation
  - Verdict OBSOLETE at exactly 0.85 confidence threshold
  - Verdict STILL-VALID just below 0.85 confidence threshold
  - Verdict SUPERSEDED-BY-#N when a superseding issue is cited
  - Verdict NEEDS-HUMAN-REVIEW for conflicting evidence
  - Batch selection interleaves never-reviewed and reviewed issues by single age key
"""
import json
import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from issue_audit_outcome import (
    CLOSING_THRESHOLD,
    NEEDS_HUMAN_REVIEW,
    OBSOLETE,
    STILL_VALID,
    batch_sort_key,
    derive_audit_verdict,
    select_batch,
)

SCHEMA_PATH = Path(__file__).parent.parent / "pipeline" / "schemas" / "issue-audit.schema.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _audit(evidence: list) -> dict:
    return {"issue_number": 100, "evidence": evidence}


def _item(**overrides):
    base = {
        "type": "code-removed",
        "confidence": 0.9,
        "citation": "src/foo.py:42",
        "excerpt": "function foo was deleted",
    }
    base.update(overrides)
    return base


class TestSchema:
    def test_valid_audit_object_passes(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors(_audit([_item()])))
        assert errors == []

    def test_non_unverifiable_without_citation_fails(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        item = _item()
        del item["citation"]
        errors = list(validator.iter_errors(_audit([item])))
        assert errors != []

    def test_unverifiable_without_citation_passes(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        item = {"type": "unverifiable", "confidence": 0.5, "excerpt": "needs live repro"}
        errors = list(validator.iter_errors(_audit([item])))
        assert errors == []

    def test_type_enum_covers_all_six_values(self):
        types = _schema()["definitions"]["EvidenceItem"]["properties"]["type"]["enum"]
        assert set(types) == {
            "code-removed", "code-changed", "merged-fix",
            "superseding-issue", "contradicted", "unverifiable",
        }

    def test_missing_issue_number_fails(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors({"evidence": []}))
        assert errors != []

    def test_missing_evidence_fails(self):
        jsonschema = pytest.importorskip("jsonschema")
        validator = jsonschema.Draft7Validator(_schema())
        errors = list(validator.iter_errors({"issue_number": 1}))
        assert errors != []


class TestDeriveAuditVerdict:
    def test_obsolete_at_exactly_threshold(self):
        evidence = [_item(type="code-removed", confidence=CLOSING_THRESHOLD)]
        assert derive_audit_verdict(evidence) == OBSOLETE

    def test_needs_human_review_just_below_threshold(self):
        """Just below 0.85: closing item does not clear the bar; no contradicted
        item is present either, so the result is NEEDS-HUMAN-REVIEW (rule 4:
        every item below the confidence threshold)."""
        evidence = [_item(type="code-removed", confidence=CLOSING_THRESHOLD - 0.001)]
        assert derive_audit_verdict(evidence) == NEEDS_HUMAN_REVIEW

    def test_obsolete_code_changed(self):
        evidence = [_item(type="code-changed", confidence=0.9)]
        assert derive_audit_verdict(evidence) == OBSOLETE

    def test_obsolete_merged_fix(self):
        evidence = [_item(type="merged-fix", confidence=1.0, citation="abc123")]
        assert derive_audit_verdict(evidence) == OBSOLETE

    def test_superseded_by_n(self):
        evidence = [
            {
                "type": "superseding-issue",
                "confidence": 0.9,
                "citation": "754",
                "excerpt": "issue #754 covers this fully",
            }
        ]
        verdict = derive_audit_verdict(evidence)
        assert verdict == "SUPERSEDED-BY-#754"

    def test_superseded_citation_with_hash_prefix(self):
        evidence = [
            {
                "type": "superseding-issue",
                "confidence": 0.9,
                "citation": "#820",
                "excerpt": "superseded by #820",
            }
        ]
        assert derive_audit_verdict(evidence) == "SUPERSEDED-BY-#820"

    def test_still_valid_contradicted_above_threshold(self):
        evidence = [_item(type="contradicted", confidence=0.9)]
        assert derive_audit_verdict(evidence) == STILL_VALID

    def test_needs_human_review_all_below_threshold(self):
        evidence = [_item(type="code-removed", confidence=0.5)]
        assert derive_audit_verdict(evidence) == NEEDS_HUMAN_REVIEW

    def test_needs_human_review_unverifiable_only(self):
        evidence = [{"type": "unverifiable", "confidence": 0.9, "excerpt": "requires live repro"}]
        assert derive_audit_verdict(evidence) == NEEDS_HUMAN_REVIEW

    def test_needs_human_review_conflicting_evidence(self):
        """Conflicting high-confidence signals must not close the issue."""
        evidence = [
            _item(type="code-removed", confidence=0.9),
            _item(type="contradicted", confidence=0.9),
        ]
        assert derive_audit_verdict(evidence) == NEEDS_HUMAN_REVIEW

    def test_needs_human_review_conflicting_superseding_and_contradicted(self):
        evidence = [
            {
                "type": "superseding-issue",
                "confidence": 0.9,
                "citation": "754",
                "excerpt": "...",
            },
            _item(type="contradicted", confidence=0.9),
        ]
        assert derive_audit_verdict(evidence) == NEEDS_HUMAN_REVIEW

    def test_needs_human_review_empty_evidence(self):
        assert derive_audit_verdict([]) == NEEDS_HUMAN_REVIEW

    def test_obsolete_not_blocked_by_low_confidence_contradicted(self):
        """A contradicted item well below the threshold does not block OBSOLETE."""
        evidence = [
            _item(type="code-removed", confidence=0.9),
            _item(type="contradicted", confidence=0.3),
        ]
        assert derive_audit_verdict(evidence) == OBSOLETE

    def test_superseded_not_returned_when_obsolete_applies(self):
        """When closing-type >= threshold and superseding-issue >= threshold
        and no contradicted >= threshold, OBSOLETE takes priority per rule 1."""
        evidence = [
            _item(type="merged-fix", confidence=0.9),
            {
                "type": "superseding-issue",
                "confidence": 0.9,
                "citation": "754",
                "excerpt": "...",
            },
        ]
        assert derive_audit_verdict(evidence) == OBSOLETE


class TestBatchSelection:
    def _issue(self, number, created_at, labels=None):
        return {
            "number": number,
            "created_at": created_at,
            "labels": labels or [],
        }

    def _reviewed_label(self, date):
        return f"issue-obsolescence-audit:reviewed-{date}"

    def test_never_reviewed_uses_created_at_as_sort_key(self):
        issue = self._issue(1, "2024-01-15")
        assert batch_sort_key(issue) == "2024-01-15"

    def test_reviewed_issue_uses_label_date_as_sort_key(self):
        issue = self._issue(2, "2023-01-01", labels=[self._reviewed_label("2024-03-10")])
        assert batch_sort_key(issue) == "2024-03-10"

    def test_reviewed_label_takes_precedence_over_created_at(self):
        issue = self._issue(3, "2023-01-01", labels=[self._reviewed_label("2024-05-01")])
        key = batch_sort_key(issue)
        assert key == "2024-05-01"
        assert key != "2023-01-01"

    def test_single_key_sort_interleaves_never_reviewed_and_reviewed(self):
        """Never-reviewed issues sort by their own age, not ahead of all reviewed
        issues -- the single-key rule from issue #741 (no two-tier bucketing).
        """
        # A: never-reviewed, oldest (2024-01-01) -> key 2024-01-01
        issue_a = self._issue(10, "2024-01-01")
        # B: reviewed 2024-02-15 -> key 2024-02-15
        issue_b = self._issue(20, "2023-06-01", labels=[self._reviewed_label("2024-02-15")])
        # C: reviewed 2024-01-20 -> key 2024-01-20
        issue_c = self._issue(30, "2023-05-01", labels=[self._reviewed_label("2024-01-20")])
        # D: never-reviewed, newest (2024-03-01) -> key 2024-03-01
        issue_d = self._issue(40, "2024-03-01")

        batch = select_batch([issue_d, issue_b, issue_a, issue_c])

        # Expected order: A (2024-01-01), C (2024-01-20), B (2024-02-15), D (2024-03-01)
        assert [i["number"] for i in batch] == [10, 30, 20, 40]

    def test_never_reviewed_old_sorts_before_reviewed_newer(self):
        """A never-reviewed issue created before a reviewed issue's reviewed-* date
        sorts ahead of that reviewed issue (the core single-key guarantee)."""
        old_never_reviewed = self._issue(1, "2024-01-01")
        newer_reviewed = self._issue(2, "2023-01-01", labels=[self._reviewed_label("2024-02-01")])

        batch = select_batch([newer_reviewed, old_never_reviewed])
        assert batch[0]["number"] == 1

    def test_never_reviewed_new_sorts_behind_reviewed_older(self):
        """A never-reviewed issue created after a reviewed issue's reviewed-* date
        sorts behind that reviewed issue."""
        reviewed_old = self._issue(1, "2022-01-01", labels=[self._reviewed_label("2024-01-10")])
        newer_never_reviewed = self._issue(2, "2024-02-01")

        batch = select_batch([newer_never_reviewed, reviewed_old])
        assert batch[0]["number"] == 1

    def test_select_batch_respects_limit(self):
        issues = [self._issue(i, f"2024-{i:02d}-01") for i in range(1, 16)]
        assert len(select_batch(issues, limit=10)) == 10

    def test_select_batch_returns_oldest_first(self):
        issues = [self._issue(i, f"2024-{i:02d}-01") for i in range(1, 6)]
        batch = select_batch(issues, limit=3)
        assert [i["number"] for i in batch] == [1, 2, 3]

    def test_label_dict_format_supported(self):
        """Labels may come as dicts with a 'name' key (GitHub API format)."""
        issue = self._issue(5, "2023-01-01", labels=[{"name": self._reviewed_label("2024-04-01")}])
        assert batch_sort_key(issue) == "2024-04-01"
