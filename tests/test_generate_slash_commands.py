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


class TestTheRequestedLabelMatchesWhatTheOrchestratorReads:
    """The generated commands tell a person which label makes a step eligible.

    `AgentDef.label_key` strips the phase prefix -- the orchestrator only ever
    reads `pr-reviewer:requested`, never `03_execute/pr-reviewer:requested`.
    The templates named the step by its full path, so every generated command
    instructed a label the orchestrator ignores: the step stayed ineligible,
    the tick reported "0 agents triggered", and nothing said why.

    One template feeds all 24 commands, so the defect was in all of them.
    """

    def _commands(self, tmp_path, monkeypatch):
        gen, commands = self._setup(tmp_path, monkeypatch)
        gen.main()
        return sorted(commands.glob("maos-*.md"))

    _setup = TestGeneratePreservesHandAuthored._setup

    def test_no_generated_command_names_a_phase_prefixed_label(self, tmp_path, monkeypatch):
        for path in self._commands(tmp_path, monkeypatch):
            text = path.read_text()
            assert "/pr-reviewer:requested" not in text, (
                f"{path.name} names a phase-prefixed label the orchestrator never reads"
            )
            for line in text.splitlines():
                if ":requested" in line:
                    label = line.split(":requested")[0]
                    assert "/" not in label.split("`")[-1].split('"')[-1], (
                        f"{path.name}: {line.strip()!r} names a label containing a "
                        "phase prefix; label_key strips it"
                    )

    def test_the_label_matches_label_key_exactly(self, tmp_path, monkeypatch):
        """Stated against the orchestrator's own accessor rather than a literal,
        so the two cannot drift apart again."""
        import sys
        sys.path.insert(0, str(REPO_ROOT / "pipeline"))
        from pipeline_orchestrator import AgentDef

        for path in self._commands(tmp_path, monkeypatch):
            text = path.read_text()
            if ":requested" not in text:
                continue
            # maos-pr-reviewer.md / maos-pr-reviewer-i.md -> pr-reviewer
            short = path.stem[len("maos-"):]
            if short.endswith("-i"):
                short = short[:-2]
            expected = AgentDef(
                agent=f"03_execute/{short}", phase="03_execute", objects=["issue"],
                trigger={}, dependencies=[], human_gate_after=False,
                human_gate_label=None, description="t",
            ).status_label("requested")
            assert expected == f"{short}:requested"
            assert f"{expected}" in text, (
                f"{path.name} does not name {expected}, the label the orchestrator reads"
            )
