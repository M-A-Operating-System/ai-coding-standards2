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
PIPELINE_DIR = REPO_ROOT / "pipeline"
PIPELINE_JSON = PIPELINE_DIR / "pipeline.json"
STATUSES_JSON = REPO_ROOT / "pipeline" / "statuses.json"
OUT_DIR = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated"

# entitlement_groups catalog resolution (issue #523) is shared with
# pipeline_orchestrator.py's loader via entitlement_groups.py, so the two
# can never silently disagree on what an allow_groups/deny_groups entry
# means (same "no orchestrator coupling" reasoning as todos_patch.py).
sys.path.insert(0, str(PIPELINE_DIR))
from entitlement_groups import resolve_group as _resolve_group_entry
from entitlement_groups import resolve_pattern_groups as _resolve_pattern_groups

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


def _resolve_groups(entitlement_groups, groups):
    """Resolve a list of allow_groups/deny_groups entries into
    {name, purpose, patterns} dicts, via the entitlement_groups module
    shared with pipeline_orchestrator.py's loader -- an unknown catalog name
    fails loudly here too, the same as it does at orchestrator load time
    (issue #523, "fail clearly"), since both go through the same resolver."""
    return [_resolve_group_entry(group, entitlement_groups) for group in (groups or [])]


def _trigger(step):
    trig = step.get("trigger") or {}
    if "label" in trig:
        return f"`{trig['label']}`"
    if "event" in trig:
        return f"event `{trig['event']}`"
    if "children" in trig:
        return f"children `{trig['children']}`"
    return _cell(trig)


def _flows(pipeline):
    """Every flow, in declaration order, as (name, flow) pairs."""
    return list((pipeline.get("flows") or {}).items())


def _flow_trigger(flow):
    trig = flow.get("trigger") or {}
    if "schedule" in trig:
        return f"schedule `{trig['schedule']}`"
    parts = [f"kind `{trig.get('kind')}`"]
    if trig.get("type"):
        parts.append("type " + ", ".join(f"`{t}`" for t in trig["type"]))
    if trig.get("labels"):
        parts.append("labels " + ", ".join(f"`{lab}`" for lab in trig["labels"]))
    return "; ".join(parts)


def _flow_naming(flow):
    naming = flow.get("naming") or {}
    if not naming:
        return "--"
    parts = [f"branch `{naming['branch']}`"]
    if naming.get("base"):
        parts.append(f"base `{naming['base']}`")
    for pr in naming.get("pull_requests", []):
        closes = "closes" if pr.get("closes_issue", True) else "does not close"
        parts.append(f"PR `{pr['id']}` on `{pr['branch']}` ({closes} the issue)")
    return "; ".join(parts)


# --- agents.md -------------------------------------------------------------


def render_agents(pipeline):
    lines = [BANNER.format(source="pipeline/pipeline.json"), "# Agent Catalogue", ""]
    lines += [
        "Every step in the pipeline, by the flow that declares it and in",
        "configuration order, with the description declared in `pipeline.json`.",
        "",
    ]

    for flow_name, flow in _flows(pipeline):
        lines += [f"## Flow: `{flow_name}`", ""]
        lines += [f"- **Applies to:** {_flow_trigger(flow)}"]
        lines += [f"- **Naming:** {_flow_naming(flow)}"]
        desc = (flow.get("description") or "").strip()
        if desc:
            lines += ["", desc]
        lines += [""]
        for step in flow.get("steps") or []:
            kind = step.get("type", "agent")
            lines += [f"### `{step['agent']}`", ""]
            lines += [f"- **Kind:** {kind}"]
            lines += [f"- **Phase:** `{step['phase']}`"]
            if step.get("script"):
                lines += [f"- **Script:** `{step['script']}`"]
            step_desc = (step.get("description") or "").strip()
            if step_desc:
                lines += ["", step_desc]
            lines += [""]
    return "\n".join(lines).rstrip() + "\n"


# --- pipeline-steps.md -----------------------------------------------------


