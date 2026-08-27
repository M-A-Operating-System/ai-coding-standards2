#!/usr/bin/env python3
"""Generate the human-readable views of pipeline.json and statuses.json.

P-2 requires one machine-readable source per concern, with human views
generated from it. This generator implements the views listed as "Planned"
in docs/product/orchestrator/generated/README.md:

    agents.md          the agent catalogue
    pipeline-steps.md  every step: trigger, dependencies, gate, entitlements
    statuses.md        the label model and its transitions

Each replaces a hand-authored document that restated the same facts and
drifted from them. Nothing here is authored: if a fact is not in
pipeline.json or statuses.json, it does not appear.

Idempotent by construction -- output depends only on the source files, so
running twice produces byte-identical output. CI regenerates and fails the
build if a committed file differs.

Usage:
    python3 pipeline/generators/generate_docs.py            # write
    python3 pipeline/generators/generate_docs.py --check    # verify only
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"
STATUSES_JSON = REPO_ROOT / "pipeline" / "statuses.json"
OUT_DIR = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated"

BANNER = (
    "<!-- GENERATED FILE -- DO NOT EDIT.\n"
    "     Source: {source}\n"
    "     Generator: pipeline/generators/generate_docs.py\n"
    "     Regenerate: python3 pipeline/generators/generate_docs.py -->\n"
)


def _load(path):
    with path.open() as fh:
        return json.load(fh)


def _cell(value):
    """Render a value for a markdown table cell."""
    if value is None:
        return "--"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(f"`{v}`" for v in value) if value else "--"
    if isinstance(value, dict):
        if not value:
            return "--"
        return ", ".join(f"`{k}={json.dumps(v)}`" for k, v in value.items())
    return f"`{value}`"


def _trigger(step):
    trig = step.get("trigger") or {}
    if "label" in trig:
        return f"`{trig['label']}`"
    if "event" in trig:
        return f"event `{trig['event']}`"
    return _cell(trig)


# --- agents.md -------------------------------------------------------------


def render_agents(pipeline):
    lines = [BANNER.format(source="pipeline/pipeline.json"), "# Agent Catalogue", ""]
    lines += [
        "Every step in the pipeline, in configuration order, with the",
        "description declared in `pipeline.json`.",
        "",
    ]

    by_phase = {}
    for step in pipeline["pipeline"]:
        by_phase.setdefault(step["phase"], []).append(step)

    for phase in sorted(by_phase):
        lines += [f"## {phase}", ""]
        for step in by_phase[phase]:
            kind = step.get("type", "agent")
            lines += [f"### `{step['agent']}`", ""]
            lines += [f"- **Kind:** {kind}"]
            lines += [f"- **Operates on:** {_cell(step.get('object'))}"]
            if step.get("script"):
                lines += [f"- **Script:** `{step['script']}`"]
            desc = (step.get("description") or "").strip()
            if desc:
                lines += ["", desc]
            lines += [""]
    return "\n".join(lines).rstrip() + "\n"


# --- pipeline-steps.md -----------------------------------------------------


def render_steps(pipeline):
    lines = [BANNER.format(source="pipeline/pipeline.json"), "# Pipeline Steps", ""]
    lines += [
        "What runs, what starts it, what must finish first, and where a human",
        "decides. This is the process definition (AS-1): `pipeline.json` is",
        "authoritative and this table is a view of it.",
        "",
        "## Sequence and gates",
        "",
        "| Step | Kind | Trigger | Depends on | Human gate |",
        "|---|---|---|---|---|",
    ]
    for step in pipeline["pipeline"]:
        gate = step.get("human_gate_label") if step.get("human_gate_after") else None
        lines.append(
            f"| `{step['agent']}` | {step.get('type', 'agent')} | {_trigger(step)} "
            f"| {_cell(step.get('dependencies'))} | {_cell(gate)} |"
        )

    lines += ["", "## Exclusions and retries", ""]
    lines += [
        "| Step | Excluded classifications | Excluded labels | Max retries |",
        "|---|---|---|---|",
    ]
    for step in pipeline["pipeline"]:
        lines.append(
            f"| `{step['agent']}` | {_cell(step.get('exclude_classifications'))} "
            f"| {_cell(step.get('exclude_labels'))} | {_cell(step.get('max_retries'))} |"
        )

    lines += ["", "## Entitled activities", ""]
    lines += [
        "What each step is permitted to do. Under AS-1 this table must be",
        "complete: an entitlement that does not appear here is not granted.",
        "",
    ]
    defaults = pipeline.get("defaults", {}).get("extra_allowedTools", [])
    lines += [f"**Granted to every step:** {_cell(defaults)}", ""]
    lines += ["| Step | Additional entitlements | Git operations |", "|---|---|---|"]
    for step in pipeline["pipeline"]:
        extra = step.get("extra_allowedTools") or []
        shown = _cell(extra[:6]) + (f" _(+{len(extra) - 6} more)_" if len(extra) > 6 else "")
        lines.append(
            f"| `{step['agent']}` | {shown if extra else '--'} "
            f"| {_cell(step.get('git_ops'))} |"
        )

    lines += [
        "",
        "> **Known gap.** Entitlements are not yet defined by `pipeline.json`",
        "> alone. `BASE_AGENT_TOOLS` in `pipeline/pipeline_orchestrator.py`, each",
        "> agent's `tools:` frontmatter, and `.claude/settings.json` also grant",
        "> capability, so this table is incomplete by construction. See AS-1 in",
        "> [`../PRODUCT.md`](../PRODUCT.md) and issue #357.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# --- statuses.md -----------------------------------------------------------


def render_statuses(statuses):
    lines = [BANNER.format(source="pipeline/statuses.json"), "# Status Model", ""]
    lines += [
        (statuses.get("description") or "").strip(),
        "",
        f"Labels take the form `{statuses['label_format']}`.",
        "",
        "## Statuses",
        "",
        "| Status | Meaning | Terminal | Blocks | Needs a human | Cleared by |",
        "|---|---|---|---|---|---|",
    ]
    for st in statuses["statuses"]:
        lines.append(
            f"| `:{st['label_suffix']}` | {st['meaning']} | {_cell(st['terminal'])} "
            f"| {_cell(st['blocks_pipeline'])} | {_cell(st['human_action_required'])} "
            f"| {st.get('cleared_by') or '--'} |"
        )

    lines += ["", "## Orchestrator behaviour", "", "| Status | Set by | Behaviour |", "|---|---|---|"]
    for st in statuses["statuses"]:
        lines.append(
            f"| `:{st['label_suffix']}` | {st.get('set_by') or '--'} "
            f"| {st.get('orchestrator_behaviour') or '--'} |"
        )

    standalone = statuses.get("standalone_labels") or []
    if standalone:
        lines += ["", "## Standalone labels", "", "| Label | Meaning |", "|---|---|"]
        for lab in standalone:
            lines.append(f"| `{lab['label']}` | {lab['meaning']} |")

    order = statuses.get("priority_ordering") or []
    if order:
        lines += ["", "## Priority ordering", ""]
        lines += ["Work items carrying these labels are evaluated first, in order:", ""]
        for i, lab in enumerate(order, 1):
            lines.append(f"{i}. `{lab}`")

    lines += [""]
    return "\n".join(lines).rstrip() + "\n"


# --- driver ----------------------------------------------------------------


def build():
    pipeline = _load(PIPELINE_JSON)
    statuses = _load(STATUSES_JSON)
    return {
        "agents.md": render_agents(pipeline),
        "pipeline-steps.md": render_steps(pipeline),
        "statuses.md": render_statuses(statuses),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed files match the regenerated output; write nothing",
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
            print("STALE (regenerate with generate_docs.py): " + ", ".join(stale))
            return 1
        print("generated docs are current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
