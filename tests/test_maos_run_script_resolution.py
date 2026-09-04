"""Tests for /maos-run's orchestrator path resolution — issue #295.

Traces to docs/features/pipeline.md:
  Scenario: /maos-run works when ai-coding-standards2 is checked out as a nested submodule
  Scenario: /maos-run continues to work in ai-coding-standards2's own repo
  Scenario: Missing orchestrator script produces a clear stop, not a silent failure

Issue #407 made `/maos-run` a thin wrapper (AS-3): the drive loop -- and with
it the orchestrator path resolution these scenarios are about -- moved into
`.github/scripts/drive-item.sh`. The same three scenarios are asserted here
against the script that now owns the resolution, plus the command file that
now has to locate the script.
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MAOS_RUN = REPO_ROOT / ".claude" / "commands" / "maos-run.md"
DRIVE_ITEM = REPO_ROOT / ".github" / "scripts" / "drive-item.sh"

STANDALONE_SCRIPT = "pipeline/pipeline_orchestrator.py"
SUBMODULE_SCRIPT = "ai-coding-standards2/pipeline/pipeline_orchestrator.py"
FALLBACK_SHELL = '[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/pipeline/pipeline_orchestrator.py'
SCRIPT_VAR = "SCRIPT=pipeline/pipeline_orchestrator.py"


def _content():
    return DRIVE_ITEM.read_text()


def _command():
    return MAOS_RUN.read_text()


class TestMaosRunWorksWhenAiCodingStandards2IsCheckedOutAsANestedSubmodule:
    def test_submodule_path_present_in_the_drive_script(self):
        assert SUBMODULE_SCRIPT in _content(), (
            "drive-item.sh must reference the submodule path "
            f"'{SUBMODULE_SCRIPT}' so it can be invoked from a consuming repo"
        )

    def test_fallback_shell_expression_present(self):
        assert FALLBACK_SHELL in _content(), (
            "drive-item.sh must contain the fallback shell expression "
            f"'{FALLBACK_SHELL}' to locate the orchestrator in the submodule layout"
        )

    def test_the_command_finds_the_drive_script_in_either_layout(self):
        content = _command()
        assert ".github/scripts/drive-item.sh" in content
        assert "ai-coding-standards2/.github/scripts/drive-item.sh" in content


class TestMaosRunContinuesToWorkInAiCodingStandards2sOwnRepo:
    def test_standalone_path_is_checked_first(self):
        content = _content()
        assert SCRIPT_VAR in content, (
            f"drive-item.sh must set SCRIPT={STANDALONE_SCRIPT} as the primary (standalone) path"
        )
        assert content.index(SCRIPT_VAR) < content.index(FALLBACK_SHELL), (
            "standalone path must appear before the submodule fallback"
        )

    def test_invocation_uses_script_variable(self):
        assert 'python3 "$SCRIPT"' in _content(), (
            'drive-item.sh must invoke `python3 "$SCRIPT"` (not a hardcoded path) '
            "so the resolved location is used"
        )

    def test_no_hardcoded_standalone_invocation(self):
        for text, where in ((_content(), "drive-item.sh"), (_command(), "maos-run.md")):
            assert "python3 pipeline/pipeline_orchestrator.py" not in text, (
                f"{where} must not hardcode `python3 pipeline/pipeline_orchestrator.py`; "
                "resolve the location into a variable first"
            )


class TestMissingOrchestratorScriptProducesAClearStopNotASilentFailure:
    def test_the_script_stops_with_a_named_reason(self, tmp_path):
        """No orchestrator in either layout: exit 1 and say which paths were tried."""
        res = subprocess.run(
            ["bash", str(DRIVE_ITEM), "42"],
            cwd=str(tmp_path), env={"PATH": "/usr/bin:/bin", "REPO": "owner/repo"},
            capture_output=True, text=True,
        )
        assert res.returncode == 1
        assert STANDALONE_SCRIPT in res.stderr
        assert SUBMODULE_SCRIPT in res.stderr

    def test_the_command_tells_the_driver_not_to_substitute(self):
        content = _command()
        assert "stop and tell the user" in content.lower()
        assert "by hand" in content

    def test_a_non_numeric_issue_is_refused(self, tmp_path):
        res = subprocess.run(
            ["bash", str(DRIVE_ITEM), "not-a-number"],
            cwd=str(tmp_path), env={"PATH": "/usr/bin:/bin", "REPO": "owner/repo"},
            capture_output=True, text=True,
        )
        assert res.returncode == 1
        assert "not an integer" in res.stderr
