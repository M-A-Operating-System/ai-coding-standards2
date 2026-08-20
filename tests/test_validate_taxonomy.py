"""Tests for pipeline/validate_taxonomy.py."""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import pytest
from pathlib import Path
from validate_taxonomy import (
    DOMAINS,
    EXEMPT_FROM_SCHEMA,
    FILE_SCHEMAS,
    build_schema_registry,
    check_schema_coverage,
    collect_canonical_ids,
    discover_json_files,
    validate,
)

HERE = Path(__file__).parent
REAL_TAXONOMY_DIR = HERE.parent / "taxonomy"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def taxonomy(tmp_path) -> Path:
    """A writable copy of the real taxonomy, so defects can be injected."""
    dest = tmp_path / "taxonomy"
    shutil.copytree(REAL_TAXONOMY_DIR, dest)
    return dest


def _read(taxonomy_dir: Path, rel: str) -> dict:
    return json.loads((taxonomy_dir / rel).read_text())


def _write(taxonomy_dir: Path, rel: str, data: dict) -> None:
    (taxonomy_dir / rel).write_text(json.dumps(data, indent=2))


def _errors_matching(errors: list[str], needle: str) -> list[str]:
    return [e for e in errors if needle in e]


# ---------------------------------------------------------------------------
# The pass case
# ---------------------------------------------------------------------------

def test_real_taxonomy_validates_clean():
    errors, file_count, id_count = validate(REAL_TAXONOMY_DIR)
    assert errors == []
    assert file_count == len(FILE_SCHEMAS) + len(EXEMPT_FROM_SCHEMA)
    assert id_count > 0


def test_copied_taxonomy_validates_clean(taxonomy):
    errors, _, _ = validate(taxonomy)
    assert errors == []


def test_missing_taxonomy_dir_is_an_error(tmp_path):
    errors, file_count, id_count = validate(tmp_path / "nope")
    assert len(errors) == 1
    assert "not found" in errors[0]
    assert (file_count, id_count) == (0, 0)


# ---------------------------------------------------------------------------
# Injected defects named in the acceptance criteria
# ---------------------------------------------------------------------------

def test_domain_file_missing_families_fails(taxonomy):
    data = _read(taxonomy, "architecture/architecture.json")
    del data["families"]
    _write(taxonomy, "architecture/architecture.json", data)

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "'families' is a required property")


def test_implementation_naming_unknown_class_fails(taxonomy):
    data = _read(taxonomy, "implementations/implementations.json")
    data["implementations"]["postgresql"]["implements"] = [
        "architecture/data/database/no-such-database"
    ]
    _write(taxonomy, "implementations/implementations.json", data)

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "no-such-database")
    assert matched
    assert "not declared in any domain file" in matched[0]
    assert "implementations/postgresql" in matched[0]


def test_rule_assigning_unknown_id_fails(taxonomy):
    data = _read(taxonomy, "rules/code-classification-rules.json")
    data["rules"][0]["assign"]["code"] = ["code/api/handler/no-such-handler"]
    _write(taxonomy, "rules/code-classification-rules.json", data)

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "no-such-handler")
    assert matched
    assert "not declared in any domain file" in matched[0]


def test_unmapped_json_file_fails(taxonomy):
    (taxonomy / "concepts" / "extra.json").write_text('{"hello": "world"}')

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "concepts/extra.json")
    assert matched
    assert "no schema mapped" in matched[0]


# ---------------------------------------------------------------------------
# Further referential and structural defects
# ---------------------------------------------------------------------------

def test_mapping_referencing_unknown_id_fails(taxonomy):
    data = _read(taxonomy, "mappings/cross-domain.json")
    data["relationships"][0]["to"] = "code/persistence/repository/ghost"
    _write(taxonomy, "mappings/cross-domain.json", data)

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "ghost")
    assert matched
    assert "relationships[0].to" in matched[0]


def test_calm_mapping_referencing_unknown_id_fails(taxonomy):
    data = _read(taxonomy, "mappings/calm-to-canonical.json")
    data["mappings"]["service"] = ["architecture/compute/service/ghost-service"]
    _write(taxonomy, "mappings/calm-to-canonical.json", data)

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "ghost-service")


