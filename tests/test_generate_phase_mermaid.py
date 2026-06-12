"""Tests for generate_phase_mermaid.py"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_GEN_PATH = Path(__file__).parent.parent / "pipeline" / "generators" / "generate_phase_mermaid.py"
_spec = importlib.util.spec_from_file_location("generate_phase_mermaid", _GEN_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

build_chart = _mod.build_chart
main = _mod.main
load_pipeline = _mod.load_pipeline
_safe_label = _mod._safe_label


_ENTRIES = [
    {
        "agent": "ph_a/agent-one",
        "phase": "ph_a",
        "dependencies": [],
        "human_gate_after": False,
    },
    {
        "agent": "ph_a/agent-two",
        "phase": "ph_a",
        "dependencies": ["ph_a/agent-one"],
        "human_gate_after": True,
        "human_gate_label": "agent-two:approved",
    },
    {
        "agent": "ph_a/my-script",
        "phase": "ph_a",
        "type": "script",
        "dependencies": ["ph_a/agent-two"],
        "human_gate_after": False,
    },
    {
        "agent": "ph_b/agent-three",
        "phase": "ph_b",
        "dependencies": ["ph_a/agent-two"],
        "human_gate_after": False,
    },
]


def _edges(chart: str) -> set[str]:
    """Return the set of `X --> Y` edge lines (normalised, sans indent)."""
    return {
        line.strip()
        for line in chart.splitlines()
        if "-->" in line
    }


def _has_edge(chart: str, src: str, dst: str) -> bool:
    return f"{src} --> {dst}" in _edges(chart)


def _node_line(chart: str, node_id: str) -> str | None:
    """Return the (stripped) node-declaration line for `node_id`, if any.

    A declaration is a non-edge line beginning with the id followed by an
    opening bracket of any Mermaid node shape.
    """
    for line in chart.splitlines():
        stripped = line.strip()
        if "-->" in stripped:
            continue
        if stripped.startswith(node_id) and len(stripped) > len(node_id):
            nxt = stripped[len(node_id)]
            if nxt in "[({":  # [ ( {
                return stripped
    return None


@pytest.fixture()
def patched(tmp_path, monkeypatch):
    pipeline_file = tmp_path / "pipeline" / "pipeline.json"
    pipeline_file.parent.mkdir(parents=True)
    pipeline_file.write_text(json.dumps({"pipeline": _ENTRIES}), encoding="utf-8")
    output_dir = tmp_path / "docs" / "product" / "agile" / "generated" / "phases"
    monkeypatch.setattr(_mod, "PIPELINE_JSON", pipeline_file)
    monkeypatch.setattr(_mod, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
    return output_dir


# --- build_chart: golden exact-shape tests ---
# These two pin the precise Mermaid node syntax. Keep them few; the rest of the
# suite uses structural checks so cosmetic rendering changes touch only these.

def test_build_chart_agent_node_golden_shape():
    chart = build_chart("ph_a", _ENTRIES)
    assert 'n_ph_a__agent_one["agent-one"]' in chart


def test_build_chart_script_node_golden_shape():
    chart = build_chart("ph_a", _ENTRIES)
    assert 'n_ph_a__my_script("my-script")' in chart


# --- build_chart: structural node checks ---

def test_build_chart_agent_node_has_label():
    chart = build_chart("ph_a", _ENTRIES)
    line = _node_line(chart, "n_ph_a__agent_two")
    assert line is not None, "agent-two node declaration missing"
    assert "agent-two" in line


def test_build_chart_script_node_distinct_shape_from_agent():
    chart = build_chart("ph_a", _ENTRIES)
    agent_line = _node_line(chart, "n_ph_a__agent_one")
    script_line = _node_line(chart, "n_ph_a__my_script")
    assert agent_line is not None and script_line is not None
    # Agents render as a different node shape from scripts.
    assert agent_line[len("n_ph_a__agent_one")] != script_line[len("n_ph_a__my_script")]


def test_build_chart_entry_without_human_gate_key():
    entries = [{"agent": "ph_x/agent", "phase": "ph_x", "dependencies": []}]
    chart = build_chart("ph_x", entries)
    line = _node_line(chart, "n_ph_x__agent")
    assert line is not None and "agent" in line
    assert "gate__" not in chart


# --- build_chart: gate nodes and edges ---

def test_build_chart_human_gate_node_has_label():
    chart = build_chart("ph_a", _ENTRIES)
    line = _node_line(chart, "gate__n_ph_a__agent_two")
    assert line is not None, "gate node declaration missing"
    assert "agent-two:approved" in line


def test_build_chart_agent_to_gate_edge():
    chart = build_chart("ph_a", _ENTRIES)
    assert _has_edge(chart, "n_ph_a__agent_two", "gate__n_ph_a__agent_two")


def test_build_chart_gate_to_successor_edge():
    chart = build_chart("ph_a", _ENTRIES)
    assert _has_edge(chart, "gate__n_ph_a__agent_two", "n_ph_a__my_script")


def test_build_chart_multiple_gates_in_one_phase():
    entries = [
        {
            "agent": "ph_m/a",
            "phase": "ph_m",
            "dependencies": [],
            "human_gate_after": True,
            "human_gate_label": "a:approved",
        },
        {
            "agent": "ph_m/b",
            "phase": "ph_m",
            "dependencies": ["ph_m/a"],
            "human_gate_after": True,
            "human_gate_label": "b:approved",
        },
    ]
    chart = build_chart("ph_m", entries)
    # Both gate nodes exist...
    assert _node_line(chart, "gate__n_ph_m__a") is not None
    assert _node_line(chart, "gate__n_ph_m__b") is not None
    # ...each agent routes to its own gate...
    assert _has_edge(chart, "n_ph_m__a", "gate__n_ph_m__a")
    assert _has_edge(chart, "n_ph_m__b", "gate__n_ph_m__b")
    # ...and b's dependency on a routes through a's gate.
    assert _has_edge(chart, "gate__n_ph_m__a", "n_ph_m__b")


# --- build_chart: cross-phase boundary ---

def test_build_chart_cross_phase_boundary_label_with_gate():
    chart = build_chart("ph_b", _ENTRIES)
    # ph_a/agent-two has a gate, so the boundary node carries the gate label.
    line = _node_line(chart, "n_ph_a__agent_two")
    assert line is not None
    assert "↓ agent-two:approved" in line


def test_build_chart_cross_phase_boundary_label_without_gate():
    # external-dep WITHOUT a gate: boundary node renders `↓ {short_name}`.
    entries = [
        {
            "agent": "ph_a/plain-dep",
            "phase": "ph_a",
            "dependencies": [],
            "human_gate_after": False,
        },
        {
            "agent": "ph_b/consumer",
            "phase": "ph_b",
            "dependencies": ["ph_a/plain-dep"],
            "human_gate_after": False,
        },
    ]
    chart = build_chart("ph_b", entries)
    line = _node_line(chart, "n_ph_a__plain_dep")
    assert line is not None, "boundary node for non-gated cross-phase dep missing"
    assert "↓ plain-dep" in line
    assert "approved" not in line


def test_build_chart_cross_phase_edge():
    chart = build_chart("ph_b", _ENTRIES)
    assert _has_edge(chart, "n_ph_a__agent_two", "n_ph_b__agent_three")


# --- build_chart: general ---

def test_build_chart_starts_with_flowchart_td():
    chart = build_chart("ph_a", _ENTRIES)
    assert chart.startswith("flowchart TD\n")


def test_build_chart_empty_phase_is_bare_flowchart():
    chart = build_chart("nonexistent", _ENTRIES)
    assert chart == "flowchart TD\n"


def test_build_chart_duplicate_node_ids_raises():
    entries = [
        {"agent": "ph_x/foo-bar", "phase": "ph_x", "dependencies": [], "human_gate_after": False},
        {"agent": "ph_x/foo_bar", "phase": "ph_x", "dependencies": [], "human_gate_after": False},
    ]
    with pytest.raises(ValueError, match="collision") as exc_info:
        build_chart("ph_x", entries)
    # The error must name the offending node id, not just say "collision".
    assert "n_ph_x__foo_bar" in str(exc_info.value)


# --- _safe_label ---

def test_safe_label_replaces_double_quotes():
    assert _safe_label('say "hello"') == "say 'hello'"


def test_safe_label_replaces_multiple_quotes():
    assert _safe_label('a "b" "c" "d"') == "a 'b' 'c' 'd'"
    assert '"' not in _safe_label('"""')


