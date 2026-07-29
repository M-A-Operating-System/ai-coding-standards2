"""Tests for the human-applied gate-label guard (issue #263 / CR-02).

Threat: a prompt-injected agent runs
``gh issue edit N --add-label "prd-writer:approved"`` to self-approve its OWN
human gate. Since PR #262 agents run with the repo-scoped GITHUB_TOKEN, so an
agent-applied label is authored by a bot account
(``actor.type == "Bot"`` and/or a login ending in ``[bot]``). A genuine human
approval is authored by a real user login.

The guard (:func:`_gate_label_human_applied`) inspects the issue's ``labeled``
events, finds the most recent one for the gate label, and returns False only
when that actor is determinably a bot. It is fail-open: on any API error,
missing event, or indeterminate actor it logs a warning and returns True.
"""

import logging
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline_orchestrator import (
    AgentDef,
    _gate_label_human_applied,
    dependencies_complete,
)

REPO = "org/repo"
GATE = "prd-writer:approved"
ISSUE = 263


def _gh_returning(events):
    gh = MagicMock()
    gh._get = MagicMock(return_value=events)
    return gh


def _labeled_event(name, login, actor_type):
    return {
        "event": "labeled",
        "label": {"name": name},
        "actor": {"login": login, "type": actor_type},
    }


# ---------------------------------------------------------------------------
# _gate_label_human_applied
# ---------------------------------------------------------------------------

class TestGateLabelHumanApplied:
    def test_bot_actor_type_returns_false(self):
        """Most-recent labeled event actor is a Bot -> gate NOT satisfied."""
        gh = _gh_returning([
            _labeled_event(GATE, "github-actions[bot]", "Bot"),
        ])
        assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is False
        gh._get.assert_called_once_with(f"/repos/{REPO}/issues/{ISSUE}/events")

    def test_bot_login_suffix_returns_false(self):
        """A [bot] login suffix is treated as a bot even without type == Bot."""
        gh = _gh_returning([
            _labeled_event(GATE, "some-app[bot]", "User"),
        ])
        assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is False

    def test_human_actor_returns_true(self):
        """Human (actor.type 'User') applied the gate -> satisfied."""
        gh = _gh_returning([
            _labeled_event(GATE, "andrew", "User"),
        ])
        assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is True

    def test_most_recent_labeled_event_wins(self):
        """When both a human and a later bot labeled the gate, the last one decides."""
        gh = _gh_returning([
            _labeled_event(GATE, "andrew", "User"),
            _labeled_event(GATE, "github-actions[bot]", "Bot"),
        ])
        assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is False

        gh = _gh_returning([
            _labeled_event(GATE, "github-actions[bot]", "Bot"),
            _labeled_event(GATE, "andrew", "User"),
        ])
        assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is True

    def test_ignores_other_labels_and_event_types(self):
        """Only 'labeled' events for the exact gate label are considered."""
        gh = _gh_returning([
            _labeled_event("other:label", "github-actions[bot]", "Bot"),
            {"event": "unlabeled", "label": {"name": GATE},
             "actor": {"login": "github-actions[bot]", "type": "Bot"}},
            _labeled_event(GATE, "andrew", "User"),
        ])
        assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is True

    def test_events_call_raises_fails_open(self, caplog):
        """A transient API error must not halt the pipeline: fail-open (True) + warn."""
        gh = MagicMock()
        gh._get = MagicMock(side_effect=RuntimeError("boom"))
        with caplog.at_level(logging.WARNING):
            assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is True
        assert any("fail-open" in r.message for r in caplog.records)

    def test_empty_events_fails_open(self, caplog):
        """No matching labeled event -> allow (fail-open) + warn."""
        gh = _gh_returning([])
        with caplog.at_level(logging.WARNING):
            assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is True
        assert any("fail-open" in r.message for r in caplog.records)

    def test_non_list_payload_fails_open(self, caplog):
        """An unexpected (non-list) payload is treated as indeterminate -> allow."""
        gh = _gh_returning({"unexpected": "shape"})
        with caplog.at_level(logging.WARNING):
            assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is True
        assert any("fail-open" in r.message for r in caplog.records)

    def test_indeterminate_actor_fails_open(self, caplog):
        """A labeled event without a usable actor -> allow (fail-open) + warn."""
        gh = _gh_returning([
            {"event": "labeled", "label": {"name": GATE}, "actor": None},
        ])
        with caplog.at_level(logging.WARNING):
            assert _gate_label_human_applied(gh, REPO, ISSUE, GATE) is True
        assert any("fail-open" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# dependencies_complete wiring
# ---------------------------------------------------------------------------

def _gated_dep() -> AgentDef:
    return AgentDef(
        agent="01_product_docs/prd-writer",
        phase="01_product_docs",
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=True,
        human_gate_label=GATE,
        description="gated dependency",
    )


def _downstream() -> AgentDef:
    return AgentDef(
        agent="02_plan/planner",
        phase="02_plan",
        objects=["issue"],
        trigger={},
        dependencies=["01_product_docs/prd-writer"],
        human_gate_after=False,
        human_gate_label=None,
        description="depends on prd-writer",
    )


class TestDependenciesCompleteGuard:
    def _labels(self):
        dep = _gated_dep()
        return {dep.complete_label, dep.human_gate_label}

    def test_bot_applied_gate_blocks_dependencies_complete(self):
        """A bot-self-applied gate label does not satisfy the dependency gate."""
        pipeline_map = {"01_product_docs/prd-writer": _gated_dep()}
        gh = _gh_returning([
            _labeled_event(GATE, "github-actions[bot]", "Bot"),
        ])
        assert dependencies_complete(
            self._labels(), _downstream(), pipeline_map,
            gh=gh, repo=REPO, work_item_number=ISSUE,
        ) is False

    def test_human_applied_gate_allows_dependencies_complete(self):
        """A human-applied gate label satisfies the dependency gate."""
        pipeline_map = {"01_product_docs/prd-writer": _gated_dep()}
        gh = _gh_returning([
            _labeled_event(GATE, "andrew", "User"),
        ])
        assert dependencies_complete(
            self._labels(), _downstream(), pipeline_map,
            gh=gh, repo=REPO, work_item_number=ISSUE,
        ) is True

    def test_no_gh_client_skips_verification(self):
        """Pure-unit callers (no gh) are unaffected: gate presence alone satisfies."""
        pipeline_map = {"01_product_docs/prd-writer": _gated_dep()}
        assert dependencies_complete(
            self._labels(), _downstream(), pipeline_map,
        ) is True

    def test_bot_gate_fails_open_on_api_error(self):
        """Even with gh wired, an events API error must not block the pipeline."""
        pipeline_map = {"01_product_docs/prd-writer": _gated_dep()}
        gh = MagicMock()
        gh._get = MagicMock(side_effect=RuntimeError("boom"))
        assert dependencies_complete(
            self._labels(), _downstream(), pipeline_map,
            gh=gh, repo=REPO, work_item_number=ISSUE,
        ) is True
