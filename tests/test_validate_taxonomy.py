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
    ID_PATTERN,
    LEVEL_PREFIX,
    build_schema_registry,
    check_facets,
    check_lifecycle,
    check_schema_coverage,
    collect_nodes,
    discover_json_files,
    validate,
)

HERE = Path(__file__).parent
REAL_TAXONOMY_DIR = HERE.parent / "taxonomy"


# ---------------------------------------------------------------------------
# Fixtures and helpers
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


def _first_subclass(domain_doc: dict) -> dict:
    """The first subclass record in a domain document."""
    family = next(iter(domain_doc["families"].values()))
    klass = next(iter(family["classes"].values()))
    return next(iter(klass["subclasses"].values()))


def _load_domain_files() -> dict:
    """The four semantic domain files, keyed as the validator keys them."""
    return {f"{d}/{d}.json": json.loads((REAL_TAXONOMY_DIR / d / f"{d}.json").read_text())
            for d in DOMAINS}


def _errors_matching(errors: list[str], needle: str) -> list[str]:
    return [e for e in errors if needle in e]


def _mutate_first_subclass(taxonomy_dir: Path, domain: str, change):
    rel = f"{domain}/{domain}.json"
    doc = _read(taxonomy_dir, rel)
    change(_first_subclass(doc))
    _write(taxonomy_dir, rel, doc)


# ---------------------------------------------------------------------------
# The pass case
# ---------------------------------------------------------------------------

def test_real_taxonomy_validates_clean():
    errors, file_count, node_count = validate(REAL_TAXONOMY_DIR)
    assert errors == []
    assert file_count == len(FILE_SCHEMAS) + len(EXEMPT_FROM_SCHEMA)
    assert node_count > 0


def test_copied_taxonomy_validates_clean(taxonomy):
    errors, _, _ = validate(taxonomy)
    assert errors == []


def test_missing_taxonomy_dir_is_an_error(tmp_path):
    errors, file_count, node_count = validate(tmp_path / "nope")
    assert len(errors) == 1
    assert "not found" in errors[0]
    assert (file_count, node_count) == (0, 0)


# ---------------------------------------------------------------------------
# Identity is a primary key
# ---------------------------------------------------------------------------

def test_every_node_has_a_well_formed_identifier():
    by_id, _, errors = collect_nodes(_load_domain_files())
    assert errors == []
    assert by_id
    assert all(ID_PATTERN.match(node_id) for node_id in by_id)


def test_identifiers_are_unique_across_the_taxonomy():
    by_id, _, _ = collect_nodes(_load_domain_files())
    # collect_nodes would have reported a reuse error; assert the count instead
    _, _, errors = collect_nodes(_load_domain_files())
    assert not _errors_matching(errors, "never reused")
    assert len(by_id) == 453


def test_reused_identifier_fails(taxonomy):
    """Give one subclass the identifier of another; identifiers are never reused."""
    doc = _read(taxonomy, "architecture/architecture.json")
    subs = [s for fam in doc["families"].values()
            for cl in fam.get("classes", {}).values()
            for s in cl.get("subclasses", {}).values()]
    subs[1]["id"] = subs[0]["id"]
    _write(taxonomy, "architecture/architecture.json", doc)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "identifiers are never reused")


