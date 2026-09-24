"""Tests for pipeline/review_outcome.py (issue #512 Part 2).

Gherkin scenarios traced (issue #512):
  - Code-computed verdict overrides the model
  - Low-confidence non-critical finding does not block
  - Critical finding always blocks
  - ADR exception is verified, not trusted
  - Human blocker with no findings
"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from review_outcome import (
    APPROVE,
    REQUEST_CHANGES,
    adr_exception_index,
    build_deferred_findings_issue,
    derive_review_verdict,
    find_duplicate_finding_ids,
    finding_blocks,
    finding_needs_human_flag,
    finding_needs_new_issue,
    render_review_comment,
    sort_findings,
)


def _finding(**overrides):
    base = {
        "id": "RV-001",
        "title": "example finding",
        "severity": "Medium",
        "category": "correctness",
        "confidence": 0.9,
        "path": "foo.py",
        "line": 10,
        "evidence": "...",
        "fix": "...",
    }
    base.update(overrides)
    return base


_OVERRIDABLE_STD = {"STD-ARCH-035": {"adr_overridable": True}}


class TestAdrExceptionIndex:
    def test_builds_index_from_authorises_exception_to(self):
        records = [
            {"id": "ADR-002", "status": "accepted", "authorises_exception_to": ["STD-ARCH-035"]},
            {"id": "ADR-001", "status": "accepted", "rationale": "plain decision, no exception"},
        ]
        index = adr_exception_index(records, _OVERRIDABLE_STD)
        assert index == {"ADR-002": {"STD-ARCH-035"}}

    def test_plain_decision_record_contributes_nothing(self):
        records = [{"id": "ADR-001"}]
        assert adr_exception_index(records, _OVERRIDABLE_STD) == {}

    def test_non_accepted_status_contributes_nothing(self):
        """A deprecated, superseded, or merely-proposed ADR cannot still be
        waiving a standard."""
        for status in ("proposed", "deprecated", "superseded", None):
            records = [{"id": "ADR-002", "status": status,
                        "authorises_exception_to": ["STD-ARCH-035"]}]
            assert adr_exception_index(records, _OVERRIDABLE_STD) == {}, f"status={status!r} must not grant an exception"

    def test_accepted_status_contributes_normally(self):
        records = [{"id": "ADR-002", "status": "accepted",
                    "authorises_exception_to": ["STD-ARCH-035"]}]
        assert adr_exception_index(records, _OVERRIDABLE_STD) == {"ADR-002": {"STD-ARCH-035"}}

    def test_standard_marked_non_overridable_contributes_nothing(self):
        """docs/product/standards/14-standards.md: "adr_overridable: false --
        always blocks; no exception is possible" -- an ADR cannot waive a
        standard that says it can never be waived, no matter what its own
        authorises_exception_to claims."""
        records = [{"id": "ADR-002", "status": "accepted",
                    "authorises_exception_to": ["STD-SEC-013"]}]
        standards_by_id = {"STD-SEC-013": {"adr_overridable": False}}
        assert adr_exception_index(records, standards_by_id) == {}

    def test_standard_missing_from_standards_by_id_contributes_nothing(self):
        """A standard the loader couldn't find (stale id, removed standard)
        is treated as non-overridable, not as silently exempt."""
        records = [{"id": "ADR-002", "status": "accepted",
                    "authorises_exception_to": ["STD-ARCH-035"]}]
        assert adr_exception_index(records, {}) == {}


class TestFindingBlocks:
    def test_improvement_category_does_not_block_for_non_critical_severity(self):
        f = _finding(category="improvement", severity="Medium", confidence=1.0)
        assert finding_blocks(f, {}) is False

    def test_critical_finding_always_blocks_regardless_of_confidence(self):
        """Gherkin: Critical finding always blocks."""
        f = _finding(severity="Critical", confidence=0.3)
        assert finding_blocks(f, {}) is True

    def test_critical_finding_blocks_even_when_labeled_improvement(self):
        """"Critical" and "improvement" are contradictory -- severity says
        how bad a finding is, category says what kind it is. A finding
        cannot be both "so bad it must block" and "purely optional." Closes
        the gap /code-review found: a real Critical bug mislabeled
        category="improvement" must not silently exempt itself."""
        f = _finding(category="improvement", severity="Critical", confidence=1.0)
        assert finding_blocks(f, {}) is True

    def test_low_confidence_non_critical_finding_does_not_block(self):
        """Gherkin: Low-confidence non-critical finding does not block."""
        f = _finding(severity="Medium", confidence=0.5)
        assert finding_blocks(f, {}) is False

    def test_high_confidence_non_critical_finding_blocks(self):
        f = _finding(severity="Medium", confidence=0.9)
        assert finding_blocks(f, {}) is True

    def test_adr_exception_verified_against_index_is_non_blocking(self):
        """Gherkin: ADR exception is verified, not trusted (grant present)."""
        f = _finding(severity="High", confidence=1.0, category="standard",
                      standard="STD-ARCH-035", adr="ADR-002")
        index = {"ADR-002": {"STD-ARCH-035"}}
        assert finding_blocks(f, index) is False

    def test_adr_not_covering_this_standard_still_blocks(self):
        """Gherkin: ADR exception is verified, not trusted (grant absent)."""
        f = _finding(severity="High", confidence=1.0, category="standard",
                      standard="STD-SEC-022", adr="ADR-002")
        index = {"ADR-002": {"STD-ARCH-035"}}
        assert finding_blocks(f, index) is True

    def test_citing_an_unknown_adr_still_blocks(self):
        f = _finding(severity="High", confidence=1.0, category="standard",
                      standard="STD-ARCH-035", adr="ADR-999")
        assert finding_blocks(f, {}) is True

    def test_obsolete_effort_metadata_does_not_change_the_outcome(self):
        """Older producers may still send effort until all callers update;
        outcome computation is based only on the supported dimensions."""
        f = _finding(severity="Low", confidence=1.0, effort="defer-ok")
        assert finding_blocks(f, {}) is True

    def test_informational_never_blocks_regardless_of_confidence(self):
        """Issue #506: Informational is below the threshold this policy
        applies at all -- unlike Low, it has no complexity escape hatch to
        check because it never needs one."""
        f = _finding(severity="Informational", confidence=1.0)
        assert finding_blocks(f, {}) is False

    def test_informational_never_blocks_even_with_high_complexity(self):
        f = _finding(severity="Informational", confidence=1.0, complexity="high")
        assert finding_blocks(f, {}) is False

    def test_low_severity_low_complexity_blocks(self):
        """STD-ARCH-007's own bar: resolvable inline, fixed now like any
        other blocking finding."""
        f = _finding(severity="Low", confidence=1.0, complexity="low")
        assert finding_blocks(f, {}) is True

    def test_low_severity_medium_complexity_does_not_block(self):
        """Issue #506: flagged for a human decision, not auto-blocked."""
        f = _finding(severity="Low", confidence=1.0, complexity="medium")
        assert finding_blocks(f, {}) is False

    def test_low_severity_high_complexity_does_not_block(self):
        """Issue #506: deferred to a follow-up issue, not auto-blocked."""
        f = _finding(severity="Low", confidence=1.0, complexity="high")
        assert finding_blocks(f, {}) is False

    def test_low_severity_missing_complexity_fails_closed_to_blocking(self):
        """A Low finding the schema should have required complexity on, but
        didn't get it -- treated the same as complexity: low, not silently
        let through as non-blocking."""
        f = _finding(severity="Low", confidence=1.0)
        assert "complexity" not in f
        assert finding_blocks(f, {}) is True

    def test_low_severity_unrecognised_complexity_fails_closed_to_blocking(self):
        f = _finding(severity="Low", confidence=1.0, complexity="urgent")
        assert finding_blocks(f, {}) is True

    def test_medium_severity_complexity_is_ignored(self):
        """complexity only matters for severity Low -- a Medium finding
        blocks the same regardless of what complexity says."""
        f = _finding(severity="Medium", confidence=1.0, complexity="high")
        assert finding_blocks(f, {}) is True

    def test_critical_finding_blocks_regardless_of_complexity(self):
        f = _finding(severity="Critical", confidence=1.0, complexity="high")
        assert finding_blocks(f, {}) is True


