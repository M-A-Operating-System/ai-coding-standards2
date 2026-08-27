#!/usr/bin/env python3
"""Generate the human-readable reference for the target pipeline schema.

P-2 applied to the schema itself: the target shape of pipeline.json is
authoritative as JSON Schema
(docs/product/orchestrator/schema/pipeline.schema.json), and the written
reference a person reads is generated from it rather than hand-maintained
beside it. If a fact is not in the schema's own type/required/description,
it does not appear here.

This is the TARGET schema. It does not describe pipeline/pipeline.json as it
exists today -- see docs/product/orchestrator/gap_analysis.md for that
distance. pipeline/schemas/pipeline.schema.json (the live schema) is
untouched by this generator.

Idempotent by construction -- output depends only on the schema file, so
running twice produces byte-identical output. CI regenerates and fails the
build if a committed file differs.

Usage:
    python3 pipeline/generators/generate_schema_reference.py            # write
    python3 pipeline/generators/generate_schema_reference.py --check    # verify only
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_JSON = REPO_ROOT / "docs" / "product" / "orchestrator" / "schema" / "pipeline.schema.json"
OUT_DIR = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated"
OUT_FILE = "pipeline-schema-reference.md"

BANNER = (
    "<!-- GENERATED FILE -- DO NOT EDIT.\n"
    "     Source: docs/product/orchestrator/schema/pipeline.schema.json\n"
    "     Generator: pipeline/generators/generate_schema_reference.py\n"
    "     Regenerate: python3 pipeline/generators/generate_schema_reference.py -->\n"
)


def _load(path):
    with path.open() as fh:
        return json.load(fh)


def _resolve(schema, node):
    """Follow a single $ref against the schema's own definitions."""
    if isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/definitions/"), f"unsupported $ref: {ref}"
        return schema["definitions"][ref[len("#/definitions/") :]]
    return node


def _type_label(node):
    t = node.get("type")
    if isinstance(t, list):
        return " or ".join(t)
    if t == "array":
        items = node.get("items", {})
        inner = items.get("type", "object" if "$ref" in items or "properties" in items else "any")
        return f"array of {inner}"
    if t == "object" and "oneOf" in node:
        return "object (one of)"
    return t or "any"


def _field_rows(schema, obj_schema, required):
    rows = []
    for name, prop in obj_schema.get("properties", {}).items():
        prop = _resolve(schema, prop)
        req = "yes" if name in required else "no"
        desc = (prop.get("description") or "").strip()
        default = prop.get("default")
        if default is not None:
            desc = f"{desc} Default: `{default}`.".strip()
        enum = prop.get("enum")
        if enum:
            desc = f"{desc} One of: {', '.join(f'`{v}`' for v in enum)}.".strip()
        rows.append((f"`{name}`", _type_label(prop), req, desc))
    return rows


def _describe_condition(cond):
    """Describe an if-condition of the shape this schema actually uses:
    {"properties": {field: {"const": v}}} optionally wrapped in {"not": ...}
    and optionally paired with {"required": [field]}."""
    negated = "not" in cond
    inner = cond["not"] if negated else cond
    (field, field_schema), = inner.get("properties", {}).items()
    const = json.dumps(field_schema["const"])
    if negated:
        return f"`{field}` is not `{const}` (including when `{field}` is absent)"
    return f"`{field}` is `{const}`"


def _describe_then(then):
    """Describe a then-branch: top-level required fields, plus any nested
    properties.<field>.required (one level, which is all this schema uses)."""
    parts = []
    top_required = then.get("required")
    if top_required:
        parts.append("requires " + ", ".join(f"`{f}`" for f in top_required))
    for name, sub in then.get("properties", {}).items():
        sub_required = sub.get("required")
        if sub_required:
            parts.append(
                f"`{name}` must include " + ", ".join(f"`{f}`" for f in sub_required)
            )
    return "; ".join(parts)


