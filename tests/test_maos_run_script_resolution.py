"""Tests for maos-run.md script path resolution — issue #295.

Traces to docs/features/pipeline.md:
  Scenario: /maos-run works when ai-coding-standards2 is checked out as a nested submodule
  Scenario: /maos-run continues to work in ai-coding-standards2's own repo
  Scenario: Missing orchestrator script produces a clear stop, not a silent failure
"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MAOS_RUN = REPO_ROOT / ".claude" / "commands" / "maos-run.md"

STANDALONE_SCRIPT = "pipeline/pipeline_orchestrator.py"
SUBMODULE_SCRIPT = "ai-coding-standards2/pipeline/pipeline_orchestrator.py"
FALLBACK_SHELL = '[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/pipeline/pipeline_orchestrator.py'
SCRIPT_VAR = "SCRIPT=pipeline/pipeline_orchestrator.py"


def _content():
    return MAOS_RUN.read_text()


class TestMaosRunWorksWhenAiCodingStandards2IsCheckedOutAsANestedSubmodule:
    def test_submodule_path_present_in_command(self):
        assert SUBMODULE_SCRIPT in _content(), (
            "maos-run.md must reference the submodule path "
            f"'{SUBMODULE_SCRIPT}' so it can be invoked from a consuming repo"
        )

    def test_fallback_shell_expression_present(self):
        assert FALLBACK_SHELL in _content(), (
            "maos-run.md must contain the fallback shell expression "
            f"'{FALLBACK_SHELL}' to locate the script in the submodule layout"
        )


class TestMaosRunContinuesToWorkInAiCodingStandards2sOwnRepo:
    def test_standalone_path_is_checked_first(self):
        content = _content()
        assert SCRIPT_VAR in content, (
            f"maos-run.md must set SCRIPT={STANDALONE_SCRIPT} as the primary (standalone) path"
        )
        standalone_pos = content.index(SCRIPT_VAR)
        fallback_pos = content.index(FALLBACK_SHELL)
        assert standalone_pos < fallback_pos, (
            "standalone path must appear before the submodule fallback in maos-run.md"
        )

    def test_invocation_uses_script_variable(self):
        assert 'python3 "$SCRIPT"' in _content(), (
            'maos-run.md step 4a must invoke `python3 "$SCRIPT"` (not a hardcoded path) '
            "so the resolved location is used"
        )

    def test_no_hardcoded_standalone_invocation(self):
        assert "python3 pipeline/pipeline_orchestrator.py" not in _content(), (
            "maos-run.md must not hardcode `python3 pipeline/pipeline_orchestrator.py`; "
            "use the SCRIPT variable instead"
        )


class TestMissingOrchestratorScriptProducesAClearStopNotASilentFailure:
    def test_step1_mentions_fallback_on_missing_script(self):
        content = _content()
        assert "If neither exists" in content, (
            "Step 1 of maos-run.md must state what to do when neither script path exists"
        )

    def test_step1_references_fallback_section(self):
        content = _content()
        assert "**Fallback**" in content, (
            "maos-run.md must reference the Fallback section when the script is missing"
        )
