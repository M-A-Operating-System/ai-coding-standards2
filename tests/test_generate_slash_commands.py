"""Tests for scripts/generate_slash_commands.py -- notably that it preserves
hand-authored maos-* commands (no marker) while managing generated ones."""
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
GEN_PATH = REPO_ROOT / "scripts" / "generate_slash_commands.py"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_mod", GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_pipeline(tmp_path):
    p = tmp_path / "pipeline.json"
    p.write_text(json.dumps({
        "flows": {
            "standard-delivery": {
                "description": "test flow",
                "trigger": {"kind": "issue"},
                "steps": [
                    {"agent": "01_product_docs/prd-writer", "type": "agent",
                     "description": "Drafts a PRD. Second sentence."},
                    {"agent": "01_product_docs/create-pr", "type": "script",
                     "script": "x.sh", "description": "Scripted step."},
                ],
            }
        }
    }))
    return p


class TestGeneratePreservesHandAuthored:
    def _setup(self, tmp_path, monkeypatch):
        gen = _load_gen()
        commands = tmp_path / "commands"
        commands.mkdir()
        monkeypatch.setattr(gen, "COMMANDS_DIR", commands)
        monkeypatch.setattr(gen, "PIPELINE_JSON", _fake_pipeline(tmp_path))
        return gen, commands

    def test_generates_agent_command_with_marker(self, tmp_path, monkeypatch):
        gen, commands = self._setup(tmp_path, monkeypatch)
        gen.main()
        f = commands / "maos-prd-writer.md"
        assert f.is_file()
        assert gen.GENERATED_MARKER in f.read_text()

    def test_script_type_agent_gets_no_command(self, tmp_path, monkeypatch):
        gen, commands = self._setup(tmp_path, monkeypatch)
        gen.main()
        assert not (commands / "maos-create-pr.md").exists()

    def test_hand_authored_command_is_preserved(self, tmp_path, monkeypatch):
        gen, commands = self._setup(tmp_path, monkeypatch)
        # A hand-authored command that maps to no pipeline agent and has no marker.
        hand = commands / "maos-merge.md"
        hand.write_text("# maos-merge\n\nHand-authored. Not generated.\n")
        gen.main()
        assert hand.exists(), "hand-authored maos-*.md must survive a sync"
        assert hand.read_text() == "# maos-merge\n\nHand-authored. Not generated.\n"

    def test_stale_generated_command_is_deleted(self, tmp_path, monkeypatch):
        gen, commands = self._setup(tmp_path, monkeypatch)
        # A generated command (carries the marker) for an agent no longer present.
        stale = commands / "maos-old-agent.md"
        stale.write_text(f"# maos-old-agent\n\nold\n\n{gen.GENERATED_MARKER}\n")
        gen.main()
        assert not stale.exists(), "a marked, agentless generated file must be removed"