def _render_conditional_requirements(obj_schema):
    """Render allOf if/then pairs as plain conditional-requirement notes.
    Purpose-built for this schema's conditionals (const-equality triggers,
    required-field consequences) -- not a general JSON Schema renderer."""
    entries = obj_schema.get("allOf")
    if not entries:
        return []
    lines = ["**Conditional requirements:**", ""]
    for entry in entries:
        condition = _describe_condition(entry["if"])
        consequence = _describe_then(entry["then"])
        if consequence:
            lines.append(f"- When {condition}: {consequence}.")
    lines.append("")
    return lines


def _render_object_section(schema, title, obj_schema, level=3, seen=None):
    """Render an object schema as a heading, an intro, a field table, and a
    recursive subsection for every nested object-typed field."""
    seen = seen if seen is not None else set()
    lines = ["#" * level + f" {title}", ""]
    desc = (obj_schema.get("description") or "").strip()
    if desc:
        lines += [desc, ""]

    required = set(obj_schema.get("required", []))

    if "oneOf" in obj_schema:
        lines += [
            "Exactly one of the following shapes:",
            "",
        ]
        for i, alt in enumerate(obj_schema["oneOf"], 1):
            alt = _resolve(schema, alt)
            alt_req = set(alt.get("required", []))
            rows = _field_rows(schema, alt, alt_req)
            lines += [f"**Shape {i}:**", "", "| Field | Type | Required | Description |", "|---|---|---|---|"]
            lines += [f"| {f} | {t} | {r} | {d} |" for f, t, r, d in rows]
            lines += [""]
        return lines

    rows = _field_rows(schema, obj_schema, required)
    if rows:
        lines += ["| Field | Type | Required | Description |", "|---|---|---|---|"]
        lines += [f"| {f} | {t} | {r} | {d} |" for f, t, r, d in rows]
        lines += [""]

    lines += _render_conditional_requirements(obj_schema)

    # Recurse into nested object-typed properties, once each.
    for name, prop in obj_schema.get("properties", {}).items():
        prop = _resolve(schema, prop)
        if prop.get("type") == "object" and ("properties" in prop or "oneOf" in prop):
            key = (title, name)
            if key in seen:
                continue
            seen.add(key)
            lines += _render_object_section(schema, f"{title} -- `{name}`", prop, level + 1, seen)

    return lines


def render(schema):
    lines = [BANNER, "# Target Pipeline Schema", ""]
    lines += [
        (schema.get("description") or "").strip(),
        "",
        "This is the target. `pipeline/schemas/pipeline.schema.json` governs",
        "the pipeline.json that exists today; see",
        "[`gap_analysis.md`](../gap_analysis.md) for the distance between them.",
        "",
        "## Top level",
        "",
    ]
    top_required = set(schema.get("required", []))
    rows = _field_rows(schema, schema, top_required)
    lines += ["| Field | Type | Required | Description |", "|---|---|---|---|"]
    lines += [f"| {f} | {t} | {r} | {d} |" for f, t, r, d in rows]
    lines += [""]

    flow = schema["definitions"]["flow"]
    lines += _render_object_section(schema, "A flow", flow, level=2)

    step = schema["definitions"]["step"]
    lines += _render_object_section(schema, "A step", step, level=2)

    return "\n".join(lines).rstrip() + "\n"


def build():
    schema = _load(SCHEMA_JSON)
    return {OUT_FILE: render(schema)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed file matches the regenerated output; write nothing",
    )
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, content in build().items():
        target = OUT_DIR / name
        if args.check:
            current = target.read_text() if target.exists() else None
            if current != content:
                stale.append(name)
        else:
            target.write_text(content)
            print(f"wrote {target.relative_to(REPO_ROOT)}")

    if args.check:
        if stale:
            print("STALE (regenerate with generate_schema_reference.py): " + ", ".join(stale))
            return 1
        print("generated schema reference is current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