def test_safe_label_passthrough():
    assert _safe_label("normal-label:approved") == "normal-label:approved"


# --- main: write mode ---

def test_main_writes_files(patched):
    assert main([]) == 0
    assert (patched / "ph_a.mmd").exists()
    assert (patched / "ph_b.mmd").exists()


def test_main_idempotent(patched):
    main([])
    first = (patched / "ph_a.mmd").read_text(encoding="utf-8")
    main([])
    second = (patched / "ph_a.mmd").read_text(encoding="utf-8")
    assert first == second


def test_main_removes_orphan_file(patched):
    patched.mkdir(parents=True, exist_ok=True)
    orphan = patched / "old_phase.mmd"
    orphan.write_text("stale\n", encoding="utf-8")
    assert main([]) == 0
    assert not orphan.exists()


# --- main: --check mode ---

def test_main_check_passes_after_write(patched):
    main([])
    assert main(["--check"]) == 0


def test_main_check_fails_when_stale(patched):
    main([])
    (patched / "ph_a.mmd").write_text("hand-edited\n", encoding="utf-8")
    assert main(["--check"]) != 0


def test_main_check_fails_when_missing(patched):
    assert main(["--check"]) != 0


def test_main_check_does_not_create_directory(patched):
    assert not patched.exists()
    main(["--check"])
    assert not patched.exists()


def test_main_check_reports_orphan(patched):
    patched.mkdir(parents=True, exist_ok=True)
    main([])
    (patched / "old_phase.mmd").write_text("stale\n", encoding="utf-8")
    assert main(["--check"]) != 0


def test_main_check_leaves_stale_file_unmodified(patched):
    main([])
    target = patched / "ph_a.mmd"
    target.write_text("hand-edited\n", encoding="utf-8")
    assert main(["--check"]) != 0
    # --check must never write: the stale content is left exactly as-is.
    assert target.read_text(encoding="utf-8") == "hand-edited\n"


# --- load_pipeline ---

def test_load_pipeline_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(_mod, "PIPELINE_JSON", tmp_path / "nonexistent.json")
    with pytest.raises(SystemExit) as exc_info:
        load_pipeline()
    assert exc_info.value.code != 0


def test_load_pipeline_empty_when_no_pipeline_key(monkeypatch, tmp_path):
    pipeline_file = tmp_path / "pipeline.json"
    pipeline_file.write_text(json.dumps({"something_else": []}), encoding="utf-8")
    monkeypatch.setattr(_mod, "PIPELINE_JSON", pipeline_file)
    assert load_pipeline() == []


def test_load_pipeline_malformed_json_raises(monkeypatch, tmp_path):
    pipeline_file = tmp_path / "pipeline.json"
    pipeline_file.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(_mod, "PIPELINE_JSON", pipeline_file)
    with pytest.raises(json.JSONDecodeError):
        load_pipeline()
