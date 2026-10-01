"""Conformance tests for issue #519's script-ownership split.

Issue #519 re-homed pipeline-runtime scripts from `.github/scripts/` to the
top-level `scripts/` directory: "Executable scripts used by the pipeline
belong in the repository's shared `scripts/` directory... GitHub
Actions/workflow integration belongs under `.github`." Per the issue's own
Scope item 6, these are generic directory/reference checks rather than a
hard-coded script list, so a new script landing back under
`.github/scripts/` fails here without needing this file updated first.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"
ORCHESTRATOR_PY = REPO_ROOT / "pipeline" / "pipeline_orchestrator.py"
GITHUB_SCRIPTS_DIR = REPO_ROOT / ".github" / "scripts"


def _iter_strings(node):
    """Yield every string value anywhere in a parsed pipeline.json tree.

    Deliberately not scoped to "script"/"post_steps" keys -- a script path
    also appears as a bare string in defaults.agent_lifecycle.before/after,
    and no other string in pipeline.json legitimately starts with
    ".github/scripts/", so walking every string cannot introduce a false
    positive while catching every current and future placement.
    """
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_strings(item)
    elif isinstance(node, str):
        yield node


class TestScriptOwnershipConformance:
    """No pipeline-runtime script reference points at .github/scripts/ (issue #519)."""

    def test_pipeline_json_script_references_stay_out_of_github_scripts(self):
        pipeline = json.loads(PIPELINE_JSON.read_text())
        offenders = sorted({
            path for path in _iter_strings(pipeline)
            if path.startswith(".github/scripts/")
        })
        assert not offenders, (
            f"pipeline.json references {offenders} under .github/scripts/ -- "
            "scripts the pipeline invokes (steps, post_steps, or "
            "agent_lifecycle before/after) belong in scripts/ (issue #519)"
        )

    def test_orchestrator_source_has_no_github_scripts_path(self):
        source = ORCHESTRATOR_PY.read_text()
        offenders = sorted(set(re.findall(r'["\'](\.github/scripts/[^"\']*)["\']', source)))
        assert not offenders, (
            f"pipeline_orchestrator.py hardcodes {offenders} under "
            ".github/scripts/ -- orchestrator-invoked scripts belong in "
            "scripts/ (issue #519)"
        )

    def test_github_scripts_directory_holds_no_pipeline_scripts(self):
        """.github/scripts/ may still exist for genuine workflow-only
        integration, but issue #519 found none, so for now any .sh/.py file
        placed there is a regression, not a legitimate new case."""
        if not GITHUB_SCRIPTS_DIR.exists():
            return
        leftover = sorted(
            str(path.relative_to(GITHUB_SCRIPTS_DIR))
            for path in GITHUB_SCRIPTS_DIR.rglob("*")
            if path.is_file() and path.suffix in (".sh", ".py")
        )
        assert not leftover, (
            f"{leftover} found under .github/scripts/ -- issue #519 moved "
            "every pipeline-runtime script to scripts/; a script placed back "
            "here needs an explicit workflow-only justification, not silent "
            "placement"
        )
