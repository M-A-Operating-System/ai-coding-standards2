#!/usr/bin/env python3
"""
validate_taxonomy.py - validate taxonomy/*.json files against the schemas in
taxonomy/schemas/ and check cross-file referential integrity.

Usage:
    python pipeline/validate_taxonomy.py [--taxonomy-dir PATH]

The taxonomy is the vocabulary that automated stack-inventory and code-analysis
processes classify into. A dangling reference here is a silently wrong
inventory downstream, so structural conformance alone is not enough - every
canonical ID a registry, mapping, rule or example cites must resolve to a real
node in a domain file.

Checks:
  1. JSON is parseable
  2. Every JSON file under the taxonomy is mapped to a schema and conforms to
     it. An unmapped file is an error, never a silent skip.
  3. Domain hierarchy is self-consistent: each family/class/subclass declares
     the id its position implies, the parent above it, and its own level
  4. taxonomy.json domain, registry, mapping and rule sources point at files
     that exist
  5. Canonical IDs cited by implementations, runtimes, mappings, rules and
     examples resolve to a node declared in a domain file
  6. Example implementation and runtime references resolve to the registries

Exits 0 if all checks pass, 1 if any error is found.
Prints findings to stderr, summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import jsonschema
    from referencing import Registry, Resource
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(2)


HERE = Path(__file__).parent
DEFAULT_TAXONOMY_DIR = HERE.parent / "taxonomy"

SCHEMA_DIRNAME = "schemas"

# Semantic domains. Each contributes canonical IDs that everything else cites.
DOMAINS = ("architecture", "patterns", "code", "concepts")

# Explicit file-to-schema map, keyed by path relative to the taxonomy root.
# Every JSON file under the taxonomy must appear here or in EXEMPT_FROM_SCHEMA;
# see check_schema_coverage for why an unmapped file is a failure.
FILE_SCHEMAS: dict[str, str] = {
    "taxonomy.json": "taxonomy.schema.json",
    "architecture/architecture.json": "domain-taxonomy.schema.json",
    "patterns/patterns.json": "domain-taxonomy.schema.json",
    "code/code.json": "domain-taxonomy.schema.json",
    "concepts/concepts.json": "domain-taxonomy.schema.json",
    "implementations/implementations.json": "implementations.schema.json",
    "runtimes/runtimes.json": "runtimes.schema.json",
    "mappings/calm-to-canonical.json": "calm-mapping.schema.json",
    "mappings/cross-domain.json": "cross-domain.schema.json",
    "mappings/semantic-analysis-boundary.json": "semantic-analysis-boundary.schema.json",
    "rules/code-classification-rules.json": "classification-rules-file.schema.json",
}

# Files deliberately exempt from schema conformance, with the reason. Examples
# are illustrations of consumer output rather than taxonomy content, and each
# has its own shape; they are still checked for parseability and for
# referential integrity, so nothing here escapes validation entirely.
EXEMPT_FROM_SCHEMA: dict[str, str] = {
    "examples/classified-code-symbol.json": "illustrative consumer output, shape is not taxonomy content",
    "examples/observed-booking-db.json": "illustrative consumer output, shape is not taxonomy content",
}


def _load(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def build_schema_registry(schema_dir: Path) -> Registry:
    """
    Register every schema under its declared $id so sibling $refs resolve.

    The taxonomy schemas use bare relative $ids (classification-rule.schema.json,
    not a URL), so without a local registry jsonschema treats a $ref as a remote
    retrieval and fails.
    """
    registry = Registry()
    for path in sorted(schema_dir.glob("*.json")):
        schema = _load(path)
        uri = schema.get("$id") or path.name
        registry = registry.with_resource(uri, Resource.from_contents(schema))
    return registry


def _validator_for(schema: dict, registry: Registry) -> jsonschema.protocols.Validator:
    """Pick the validator class the schema declares, rather than assuming a draft."""
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema, registry=registry)


def discover_json_files(taxonomy_dir: Path) -> list[Path]:
    """Every JSON file under the taxonomy, excluding the schemas themselves."""
    schema_dir = taxonomy_dir / SCHEMA_DIRNAME
    return sorted(
        p for p in taxonomy_dir.rglob("*.json") if schema_dir not in p.parents
    )


def check_schema_coverage(taxonomy_dir: Path, files: list[Path]) -> list[str]:
    """
    Every discovered file must be mapped or explicitly exempt, and every mapped
    path must exist.

    Without this, adding a file to the taxonomy would quietly bypass validation
    - the failure mode this validator exists to prevent.
    """
    errors: list[str] = []
    discovered = {p.relative_to(taxonomy_dir).as_posix() for p in files}
    declared = set(FILE_SCHEMAS) | set(EXEMPT_FROM_SCHEMA)

    for rel in sorted(discovered - declared):
        errors.append(
            f"{rel}: no schema mapped - add it to FILE_SCHEMAS, or to "
            f"EXEMPT_FROM_SCHEMA with a reason"
        )
    for rel in sorted(declared - discovered):
        errors.append(f"{rel}: declared in the schema map but no such file exists")
    return errors


def check_schema(
    data: dict, schema: dict, filename: str, registry: Registry
) -> list[str]:
    validator = _validator_for(schema, registry)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    return [
        f"{filename}: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    ]


def collect_canonical_ids(
    loaded: dict[str, dict],
) -> tuple[set[str], list[str]]:
    """
    Walk every domain file and collect the canonical ID of each family, class
    and subclass. Returns (ids, hierarchy_errors).

    The declared id, parent and level are checked against the position the node
    actually occupies. A node whose id disagrees with its position would be
    unreachable by the composed `<domain>/<family>/<class>/<subclass>` lookup
    every consumer uses.
    """
    ids: set[str] = set()
    errors: list[str] = []

    for domain in DOMAINS:
        rel = f"{domain}/{domain}.json"
        data = loaded.get(rel)
        if data is None:
            continue

        declared_domain = data.get("domain")
        if declared_domain != domain:
            errors.append(
                f"{rel}: domain is {declared_domain!r}, expected {domain!r}"
            )

        for family_key, family in (data.get("families") or {}).items():
            family_id = f"{domain}/{family_key}"
            errors += _check_node(rel, family, family_id, domain, "family")
            ids.add(family_id)

            for class_key, klass in (family.get("classes") or {}).items():
                class_id = f"{family_id}/{class_key}"
                errors += _check_node(rel, klass, class_id, family_id, "class")
                ids.add(class_id)

                for sub_key, sub in (klass.get("subclasses") or {}).items():
                    sub_id = f"{class_id}/{sub_key}"
                    errors += _check_node(rel, sub, sub_id, class_id, "subclass")
                    ids.add(sub_id)

    return ids, errors


def _check_node(
    filename: str, node: dict, expected_id: str, expected_parent: str, level: str
) -> list[str]:
    errors: list[str] = []
    actual_id = node.get("id")
    if actual_id != expected_id:
        errors.append(
            f"{filename}: {level} at {expected_id!r} declares id {actual_id!r}"
        )
    actual_parent = node.get("parent")
    if actual_parent != expected_parent:
        errors.append(
            f"{filename}: {expected_id}: parent is {actual_parent!r}, "
            f"expected {expected_parent!r}"
        )
    actual_level = node.get("level")
    if actual_level != level:
        errors.append(
            f"{filename}: {expected_id}: level is {actual_level!r}, expected {level!r}"
        )
    return errors


def check_sources(taxonomy_dir: Path, loaded: dict[str, dict]) -> list[str]:
    """Every source path registered in taxonomy.json must exist on disk."""
    errors: list[str] = []
    root = loaded.get("taxonomy.json")
    if root is None:
        return errors

    for section in ("domains", "registries", "mappings", "rules"):
        for name, entry in (root.get(section) or {}).items():
            source = (entry or {}).get("source")
            if not source:
                errors.append(f"taxonomy.json: {section}/{name}: no source declared")
                continue
            if not (taxonomy_dir / source).is_file():
                errors.append(
                    f"taxonomy.json: {section}/{name}: source {source!r} does not exist"
                )
    return errors


def _refs_implementations(data: dict) -> list[tuple[str, str]]:
    return [
        (f"implementations/{key}", ref)
        for key, impl in (data.get("implementations") or {}).items()
        for ref in (impl.get("implements") or [])
    ]


def _refs_runtimes(data: dict) -> list[tuple[str, str]]:
    return [
        (f"providers/{provider}/services/{service}", ref)
        for provider, pdata in (data.get("providers") or {}).items()
        for service, sdata in (pdata.get("services") or {}).items()
        for ref in (sdata.get("supports") or [])
    ]


def _refs_calm(data: dict) -> list[tuple[str, str]]:
    return [
        (f"mappings/{node_type}", ref)
        for node_type, refs in (data.get("mappings") or {}).items()
        for ref in refs or []
    ]


def _refs_cross_domain(data: dict) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for index, rel in enumerate(data.get("relationships") or []):
        for side in ("from", "to"):
            value = rel.get(side)
            if value:
                refs.append((f"relationships[{index}].{side}", value))
    return refs


def _refs_rules(data: dict) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for rule in data.get("rules") or []:
        rule_id = rule.get("id", "?")
        for domain, assigned in (rule.get("assign") or {}).items():
            for ref in assigned or []:
                refs.append((f"{rule_id}.assign.{domain}", ref))
    return refs


def _refs_classified_symbol(data: dict) -> list[tuple[str, str]]:
    return [
        (f"classifications[{index}].taxonomy_id", entry["taxonomy_id"])
        for index, entry in enumerate(data.get("classifications") or [])
        if entry.get("taxonomy_id")
    ]


def _refs_observed(data: dict) -> list[tuple[str, str]]:
    value = data.get("classification")
    return [("classification", value)] if value else []


# Files that cite canonical IDs, and how to pull those citations out of each.
CANONICAL_REF_EXTRACTORS = {
    "implementations/implementations.json": _refs_implementations,
    "runtimes/runtimes.json": _refs_runtimes,
    "mappings/calm-to-canonical.json": _refs_calm,
    "mappings/cross-domain.json": _refs_cross_domain,
    "rules/code-classification-rules.json": _refs_rules,
    "examples/classified-code-symbol.json": _refs_classified_symbol,
    "examples/observed-booking-db.json": _refs_observed,
}


def check_canonical_references(
    loaded: dict[str, dict], canonical_ids: set[str]
) -> list[str]:
    """Every cited canonical ID must resolve to a node declared in a domain file."""
    errors: list[str] = []
    for rel, extractor in CANONICAL_REF_EXTRACTORS.items():
        data = loaded.get(rel)
        if data is None:
            continue
        for location, ref in extractor(data):
            if ref not in canonical_ids:
                errors.append(
                    f"{rel}: {location}: {ref!r} - not declared in any domain file"
                )
    return errors


def check_registry_references(loaded: dict[str, dict]) -> list[str]:
    """
    Example implementation and runtime citations must resolve to the registries.

    Runtime references use `<provider>/<service>`, matching the two-level shape
    of runtimes.json.
    """
    errors: list[str] = []
    example = loaded.get("examples/observed-booking-db.json")
    if example is None:
        return errors

    rel = "examples/observed-booking-db.json"
    implementations = (
        loaded.get("implementations/implementations.json") or {}
    ).get("implementations") or {}
    providers = (loaded.get("runtimes/runtimes.json") or {}).get("providers") or {}

    impl = example.get("implementation")
    if impl and impl not in implementations:
        errors.append(f"{rel}: implementation {impl!r} - not in the implementation registry")

    runtime = example.get("runtime")
    if runtime:
        provider, _, service = runtime.partition("/")
        services = (providers.get(provider) or {}).get("services") or {}
        if not service or service not in services:
            errors.append(f"{rel}: runtime {runtime!r} - not in the runtime registry")

    return errors


def validate(taxonomy_dir: Path) -> tuple[list[str], int, int]:
    """
    Run all checks. Returns (errors, file_count, canonical_id_count).
    """
    if not taxonomy_dir.is_dir():
        return [f"taxonomy directory not found: {taxonomy_dir}"], 0, 0

    schema_dir = taxonomy_dir / SCHEMA_DIRNAME
    files = discover_json_files(taxonomy_dir)
    if not files:
        return [f"no JSON files found in {taxonomy_dir}"], 0, 0

    registry = build_schema_registry(schema_dir)
    all_errors: list[str] = check_schema_coverage(taxonomy_dir, files)
    loaded: dict[str, dict] = {}

    for path in files:
        rel = path.relative_to(taxonomy_dir).as_posix()
        try:
            data = _load(path)
        except json.JSONDecodeError as exc:
            all_errors.append(f"{rel}: invalid JSON - {exc}")
            continue
        loaded[rel] = data

        schema_name = FILE_SCHEMAS.get(rel)
        if schema_name is None:
            continue
        schema_path = schema_dir / schema_name
        if not schema_path.is_file():
            all_errors.append(f"{rel}: schema {schema_name!r} not found in {schema_dir}")
            continue
        all_errors += check_schema(data, _load(schema_path), rel, registry)

    canonical_ids, hierarchy_errors = collect_canonical_ids(loaded)
    all_errors += hierarchy_errors
    all_errors += check_sources(taxonomy_dir, loaded)
    all_errors += check_canonical_references(loaded, canonical_ids)
    all_errors += check_registry_references(loaded)

    return all_errors, len(loaded), len(canonical_ids)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate taxonomy JSON files against their schemas and each other."
    )
    parser.add_argument(
        "--taxonomy-dir",
        type=Path,
        default=DEFAULT_TAXONOMY_DIR,
        help=f"Root of the taxonomy folder (default: {DEFAULT_TAXONOMY_DIR})",
    )
    args = parser.parse_args()

    errors, file_count, id_count = validate(args.taxonomy_dir)

    if errors:
        print(
            f"FAIL: {len(errors)} error(s) across {file_count} file(s) "
            f"in {args.taxonomy_dir}",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"OK: {file_count} files, {id_count} canonical IDs ({args.taxonomy_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