class TestFindingNeedsHumanFlag:
    def test_low_severity_medium_complexity_needs_human_flag(self):
        f = _finding(severity="Low", complexity="medium")
        assert finding_needs_human_flag(f) is True

    def test_low_severity_low_complexity_does_not_need_human_flag(self):
        f = _finding(severity="Low", complexity="low")
        assert finding_needs_human_flag(f) is False

    def test_low_severity_high_complexity_does_not_need_human_flag(self):
        f = _finding(severity="Low", complexity="high")
        assert finding_needs_human_flag(f) is False

    def test_medium_severity_medium_complexity_does_not_need_human_flag(self):
        """The medium/high complexity dispositions only apply to Low
        severity -- a Medium-severity finding always blocks outright."""
        f = _finding(severity="Medium", complexity="medium")
        assert finding_needs_human_flag(f) is False


class TestFindingNeedsNewIssue:
    def test_low_severity_high_complexity_needs_new_issue(self):
        f = _finding(severity="Low", complexity="high")
        assert finding_needs_new_issue(f) is True

    def test_low_severity_medium_complexity_does_not_need_new_issue(self):
        f = _finding(severity="Low", complexity="medium")
        assert finding_needs_new_issue(f) is False

    def test_low_severity_low_complexity_does_not_need_new_issue(self):
        f = _finding(severity="Low", complexity="low")
        assert finding_needs_new_issue(f) is False


