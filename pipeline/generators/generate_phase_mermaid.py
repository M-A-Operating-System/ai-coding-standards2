#!/usr/bin/env python3
"""Generate per-phase Mermaid flowcharts from pipeline/pipeline.json.

Produces one .mmd file per phase under docs/product/orchestrator/generated/phases/,
a single lifecycle flowchart at docs/product/orchestrator/generated/pipeline.mmd,
and a complete-flow diagram grouped by phase at
docs/product/orchestrator/generated/pipeline_phases.mmd.
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
OUTPUT_DIR = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated" / "phases"
LIFECYCLE_FILE = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated" / "pipeline.mmd"
COMPLETE_FLOW_FILE = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated" / "pipeline_phases.mmd"

# ---------------------------------------------------------------------------
# Hand-curated outcome branches not yet expressible as structured JSON fields.
# Step 2 (GitHub issue #TODO) replaces these with a declarative `outcomes`
# field per agent so the lifecycle chart generates without any hard-coding.
# ---------------------------------------------------------------------------

# Extra labeled solid edges: agent_path → [(edge_label, "terminal:<key>")]
_LIFECYCLE_SOLID: dict[str, list[tuple[str, str]]] = {
    "01_product_docs/issue-classifier": [("malformed",   "terminal:rejected")],
    "03_execute/ci-gate":               [("timeout",     "terminal:blocked")],
    "03_execute/pr-reviewer":           [("APPROVE",     "terminal:ready")],
    "00_ondemand/sizer":                [("small · auto", "terminal:sized"),
                                         ("large",        "terminal:epic")],
    "00_ondemand/codebase-reviewer":    [("complete",    "terminal:cr-done")],
}

# Extra dashed back-edges not covered by the JSON `review_loop` field.
# Each entry: agent_path → [(edge_label, target_agent_path, max_cycles|None)]
_LIFECYCLE_LOOPS: dict[str, list[tuple[str, str, int | None]]] = {
    "03_execute/ci-gate": [("fail", "03_execute/coder", 3)],
}

_TERMINAL_LABELS: dict[str, str] = {
    "terminal:rejected": "rejected",
    "terminal:blocked":  "blocked — human",
    "terminal:ready":    "ready for human review",
    "terminal:sized":    "sized",
    "terminal:epic":     "epic — sub-issues",
    "terminal:cr-done":  "review issue created",
}


def _node_id(agent_path: str) -> str:
    safe = agent_path.replace("/", "__").replace("-", "_")
    return f"n_{safe}"


def _short_name(agent_path: str) -> str:
    return agent_path.split("/")[-1]


def _gate_node_id(agent_path: str) -> str:
    return f"gate__{_node_id(agent_path)}"


def _terminal_node_id(terminal_key: str) -> str:
    return "term_" + terminal_key.replace("terminal:", "", 1).replace("-", "_")


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


def build_lifecycle_chart(all_entries: list[dict]) -> str:
    """Return a single Mermaid flowchart of the full issue lifecycle."""
    entry_map = {e["agent"]: e for e in all_entries}
    lines: list[str] = ["flowchart TD"]

    # Entry point nodes
    for entry in all_entries:
        trigger = entry.get("trigger", {})
        event = trigger.get("event", "")
        label = trigger.get("label", "")
        if event == "issue.opened":
            eid = f"entry_{_node_id(entry['agent'])}"
            lines.append(f'    {eid}(["issue.opened"])')
        elif label.endswith(":requested"):
            eid = f"entry_{_node_id(entry['agent'])}"
            lines.append(f'    {eid}(["{label}"])')

    # Agent / script nodes
    for entry in all_entries:
        nid = _node_id(entry["agent"])
        label = _safe_label(_short_name(entry["agent"]))
        if entry.get("type") == "script":
            lines.append(f'    {nid}("{label}")')
        else:
            lines.append(f'    {nid}["{label}"]')

    # Gate nodes
    for entry in all_entries:
        if entry.get("human_gate_after"):
            gid = _gate_node_id(entry["agent"])
            gate_label = _safe_label(entry.get("human_gate_label", "human-gate"))
            if entry.get("auto_approve_on_complete"):
                gate_label += " · auto"
            lines.append(f'    {gid}{{"{gate_label}"}}')

    # Terminal nodes — only declare terminals whose source agent is present
    used_terms: set[str] = set()
    for agent_path, outcomes in _LIFECYCLE_SOLID.items():
        if agent_path in entry_map:
            for _, target in outcomes:
                used_terms.add(target)
    for target in sorted(used_terms):
        nid = _terminal_node_id(target)
        label = _TERMINAL_LABELS.get(target, target)
        lines.append(f'    {nid}(["{label}"]):::term')

    # Edges: entry point → agent
    for entry in all_entries:
        trigger = entry.get("trigger", {})
        event = trigger.get("event", "")
        label = trigger.get("label", "")
        if event == "issue.opened" or label.endswith(":requested"):
            eid = f"entry_{_node_id(entry['agent'])}"
            lines.append(f"    {eid} --> {_node_id(entry['agent'])}")

    # Edges: dependency → agent (routing through gate when dep has one)
    for entry in all_entries:
        aid = _node_id(entry["agent"])
        for dep in entry.get("dependencies", []):
            dep_entry = entry_map.get(dep)
            if dep_entry and dep_entry.get("human_gate_after"):
                src = _gate_node_id(dep)
            else:
                src = _node_id(dep)
            lines.append(f"    {src} --> {aid}")

    # Edges: agent → gate
    for entry in all_entries:
        if entry.get("human_gate_after"):
            lines.append(
                f"    {_node_id(entry['agent'])} --> {_gate_node_id(entry['agent'])}"
            )

    # Dashed back-edges from JSON `review_loop` field
    for entry in all_entries:
        review_loop = entry.get("review_loop")
        if not review_loop:
            continue
        re_invoke = review_loop.get("re_invoke")
        max_cycles = review_loop.get("max_cycles")
        if re_invoke and re_invoke in entry_map:
            source_id = _node_id(entry["agent"])
            target_id = _node_id(re_invoke)
            cycle_text = f" ≤{max_cycles}" if max_cycles else ""
            lines.append(f"    {source_id} -. REQUEST_CHANGES{cycle_text} .-> {target_id}")

    # Dashed back-edges from hand-curated loop outcomes
    for agent_path, loops in _LIFECYCLE_LOOPS.items():
        if agent_path not in entry_map:
            continue
        src_id = _node_id(agent_path)
        for edge_label, target_agent, max_cycles in loops:
            if target_agent not in entry_map:
                continue
            tgt_id = _node_id(target_agent)
            cycle_text = f" ≤{max_cycles}" if max_cycles else ""
            lines.append(f"    {src_id} -. {edge_label}{cycle_text} .-> {tgt_id}")

    # Labeled solid edges to terminal nodes
    for agent_path, outcomes in _LIFECYCLE_SOLID.items():
        if agent_path not in entry_map:
            continue
        src_id = _node_id(agent_path)
        for edge_label, target in outcomes:
            tgt_id = _terminal_node_id(target)
            lines.append(f"    {src_id} -->|{edge_label}| {tgt_id}")

    lines.append("    classDef term fill:#f0f0f0,stroke:#999,stroke-dasharray:3")
    return "\n".join(lines) + "\n"


def build_complete_chart(all_entries: list[dict]) -> str:
    """Return a Mermaid flowchart of the complete pipeline grouped by phase.

    Agents are wrapped in labelled subgraph blocks so phase boundaries are
    immediately visible.  Entry nodes for ``issue.opened`` events sit above
    the first subgraph; entry nodes for ``:requested`` triggers sit inside
    their phase's subgraph.  All edges, dashed back-loops, and terminal nodes
    are rendered identically to the lifecycle chart.
    """
    entry_map = {e["agent"]: e for e in all_entries}

    # Discover phases in pipeline order (first-seen wins).
    phases: list[str] = []
    seen_phases: set[str] = set()
    for e in all_entries:
        ph = e["phase"]
        if ph not in seen_phases:
            phases.append(ph)
            seen_phases.add(ph)

    lines: list[str] = ["flowchart TD"]

    # Entry nodes for issue.opened (outside every subgraph so they float at top)
    for entry in all_entries:
        trigger = entry.get("trigger", {})
        if trigger.get("event") == "issue.opened":
            eid = f"entry_{_node_id(entry['agent'])}"
            lines.append(f'    {eid}(["issue.opened"])')

    # One subgraph per phase
    for phase in phases:
        phase_entries = [e for e in all_entries if e["phase"] == phase]
        phase_label = phase.replace("_", " ").title()
        lines.append(f'    subgraph {phase}["{phase_label}"]')

        # :requested entry nodes inside the phase that owns them
        for entry in phase_entries:
            trigger = entry.get("trigger", {})
            label = trigger.get("label", "")
            if label.endswith(":requested"):
                eid = f"entry_{_node_id(entry['agent'])}"
                lines.append(f'        {eid}(["{label}"])')

        # Agent / script nodes
        for entry in phase_entries:
            nid = _node_id(entry["agent"])
            label = _safe_label(_short_name(entry["agent"]))
            if entry.get("type") == "script":
                lines.append(f'        {nid}("{label}")')
            else:
                lines.append(f'        {nid}["{label}"]')

        # Gate nodes
        for entry in phase_entries:
            if entry.get("human_gate_after"):
                gid = _gate_node_id(entry["agent"])
                gate_label = _safe_label(entry.get("human_gate_label", "human-gate"))
                if entry.get("auto_approve_on_complete"):
                    gate_label += " · auto"
                lines.append(f'        {gid}{{"{gate_label}"}}')

        lines.append("    end")

    # Terminal nodes (outside every subgraph)
    used_terms: set[str] = set()
    for agent_path, outcomes in _LIFECYCLE_SOLID.items():
        if agent_path in entry_map:
            for _, target in outcomes:
                used_terms.add(target)
    for target in sorted(used_terms):
        nid = _terminal_node_id(target)
        label = _TERMINAL_LABELS.get(target, target)
        lines.append(f'    {nid}(["{label}"]):::term')

    # Edges: entry points → agents
    for entry in all_entries:
        trigger = entry.get("trigger", {})
        event = trigger.get("event", "")
        label = trigger.get("label", "")
        if event == "issue.opened" or label.endswith(":requested"):
            eid = f"entry_{_node_id(entry['agent'])}"
            lines.append(f"    {eid} --> {_node_id(entry['agent'])}")

    # Edges: agent → gate
    for entry in all_entries:
        if entry.get("human_gate_after"):
            lines.append(
                f"    {_node_id(entry['agent'])} --> {_gate_node_id(entry['agent'])}"
            )

    # Edges: dependency → agent (routing through gate when dep has one)
    for entry in all_entries:
        aid = _node_id(entry["agent"])
        for dep in entry.get("dependencies", []):
            dep_entry = entry_map.get(dep)
            if dep_entry and dep_entry.get("human_gate_after"):
                src = _gate_node_id(dep)
            else:
                src = _node_id(dep)
            lines.append(f"    {src} --> {aid}")

    # Dashed back-edges from JSON review_loop field
    for entry in all_entries:
        review_loop = entry.get("review_loop")
        if not review_loop:
            continue
        re_invoke = review_loop.get("re_invoke")
        max_cycles = review_loop.get("max_cycles")
        if re_invoke and re_invoke in entry_map:
            source_id = _node_id(entry["agent"])
            target_id = _node_id(re_invoke)
            cycle_text = f" ≤{max_cycles}" if max_cycles else ""
            lines.append(f"    {source_id} -. REQUEST_CHANGES{cycle_text} .-> {target_id}")

    # Dashed back-edges from hand-curated loop outcomes
    for agent_path, loops in _LIFECYCLE_LOOPS.items():
        if agent_path not in entry_map:
            continue
        src_id = _node_id(agent_path)
        for edge_label, target_agent, max_cycles in loops:
            if target_agent not in entry_map:
                continue
            tgt_id = _node_id(target_agent)
            cycle_text = f" ≤{max_cycles}" if max_cycles else ""
            lines.append(f"    {src_id} -. {edge_label}{cycle_text} .-> {tgt_id}")

    # Labeled solid edges to terminal nodes
    for agent_path, outcomes in _LIFECYCLE_SOLID.items():
        if agent_path not in entry_map:
            continue
        src_id = _node_id(agent_path)
        for edge_label, target in outcomes:
            tgt_id = _terminal_node_id(target)
            lines.append(f"    {src_id} -->|{edge_label}| {tgt_id}")

    lines.append("    classDef term fill:#f0f0f0,stroke:#999,stroke-dasharray:3")
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
    lifecycle_content = build_lifecycle_chart(all_entries)
    complete_content = build_complete_chart(all_entries)

    if not args.check:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        LIFECYCLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COMPLETE_FLOW_FILE.parent.mkdir(parents=True, exist_ok=True)

    expected_files = {OUTPUT_DIR / f"{ph}.mmd" for ph in phases}
    failures: list[str] = []

    # Per-phase charts
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

    # Orphan phase charts
    if OUTPUT_DIR.exists():
        for existing in sorted(OUTPUT_DIR.glob("*.mmd")):
            if existing not in expected_files:
                if args.check:
                    failures.append(f"orphan: {existing.relative_to(REPO_ROOT)}")
                else:
                    existing.unlink()
                    print(f"removed {existing.relative_to(REPO_ROOT)}")

    # Lifecycle chart
    if args.check:
        if not LIFECYCLE_FILE.exists():
            failures.append(f"missing: {LIFECYCLE_FILE.relative_to(REPO_ROOT)}")
        elif LIFECYCLE_FILE.read_text(encoding="utf-8") != lifecycle_content:
            failures.append(f"stale: {LIFECYCLE_FILE.relative_to(REPO_ROOT)}")
    else:
        LIFECYCLE_FILE.write_text(lifecycle_content, encoding="utf-8")
        print(f"wrote {LIFECYCLE_FILE.relative_to(REPO_ROOT)}")

    # Complete flow chart (phase-grouped)
    if args.check:
        if not COMPLETE_FLOW_FILE.exists():
            failures.append(f"missing: {COMPLETE_FLOW_FILE.relative_to(REPO_ROOT)}")
        elif COMPLETE_FLOW_FILE.read_text(encoding="utf-8") != complete_content:
            failures.append(f"stale: {COMPLETE_FLOW_FILE.relative_to(REPO_ROOT)}")
    else:
        COMPLETE_FLOW_FILE.write_text(complete_content, encoding="utf-8")
        print(f"wrote {COMPLETE_FLOW_FILE.relative_to(REPO_ROOT)}")

    for msg in failures:
        print(f"error: {msg}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
