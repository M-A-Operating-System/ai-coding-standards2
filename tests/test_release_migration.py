"""Tests for issue #621: shadow runs, parity validation, and production migration.

Covers:
- Scenario R2: Production release ownership transferred to orchestrator after
  parity confirmed -- the weekly-release flow in pipeline.json owns the
  scheduled release, not release.yml.
- Scenario R4: Migration documentation is present and accessible.

release.yml itself was removed in issue #695 -- its manual-dispatch and
off-cycle tag-push triggers (R3/R5) were retired along with the file, not
retained, so the scenarios that once asserted on its 'on:' block no longer
apply.
"""

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent
_RELEASE_YML = _REPO_ROOT / ".github" / "workflows" / "release.yml"
_RELEASE_PATCH_TAG_YML = _REPO_ROOT / ".github" / "workflows" / "release-patch-tag.yml"
_PIPELINE_JSON = _REPO_ROOT / "pipeline" / "pipeline.json"
_MIGRATION_DOC = _REPO_ROOT / "docs" / "product" / "orchestrator" / "release-migration.md"


def test_release_yml_removed():
    """release.yml (and its triggers) is retired, not merely narrowed (issue #695)."""
    assert not _RELEASE_YML.exists(), (
        "release.yml should have been deleted in issue #695's workflow-removal cutover."
    )


def test_release_patch_tag_yml_removed():
    """release-patch-tag.yml is retired now that 05_continuous/pr/patch-tag
    (issue #694) owns PATCH tagging."""
    assert not _RELEASE_PATCH_TAG_YML.exists(), (
        "release-patch-tag.yml should have been deleted in issue #695's "
        "workflow-removal cutover."
    )


# ---------------------------------------------------------------------------
# Scenario R2: production ownership transferred to the orchestrator
# ---------------------------------------------------------------------------

class TestOrchestratorOwnsProduction:
    def test_weekly_release_flow_in_pipeline(self):
        """Scenario R2: the orchestrator must own a weekly-release flow."""
        import json
        with open(_PIPELINE_JSON) as f:
            pipeline = json.load(f)
        flows = pipeline.get("flows", {})
        assert "weekly-release" in flows, (
            "weekly-release flow not found in pipeline.json; the orchestrator "
            "must own this flow after the production cutover."
        )

    def test_weekly_release_flow_has_schedule(self):
        """Scenario R2: the weekly-release flow must have a schedule trigger."""
        import json
        with open(_PIPELINE_JSON) as f:
            pipeline = json.load(f)
        flow = pipeline["flows"]["weekly-release"]
        trigger = flow.get("trigger", {})
        assert "schedule" in trigger, (
            "weekly-release flow trigger must declare a schedule (cron)."
        )

    def test_weekly_release_script_exists(self):
        """Scenario R2: the script invoked by the weekly-release flow must exist."""
        import json
        with open(_PIPELINE_JSON) as f:
            pipeline = json.load(f)
        steps = pipeline["flows"]["weekly-release"].get("steps", [])
        assert steps, "weekly-release flow must have at least one step."
        script_path = steps[0].get("script")
        assert script_path, "weekly-release step must declare a script path."
        assert (_REPO_ROOT / script_path).exists(), (
            f"weekly-release script {script_path!r} not found at {_REPO_ROOT / script_path}"
        )

    def test_patch_tag_flow_in_pipeline(self):
        """Scenario R3: the orchestrator must own a patch-tag flow (issue #694)."""
        import json
        with open(_PIPELINE_JSON) as f:
            pipeline = json.load(f)
        flows = pipeline.get("flows", {})
        assert "patch-tag" in flows, (
            "patch-tag flow not found in pipeline.json; the orchestrator "
            "must own PATCH tagging after release-patch-tag.yml's removal."
        )

    def test_patch_tag_flow_has_pull_request_event_trigger(self):
        """Scenario R3: the patch-tag flow must fire on a merged pull request."""
        import json
        with open(_PIPELINE_JSON) as f:
            pipeline = json.load(f)
        trigger = pipeline["flows"]["patch-tag"].get("trigger", {})
        assert trigger.get("event") == "pull_request.closed", (
            "patch-tag flow trigger must declare event: pull_request.closed."
        )

    def test_patch_tag_script_exists(self):
        """Scenario R3: the script invoked by the patch-tag flow must exist."""
        import json
        with open(_PIPELINE_JSON) as f:
            pipeline = json.load(f)
        steps = pipeline["flows"]["patch-tag"].get("steps", [])
        assert steps, "patch-tag flow must have at least one step."
        script_path = steps[0].get("script")
        assert script_path, "patch-tag step must declare a script path."
        assert (_REPO_ROOT / script_path).exists(), (
            f"patch-tag script {script_path!r} not found at {_REPO_ROOT / script_path}"
        )


# ---------------------------------------------------------------------------
# Scenario R4: migration documentation is present and accessible
# ---------------------------------------------------------------------------

class TestMigrationDocumentation:
    def test_migration_doc_exists(self):
        """Scenario R4: migration doc must be present in the repo."""
        assert _MIGRATION_DOC.exists(), (
            f"migration documentation not found at {_MIGRATION_DOC}; "
            "create docs/product/orchestrator/release-migration.md."
        )

    def test_migration_doc_has_rollback_section(self):
        """Scenario R4: migration doc must contain a rollback plan."""
        text = _MIGRATION_DOC.read_text()
        assert re.search(r'(?i)rollback', text), (
            "migration documentation must include a rollback plan."
        )

    def test_migration_doc_describes_manual_dispatch(self):
        """Scenario R4: migration doc must describe how to manually trigger the flow."""
        text = _MIGRATION_DOC.read_text()
        assert "dispatch" in text.lower() or "manual" in text.lower(), (
            "migration documentation must describe manual dispatch/retry."
        )
