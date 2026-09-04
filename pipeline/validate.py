#!/usr/bin/env python3
"""
validate.py — validate pipeline.json against the schema, then check what the
schema cannot express.

The JSON Schema says what shape the file has. Everything below is a claim the
schema has no way to state: that the dependency graph is acyclic and names
steps that exist, that every agent prompt and every named script is on disk,
that every naming pattern uses a token the orchestrator can resolve, and that
no step's declared allowances cover a label only the orchestrator may write.
All of it serves AS-1 — pipeline.json is the authoritative definition, so a
definition it cannot honour must fail here, not partway through a run.

AS-3's structural thinness (a command names one target and contains no
procedure, conditional or retry loop) is deliberately NOT checked here: it is
a check over `.claude/commands/`, not over pipeline.json, and it already lives
in `tests/test_command_thinness.py` and `tests/test_promise_conformance.py`.
Two implementations of one check drift; one is enough.

Usage:
    python pipeline/validate.py [--pipeline PATH]

Exits 0 if valid, 1 if not. Prints findings to stderr.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
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
DEFAULT_AGENTS_DIR = HERE.parent / ".claude" / "agents"
DEFAULT_REPO_ROOT = HERE.parent
DEFAULT_STATUSES = HERE / "statuses.json"

# The tokens pipeline_orchestrator.resolve_naming_pattern can substitute. A
# branch pattern using anything else raises mid-flow rather than at load, so
# it is caught here instead (AS-1: a definition the file cannot express is a
# file that does not parse, not a failure to discover later).
NAMING_TOKENS = frozenset({"number", "parent_number"})
_NAMING_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

VALID_MODELS = frozenset({
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
})


def _load(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def steps(pipeline: dict) -> list[dict]:
    """Every step in the file, in declaration order, across all flows.

    pipeline.json declares flows, not a flow (PRODUCT.md, "The pipeline
    defines flows, not a flow"); the checks below are about steps, so they
    walk the flows once here rather than each knowing the file's shape.
    """
    out: list[dict] = []
    for flow in (pipeline.get("flows") or {}).values():
        out.extend(flow.get("steps") or [])
    return out


def flow_of(pipeline: dict, step: dict) -> str:
    """The name of the flow a step was declared in."""
    for name, flow in (pipeline.get("flows") or {}).items():
        if step in (flow.get("steps") or []):
            return name
    return "<unknown>"


def validate_schema(pipeline: dict, schema: dict) -> list[str]:
    """Return a list of schema-violation messages; empty if valid."""
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(pipeline), key=lambda e: e.path)
    return [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors]


def validate_dependency_references(pipeline: dict) -> list[str]:
    """Every dependency must reference an agent declared in the same file."""
    errors = []
    for flow_name, flow in (pipeline.get("flows") or {}).items():
        # A step depends on other steps in its OWN flow (the schema:
        # "Other steps in this flow that must be complete first").
        in_flow = {s["agent"] for s in (flow.get("steps") or [])}
        for entry in flow.get("steps") or []:
            for dep in entry.get("dependencies", []):
                if dep not in in_flow:
                    errors.append(
                        f"step '{entry['agent']}' in flow '{flow_name}' depends on "
                        f"'{dep}', which is not a step of that flow"
                    )
    return errors


def validate_acyclic(pipeline: dict) -> list[str]:
    """Topological sort (Kahn's algorithm); report a cycle if one exists.

    indegree[n] = number of OPEN dependencies n still has. A node with
    indegree 0 has no remaining dependencies and is processable. We
    drain such nodes; each time we drain n, we decrement the indegree
    of every node that depends on n.
    """
    graph = {a["agent"]: list(a.get("dependencies", [])) for a in steps(pipeline)}
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
    for entry in steps(pipeline):
        if entry["agent"] in seen:
            dupes.append(entry["agent"])
        seen.add(entry["agent"])
    return [f"duplicate agent name: {d}" for d in dupes]


def validate_agent_phase_prefix(pipeline: dict) -> list[str]:
    """The phase prefix in the agent name must equal the `phase` field.

    e.g. agent: "product-docs/prd-writer" must have phase: "product-docs".
    """
    errors = []
    for entry in steps(pipeline):
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


def validate_agent_files(pipeline: dict, agents_dir: Path) -> list[str]:
    """For each agent in the pipeline, verify the prompt file exists and
    pipeline.json declares a valid model for it.

    Model lives in pipeline.json, not the agent's frontmatter (AS-1: a step
    does not choose its own model, and the frontmatter declares only name and
    description). Only runs when agents_dir exists on disk; silently passes
    when the directory is absent (e.g. consuming repos that haven't synced yet).
    """
    if not agents_dir.is_dir():
        return []
    errors = []
    for entry in steps(pipeline):
        # Script steps run a bash script directly — no agent prompt file, no model.
        if entry.get("type") == "script":
            continue
        agent_name = entry["agent"]
        agent_file = agents_dir / f"{agent_name}.md"
        if not agent_file.exists():
            errors.append(
                f"agent '{agent_name}': prompt file not found at {agent_file.relative_to(agents_dir.parent.parent)}"
            )
            continue
        model = entry.get("model")
        if not model:
            errors.append(
                f"agent '{agent_name}': missing 'model' field in pipeline.json"
            )
        elif model not in VALID_MODELS:
            errors.append(
                f"agent '{agent_name}': model '{model}' not in approved set "
                f"({', '.join(sorted(VALID_MODELS))})"
            )
    return errors


def validate_flow_naming(pipeline: dict) -> list[str]:
    """A step's git_ops.commits_to must name a pull request its flow declares.

    Branch and pull-request names are declared, never computed (AS-1), so a
    commits_to pointing at nothing is a broken declaration, not a runtime
    surprise -- catch it here rather than mid-flow.
    """
    errors = []
    for flow_name, flow in (pipeline.get("flows") or {}).items():
        naming = flow.get("naming") or {}
        pr_ids = {pr["id"] for pr in naming.get("pull_requests", [])}
        for entry in flow.get("steps") or []:
            git_ops = entry.get("git_ops") or {}
            commits_to = git_ops.get("commits_to")
            if commits_to is not None and commits_to not in pr_ids:
                errors.append(
                    f"step '{entry['agent']}' in flow '{flow_name}' commits_to "
                    f"'{commits_to}', which names no pull request in that flow's "
                    f"naming.pull_requests ({sorted(pr_ids) or 'none declared'})"
                )
            if git_ops.get("commit_after") and not naming.get("branch"):
                errors.append(
                    f"step '{entry['agent']}' in flow '{flow_name}' commits but the "
                    f"flow declares no naming.branch to commit to"
                )
            if git_ops.get("commit_after") and commits_to is None and len(pr_ids) > 1:
                errors.append(
                    f"step '{entry['agent']}' in flow '{flow_name}' commits but "
                    f"declares no git_ops.commits_to, and the flow declares more "
                    f"than one pull request ({sorted(pr_ids)})"
                )
    return errors


def validate_naming_tokens(pipeline: dict) -> list[str]:
    """Every naming pattern uses only tokens the orchestrator can resolve.

    AS-1: branch and pull-request names are declared in pipeline.json and
    resolved from it, never built in code. The schema can say a pattern is a
    string; only this file knows which tokens exist. A pattern naming a token
    the orchestrator cannot substitute would raise partway through a flow,
    after the step had already been dispatched -- so it is refused up front.
    """
    errors = []
    for flow_name, flow in (pipeline.get("flows") or {}).items():
        naming = flow.get("naming") or {}
        patterns = [("naming.branch", naming.get("branch")), ("naming.base", naming.get("base"))]
        for pr in naming.get("pull_requests") or []:
            patterns.append((f"naming.pull_requests[{pr.get('id')}].branch", pr.get("branch")))
        for where, pattern in patterns:
            if not isinstance(pattern, str):
                continue
            unknown = sorted(set(_NAMING_TOKEN_RE.findall(pattern)) - NAMING_TOKENS)
            if unknown:
                errors.append(
                    f"flow '{flow_name}' {where} '{pattern}' uses unknown token(s) "
                    f"{unknown}; the orchestrator resolves only "
                    f"{sorted(NAMING_TOKENS)}"
                )
    return errors


def validate_named_scripts_exist(pipeline: dict, repo_root: Path) -> list[str]:
    """Every script the file names exists on disk.

    The counterpart to validate_agent_files, for the other kind of step the
    pipeline names: a script step's `script`, a step's `post_steps`, and the
    global `defaults.agent_lifecycle` hooks. AS-2 puts every piece of
    value-add work in a script named here; a name pointing at nothing is a
    step that fails when it is finally reached rather than when it was
    declared.
    """
    if not repo_root.is_dir():
        return []
    errors = []
    for entry in steps(pipeline):
        named = []
        if entry.get("type") == "script" and entry.get("script"):
            named.append(("script", entry["script"]))
        named += [("post_steps", p) for p in entry.get("post_steps") or []]
        for field, rel in named:
            if not (repo_root / rel).is_file():
                errors.append(
                    f"step '{entry['agent']}' names {field} '{rel}', which does not exist"
                )
    lifecycle = (pipeline.get("defaults") or {}).get("agent_lifecycle") or {}
    for when in ("before", "after"):
        for rel in lifecycle.get(when) or []:
            if not (repo_root / rel).is_file():
                errors.append(
                    f"defaults.agent_lifecycle.{when} names '{rel}', which does not exist"
                )
    return errors


def validate_no_step_grants_itself_a_lifecycle_or_gate_label(
    pipeline: dict, statuses_path: Path,
) -> list[str]:
    """No step's allowed_labels may cover a gate label or a lifecycle label.

    AS-1 says everything a step may do is declared here and nowhere else, so
    the declaration itself must not grant what the orchestrator alone may
    write. Two families:

      - a `{step}:approved`-style human gate label, which only a person's own
        application (or the orchestrator recording a relayed confirmation)
        may put on an issue -- a step able to request one has an approval
        path of its own (MI-7);
      - a `{step}:{status}` lifecycle label, which the orchestrator applies
        as it moves the step through its states -- a step writing its own
        would be reporting its outcome twice, in two voices (MI-6).

    Patterns are matched with the orchestrator's own glob convention, so a
    wildcard broad enough to sweep one of these in is caught as readily as a
    literal.
    """
    try:
        suffixes = [
            s["label_suffix"] for s in json.loads(statuses_path.read_text())["statuses"]
        ]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        return [f"could not read statuses from {statuses_path}: {exc}"]

    all_steps = steps(pipeline)
    gate_labels = {
        entry["human_gate_label"] for entry in all_steps if entry.get("human_gate_label")
    }
    lifecycle_labels = {
        f"{entry['agent'].split('/')[-1]}:{suffix}"
        for entry in all_steps for suffix in suffixes
    }

    errors = []
    for entry in all_steps:
        for op in ("add", "remove"):
            for pattern in (entry.get("allowed_labels") or {}).get(op) or []:
                for family, labels in (
                    ("a human gate label", gate_labels),
                    ("a lifecycle status label", lifecycle_labels),
                ):
                    covered = sorted(
                        lbl for lbl in labels if fnmatch.fnmatchcase(lbl, pattern)
                    )
                    if covered:
                        errors.append(
                            f"step '{entry['agent']}' allowed_labels.{op} pattern "
                            f"'{pattern}' covers {family}: {covered[:3]} -- only the "
                            f"orchestrator may write those"
                        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate pipeline.json")
    parser.add_argument("--pipeline", type=Path, default=DEFAULT_PIPELINE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Repository root the file's script paths are relative to "
             "(default: the parent of pipeline/). Pass an empty string to skip.",
    )
    parser.add_argument(
        "--statuses",
        type=Path,
        default=DEFAULT_STATUSES,
        help="statuses.json, for the lifecycle-label grant check "
             "(default: pipeline/statuses.json).",
    )
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
    all_errors += validate_flow_naming(pipeline)
    all_errors += validate_naming_tokens(pipeline)
    all_errors += validate_no_step_grants_itself_a_lifecycle_or_gate_label(
        pipeline, args.statuses,
    )
    if args.repo_root:
        all_errors += validate_named_scripts_exist(pipeline, args.repo_root)
    if args.agents_dir:
        all_errors += validate_agent_files(pipeline, args.agents_dir)

    if all_errors:
        print(f"FAIL: {args.pipeline}", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"OK: {args.pipeline} "
        f"({len(pipeline.get('flows') or {})} flows, {len(steps(pipeline))} steps)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