class TestBuildDeferredFindingsIssue:
    def test_no_deferred_findings_returns_empty_dict(self):
        findings = [_finding(severity="Critical"), _finding(severity="Low", complexity="low")]
        assert build_deferred_findings_issue(findings, 42) == {}

    def test_bundles_every_deferred_finding_into_one_issue(self):
        f1 = _finding(id="RV-001", title="first", severity="Low", complexity="high")
        f2 = _finding(id="RV-002", title="second", severity="Low", complexity="high")
        request = build_deferred_findings_issue([f1, f2], 42)
        assert request["title"]
        assert "RV-001" in request["body"] and "RV-002" in request["body"]
        assert "first" in request["body"] and "second" in request["body"]

    def test_excludes_non_deferred_findings(self):
        f1 = _finding(id="RV-001", severity="Low", complexity="high")
        f2 = _finding(id="RV-002", severity="Low", complexity="medium")
        f3 = _finding(id="RV-003", severity="Critical")
        request = build_deferred_findings_issue([f1, f2, f3], 42)
        assert "RV-001" in request["body"]
        assert "RV-002" not in request["body"]
        assert "RV-003" not in request["body"]

    def test_title_includes_pr_number(self):
        f = _finding(severity="Low", complexity="high")
        request = build_deferred_findings_issue([f], 42)
        assert "42" in request["title"]

    def test_labels_include_tech_debt_classification(self):
        f = _finding(severity="Low", complexity="high")
        request = build_deferred_findings_issue([f], 42)
        assert "classification: tech-debt" in request["labels"]


class TestDeriveReviewVerdict:
    def test_no_findings_no_human_blockers_approves(self):
        assert derive_review_verdict([], [], []) == APPROVE

    def test_human_blocker_with_no_findings_requests_changes(self):
        """Gherkin: Human blocker with no findings."""
        assert derive_review_verdict([], ["@alice"], []) == REQUEST_CHANGES

    def test_any_blocking_finding_requests_changes(self):
        f = _finding(severity="Critical", confidence=1.0)
        assert derive_review_verdict([f], [], []) == REQUEST_CHANGES

    def test_low_severity_medium_or_high_complexity_approves(self):
        """Issue #506: neither the human-flagged nor the deferred
        disposition forces a coder cycle by itself."""
        flagged = _finding(id="RV-001", severity="Low", confidence=1.0, complexity="medium")
        deferred = _finding(id="RV-002", severity="Low", confidence=1.0, complexity="high")
        assert derive_review_verdict([flagged, deferred], [], []) == APPROVE

    def test_verified_adr_exception_for_overridable_standard_approves(self):
        f = _finding(severity="High", confidence=1.0, category="standard",
                      standard="STD-ARCH-035", adr="ADR-002")
        records = [{"id": "ADR-002", "status": "accepted",
                    "authorises_exception_to": ["STD-ARCH-035"]}]
        assert derive_review_verdict([f], [], records, _OVERRIDABLE_STD) == APPROVE

    def test_adr_exception_for_non_overridable_standard_still_blocks(self):
        """An ADR cannot waive a standard marked adr_overridable: false, even
        if its own authorises_exception_to lists it -- the standard's own
        flag is checked, never trusted from the ADR's claim alone."""
        f = _finding(severity="High", confidence=1.0, category="standard",
                      standard="STD-SEC-013", adr="ADR-002")
        records = [{"id": "ADR-002", "status": "accepted",
                    "authorises_exception_to": ["STD-SEC-013"]}]
        standards_by_id = {"STD-SEC-013": {"adr_overridable": False}}
        assert derive_review_verdict([f], [], records, standards_by_id) == REQUEST_CHANGES

    def test_only_non_blocking_findings_approves(self):
        f = _finding(severity="Medium", confidence=0.5)
        assert derive_review_verdict([f], [], []) == APPROVE

    def test_model_outcome_is_never_consulted(self):
        """The model's own outcome/verdict fields play no part in this
        computation -- derive_review_verdict takes no such argument."""
        import inspect
        params = inspect.signature(derive_review_verdict).parameters
        assert "outcome" not in params and "verdict" not in params


