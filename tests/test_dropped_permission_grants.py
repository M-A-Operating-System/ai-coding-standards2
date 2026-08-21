"""Tests for the untrusted-workspace grant drop (issue #362).

The Claude CLI discards every `permissions.allow` entry in
`.claude/settings.json` unless the workspace carries
`projects[<root>].hasTrustDialogAccepted: true` in the CLI's own config. It
warns on stderr and runs with narrower permissions than the repo configured,
which is invisible to both the orchestrator and the agent: the agent just sees
a denial on a path the repo explicitly granted.

The fix is to name it. These tests pin that the orchestrator reports the drop
at WARNING, counts it, and stays quiet when there is nothing to report.
"""
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
import pipeline_orchestrator as po


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A repo root with one allow entry and a CLI config that does not trust it."""
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Edit(.claude/agents/**)"]}})
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"projects": {str(root): {"hasTrustDialogAccepted": False}}})
    )

    monkeypatch.setattr(po, "SUBMODULE_ROOT", root)
    monkeypatch.setattr(po, "_WORKSPACE_TRUST_WARNED", False)
    monkeypatch.setenv("AI_AGILE_ROOT", str(root))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return root, home


def _trust(home, root, trusted):
    (home / ".claude.json").write_text(
        json.dumps({"projects": {str(root): {"hasTrustDialogAccepted": trusted}}})
    )


def test_dropped_grant_is_counted(workspace):
    assert po._warn_if_grants_dropped() == 1


def test_dropped_grant_is_logged_at_warning(workspace, caplog):
    with caplog.at_level(logging.WARNING, logger=po.log.name):
        po._warn_if_grants_dropped()
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno >= logging.WARNING
    message = record.getMessage()
    assert "Edit(.claude/agents/**)" in message, "the warning must name the entry"
    assert "hasTrustDialogAccepted" in message, "the warning must name the remedy"


def test_warning_is_emitted_once_per_run(workspace, caplog):
    """A per-agent warning would bury the log on a multi-agent tick."""
    with caplog.at_level(logging.WARNING, logger=po.log.name):
        po._warn_if_grants_dropped()
        po._warn_if_grants_dropped()
        po._warn_if_grants_dropped()
    assert len(caplog.records) == 1


def test_count_is_reported_on_every_call(workspace):
    """The count feeds the audit event, so it must survive the warn-once flag."""
    po._warn_if_grants_dropped()
    assert po._warn_if_grants_dropped() == 1


def test_trusted_workspace_drops_nothing(workspace, caplog):
    root, home = workspace
    _trust(home, root, True)
    with caplog.at_level(logging.WARNING, logger=po.log.name):
        assert po._warn_if_grants_dropped() == 0
    assert caplog.records == []


def test_no_allow_entries_drops_nothing(workspace, caplog):
    root, _ = workspace
    (root / ".claude" / "settings.json").write_text(json.dumps({"permissions": {}}))
    with caplog.at_level(logging.WARNING, logger=po.log.name):
        assert po._warn_if_grants_dropped() == 0
    assert caplog.records == []


def test_unreadable_config_is_not_reported_as_a_drop(workspace, caplog):
    """Absent evidence is not evidence of a drop -- do not cry wolf."""
    root, home = workspace
    (home / ".claude.json").unlink()
    with caplog.at_level(logging.WARNING, logger=po.log.name):
        assert po._warn_if_grants_dropped() == 0
    assert caplog.records == []


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Pending: add \"Edit(.claude/AGENTS.md)\" to permissions.allow in "
        ".claude/settings.json. Editing that file is blocked in the session "
        "that raised #362, so the declaration has not been applied yet. This "
        "test passes the moment it is, and can then lose the xfail marker."
    ),
)
def test_agents_md_is_an_editable_target():
    """Defect 2: `Edit(.claude/agents/**)` does not match `.claude/AGENTS.md`,
    which sits one level up and is a legitimate edit target."""
    settings = json.loads(
        (Path(__file__).parent.parent / ".claude" / "settings.json").read_text()
    )
    allow = settings.get("permissions", {}).get("allow", [])
    assert "Edit(.claude/AGENTS.md)" in allow, (
        ".claude/AGENTS.md is the shared protocol every agent inlines and a "
        "legitimate edit target; Edit(.claude/agents/**) does not cover it"
    )
