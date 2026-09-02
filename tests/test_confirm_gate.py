"""Tests for issue #403's --confirm-gate interactive gate-crossing mode
(PRODUCT.md MI-7): the orchestrator, not the driver, writes a human-gate
label, on the driver's relayed word that a person confirmed. Refuses rather
than silently no-ops on a missing gate, an already-present label, or an
already-present label that wasn't verifiably human-applied (issue #377).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pipeline_orchestrator as po

REPO_ROOT = Path(__file__).parent.parent
PIPELINE = REPO_ROOT / "pipeline" / "pipeline.json"

GATED_AGENT = "01_product_docs/prd-writer"
GATE_LABEL = "prd-writer:approved"
UNGATED_AGENT = "03_execute/coder"


def _args(**overrides):
    args = MagicMock()
    args.agent = GATED_AGENT
    args.issue = 42
    args.repo = "test/repo"
    args.pipeline = PIPELINE
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def _gh_with_labels(labels, events=None):
    gh = MagicMock()
    gh.get_issue_labels.return_value = set(labels)
    gh._get = MagicMock(return_value=events or [])
    return gh


@pytest.fixture(autouse=True)
def _no_stray_audit_output(monkeypatch):
    monkeypatch.setattr(po, "_emit_audit_event", lambda *a, **k: None)


class TestConfirmGateValidation:
    def test_missing_agent_exits(self):
        with patch.object(po, "_discover_github_token", return_value="t"):
            with pytest.raises(SystemExit) as excinfo:
                po._run_confirm_gate(_args(agent=None))
        assert excinfo.value.code == 1

    def test_missing_issue_exits(self):
        with patch.object(po, "_discover_github_token", return_value="t"):
            with pytest.raises(SystemExit) as excinfo:
                po._run_confirm_gate(_args(issue=None))
        assert excinfo.value.code == 1

    def test_missing_repo_exits(self):
        with patch.object(po, "_discover_github_token", return_value="t"):
            with pytest.raises(SystemExit) as excinfo:
                po._run_confirm_gate(_args(repo=None))
        assert excinfo.value.code == 1

    def test_unknown_agent_exits(self):
        with patch.object(po, "_discover_github_token", return_value="t"):
            with pytest.raises(SystemExit) as excinfo:
                po._run_confirm_gate(_args(agent="not/a-real-agent"))
        assert excinfo.value.code == 1

    def test_agent_with_no_human_gate_label_exits(self):
        """--confirm-gate has nothing to confirm for a step with no gate."""
        with patch.object(po, "_discover_github_token", return_value="t"):
            with pytest.raises(SystemExit) as excinfo:
                po._run_confirm_gate(_args(agent=UNGATED_AGENT))
        assert excinfo.value.code == 1


class TestConfirmGateApplication:
    def test_absent_label_is_applied_and_audited(self):
        gh = _gh_with_labels(labels=set())
        events = []
        with patch.object(po, "_discover_github_token", return_value="t"), \
             patch.object(po, "GitHubClient", return_value=gh), \
             patch.object(po, "_emit_audit_event", lambda e: events.append(e)):
            po._run_confirm_gate(_args())

        gh.add_label.assert_called_once_with(42, GATE_LABEL)
        assert len(events) == 1
        assert events[0]["event"] == "gate.confirmed"
        assert GATE_LABEL in events[0]["detail"]

    def test_already_present_and_human_applied_is_a_no_op(self):
        gh = _gh_with_labels(
            labels={GATE_LABEL},
            events=[{
                "event": "labeled", "label": {"name": GATE_LABEL},
                "actor": {"login": "andrew", "type": "User"},
            }],
        )
        with patch.object(po, "_discover_github_token", return_value="t"), \
             patch.object(po, "GitHubClient", return_value=gh):
            po._run_confirm_gate(_args())  # must not raise

        gh.add_label.assert_not_called()

    def test_already_present_but_not_human_applied_refuses(self, caplog):
        """The exact trap issue #377 named: a bot-authored label is already
        present, and re-adding it would be a silent no-op that leaves the
        bot-authored event as the most recent one. Must refuse, not proceed."""
        gh = _gh_with_labels(
            labels={GATE_LABEL},
            events=[{
                "event": "labeled", "label": {"name": GATE_LABEL},
                "actor": {"login": "claude[bot]", "type": "Bot"},
            }],
        )
        with patch.object(po, "_discover_github_token", return_value="t"), \
             patch.object(po, "GitHubClient", return_value=gh):
            with pytest.raises(SystemExit) as excinfo:
                po._run_confirm_gate(_args())
        assert excinfo.value.code == 1
        gh.add_label.assert_not_called()
        assert any(
            "--remove-label" in r.message and GATE_LABEL in r.message
            for r in caplog.records
        ), "must name the exact remove-label command to run first"
