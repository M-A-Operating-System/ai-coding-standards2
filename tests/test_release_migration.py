"""Tests for issue #621: shadow runs, parity validation, and production migration.

Covers:
- Scenario R2: Production release ownership transferred to orchestrator after
  parity confirmed -- the weekly-release flow in pipeline.json owns the
  scheduled release, not release.yml.
- Scenario R3: Existing Wednesday workflow no longer independently publishes
  releases -- release.yml no longer carries a schedule trigger.
- Scenario R4: Migration documentation is present and accessible.
- Scenario R5: Manual dispatch and retry continue to function -- release.yml
  retains workflow_dispatch and push:tags:v* triggers.
"""

import re
from pathlib import Path

import yaml
import pytest

_REPO_ROOT = Path(__file__).parent.parent
_RELEASE_YML = _REPO_ROOT / ".github" / "workflows" / "release.yml"
_PIPELINE_JSON = _REPO_ROOT / "pipeline" / "pipeline.json"
_MIGRATION_DOC = _REPO_ROOT / "docs" / "product" / "orchestrator" / "release-migration.md"


# ---------------------------------------------------------------------------
# Scenario R3: existing Wednesday workflow no longer independently publishes
# ---------------------------------------------------------------------------

def _release_yml_on():
    """Return the 'on:' block from release.yml.

    PyYAML parses 'on:' as the boolean key True (YAML 1.1 quirk), so we
    look for both True and the string 'on'.
    """
    with open(_RELEASE_YML) as f:
        doc = yaml.safe_load(f)
    return doc.get(True) or doc.get("on") or {}


class TestReleaseYmlRetired:
    def test_schedule_trigger_removed(self):
        """Scenario R3: release.yml must not have a schedule trigger."""
        on = _release_yml_on()
        assert "schedule" not in on, (
            "release.yml still carries a schedule trigger; it must be removed "
            "after cutover to the orchestrator-owned weekly-release flow."
        )

    def test_workflow_dispatch_retained(self):
        """Scenario R5: emergency manual dispatch must still be available."""
        on = _release_yml_on()
        assert "workflow_dispatch" in on, (
            "release.yml must retain workflow_dispatch for emergency manual releases."
        )

    def test_push_tags_trigger_retained(self):
        """Scenario R5: off-cycle tag-push releases must still work."""
        on = _release_yml_on()
        push = on.get("push") or {}
        tags = push.get("tags") or []
        assert any("v*" in t for t in tags), (
            "release.yml must retain push:tags:v* for off-cycle releases."
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
        """Scenario R4/R5: migration doc must describe how to manually trigger the flow."""
        text = _MIGRATION_DOC.read_text()
        assert "dispatch" in text.lower() or "manual" in text.lower(), (
            "migration documentation must describe manual dispatch/retry."
        )
