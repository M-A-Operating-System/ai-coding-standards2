#!/usr/bin/env python3
"""Generate per-phase Mermaid flowcharts from pipeline/pipeline.json.

Produces one .mmd file per phase under docs/product/agile/generated/phases/.
Run without arguments to regenerate all charts. Run with --check to verify
charts are up-to-date without writing; exits non-zero if any chart is missing,
stale, or orphaned.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"
OUTPUT_DIR = REPO_ROOT / "docs" / "product" / "agile" / "generated" / "phases"


def _node_id(agent_path: str) -> str:
    safe = agent_path.replace("/", "__").replace("-", "_")
    return f"n_{safe}"


def _short_name(agent_path: str) -> str:
    return agent_path.split("/")[-1]


def _gate_node_id(agent_path: str) -> str:
    return f"gate__{_node_id(agent_path)}"


def build_chart(phase: str, all_entries: list[dict]) -> str:
    """Return Mermaid flowchart source for one phase."""
    entries = [e for e in all_entries if e["phase"] == phase]
    all_entry_map = {e["agent"]: e for e in all_entries}
    phase_agent_set = {e["agent"] for e in entries}

    lines: list[str] = ["flowchart TD"]

    # Cross-phase boundary entry nodes
    external_deps: set[str] = set()
    for entry in entries:
        for dep in entry.get("dependencies", []):
            if dep not in phase_agent_set:
                external_deps.add(dep)

    for dep in sorted(external_deps):
        dep_entry = all_entry_map.get(dep)
        nid = _node_id(dep)
        if dep_entry and dep_entry.get("human_gate_after"):
            gate_label = dep_entry.get("human_gate_label", "human-gate")
            lines.append(f'    {nid}(["↓ {gate_label}"])')
        else:
            lines.append(f'    {nid}(["↓ {_short_name(dep)}"])')

    # Agent nodes
    for entry in entries:
        nid = _node_id(entry["agent"])
        label = _short_name(entry["agent"])
        if entry.get("type") == "script":
            lines.append(f'    {nid}("{label}")')
        else:
            lines.append(f'    {nid}["{label}"]')

    # Human gate nodes (within this phase)
    for entry in entries:
        if entry.get("human_gate_after"):
            gid = _gate_node_id(entry["agent"])
            gate_label = entry.get("human_gate_label", "human-gate")
            lines.append(f'    {gid}{{"{gate_label}"}}')

    # Edges: agent → gate
    for entry in entries:
        if entry.get("human_gate_after"):
            aid = _node_id(entry["agent"])
            gid = _gate_node_id(entry["agent"])
            lines.append(f"    {aid} --> {gid}")

    # Edges: dependency → agent (routing through gate if the dep has one)
    for entry in entries:
        aid = _node_id(entry["agent"])
        for dep in entry.get("dependencies", []):
            dep_in_phase = next((e for e in entries if e["agent"] == dep), None)
            if dep_in_phase and dep_in_phase.get("human_gate_after"):
                lines.append(f"    {_gate_node_id(dep)} --> {aid}")
            else:
                lines.append(f"    {_node_id(dep)} --> {aid}")

    return "\n".join(lines) + "\n"


def load_pipeline() -> list[dict]:
    if not PIPELINE_JSON.exists():
        print(f"error: {PIPELINE_JSON} not found", file=sys.stderr)
        sys.exit(1)
    with PIPELINE_JSON.open() as fh:
        return json.load(fh).get("pipeline", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify charts match pipeline.json; exit non-zero if any differ.",
    )
    args = parser.parse_args(argv)

    all_entries = load_pipeline()

    phases: list[str] = []
    seen: set[str] = set()
    for entry in all_entries:
        ph = entry["phase"]
        if ph not in seen:
            phases.append(ph)
            seen.add(ph)

    charts: dict[str, str] = {ph: build_chart(ph, all_entries) for ph in phases}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    expected_files = {OUTPUT_DIR / f"{ph}.mmd" for ph in phases}
    failures: list[str] = []

    for phase, content in charts.items():
        outfile = OUTPUT_DIR / f"{phase}.mmd"
        if args.check:
            if not outfile.exists():
                failures.append(f"missing: {outfile.relative_to(REPO_ROOT)}")
            elif outfile.read_text() != content:
                failures.append(f"stale: {outfile.relative_to(REPO_ROOT)}")
        else:
            outfile.write_text(content)
            print(f"wrote {outfile.relative_to(REPO_ROOT)}")

    for existing in sorted(OUTPUT_DIR.glob("*.mmd")):
        if existing not in expected_files:
            if args.check:
                failures.append(f"orphan: {existing.relative_to(REPO_ROOT)}")
            else:
                existing.unlink()
                print(f"removed {existing.relative_to(REPO_ROOT)}")

    for msg in failures:
        print(f"error: {msg}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
