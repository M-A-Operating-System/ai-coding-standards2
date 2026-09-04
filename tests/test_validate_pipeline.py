"""The pipeline checks validate.py makes that the JSON Schema cannot (#408).

AS-1 says pipeline.json is the authoritative definition of what the pipeline
does. The schema states the file's shape; these three checks state what the
shape cannot: that a branch pattern names a token the orchestrator can
substitute, that every script the file names is on disk, and that no step's
declared allowances cover a label only the orchestrator may write.

Each is checked both ways round -- the shipped file clears it, and a
deliberately broken definition is caught -- so a check that silently stopped
looking would fail here.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from validate import (  # noqa: E402
    NAMING_TOKENS,
    validate_naming_tokens,
    validate_named_scripts_exist,
    validate_no_step_grants_itself_a_lifecycle_or_gate_label,
)

PIPELINE_PATH = REPO_ROOT / "pipeline" / "pipeline.json"
STATUSES_PATH = REPO_ROOT / "pipeline" / "statuses.json"


@pytest.fixture
def shipped():
    return json.loads(PIPELINE_PATH.read_text())


def _flow(**naming):
    return {
        "flows": {
            "a-flow": {
                "description": "d",
                "trigger": {"kind": "issue"},
                "naming": naming,
                "steps": [],
            },
        },
    }


def _step(**overrides):
    entry = {
        "agent": "03_execute/coder",
        "phase": "03_execute",
        "trigger": {"event": "issue.opened"},
        "dependencies": [],
        "human_gate_after": False,
        "description": "d",
        "expected_effect": {"commits": True},
    }
    entry.update(overrides)
    return {"flows": {"a-flow": {"description": "d", "trigger": {"kind": "issue"}, "steps": [entry]}}}


# ---------------------------------------------------------------------------
# validate_naming_tokens
# ---------------------------------------------------------------------------

class TestNamingTokens:
    def test_the_shipped_pipeline_clears_it(self, shipped):
        assert validate_naming_tokens(shipped) == []

    def test_a_known_token_is_accepted(self):
        assert validate_naming_tokens(_flow(branch="issue-{number}")) == []
        assert validate_naming_tokens(
            _flow(branch="issue-{number}", base="feature-{parent_number}")
        ) == []

    def test_an_unknown_token_in_the_primary_branch_is_caught(self):
        errors = validate_naming_tokens(_flow(branch="issue-{titel}"))
        assert len(errors) == 1
        assert "titel" in errors[0] and "a-flow" in errors[0]

    def test_an_unknown_token_in_the_base_branch_is_caught(self):
        errors = validate_naming_tokens(_flow(branch="issue-{number}", base="{epic}"))
        assert len(errors) == 1 and "epic" in errors[0]

    def test_an_unknown_token_in_a_pull_requests_branch_is_caught(self):
        errors = validate_naming_tokens(_flow(
            branch="issue-{number}",
            pull_requests=[{"id": "docs", "branch": "issue-{number}-{author}"}],
        ))
        assert len(errors) == 1
        assert "author" in errors[0] and "docs" in errors[0]

    def test_the_message_names_the_tokens_that_do_exist(self):
        errors = validate_naming_tokens(_flow(branch="{nope}"))
        for token in NAMING_TOKENS:
            assert token in errors[0]

    def test_a_flow_with_no_naming_is_fine(self):
        assert validate_naming_tokens({
            "flows": {"a": {"description": "d", "trigger": {"kind": "issue"}, "steps": []}},
        }) == []


# ---------------------------------------------------------------------------
# validate_named_scripts_exist
# ---------------------------------------------------------------------------

class TestNamedScriptsExist:
    def test_the_shipped_pipeline_clears_it(self, shipped):
        assert validate_named_scripts_exist(shipped, REPO_ROOT) == []

    def test_a_script_step_pointing_at_nothing_is_caught(self, tmp_path):
        errors = validate_named_scripts_exist(
            _step(type="script", script=".github/scripts/not-here.sh"), tmp_path,
        )
        assert len(errors) == 1
        assert "not-here.sh" in errors[0] and "03_execute/coder" in errors[0]

    def test_a_post_step_pointing_at_nothing_is_caught(self, tmp_path):
        errors = validate_named_scripts_exist(
            _step(post_steps=[".github/scripts/gone.sh"]), tmp_path,
        )
        assert len(errors) == 1 and "post_steps" in errors[0]

    def test_a_lifecycle_hook_pointing_at_nothing_is_caught(self, tmp_path):
        raw = _step()
        raw["defaults"] = {"agent_lifecycle": {"before": [".github/scripts/gone.sh"]}}
        errors = validate_named_scripts_exist(raw, tmp_path)
        assert len(errors) == 1 and "agent_lifecycle.before" in errors[0]

    def test_a_script_that_is_there_clears_it(self, tmp_path):
        script = tmp_path / ".github" / "scripts" / "here.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/usr/bin/env bash\n")
        assert validate_named_scripts_exist(
            _step(type="script", script=".github/scripts/here.sh"), tmp_path,
        ) == []

    def test_an_agent_steps_absent_script_field_is_not_a_finding(self, tmp_path):
        """An agent step names no script; there is nothing to look for."""
        assert validate_named_scripts_exist(_step(), tmp_path) == []


# ---------------------------------------------------------------------------
# validate_no_step_grants_itself_a_lifecycle_or_gate_label
# ---------------------------------------------------------------------------

class TestNoSelfGrantedGateOrLifecycleLabel:
    def test_the_shipped_pipeline_clears_it(self, shipped):
        assert validate_no_step_grants_itself_a_lifecycle_or_gate_label(
            shipped, STATUSES_PATH,
        ) == []

    def test_a_literal_gate_label_grant_is_caught(self):
        raw = _step(
            human_gate_label="coder:approved",
            allowed_labels={"add": ["coder:approved"], "remove": []},
        )
        errors = validate_no_step_grants_itself_a_lifecycle_or_gate_label(raw, STATUSES_PATH)
        assert errors and "human gate label" in errors[0]

    def test_a_wildcard_broad_enough_to_sweep_a_gate_label_in_is_caught(self):
        """A glob is exactly how this would happen by accident."""
        raw = _step(
            human_gate_label="coder:approved",
            allowed_labels={"add": ["coder:*"], "remove": []},
        )
        errors = validate_no_step_grants_itself_a_lifecycle_or_gate_label(raw, STATUSES_PATH)
        assert errors
        assert any("human gate label" in e for e in errors)

    def test_a_lifecycle_label_grant_is_caught(self):
        raw = _step(allowed_labels={"add": ["coder:complete"], "remove": []})
        errors = validate_no_step_grants_itself_a_lifecycle_or_gate_label(raw, STATUSES_PATH)
        assert errors and "lifecycle status label" in errors[0]

    def test_a_grant_on_the_remove_side_is_caught_too(self):
        raw = _step(allowed_labels={"add": [], "remove": ["coder:blocked"]})
        errors = validate_no_step_grants_itself_a_lifecycle_or_gate_label(raw, STATUSES_PATH)
        assert errors and "allowed_labels.remove" in errors[0]

    def test_an_ordinary_label_grant_is_left_alone(self):
        raw = _step(allowed_labels={"add": ["needs-design", "area:*"], "remove": ["stale"]})
        assert validate_no_step_grants_itself_a_lifecycle_or_gate_label(
            raw, STATUSES_PATH,
        ) == []

    def test_an_unreadable_statuses_file_is_reported_not_ignored(self, tmp_path):
        """Fail loud: a check that cannot run must not read as a clean pass."""
        errors = validate_no_step_grants_itself_a_lifecycle_or_gate_label(
            _step(), tmp_path / "nope.json",
        )
        assert len(errors) == 1 and "could not read statuses" in errors[0]
