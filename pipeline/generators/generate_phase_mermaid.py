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


def _safe_label(text: str) -> str:
    """Return a Mermaid-safe label (double quotes break node syntax)."""
    return text.replace('"', "'")


def build_chart(phase: str, all_entries: list[dict]) -> str:
    """Return Mermaid flowchart source for one phase."""
    entries = [e for e in all_entries if e["phase"] == phase]
    all_entry_map = {e["agent"]: e for e in all_entries}
    phase_entry_map = {e["agent"]: e for e in entries}

    # Guard against node ID collisions (e.g. 'agent-x' and 'agent_x' collide)
    node_ids = [_node_id(e["agent"]) for e in entries]
    if len(node_ids) != len(set(node_ids)):
        seen_ids: set[str] = set()
        dupes: list[str] = []
        for nid in node_ids:
            if nid in seen_ids:
                dupes.append(nid)
            seen_ids.add(nid)
        raise ValueError(f"Node ID collision in phase {phase!r}: {dupes}")

    lines: list[str] = ["flowchart TD"]

    # Cross-phase boundary entry nodes
    external_deps: set[str] = set()
    for entry in entries:
        for dep in entry.get("dependencies", []):
            if dep not in phase_entry_map:
                external_deps.add(dep)

    for dep in sorted(external_deps):
        dep_entry = all_entry_map.get(dep)
        nid = _node_id(dep)
        if dep_entry and dep_entry.get("human_gate_after"):
            gate_label = _safe_label(dep_entry.get("human_gate_label", "human-gate"))
            lines.append(f'    {nid}(["↓ {gate_label}"])')
        else:
            lines.append(f'    {nid}(["↓ {_safe_label(_short_name(dep))}"])')

    # Agent nodes
    for entry in entries:
        nid = _node_id(entry["agent"])
        label = _safe_label(_short_name(entry["agent"]))
        if entry.get("type") == "script":
            lines.append(f'    {nid}("{label}")')
        else:
            lines.append(f'    {nid}["{label}"]')

    # Human gate nodes (within this phase)
    for entry in entries:
        if entry.get("human_gate_after"):
            gid = _gate_node_id(entry["agent"])
            gate_label = _safe_label(entry.get("human_gate_label", "human-gate"))
            if entry.get("auto_approve_on_complete"):
                gate_label += " (auto)"
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
            dep_in_phase = phase_entry_map.get(dep)
            if dep_in_phase and dep_in_phase.get("human_gate_after"):
                lines.append(f"    {_gate_node_id(dep)} --> {aid}")
            else:
                lines.append(f"    {_node_id(dep)} --> {aid}")

    # Review loop: dashed feedback arrows (REQUEST_CHANGES → re-invoke target)
    for entry in entries:
        review_loop = entry.get("review_loop")
        if not review_loop:
            continue
        re_invoke = review_loop.get("re_invoke")
        max_cycles = review_loop.get("max_cycles")
        if re_invoke and re_invoke in phase_entry_map:
            source_id = _node_id(entry["agent"])
            target_id = _node_id(re_invoke)
            cycle_text = f" ≤{max_cycles}" if max_cycles else ""
            lines.append(f"    {source_id} -. REQUEST_CHANGES{cycle_text} .-> {target_id}")

    return "\n".join(lines) + "\n"


def load_pipeline() -> list[dict]:
    if not PIPELINE_JSON.exists():
        print(f"error: {PIPELINE_JSON} not found", file=sys.stderr)
        sys.exit(1)
    with PIPELINE_JSON.open(encoding="utf-8") as fh:
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

    if not args.check:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    expected_files = {OUTPUT_DIR / f"{ph}.mmd" for ph in phases}
    failures: list[str] = []

    for phase, content in charts.items():
        outfile = OUTPUT_DIR / f"{phase}.mmd"
        if args.check:
            if not outfile.exists():
                failures.append(f"missing: {outfile.relative_to(REPO_ROOT)}")
            elif outfile.read_text(encoding="utf-8") != content:
                failures.append(f"stale: {outfile.relative_to(REPO_ROOT)}")
        else:
            outfile.write_text(content, encoding="utf-8")
            print(f"wrote {outfile.relative_to(REPO_ROOT)}")

    if OUTPUT_DIR.exists():
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
