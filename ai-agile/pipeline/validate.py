#!/usr/bin/env python3
"""
validate.py — validate pipeline.json against the schema and check the
dependency graph is acyclic and references existing agents.

Usage:
    python ai-agile/pipeline/validate.py [--pipeline PATH]

Exits 0 if valid, 1 if not. Prints findings to stderr.
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
DEFAULT_PIPELINE = HERE / "pipeline.json"
DEFAULT_SCHEMA = HERE / "schemas" / "pipeline.schema.json"
DEFAULT_AGENTS_DIR = HERE.parent.parent / ".claude" / "agents"

VALID_MODELS = frozenset({
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
})


def _load(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def validate_schema(pipeline: dict, schema: dict) -> list[str]:
    """Return a list of schema-violation messages; empty if valid."""
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(pipeline), key=lambda e: e.path)
    return [f"{"/".join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors]


def validate_dependency_references(pipeline: dict) -> list[str]:
    """Every dependency must reference an agent declared in the same file."""
    errors = []
    agents = {a["agent"] for a in pipeline["pipeline"]}
    for entry in pipeline["pipeline"]:
        for dep in entry.get("dependencies", []):
            if dep not in agents:
                errors.append(
                    f"agent '{entry['agent']}' depends on unknown agent '{dep}'"
                )
    return errors


def validate_acyclic(pipeline: dict) -> list[str]:
    """Topological sort (Kahn's algorithm); report a cycle if one exists.

    indegree[n] = number of OPEN dependencies n still has. A node with
    indegree 0 has no remaining dependencies and is processable. We
    drain such nodes; each time we drain n, we decrement the indegree
    of every node that depends on n.
    """
    graph = {a["agent"]: list(a.get("dependencies", [])) for a in pipeline["pipeline"]}
    # Count only deps that exist in the graph (unknown deps are caught
    # by validate_dependency_references, not here).
    indegree = {n: sum(1 for d in deps if d in graph) for n, deps in graph.items()}
    queue = [n for n, d in indegree.items() if d == 0]
    visited = 0
    while queue:
        n = queue.pop()
        visited += 1
        for m, m_deps in graph.items():
            if n in m_deps:
                indegree[m] -= 1
                if indegree[m] == 0:
                    queue.append(m)
    if visited != len(graph):
        cyclic = [n for n, d in indegree.items() if d > 0]
        return [f"dependency graph has a cycle involving: {sorted(cyclic)}"]
    return []


def validate_agent_names_unique(pipeline: dict) -> list[str]:
    seen = set()
    dupes = []
    for entry in pipeline["pipeline"]:
        if entry["agent"] in seen:
            dupes.append(entry["agent"])
        seen.add(entry["agent"])
    return [f"duplicate agent name: {d}" for d in dupes]


def validate_agent_phase_prefix(pipeline: dict) -> list[str]:
    """The phase prefix in the agent name must equal the `phase` field.

    e.g. agent: "product-docs/prd-writer" must have phase: "product-docs".
    """
    errors = []
    for entry in pipeline["pipeline"]:
        agent_name = entry.get("agent", "")
        phase = entry.get("phase", "")
        if "/" not in agent_name:
            errors.append(
                f"agent '{agent_name}' is missing phase prefix; expected '{phase}/<short-name>'"
            )
            continue
        prefix, _, short = agent_name.partition("/")
        if prefix != phase:
            errors.append(
                f"agent '{agent_name}' phase prefix '{prefix}' does not match phase field '{phase}'"
            )
        if not short:
            errors.append(
                f"agent '{agent_name}' has empty short-name after the phase prefix"
            )
    return errors


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML-like frontmatter between --- delimiters (scalars + inline lists)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}
    result: dict = {}
    for line in lines[1:end]:
        if ":" not in line or line.startswith(" "):
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not key or not raw or raw == ">":
            continue
        if raw.startswith("[") and raw.endswith("]"):
            result[key] = [x.strip() for x in raw[1:-1].split(",") if x.strip()]
        else:
            result[key] = raw
    return result


def validate_agent_files(pipeline: dict, agents_dir: Path) -> list[str]:
    """For each agent in the pipeline, verify the prompt file exists and
    declares a valid model in its frontmatter.

    Only runs when agents_dir exists on disk; silently passes when the
    directory is absent (e.g. consuming repos that haven't synced yet).
    """
    if not agents_dir.is_dir():
        return []
    errors = []
    for entry in pipeline["pipeline"]:
        # Script steps run a bash script directly — no agent prompt file.
        if entry.get("type") == "script":
            continue
        agent_name = entry["agent"]
        agent_file = agents_dir / f"{agent_name}.md"
        if not agent_file.exists():
            errors.append(
                f"agent '{agent_name}': prompt file not found at {agent_file.relative_to(agents_dir.parent.parent)}"
            )
            continue
        fm = _parse_frontmatter(agent_file.read_text())
        model = fm.get("model")
        if not model:
            errors.append(
                f"agent '{agent_name}': missing 'model' field in frontmatter"
            )
        elif model not in VALID_MODELS:
            errors.append(
                f"agent '{agent_name}': model '{model}' not in approved set "
                f"({', '.join(sorted(VALID_MODELS))})"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate pipeline.json")
    parser.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument(
        "--agents-dir",
        type=Path,
        default=DEFAULT_AGENTS_DIR,
        help="Directory containing agent prompt files (default: .claude/agents/). "
             "Pass an empty string to skip agent file validation.",
    )
    args = parser.parse_args()

    pipeline = _load(args.pipeline)
    schema = _load(args.schema)

    all_errors = []
    all_errors += validate_schema(pipeline, schema)
    all_errors += validate_agent_names_unique(pipeline)
    all_errors += validate_agent_phase_prefix(pipeline)
    all_errors += validate_dependency_references(pipeline)
    all_errors += validate_acyclic(pipeline)
    if args.agents_dir:
        all_errors += validate_agent_files(pipeline, args.agents_dir)

    if all_errors:
        print(f"FAIL: {args.pipeline}", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"OK: {args.pipeline} ({len(pipeline['pipeline'])} agents)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