def test_malformed_identifier_fails(taxonomy):
    _mutate_first_subclass(taxonomy, "architecture", lambda n: n.update({"id": "nope"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "is not a valid identifier")


def test_identifier_prefix_must_match_level(taxonomy):
    """The three-letter code records the level, so a family code on a subclass fails."""
    _mutate_first_subclass(taxonomy, "patterns", lambda n: n.update({"id": "FAM999999"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "prefix does not match level")


def test_identifier_is_independent_of_domain(taxonomy):
    """A subclass code is valid in any domain - identity does not encode content."""
    doc = _read(taxonomy, "code/code.json")
    _first_subclass(doc)["id"] = "SUB900001"
    _write(taxonomy, "code/code.json", doc)
    errors, _, _ = validate(taxonomy)
    assert not _errors_matching(errors, "prefix does not match")


# ---------------------------------------------------------------------------
# Position: path, parent, level
# ---------------------------------------------------------------------------

def test_path_must_match_position(taxonomy):
    _mutate_first_subclass(taxonomy, "code", lambda n: n.update({"path": "code/wrong/place/here"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "path is 'code/wrong/place/here'")


def test_parent_must_be_the_identifier_above(taxonomy):
    _mutate_first_subclass(taxonomy, "code", lambda n: n.update({"parent": "CLS999999"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "parent is 'CLS999999'")


def test_level_must_match_position(taxonomy):
    _mutate_first_subclass(taxonomy, "concepts", lambda n: n.update({"level": "family"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "level is 'family'")


def test_duplicate_path_fails(taxonomy):
    doc = _read(taxonomy, "architecture/architecture.json")
    family = next(iter(doc["families"].values()))
    klass = next(iter(family["classes"].values()))
    subs = list(klass["subclasses"].values())
    if len(subs) < 2:
        pytest.skip("first class has a single subclass")
    subs[1]["path"] = subs[0]["path"]
    _write(taxonomy, "architecture/architecture.json", doc)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "is claimed by both")


def test_wrong_declared_domain_fails(taxonomy):
    doc = _read(taxonomy, "patterns/patterns.json")
    doc["domain"] = "architecture"
    _write(taxonomy, "patterns/patterns.json", doc)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "domain is 'architecture', expected 'patterns'")


# ---------------------------------------------------------------------------
# A domain is a field, not a level and not a node
# ---------------------------------------------------------------------------

def test_a_family_parent_is_its_domain():
    """A family sits at the top of the tree, so its parent is the domain itself."""
    by_id, _, errors = collect_nodes(_load_domain_files())
    assert errors == []
    parents = {node["parent"] for node in by_id.values() if node["level"] == "family"}
    assert parents == set(DOMAINS)


def test_no_node_is_a_domain():
    """A domain is a field with a controlled value set, so it carries no identifier."""
    by_id, _, _ = collect_nodes(_load_domain_files())
    assert all(ID_PATTERN.match(node_id) for node_id in by_id)
    assert set(LEVEL_PREFIX) == {"family", "class", "subclass"}
    assert not any(node_id.startswith("DOM") for node_id in by_id)


def test_taxonomy_folder_has_no_domain_registry():
    """Nothing to register: the domain lives in the schema as an enum."""
    assert not (REAL_TAXONOMY_DIR / "domains").exists()
    root = json.loads((REAL_TAXONOMY_DIR / "taxonomy.json").read_text())
    assert set(root["domains"]) == set(DOMAINS)
    assert "domain_registry" not in root["registries"]


def test_domain_field_is_constrained_by_the_schema():
    schema = json.loads(
        (REAL_TAXONOMY_DIR / "schemas" / "domain-taxonomy.schema.json").read_text())
    assert set(schema["properties"]["domain"]["enum"]) == set(DOMAINS)
    assert "domain" in schema["required"]


def test_undeclared_domain_value_fails(taxonomy):
    doc = _read(taxonomy, "code/code.json")
    doc["domain"] = "infrastructure"
    _write(taxonomy, "code/code.json", doc)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "domain is 'infrastructure', expected 'code'")
    assert _errors_matching(errors, "'infrastructure' is not one of")


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------

def test_every_node_carries_a_declared_concern():
    loaded = _load_domain_files()
    loaded["facets/facets.json"] = json.loads(
        (REAL_TAXONOMY_DIR / "facets" / "facets.json").read_text())
    by_id, _, _ = collect_nodes(loaded)
    assert check_facets(by_id, loaded) == []
    assert all(node.get("facets", {}).get("concern") for node in by_id.values())


def test_undeclared_facet_value_fails(taxonomy):
    _mutate_first_subclass(taxonomy, "concepts",
                           lambda n: n.update({"facets": {"concern": ["not-a-concern"]}}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "is not declared")


def test_undeclared_facet_name_fails(taxonomy):
    _mutate_first_subclass(taxonomy, "concepts",
                           lambda n: n.update({"facets": {"invented": ["x"]}}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "not in the facet registry")


def test_single_valued_facet_rejects_two_values(taxonomy):
    reg = _read(taxonomy, "facets/facets.json")
    reg["facets"]["concern"]["multi_valued"] = False
    _write(taxonomy, "facets/facets.json", reg)
    _mutate_first_subclass(taxonomy, "concepts",
                           lambda n: n.update({"facets": {"concern": ["security", "observability"]}}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "is single-valued")


def test_concern_facet_spans_domains():
    """The point of facets: one value reaches nodes in several domains."""
    reg = json.loads((REAL_TAXONOMY_DIR / "facets" / "facets.json").read_text())
    spanning = [v for v, spec in reg["facets"]["concern"]["values"].items()
                if len(spec.get("domains", [])) > 1]
    assert "security" in spanning
    assert len(spanning) >= 5


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_deprecated_node_must_name_a_replacement(taxonomy):
    _mutate_first_subclass(taxonomy, "patterns", lambda n: n.update({"status": "deprecated"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "names no replaced_by")


def test_replaced_by_must_resolve(taxonomy):
    _mutate_first_subclass(taxonomy, "patterns",
                           lambda n: n.update({"status": "deprecated", "replaced_by": "SUB999999"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "does not resolve")


def test_replacement_may_not_itself_be_deprecated(taxonomy):
    doc = _read(taxonomy, "patterns/patterns.json")
    family = next(iter(doc["families"].values()))
    klass = next(iter(family["classes"].values()))
    subs = list(klass["subclasses"].values())
    if len(subs) < 2:
        pytest.skip("first class has a single subclass")
    subs[0].update({"status": "deprecated", "replaced_by": subs[1]["id"]})
    subs[1].update({"status": "deprecated", "replaced_by": subs[0]["id"]})
    _write(taxonomy, "patterns/patterns.json", doc)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "is itself deprecated")


def test_replaced_by_without_deprecation_fails(taxonomy):
    _mutate_first_subclass(taxonomy, "patterns", lambda n: n.update({"replaced_by": "SUB000001"}))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "names replaced_by but status is")


def test_lifecycle_clean_on_real_taxonomy():
    loaded = _load_domain_files()
    by_id, _, _ = collect_nodes(loaded)
    assert check_lifecycle(by_id) == []


# ---------------------------------------------------------------------------
# References point at identity
# ---------------------------------------------------------------------------

def test_reference_by_path_is_rejected_with_the_identifier(taxonomy):
    data = _read(taxonomy, "implementations/implementations.json")
    data["implementations"]["postgresql"]["implements"] = [
        "architecture/data/database/relational-database"
    ]
    _write(taxonomy, "implementations/implementations.json", data)
    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "is a path, not an identifier")
    assert matched
    assert "SUB" in matched[0]


def test_reference_to_unknown_identifier_fails(taxonomy):
    data = _read(taxonomy, "rules/code-classification-rules.json")
    data["rules"][0]["assign"]["code"] = ["SUB999999"]
    _write(taxonomy, "rules/code-classification-rules.json", data)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "not declared in any domain file")


def test_reference_to_deprecated_node_fails(taxonomy):
    doc = _read(taxonomy, "code/code.json")
    target = _first_subclass(doc)
    family = next(iter(doc["families"].values()))
    klass = next(iter(family["classes"].values()))
    subs = list(klass["subclasses"].values())
    replacement = subs[1]["id"] if len(subs) > 1 else next(
        iter(next(iter(doc["families"].values()))["classes"].values()))["id"]
    target.update({"status": "deprecated", "replaced_by": replacement})
    _write(taxonomy, "code/code.json", doc)

    rules = _read(taxonomy, "rules/code-classification-rules.json")
    rules["rules"][0]["assign"]["code"] = [target["id"]]
    _write(taxonomy, "rules/code-classification-rules.json", rules)

    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "is deprecated")


def test_example_citing_unknown_implementation_fails(taxonomy):
    data = _read(taxonomy, "examples/observed-booking-db.json")
    data["implementation"] = "not-a-real-database"
    _write(taxonomy, "examples/observed-booking-db.json", data)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "not in the implementation registry")


def test_example_citing_unknown_runtime_fails(taxonomy):
    data = _read(taxonomy, "examples/observed-booking-db.json")
    data["runtime"] = "aws/not-a-real-service"
    _write(taxonomy, "examples/observed-booking-db.json", data)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "not in the runtime registry")


# ---------------------------------------------------------------------------
# Structure and coverage
# ---------------------------------------------------------------------------

def test_domain_file_missing_families_fails(taxonomy):
    data = _read(taxonomy, "architecture/architecture.json")
    del data["families"]
    _write(taxonomy, "architecture/architecture.json", data)
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "'families' is a required property")


def test_node_missing_required_field_fails(taxonomy):
    _mutate_first_subclass(taxonomy, "architecture", lambda n: n.pop("stability"))
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "'stability' is a required property")


def test_unmapped_json_file_fails(taxonomy):
    (taxonomy / "concepts" / "extra.json").write_text('{"hello": "world"}')
    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "concepts/extra.json")
    assert matched
    assert "no schema mapped" in matched[0]


def test_dangling_source_in_taxonomy_json_fails(taxonomy):
    data = _read(taxonomy, "taxonomy.json")
    data["domains"]["architecture"]["source"] = "architecture/missing.json"
    _write(taxonomy, "taxonomy.json", data)
    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "architecture/missing.json")
    assert matched
    assert "does not exist" in matched[0]


def test_facet_registry_is_declared_in_the_master_registry():
    root = json.loads((REAL_TAXONOMY_DIR / "taxonomy.json").read_text())
    assert root["registries"]["facets"]["source"] == "facets/facets.json"


def test_master_registry_declares_exactly_three_semantic_levels():
    root = json.loads((REAL_TAXONOMY_DIR / "taxonomy.json").read_text())
    assert root["classification_model"]["semantic_levels"] == ["family", "class", "subclass"]


def test_invalid_json_is_reported_not_raised(taxonomy):
    (taxonomy / "runtimes" / "runtimes.json").write_text("{ not json")
    errors, _, _ = validate(taxonomy)
    assert _errors_matching(errors, "invalid JSON")


def test_deleted_file_still_declared_fails(taxonomy):
    (taxonomy / "mappings" / "cross-domain.json").unlink()
    errors, _, _ = validate(taxonomy)
    matched = _errors_matching(errors, "mappings/cross-domain.json")
    assert any("no such file exists" in e for e in matched)


def test_discover_excludes_the_schemas_themselves():
    files = discover_json_files(REAL_TAXONOMY_DIR)
    rels = {p.relative_to(REAL_TAXONOMY_DIR).as_posix() for p in files}
    assert not any(rel.startswith("schemas/") for rel in rels)
    assert "taxonomy.json" in rels
    assert "facets/facets.json" in rels


def test_every_discovered_file_is_declared():
    errors = check_schema_coverage(
        REAL_TAXONOMY_DIR, discover_json_files(REAL_TAXONOMY_DIR)
    )
    assert errors == []


def test_schema_registry_resolves_sibling_refs():
    registry = build_schema_registry(REAL_TAXONOMY_DIR / "schemas")
    resolver = registry.resolver()
    assert resolver.lookup("node.schema.json").contents["title"] == "Taxonomy Node"
    assert resolver.lookup("classification-rule.schema.json").contents["title"] == (
        "Deterministic Code Classification Rule"
    )
