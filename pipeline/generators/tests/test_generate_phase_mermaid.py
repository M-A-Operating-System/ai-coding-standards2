"""Tests for generate_phase_mermaid.py"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_GEN_PATH = Path(__file__).parents[1] / "generate_phase_mermaid.py"
_spec = importlib.util.spec_from_file_location("generate_phase_mermaid", _GEN_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

build_chart = _mod.build_chart
main = _mod.main


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


@pytest.fixture()
def patched(tmp_path, monkeypatch):
    pipeline_file = tmp_path / "pipeline" / "pipeline.json"
    pipeline_file.parent.mkdir(parents=True)
    pipeline_file.write_text(json.dumps({"pipeline": _ENTRIES}))
    output_dir = tmp_path / "docs" / "product" / "agile" / "generated" / "phases"
    monkeypatch.setattr(_mod, "PIPELINE_JSON", pipeline_file)
    monkeypatch.setattr(_mod, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
    return output_dir


def test_build_chart_agent_nodes():
    chart = build_chart("ph_a", _ENTRIES)
    assert 'n_ph_a__agent_one["agent-one"]' in chart
    assert 'n_ph_a__agent_two["agent-two"]' in chart


def test_build_chart_script_node():
    chart = build_chart("ph_a", _ENTRIES)
    assert 'n_ph_a__my_script("my-script")' in chart


def test_build_chart_human_gate_node():
    chart = build_chart("ph_a", _ENTRIES)
    assert 'gate__n_ph_a__agent_two{"agent-two:approved"}' in chart


def test_build_chart_agent_to_gate_edge():
    chart = build_chart("ph_a", _ENTRIES)
    assert "n_ph_a__agent_two --> gate__n_ph_a__agent_two" in chart


def test_build_chart_gate_to_successor_edge():
    chart = build_chart("ph_a", _ENTRIES)
    assert "gate__n_ph_a__agent_two --> n_ph_a__my_script" in chart


def test_build_chart_cross_phase_boundary_label():
    chart = build_chart("ph_b", _ENTRIES)
    assert "↓ agent-two:approved" in chart


def test_build_chart_cross_phase_edge():
    chart = build_chart("ph_b", _ENTRIES)
    assert "n_ph_a__agent_two --> n_ph_b__agent_three" in chart


def test_build_chart_starts_with_flowchart_td():
    chart = build_chart("ph_a", _ENTRIES)
    assert chart.startswith("flowchart TD\n")


def test_main_writes_files(patched):
    assert main([]) == 0
    assert (patched / "ph_a.mmd").exists()
    assert (patched / "ph_b.mmd").exists()


def test_main_idempotent(patched):
    main([])
    first = (patched / "ph_a.mmd").read_text()
    main([])
    second = (patched / "ph_a.mmd").read_text()
    assert first == second


def test_main_check_passes_after_write(patched):
    main([])
    assert main(["--check"]) == 0


def test_main_check_fails_when_stale(patched):
    main([])
    (patched / "ph_a.mmd").write_text("hand-edited\n")
    assert main(["--check"]) != 0


def test_main_check_fails_when_missing(patched):
    assert main(["--check"]) != 0


def test_main_removes_orphan_file(patched):
    patched.mkdir(parents=True, exist_ok=True)
    orphan = patched / "old_phase.mmd"
    orphan.write_text("stale\n")
    assert main([]) == 0
    assert not orphan.exists()


def test_main_check_reports_orphan(patched):
    patched.mkdir(parents=True, exist_ok=True)
    main([])
    (patched / "old_phase.mmd").write_text("stale\n")
    assert main(["--check"]) != 0
