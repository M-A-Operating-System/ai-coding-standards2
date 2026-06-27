"""Tests for pipeline/validate_standards.py."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import pytest
from pathlib import Path
from validate_standards import (
    check_schema,
    check_id_prefix,
    collect_all_standards,
    check_references,
    check_prose_references,
    check_adrs,
    validate,
    CATEGORY_TO_PREFIX,
)

HERE = Path(__file__).parent
SCHEMA_PATH = HERE.parent / "pipeline" / "schemas" / "standards.schema.json"
REAL_STANDARDS_DIR = HERE.parent / "standards"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def schema():
    return json.loads(SCHEMA_PATH.read_text())


def _make_std(
    std_id="STD-PROC-001",
    title="Do the thing",
    description="Never skip the thing.",
    rationale="Skipping causes drift.",
    acceptance_criteria=["PR diff contains the thing."],
    anti_patterns=["Skipping the thing."],
    adr_overridable=True,
    applies_to=None,
    **extra,
) -> dict:
    s = {
        "id": std_id,
        "title": title,
        "description": description,
        "rationale": rationale,
        "acceptance_criteria": acceptance_criteria,
        "anti_patterns": anti_patterns,
        "adr_overridable": adr_overridable,
        "applies_to": applies_to or ["coder", "pr-reviewer"],
    }
    s.update(extra)
    return s


def _make_file(
    category="process",
    scope="org",
    standards=None,
    adrs=None,
) -> dict:
    d: dict = {"version": "1.0", "scope": scope, "category": category, "standards": standards or []}
    if adrs is not None:
        # AdrsFile shape
        d = {"version": "1.0", "scope": scope, "adrs": adrs}
    return d


def _write_standards(tmp_path: Path, files: dict[str, dict]) -> Path:
    for name, content in files.items():
        (tmp_path / name).write_text(json.dumps(content))
    return tmp_path


# ---------------------------------------------------------------------------
# check_schema
# ---------------------------------------------------------------------------

class TestCheckSchema:
    def test_valid_standards_file_no_errors(self, schema):
        data = _make_file(standards=[_make_std()])
        assert check_schema(data, schema, "process.json") == []

    def test_missing_required_field_reports_error(self, schema):
        data = _make_file(standards=[{
            "id": "STD-PROC-001",
            "title": "t",
            # missing description, rationale, acceptance_criteria, anti_patterns,
            # adr_overridable, applies_to
        }])
        errors = check_schema(data, schema, "process.json")
        assert errors

    def test_bad_id_pattern_reports_error(self, schema):
        std = _make_std(std_id="BAD-001")
        data = _make_file(standards=[std])
        errors = check_schema(data, schema, "process.json")
        assert any("BAD-001" in e or "pattern" in e.lower() for e in errors)

    def test_invalid_scope_reports_error(self, schema):
        data = _make_file(scope="team")  # not in enum
        errors = check_schema(data, schema, "process.json")
        assert errors

    def test_valid_adrs_file_no_errors(self, schema):
        data = {
            "version": "1.0",
            "scope": "org",
            "adrs": [{
                "id": "ADR-001",
                "title": "Allow exception",
                "authorises_exception_to": ["STD-PROC-001"],
                "rationale": "Because reasons.",
            }],
        }
        assert check_schema(data, schema, "adrs.json") == []


# ---------------------------------------------------------------------------
# check_id_prefix
# ---------------------------------------------------------------------------

class TestCheckIdPrefix:
    @pytest.mark.parametrize("category,prefix", CATEGORY_TO_PREFIX.items())
    def test_correct_prefix_no_error(self, category, prefix):
        data = _make_file(category=category, standards=[_make_std(std_id=f"{prefix}-001")])
        assert check_id_prefix(data, "x.json") == []

    def test_wrong_prefix_reports_error(self):
        data = _make_file(category="process", standards=[_make_std(std_id="STD-DATA-001")])
        errors = check_id_prefix(data, "process.json")
        assert errors
        assert "STD-DATA-001" in errors[0]

    def test_unknown_category_passes(self):
        data = _make_file(category="unknown", standards=[_make_std()])
        assert check_id_prefix(data, "x.json") == []


# ---------------------------------------------------------------------------
# collect_all_standards
# ---------------------------------------------------------------------------

class TestCollectAllStandards:
    def test_unique_ids_no_errors(self):
        loaded = [
            ("a.json", _make_file(standards=[_make_std("STD-PROC-001")])),
            ("b.json", _make_file(standards=[_make_std("STD-PROC-002")])),
        ]
        id_map, errors = collect_all_standards(loaded)
        assert errors == []
        assert set(id_map) == {"STD-PROC-001", "STD-PROC-002"}

    def test_duplicate_id_reports_error(self):
        loaded = [
            ("a.json", _make_file(standards=[_make_std("STD-PROC-001")])),
            ("b.json", _make_file(standards=[_make_std("STD-PROC-001")])),
        ]
        _, errors = collect_all_standards(loaded)
        assert len(errors) == 1
        assert "STD-PROC-001" in errors[0]

    def test_adr_file_standards_ignored(self):
        loaded = [("adrs.json", {"version": "1.0", "scope": "org", "adrs": []})]
        id_map, errors = collect_all_standards(loaded)
        assert errors == []
        assert id_map == {}


# ---------------------------------------------------------------------------
# check_references
# ---------------------------------------------------------------------------

class TestCheckReferences:
    def test_valid_instantiates_no_error(self):
        parent = _make_std("STD-PROC-001")
        child = _make_std("STD-PROC-002", instantiates="STD-PROC-001")
        loaded = [("p.json", _make_file(standards=[parent, child]))]
        id_map, _ = collect_all_standards(loaded)
        assert check_references(loaded, id_map) == []

    def test_dangling_instantiates_reports_error(self):
        std = _make_std("STD-PROC-001", instantiates="STD-ARCH-999")
        loaded = [("p.json", _make_file(standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        errors = check_references(loaded, id_map)
        assert errors
        assert "STD-ARCH-999" in errors[0]

    def test_valid_related_no_error(self):
        a = _make_std("STD-PROC-001")
        b = _make_std("STD-PROC-002", related=["STD-PROC-001"])
        loaded = [("p.json", _make_file(standards=[a, b]))]
        id_map, _ = collect_all_standards(loaded)
        assert check_references(loaded, id_map) == []

    def test_dangling_related_reports_error(self):
        std = _make_std("STD-PROC-001", related=["STD-DATA-999"])
        loaded = [("p.json", _make_file(standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        errors = check_references(loaded, id_map)
        assert errors
        assert "STD-DATA-999" in errors[0]

    def test_cross_file_reference_resolves(self):
        a = ("proc.json", _make_file(category="process", standards=[_make_std("STD-PROC-001")]))
        b_std = _make_std("STD-PROC-002", related=["STD-PROC-001"])
        b = ("proc2.json", _make_file(category="process", standards=[b_std]))
        loaded = [a, b]
        id_map, _ = collect_all_standards(loaded)
        assert check_references(loaded, id_map) == []


# ---------------------------------------------------------------------------
# check_prose_references
# ---------------------------------------------------------------------------

class TestCheckProseReferences:
    def test_resolved_prose_reference_no_error(self):
        target = _make_std("STD-SEC-002")
        citing = _make_std(
            "STD-DATA-016",
            description="Roles are enforced through has_role() (STD-SEC-002).",
        )
        loaded = [("s.json", _make_file(standards=[target, citing]))]
        id_map, _ = collect_all_standards(loaded)
        assert check_prose_references(loaded, id_map) == []

    def test_dangling_reference_in_description_reported(self):
        std = _make_std(
            "STD-DATA-016",
            description="Roles are enforced through has_role() (STD-SEC-002).",
        )
        loaded = [("data.json", _make_file(category="data", standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        errors = check_prose_references(loaded, id_map)
        assert len(errors) == 1
        assert "STD-SEC-002" in errors[0]
        assert "STD-DATA-016" in errors[0]

    def test_dangling_reference_in_anti_patterns_reported(self):
        std = _make_std(
            "STD-DATA-016",
            anti_patterns=["Granting write access without a has_role() check (see STD-SEC-002)."],
        )
        loaded = [("data.json", _make_file(category="data", standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        errors = check_prose_references(loaded, id_map)
        assert errors and "STD-SEC-002" in errors[0]

    def test_source_provenance_not_scanned(self):
        # `source` is provenance, not a resolvable reference — a dangling ID
        # there must NOT be flagged (it may name a retired or cross-tier std).
        std = _make_std(
            "STD-PROC-011",
            source="Migrated from org STD-ARCH-006 / STD-ARCH-007 (fix-now / no-issues).",
        )
        loaded = [("process.json", _make_file(category="process", standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        assert check_prose_references(loaded, id_map) == []

    def test_unanchored_partial_match_not_flagged(self):
        # A 4-digit typo or a glued mid-word occurrence must not match a real 3-digit ID.
        std = _make_std(
            "STD-DATA-001",
            description="Bad ref STD-ARCH-0091 and glued fooSTD-SEC-002 should not match.",
        )
        loaded = [("data.json", _make_file(category="data", standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        assert check_prose_references(loaded, id_map) == []

    def test_self_reference_not_flagged(self):
        std = _make_std(
            "STD-PROC-001",
            description="This rule (STD-PROC-001) supersedes ad-hoc practice.",
        )
        loaded = [("p.json", _make_file(standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        assert check_prose_references(loaded, id_map) == []

    def test_duplicate_mention_reported_once(self):
        std = _make_std(
            "STD-UX-010",
            description="Error text is translated/safe (STD-SEC-009).",
            anti_patterns=["Raw error shown to users instead of a safe message (STD-SEC-009)."],
        )
        loaded = [("ux-design.json", _make_file(category="ux-design", standards=[std]))]
        id_map, _ = collect_all_standards(loaded)
        errors = check_prose_references(loaded, id_map)
        assert len(errors) == 1
        assert "STD-SEC-009" in errors[0]

    def test_cross_file_prose_reference_resolves(self):
        defn = ("sec.json", _make_file(category="security", standards=[_make_std("STD-SEC-009")]))
        citing = _make_std("STD-UX-010", description="Error text is safe (STD-SEC-009).")
        ux = ("ux-design.json", _make_file(category="ux-design", standards=[citing]))
        loaded = [defn, ux]
        id_map, _ = collect_all_standards(loaded)
        assert check_prose_references(loaded, id_map) == []


# ---------------------------------------------------------------------------
# check_adrs
# ---------------------------------------------------------------------------

class TestCheckAdrs:
    def test_valid_adr_no_error(self):
        std = _make_std("STD-PROC-001", adr_overridable=True)
        std_loaded = [("p.json", _make_file(standards=[std]))]
        adr_loaded = [("adrs.json", {
            "version": "1.0", "scope": "org",
            "adrs": [{"id": "ADR-001", "title": "t",
                       "authorises_exception_to": ["STD-PROC-001"],
                       "rationale": "r"}],
        })]
        id_map, _ = collect_all_standards(std_loaded)
        assert check_adrs(adr_loaded, id_map) == []

    def test_adr_waiving_nonexistent_id_reports_error(self):
        loaded = [("adrs.json", {
            "version": "1.0", "scope": "org",
            "adrs": [{"id": "ADR-001", "title": "t",
                       "authorises_exception_to": ["STD-PROC-999"],
                       "rationale": "r"}],
        })]
        errors = check_adrs(loaded, {})
        assert errors
        assert "STD-PROC-999" in errors[0]

    def test_adr_waiving_non_overridable_standard_reports_error(self):
        std = _make_std("STD-SEC-001", adr_overridable=False)
        std_loaded = [("sec.json", _make_file(category="security", standards=[std]))]
        adr_loaded = [("adrs.json", {
            "version": "1.0", "scope": "org",
            "adrs": [{"id": "ADR-001", "title": "t",
                       "authorises_exception_to": ["STD-SEC-001"],
                       "rationale": "r"}],
        })]
        id_map, _ = collect_all_standards(std_loaded)
        errors = check_adrs(adr_loaded, id_map)
        assert errors
        assert "adr_overridable: false" in errors[0]


# ---------------------------------------------------------------------------
# validate (integration) — runs against the real standards directory
# ---------------------------------------------------------------------------

class TestValidateRealStandards:
    def test_real_standards_pass_all_checks(self):
        errors, file_count, std_count, adr_count = validate(REAL_STANDARDS_DIR, SCHEMA_PATH)
        assert errors == [], "\n".join(errors)
        assert file_count >= 4
        assert std_count > 0

    def test_missing_directory_returns_error(self, tmp_path):
        absent = tmp_path / "nonexistent"
        errors, *_ = validate(absent, SCHEMA_PATH)
        assert errors

    def test_empty_directory_returns_error(self, tmp_path):
        errors, *_ = validate(tmp_path, SCHEMA_PATH)
        assert errors

    def test_duplicate_id_caught(self, tmp_path):
        std = _make_std("STD-PROC-001")
        _write_standards(tmp_path, {
            "a.json": _make_file(standards=[std]),
            "b.json": _make_file(standards=[std]),
        })
        errors, *_ = validate(tmp_path, SCHEMA_PATH)
        assert any("duplicate" in e for e in errors)

    def test_dangling_reference_caught(self, tmp_path):
        std = _make_std("STD-PROC-001", related=["STD-ARCH-999"])
        _write_standards(tmp_path, {"p.json": _make_file(standards=[std])})
        errors, *_ = validate(tmp_path, SCHEMA_PATH)
        assert any("STD-ARCH-999" in e for e in errors)

    def test_wrong_id_prefix_caught(self, tmp_path):
        std = _make_std("STD-DATA-001")  # wrong prefix for process category
        _write_standards(tmp_path, {"p.json": _make_file(category="process", standards=[std])})
        errors, *_ = validate(tmp_path, SCHEMA_PATH)
        assert any("STD-DATA-001" in e for e in errors)
