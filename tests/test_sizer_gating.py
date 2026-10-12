"""Tests for issue #565: sizer gating in standard-delivery.

Covers the two scenarios added to docs/features/pipeline.md:

  - build-affecting steps blocked while sizer is pending or in progress
  - issue flows through standard-delivery after sizer pass-through

The structural tests verify that pipeline.json itself encodes the gating
correctly (sizer before prd-writer in standard-delivery, prd-writer triggers
on sizer:complete). The eligibility tests verify _should_run behaviour against
the scenarios.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline_orchestrator import (
    AgentDef,
    WorkItem,
    _should_run,
    load_pipeline,
    pipeline_by_name,
)

PIPELINE_PATH = Path(__file__).parent.parent / "pipeline" / "pipeline.json"


def _agents_by_name():
    agents, _ = load_pipeline(PIPELINE_PATH)
    return {a.agent: a for a in agents}


def _all_agents():
    agents, _ = load_pipeline(PIPELINE_PATH)
    return agents


def _wi(labels):
    return WorkItem(
        number=1, kind="issue", title="t",
        labels=set(labels), url="https://github.com/x/y/issues/1",
    )


def _noop_gh():
    gh = MagicMock()
    gh._get.return_value = []
    return gh


# ---------------------------------------------------------------------------
# Structural: pipeline.json wires sizer before prd-writer in standard-delivery
# ---------------------------------------------------------------------------

class TestSizerGatingStructure:
    """Verify pipeline.json encodes the correct sizer->prd-writer chain."""

    def test_sizer_is_a_step_in_standard_delivery(self):
        """standard-delivery must include 00_ondemand/sizer as a step."""
        import json
        raw = json.loads(PIPELINE_PATH.read_text())
        sd_agents = [s["agent"] for s in raw["flows"]["standard-delivery"]["steps"]]
        assert "00_ondemand/sizer" in sd_agents

    def test_sizer_precedes_prd_writer_in_standard_delivery(self):
        """sizer must appear before prd-writer in the standard-delivery step list."""
        import json
        raw = json.loads(PIPELINE_PATH.read_text())
        sd_agents = [s["agent"] for s in raw["flows"]["standard-delivery"]["steps"]]
        assert sd_agents.index("00_ondemand/sizer") < sd_agents.index("01_product_docs/prd-writer")

    def test_sizer_triggers_on_issue_classifier_complete_in_standard_delivery(self):
        """The standard-delivery sizer step must trigger on issue-classifier:complete."""
        import json
        raw = json.loads(PIPELINE_PATH.read_text())
        sd_steps = raw["flows"]["standard-delivery"]["steps"]
        sizer_step = next(s for s in sd_steps if s["agent"] == "00_ondemand/sizer")
        assert sizer_step["trigger"]["label"] == "issue-classifier:complete"

    def test_prd_writer_triggers_on_sizer_complete(self):
        """prd-writer must trigger on sizer:complete, not issue-classifier:complete."""
        a = _agents_by_name()
        assert a["01_product_docs/prd-writer"].trigger["label"] == "sizer:complete"

    def test_prd_writer_depends_on_sizer(self):
        """prd-writer must declare 00_ondemand/sizer as its dependency."""
        a = _agents_by_name()
        assert "00_ondemand/sizer" in a["01_product_docs/prd-writer"].dependencies

    def test_sizer_in_standard_delivery_has_self_gates(self):
        """The standard-delivery sizer step must be self-gating (pass-through emits complete directly)."""
        import json
        raw = json.loads(PIPELINE_PATH.read_text())
        sd_steps = raw["flows"]["standard-delivery"]["steps"]
        sizer_step = next(s for s in sd_steps if s["agent"] == "00_ondemand/sizer")
        assert sizer_step.get("self_gates") is True


# ---------------------------------------------------------------------------
# Scenario: build-affecting steps blocked while sizer is pending or in progress
# ---------------------------------------------------------------------------

class TestBuildAffectingStepsBlockedDuringSizing:
    """Feature: pipeline / Scenario: build-affecting steps blocked while sizer
    is pending or in progress.

    Given an issue has been classified (a classification: * label is present)
    and sizer has not yet reached a terminal outcome
    When the pipeline orchestrator evaluates which standard-delivery steps are
    eligible to run
    Then all build-affecting standard-delivery steps from prd-writer onward are
    ineligible to run
    """

    def _prd_writer(self):
        agents, _ = load_pipeline(PIPELINE_PATH)
        return next(a for a in agents
                    if a.agent == "01_product_docs/prd-writer"
                    and a.flow == "standard-delivery")

    def _pipeline_map(self):
        agents, _ = load_pipeline(PIPELINE_PATH)
        return pipeline_by_name(agents)

    def test_prd_writer_not_eligible_after_classification_only(self):
        """issue-classifier:complete alone must not unlock prd-writer."""
        agent = self._prd_writer()
        pm = self._pipeline_map()
        wi = _wi({"classification: bug", "issue-classifier:complete"})
        result = _should_run(agent, wi, wi.labels, pm, None, gh=_noop_gh(), repo="x/y")
        assert result is False

    def test_prd_writer_not_eligible_while_sizer_is_in_progress(self):
        """prd-writer must remain ineligible while sizer:wip is on the issue."""
        agent = self._prd_writer()
        pm = self._pipeline_map()
        wi = _wi({"classification: bug", "issue-classifier:complete", "sizer:wip"})
        result = _should_run(agent, wi, wi.labels, pm, None, gh=_noop_gh(), repo="x/y")
        assert result is False

    def test_prd_writer_not_eligible_while_sizer_is_in_review(self):
        """prd-writer must remain ineligible while sizer:review is on the issue
        (decomposition proposed, awaiting human approval)."""
        agent = self._prd_writer()
        pm = self._pipeline_map()
        wi = _wi({"classification: bug", "issue-classifier:complete", "sizer:review"})
        result = _should_run(agent, wi, wi.labels, pm, None, gh=_noop_gh(), repo="x/y")
        assert result is False


# ---------------------------------------------------------------------------
# Scenario: issue flows through standard-delivery after sizer pass-through
# ---------------------------------------------------------------------------

class TestIssueFlowsAfterSizerPassThrough:
    """Feature: pipeline / Scenario: issue flows through standard-delivery after
    sizer pass-through.

    Given an issue has been classified and sizer has determined it fits one
    development cycle (sizer reached a terminal outcome without applying the
    epic label)
    When the pipeline orchestrator evaluates which standard-delivery steps are
    eligible next
    Then prd-writer becomes eligible and the issue proceeds through
    standard-delivery without added waiting
    """

    def _prd_writer(self):
        agents, _ = load_pipeline(PIPELINE_PATH)
        return next(a for a in agents
                    if a.agent == "01_product_docs/prd-writer"
                    and a.flow == "standard-delivery")

    def _pipeline_map(self):
        agents, _ = load_pipeline(PIPELINE_PATH)
        return pipeline_by_name(agents)

    def test_prd_writer_eligible_after_sizer_passthrough(self):
        """After sizer:complete without epic, prd-writer must be eligible."""
        agent = self._prd_writer()
        pm = self._pipeline_map()
        wi = _wi({
            "classification: bug",
            "issue-classifier:complete",
            "sizer:complete",
        })
        result = _should_run(agent, wi, wi.labels, pm, None, gh=_noop_gh(), repo="x/y")
        assert result is True

    def test_prd_writer_blocked_by_epic_after_sizer_decomposition(self):
        """After sizer decomposes (applies epic), prd-writer must be excluded."""
        agent = self._prd_writer()
        pm = self._pipeline_map()
        wi = _wi({
            "classification: bug",
            "issue-classifier:complete",
            "sizer:complete",
            "epic",
        })
        result = _should_run(agent, wi, wi.labels, pm, None, gh=_noop_gh(), repo="x/y")
        assert result is False
