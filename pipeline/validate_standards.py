#!/usr/bin/env python3
"""
validate_standards.py — validate standards/*.json files against the schema
and check cross-file referential integrity.

Usage:
    python pipeline/validate_standards.py [--standards-dir PATH]

Checks:
  1. JSON is parseable
  2. Each file conforms to the StandardsFile or AdrsFile JSON schema
  3. STD ID prefix matches the file's declared category (e.g. process → STD-PROC-*)
  4. No duplicate STD IDs across all files
  5. instantiates and related IDs resolve to a known standard in the loaded set
  6. ADR authorises_exception_to IDs exist and are adr_overridable: true

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
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(2)


HERE = Path(__file__).parent
DEFAULT_STANDARDS_DIR = HERE.parent / "standards"
DEFAULT_SCHEMA = HERE / "schemas" / "standards.schema.json"

CATEGORY_TO_PREFIX: dict[str, str] = {
    "architecture": "STD-ARCH",
    "security": "STD-SEC",
    "testing": "STD-TEST",
    "process": "STD-PROC",
    "data": "STD-DATA",
    "ux-design": "STD-UX",
    "documentation": "STD-DOC",
}


def _load(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def check_schema(data: dict, schema: dict, filename: str) -> list[str]:
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    return [
        f"{filename}: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    ]


def check_id_prefix(data: dict, filename: str) -> list[str]:
    """Every STD ID in a file must start with the category's expected prefix."""
    errors = []
    category = data.get("category")
    prefix = CATEGORY_TO_PREFIX.get(category or "")
    if not prefix:
        return []
    for std in data.get("standards", []):
        std_id = std.get("id", "")
        if not std_id.startswith(f"{prefix}-"):
            errors.append(
                f"{filename}: {std_id!r}: ID prefix does not match category "
                f"{category!r} (expected {prefix}-NNN)"
            )
    return errors


def collect_all_standards(
    loaded: list[tuple[str, dict]],
) -> tuple[dict[str, dict], list[str]]:
    """
    Build filename → standard mapping keyed by STD ID.
    Return (id_map, duplicate_errors).
    """
    errors: list[str] = []
    id_map: dict[str, dict] = {}
    for filename, data in loaded:
        for std in data.get("standards", []):
            std_id = std.get("id")
            if not std_id:
                continue
            if std_id in id_map:
                errors.append(
                    f"duplicate STD ID {std_id!r} — "
                    f"already declared in {id_map[std_id]['_file']}, "
                    f"re-declared in {filename}"
                )
            else:
                id_map[std_id] = {**std, "_file": filename}
    return id_map, errors


def check_references(
    loaded: list[tuple[str, dict]],
    id_map: dict[str, dict],
) -> list[str]:
    """Check instantiates and related IDs resolve to a known standard."""
    errors: list[str] = []
    known = set(id_map)
    for filename, data in loaded:
        for std in data.get("standards", []):
            std_id = std.get("id", "?")
            inst = std.get("instantiates")
            if inst and inst not in known:
                errors.append(
                    f"{filename}: {std_id}: instantiates {inst!r} "
                    f"— ID not found in any loaded standards file"
                )
            for rel in std.get("related", []):
                if rel not in known:
                    errors.append(
                        f"{filename}: {std_id}: related {rel!r} "
                        f"— ID not found in any loaded standards file"
                    )
    return errors


def check_adrs(
    loaded: list[tuple[str, dict]],
    id_map: dict[str, dict],
) -> list[str]:
    """
    Check ADR authorises_exception_to entries:
    - referenced ID must exist
    - referenced standard must be adr_overridable: true
    """
    errors: list[str] = []
    known = set(id_map)
    for filename, data in loaded:
        for adr in data.get("adrs", []):
            adr_id = adr.get("id", "?")
            for std_id in adr.get("authorises_exception_to", []):
                if std_id not in known:
                    errors.append(
                        f"{filename}: {adr_id}: authorises_exception_to {std_id!r} "
                        f"— ID not found in any loaded standards file"
                    )
                elif not id_map[std_id].get("adr_overridable", False):
                    errors.append(
                        f"{filename}: {adr_id}: authorises_exception_to {std_id!r} "
                        f"— that standard is adr_overridable: false and cannot be waived by an ADR"
                    )
    return errors


def validate(standards_dir: Path, schema_path: Path) -> tuple[list[str], int, int, int]:
    """
    Run all checks. Returns (errors, file_count, std_count, adr_count).
    """
    schema = _load(schema_path)
    json_files = sorted(standards_dir.glob("*.json"))

    if not json_files:
        return [f"no JSON files found in {standards_dir}"], 0, 0, 0

    loaded: list[tuple[str, dict]] = []
    all_errors: list[str] = []

    for path in json_files:
        try:
            data = _load(path)
        except json.JSONDecodeError as exc:
            all_errors.append(f"{path.name}: invalid JSON — {exc}")
            continue

        all_errors += check_schema(data, schema, path.name)
        all_errors += check_id_prefix(data, path.name)
        loaded.append((path.name, data))

    id_map, dup_errors = collect_all_standards(loaded)
    all_errors += dup_errors
    all_errors += check_references(loaded, id_map)
    all_errors += check_adrs(loaded, id_map)

    std_count = sum(len(d.get("standards", [])) for _, d in loaded)
    adr_count = sum(len(d.get("adrs", [])) for _, d in loaded)
    return all_errors, len(loaded), std_count, adr_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate standards/*.json files against the schema and each other."
    )
    parser.add_argument(
        "--standards-dir",
        type=Path,
        default=DEFAULT_STANDARDS_DIR,
        help=f"Directory containing standards JSON files (default: {DEFAULT_STANDARDS_DIR})",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"Path to standards.schema.json (default: {DEFAULT_SCHEMA})",
    )
    args = parser.parse_args()

    errors, file_count, std_count, adr_count = validate(args.standards_dir, args.schema)

    if errors:
        print(
            f"FAIL: {len(errors)} error(s) across {file_count} file(s) "
            f"in {args.standards_dir}",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"OK: {file_count} files · {std_count} standards · {adr_count} ADRs "
        f"({args.standards_dir})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