def render_steps(pipeline):
    entitlement_groups = pipeline.get("entitlement_groups") or {}
    lines = [BANNER.format(source="pipeline/pipeline.json"), "# Pipeline Steps", ""]
    lines += [
        "What runs, what starts it, what must finish first, and where a human",
        "decides -- one section per flow, because the pipeline defines flows,",
        "not a flow. This is the process definition (AS-1): `pipeline.json` is",
        "authoritative and these tables are a view of it.",
        "",
        "## Flows",
        "",
        "| Flow | Applies to | Naming |",
        "|---|---|---|",
    ]
    for flow_name, flow in _flows(pipeline):
        lines.append(f"| `{flow_name}` | {_flow_trigger(flow)} | {_flow_naming(flow)} |")

    for flow_name, flow in _flows(pipeline):
        flow_steps = flow.get("steps") or []
        lines += ["", f"## Flow: `{flow_name}`", ""]
        lines += [
            "### Sequence and gates",
            "",
            "| Step | Kind | Unit | Trigger | Depends on | Human gate |",
            "|---|---|---|---|---|---|",
        ]
        for step in flow_steps:
            gate = step.get("human_gate_label") if step.get("human_gate_after") else None
            lines.append(
                f"| `{step['agent']}` | {step.get('type', 'agent')} "
                f"| `{step.get('unit', 'item')}` | {_trigger(step)} "
                f"| {_cell(step.get('dependencies'))} | {_cell(gate)} |"
            )

        lines += ["", "### Exclusions and retries", ""]
        lines += [
            "| Step | Excluded classifications | Excluded labels | Max retries |",
            "|---|---|---|---|",
        ]
        for step in flow_steps:
            lines.append(
                f"| `{step['agent']}` | {_cell(step.get('exclude_classifications'))} "
                f"| {_cell(step.get('exclude_labels'))} | {_cell(step.get('max_retries'))} |"
            )

        lines += ["", "### Entitled activities", ""]
        lines += [
            "| Step | Additional entitlements | Declared prohibitions | Git operations |",
            "|---|---|---|---|",
        ]
        def _resolved_groups(step, field):
            return _resolve_groups(entitlement_groups, step.get(field))

        deny_group_steps = []
        allow_group_steps = []
        for step in flow_steps:
            allow_groups = _resolved_groups(step, "allow_groups")
            # A referenced group is shown by name, not expanded to its
            # patterns here -- the "Allow/Deny rule groups" sections below
            # are where a group's patterns are spelled out.
            extra = list(dict.fromkeys(
                (step.get("extra_allowedTools") or []) + [g["name"] for g in allow_groups]
            ))
            deny_groups = _resolved_groups(step, "deny_groups")
            denied = list(dict.fromkeys(
                (step.get("deniedTools") or []) + [g["name"] for g in deny_groups]
            ))
            shown_extra = _cell(extra[:6]) + (f" _(+{len(extra) - 6} more)_" if len(extra) > 6 else "")
            shown_denied = _cell(denied[:4]) + (f" _(+{len(denied) - 4} more)_" if len(denied) > 4 else "")
            lines.append(
                f"| `{step['agent']}` | {shown_extra if extra else '--'} "
                f"| {shown_denied if denied else '--'} "
                f"| {_cell(step.get('git_ops'))} |"
            )
            if deny_groups:
                deny_group_steps.append((step, deny_groups))
            if allow_groups:
                allow_group_steps.append((step, allow_groups))

        for step, deny_groups in deny_group_steps:
            if step.get("deniedTools"):
                authority_note = (
                    "The groups below are additive to this step's flat `deniedTools` list"
                    " above (issue #523) -- both are authoritative and merged into the"
                    " effective deny list."
                )
            else:
                authority_note = (
                    "The groups below are this step's authoritative deny list, flattened at"
                    " load time (no separate `deniedTools` declared)."
                )
            lines += [
                "",
                f"### Deny rule groups: `{step['agent']}`",
                "",
                f"{authority_note} The matcher sees the command string"
                " as written; a command reached through an interpreter wrapper"
                " (e.g. `bash -c '...'`) is not matched and is documented as the"
                " deny list's known limitation.",
                "",
            ]
            for group in deny_groups:
                lines += [f"**{group['name']}** -- {group['purpose']}", ""]
                for pat in group.get("patterns", []):
                    lines.append(f"- `{pat}`")
                lines.append("")

        for step, allow_groups in allow_group_steps:
            lines += [
                "",
                f"### Allow rule groups: `{step['agent']}`",
                "",
                "The groups below are additive to this step's `extra_allowedTools` above"
                " (not an alternative to it) -- the same named group can be an allow"
                " reference here and a deny reference for another step.",
                "",
            ]
            for group in allow_groups:
                lines += [f"**{group['name']}** -- {group['purpose']}", ""]
                for pat in group.get("patterns", []):
                    lines.append(f"- `{pat}`")
                lines.append("")

    lines += ["", "## Entitlements granted to every step", ""]
    lines += [
        "Under AS-1 the tables above must be complete: an entitlement that does",
        "not appear there or here is not granted.",
        "",
    ]
    # Referenced groups are shown by name here too, matching the per-step
    # table above -- see the "Allow/Deny rule groups" sections for a named
    # group's actual patterns.
    _default_allow_groups = _resolve_groups(
        entitlement_groups, pipeline.get("defaults", {}).get("allow_groups")
    )
    defaults = list(dict.fromkeys(
        (pipeline.get("defaults", {}).get("extra_allowedTools", []))
        + [g["name"] for g in _default_allow_groups]
    ))
    lines += [f"**Granted to every step:** {_cell(defaults)}"]
    _default_deny_groups = _resolve_groups(
        entitlement_groups, pipeline.get("defaults", {}).get("deny_groups")
    )
    default_denied = list(dict.fromkeys(
        (pipeline.get("defaults", {}).get("deniedTools", []))
        + [g["name"] for g in _default_deny_groups]
    ))
    if default_denied:
        lines += [f"**Declared prohibition for every step:** {_cell(default_denied)}"]
    lines += [
        "",
        "Declared prohibitions state what a step must not do. They are matched",
        "against the command string as written; a command reached through an",
        "interpreter wrapper (e.g. `bash -c '...'`) is not matched.",
    ]

    if _default_allow_groups:
        lines += ["", "### Default allow rule groups", ""]
        for group in _default_allow_groups:
            lines += [f"**{group['name']}** -- {group['purpose']}", ""]
            for pat in group.get("patterns", []):
                lines.append(f"- `{pat}`")
            lines.append("")

    if _default_deny_groups:
        lines += ["", "### Default deny rule groups", ""]
        for group in _default_deny_groups:
            lines += [f"**{group['name']}** -- {group['purpose']}", ""]
            for pat in group.get("patterns", []):
                lines.append(f"- `{pat}`")
            lines.append("")

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