class TestFindDuplicateFindingIds:
    def test_no_duplicates_returns_empty(self):
        findings = [_finding(id="RV-001"), _finding(id="RV-002")]
        assert find_duplicate_finding_ids(findings) == []

    def test_duplicate_id_detected(self):
        findings = [_finding(id="RV-001"), _finding(id="RV-001")]
        assert find_duplicate_finding_ids(findings) == ["RV-001"]

    def test_findings_missing_id_are_ignored(self):
        findings = [{"title": "no id"}, {"title": "also no id"}]
        assert find_duplicate_finding_ids(findings) == []


class TestSortFindings:
    def test_sorts_critical_first(self):
        findings = [
            _finding(id="RV-001", severity="Low"),
            _finding(id="RV-002", severity="Critical"),
            _finding(id="RV-003", severity="Medium"),
        ]
        ordered = sort_findings(findings)
        assert [f["id"] for f in ordered] == ["RV-002", "RV-003", "RV-001"]

    def test_stable_within_same_severity(self):
        findings = [
            _finding(id="RV-001", severity="High"),
            _finding(id="RV-002", severity="High"),
        ]
        ordered = sort_findings(findings)
        assert [f["id"] for f in ordered] == ["RV-001", "RV-002"]


class TestRenderReviewComment:
    def test_includes_verdict_line(self):
        body = render_review_comment(APPROVE, "abc123", [], [])
        assert "**Verdict: APPROVE**" in body

    def test_includes_reviewed_sha(self):
        body = render_review_comment(APPROVE, "abc123", [], [])
        assert "abc123" in body

    def test_includes_fenced_json_block_with_head_sha_and_findings(self):
        f = _finding(id="RV-001")
        body = render_review_comment(REQUEST_CHANGES, "deadbeef", [f], [])
        assert "```json" in body
        start = body.index("```json") + len("```json")
        end = body.index("```", start)
        payload = json.loads(body[start:end])
        assert payload["head_sha"] == "deadbeef"
        assert payload["findings"][0]["id"] == "RV-001"

    def test_no_findings_says_so(self):
        body = render_review_comment(APPROVE, "abc123", [], [])
        assert "No findings." in body

    def test_human_blockers_are_named_even_with_no_findings(self):
        """A REQUEST CHANGES verdict driven purely by an unresolved human
        review must not read as unexplained -- the old HR-001 finding this
        replaces named the blocking reviewer; the render must too."""
        blockers = [{"user": {"login": "alice", "type": "User"}, "state": "CHANGES_REQUESTED"}]
        body = render_review_comment(REQUEST_CHANGES, "abc123", [], [], human_blockers=blockers)
        assert "@alice" in body
        assert "REQUEST_CHANGES" in body or "REQUEST CHANGES" in body

    def test_no_human_blockers_line_when_none_present(self):
        body = render_review_comment(APPROVE, "abc123", [], [], human_blockers=[])
        assert "Unresolved human" not in body

    def test_rerun_flag_headers_as_rerun(self):
        body = render_review_comment(APPROVE, "abc123", [], [], prior_rerun=True)
        assert "(Re-run)" in body

    def test_json_block_findings_carry_blocking_field(self):
        """Issue #512, Scenario: Coder reads the rendered findings -- coder.md
        must not re-derive severity/confidence/ADR rules itself; the rendered
        JSON already says which findings block."""
        blocking_finding = _finding(id="RV-001", severity="Critical", confidence=1.0)
        non_blocking_finding = _finding(id="RV-002", severity="Medium", confidence=0.5)
        body = render_review_comment(
            REQUEST_CHANGES, "deadbeef", [blocking_finding, non_blocking_finding], [],
        )
        start = body.index("```json") + len("```json")
        end = body.index("```", start)
        payload = json.loads(body[start:end])
        by_id = {f["id"]: f["blocking"] for f in payload["findings"]}
        assert by_id["RV-001"] is True
        assert by_id["RV-002"] is False

    def test_human_flag_finding_is_tagged_distinctly(self):
        """Issue #506: a Low/Medium-complexity finding must read differently
        from an ordinary non-blocking finding -- it's the mechanism by which
        a human is expected to actually notice and decide."""
        f = _finding(id="RV-001", severity="Low", confidence=1.0, complexity="medium")
        body = render_review_comment(APPROVE, "abc123", [f], [])
        assert "FLAGGED FOR HUMAN DECISION" in body
        assert "[non-blocking]" not in body

    def test_deferred_finding_is_tagged_distinctly(self):
        f = _finding(id="RV-001", severity="Low", confidence=1.0, complexity="high")
        body = render_review_comment(APPROVE, "abc123", [f], [])
        assert "DEFERRED" in body
        assert "[non-blocking]" not in body

    def test_ordinary_non_blocking_finding_still_tagged_non_blocking(self):
        f = _finding(id="RV-001", severity="Medium", confidence=0.5)
        body = render_review_comment(APPROVE, "abc123", [f], [])
        assert "[non-blocking]" in body