def test_runtime_supporting_unknown_id_fails(taxonomy):
    data = _read(taxonomy, "runtimes/runtimes.json")
    data["providers"]["aws"]["services"]["rds"]["supports"] = [
        "architecture/data/database/ghost-database"
    ]
    _write(taxonomy, "runtimes/runtimes.json", data)

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "ghost-database")
    assert matched
    assert "providers/aws/services/rds" in matched[0]


def test_example_citing_unknown_implementation_fails(taxonomy):
    data = _read(taxonomy, "examples/observed-booking-db.json")
    data["implementation"] = "not-a-real-database"
    _write(taxonomy, "examples/observed-booking-db.json", data)

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "not-a-real-database")
    assert matched
    assert "not in the implementation registry" in matched[0]


def test_example_citing_unknown_runtime_fails(taxonomy):
    data = _read(taxonomy, "examples/observed-booking-db.json")
    data["runtime"] = "aws/not-a-real-service"
    _write(taxonomy, "examples/observed-booking-db.json", data)

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "not in the runtime registry")


def test_node_id_disagreeing_with_position_fails(taxonomy):
    data = _read(taxonomy, "code/code.json")
    family_key = next(iter(data["families"]))
    data["families"][family_key]["id"] = "code/wrong-id"
    _write(taxonomy, "code/code.json", data)

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "declares id 'code/wrong-id'")


def test_node_parent_disagreeing_with_position_fails(taxonomy):
    data = _read(taxonomy, "code/code.json")
    family_key = next(iter(data["families"]))
    class_key = next(iter(data["families"][family_key]["classes"]))
    data["families"][family_key]["classes"][class_key]["parent"] = "code/elsewhere"
    _write(taxonomy, "code/code.json", data)

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "parent is 'code/elsewhere'")


def test_wrong_declared_domain_fails(taxonomy):
    data = _read(taxonomy, "patterns/patterns.json")
    data["domain"] = "architecture"
    _write(taxonomy, "patterns/patterns.json", data)

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "domain is 'architecture', expected 'patterns'")


def test_dangling_source_in_taxonomy_json_fails(taxonomy):
    data = _read(taxonomy, "taxonomy.json")
    data["domains"]["architecture"]["source"] = "architecture/missing.json"
    _write(taxonomy, "taxonomy.json", data)

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "architecture/missing.json")
    assert matched
    assert "does not exist" in matched[0]


def test_invalid_json_is_reported_not_raised(taxonomy):
    (taxonomy / "runtimes" / "runtimes.json").write_text("{ not json")

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "invalid JSON")


def test_deleted_file_still_declared_fails(taxonomy):
    (taxonomy / "mappings" / "cross-domain.json").unlink()

    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "mappings/cross-domain.json")
    assert matched
    assert any("no such file exists" in e for e in matched)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def test_discover_excludes_the_schemas_themselves():
    files = discover_json_files(REAL_TAXONOMY_DIR)
    rels = {p.relative_to(REAL_TAXONOMY_DIR).as_posix() for p in files}
    assert not any(rel.startswith("schemas/") for rel in rels)
    assert "taxonomy.json" in rels


def test_every_discovered_file_is_declared():
    errors = check_schema_coverage(
        REAL_TAXONOMY_DIR, discover_json_files(REAL_TAXONOMY_DIR)
    )
    assert errors == []


def test_schema_registry_resolves_sibling_refs():
    registry = build_schema_registry(REAL_TAXONOMY_DIR / "schemas")
    resolver = registry.resolver()
    resolved = resolver.lookup("classification-rule.schema.json")
    assert resolved.contents["title"] == "Deterministic Code Classification Rule"


def test_canonical_ids_cover_every_domain():
    loaded = {
        f"{d}/{d}.json": json.loads((REAL_TAXONOMY_DIR / d / f"{d}.json").read_text())
        for d in DOMAINS
    }
    ids, errors = collect_canonical_ids(loaded)
    assert errors == []
    for domain in DOMAINS:
        assert any(i.startswith(f"{domain}/") for i in ids)
