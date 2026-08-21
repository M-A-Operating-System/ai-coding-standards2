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
  3. Identity is sound: every node id is unique across the taxonomy, carries
     the three-letter code for its level, and is never reused
  4. Paths are positional: each node declares the path its position implies,
     its own level, and the identifier of the node above it
  5. taxonomy.json domain, registry, mapping and rule sources point at files
     that exist
  6. Identifiers cited by implementations, runtimes, mappings, rules and
     examples resolve to a node declared in a domain file
  7. Facet values used by nodes are declared in the facet registry, and a
     single-valued facet carries at most one value
  8. Example implementation and runtime references resolve to the registries
  9. Lifecycle is coherent: a deprecated node names a replacement that
     resolves, and nothing active cites a deprecated node

Exits 0 if all checks pass, 1 if any error is found.
Prints findings to stderr, summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import re
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
    "facets/facets.json": "facets.schema.json",
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


ID_PATTERN = re.compile(r"^(FAM|CLS|SUB)[0-9]{6}$")

# The three-letter code records the level, not the domain or the subject. A node
# can therefore move between domains and keep its identity, which is the whole
# point of separating identity from location. Counters run per level across the
# whole taxonomy.
LEVEL_PREFIX = {"family": "FAM", "class": "CLS", "subclass": "SUB"}


def collect_nodes(loaded: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str], list[str]]:
    """
    Walk every domain file and index it two ways.

    Returns (by_id, path_to_id, errors).

    Identity and location are checked separately because they mean different
    things. The id is the primary key: unique across the taxonomy, carrying the
    three-letter code for its level, never reused. The path is where the node
    currently sits: it must match the position it occupies, or the composed
    lookup a consumer performs would miss it.
    """
    by_id: dict[str, dict] = {}
    path_to_id: dict[str, str] = {}
    errors: list[str] = []

    for domain in DOMAINS:
        rel = f"{domain}/{domain}.json"
        data = loaded.get(rel)
        if data is None:
            continue

        declared_domain = data.get("domain")
        if declared_domain != domain:
            errors.append(f"{rel}: domain is {declared_domain!r}, expected {domain!r}")

        def visit(node: dict, path: str, parent_ref: str, level: str) -> None:
            node_id = node.get("id")
            errors.extend(_check_identity(rel, node, node_id, level, by_id))
            errors.extend(_check_position(rel, node, node_id, path, parent_ref, level))
            if isinstance(node_id, str):
                by_id[node_id] = {**node, "_file": rel}
                declared_path = node.get("path")
                if isinstance(declared_path, str):
                    if declared_path in path_to_id:
                        errors.append(
                            f"{rel}: path {declared_path!r} is claimed by both "
                            f"{path_to_id[declared_path]} and {node_id}"
                        )
                    path_to_id[declared_path] = node_id
                for former in node.get("former_paths") or []:
                    path_to_id.setdefault(former, node_id)

        # A domain is a field, not a node, so a family's parent is the domain
        # itself rather than an identifier one rung above it.
        for family_key, family in (data.get("families") or {}).items():
            fpath = f"{domain}/{family_key}"
            visit(family, fpath, domain, "family")
            fid = family.get("id")

            for class_key, klass in (family.get("classes") or {}).items():
                cpath = f"{fpath}/{class_key}"
                visit(klass, cpath, fid, "class")
                cid = klass.get("id")

                for sub_key, sub in (klass.get("subclasses") or {}).items():
                    visit(sub, f"{cpath}/{sub_key}", cid, "subclass")

    return by_id, path_to_id, errors


def _check_identity(
    filename: str, node: dict, node_id, level: str, seen: dict[str, dict]
) -> list[str]:
    """The id is a primary key. Unique, correctly formed, never reused."""
    errors: list[str] = []
    if not isinstance(node_id, str) or not ID_PATTERN.match(node_id):
        errors.append(f"{filename}: {node.get('path', '?')}: id {node_id!r} is not a valid identifier")
        return errors
    expected_prefix = LEVEL_PREFIX[level]
    if not node_id.startswith(expected_prefix):
        errors.append(
            f"{filename}: {node_id}: identifier prefix does not match level "
            f"{level!r} (expected {expected_prefix}NNNNNN)"
        )
    if node_id in seen:
        errors.append(
            f"{filename}: {node_id}: identifier already used by "
            f"{seen[node_id].get('path', '?')} - identifiers are never reused"
        )
    return errors


def _check_position(
    filename: str, node: dict, node_id, path: str, parent_ref: str, level: str
) -> list[str]:
    """The path and parent must match the position the node occupies."""
    errors: list[str] = []
    ref = node_id if isinstance(node_id, str) else path
    if node.get("path") != path:
        errors.append(f"{filename}: {ref}: path is {node.get('path')!r}, expected {path!r}")
    if node.get("parent") != parent_ref:
        errors.append(f"{filename}: {ref}: parent is {node.get('parent')!r}, expected {parent_ref!r}")
    if node.get("level") != level:
        errors.append(f"{filename}: {ref}: level is {node.get('level')!r}, expected {level!r}")
    return errors


def check_facets(by_id: dict[str, dict], loaded: dict[str, dict]) -> list[str]:
    """
    Every facet a node carries must be declared, with a declared value, and a
    single-valued facet must carry at most one.
    """
    errors: list[str] = []
    registry = (loaded.get("facets/facets.json") or {}).get("facets") or {}
    for node_id, node in sorted(by_id.items()):
        for facet, values in (node.get("facets") or {}).items():
            spec = registry.get(facet)
            if spec is None:
                errors.append(f"{node['_file']}: {node_id}: facet {facet!r} is not in the facet registry")
                continue
            if not spec.get("multi_valued", False) and len(values) > 1:
                errors.append(
                    f"{node['_file']}: {node_id}: facet {facet!r} is single-valued "
                    f"but carries {len(values)} values"
                )
            for value in values:
                if value not in (spec.get("values") or {}):
                    errors.append(
                        f"{node['_file']}: {node_id}: facet {facet!r} value {value!r} is not declared"
                    )
    return errors


def check_lifecycle(by_id: dict[str, dict]) -> list[str]:
    """A deprecated node names a live replacement; nothing else is required."""
    errors: list[str] = []
    for node_id, node in sorted(by_id.items()):
        status = node.get("status")
        replaced = node.get("replaced_by")
        if status == "deprecated":
            if not replaced:
                errors.append(f"{node['_file']}: {node_id}: deprecated but names no replaced_by")
            elif replaced not in by_id:
                errors.append(f"{node['_file']}: {node_id}: replaced_by {replaced!r} does not resolve")
            elif by_id[replaced].get("status") == "deprecated":
                errors.append(f"{node['_file']}: {node_id}: replaced_by {replaced!r} is itself deprecated")
        elif replaced:
            errors.append(f"{node['_file']}: {node_id}: names replaced_by but status is {status!r}")
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
    """Both the canonical classes a technology realises and the code roles it relates to."""
    refs: list[tuple[str, str]] = []
    for key, impl in (data.get("implementations") or {}).items():
        for ref in impl.get("implements") or []:
            refs.append((f"implementations/{key}.implements", ref))
        for ref in impl.get("related_code") or []:
            refs.append((f"implementations/{key}.related_code", ref))
    return refs


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
    loaded: dict[str, dict], by_id: dict[str, dict], path_to_id: dict[str, str]
) -> list[str]:
    """
    Every cited identifier must resolve to a node declared in a domain file.

    References are identifiers, not paths - everything points at identity so a
    rename never invalidates a citation. A reference that looks like a path is
    reported with the identifier it should have been written as, which is the
    likely mistake once identity and location are separate.
    """
    errors: list[str] = []
    for rel, extractor in CANONICAL_REF_EXTRACTORS.items():
        data = loaded.get(rel)
        if data is None:
            continue
        for location, ref in extractor(data):
            if ref in by_id:
                if by_id[ref].get("status") == "deprecated":
                    errors.append(
                        f"{rel}: {location}: {ref} is deprecated - "
                        f"use {by_id[ref].get('replaced_by')!r}"
                    )
                continue
            if ref in path_to_id:
                errors.append(
                    f"{rel}: {location}: {ref!r} is a path, not an identifier - "
                    f"reference {path_to_id[ref]} instead"
                )
            else:
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
    Run all checks. Returns (errors, file_count, node_count).
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

    by_id, path_to_id, node_errors = collect_nodes(loaded)
    all_errors += node_errors
    all_errors += check_sources(taxonomy_dir, loaded)
    all_errors += check_canonical_references(loaded, by_id, path_to_id)
    all_errors += check_registry_references(loaded)
    all_errors += check_facets(by_id, loaded)
    all_errors += check_lifecycle(by_id)

    return all_errors, len(loaded), len(by_id)


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

    print(f"OK: {file_count} files, {id_count} nodes ({args.taxonomy_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
