"""Tests for issue #565: sizer gating in standard-delivery.

Covers the two scenarios added to docs/features/pipeline.md:

  - build-affecting steps blocked while sizer is pending or in progress
  - issue flows through standard-delivery after sizer pass-through

Sizing is NOT duplicated as a second step inside standard-delivery (the
00_ondemand/sizer agent stays a single step, in its own standalone "sizer"
flow -- agent names are a global key throughout the orchestrator, including
pipeline_map, so the same agent cannot safely appear in two flows). Instead:

  - A new scripted step, 01_product_docs/request-sizing, triggers right
    after issue-classifier:complete and applies sizer:requested on every
    issue, instead of requiring a human to apply the label. It is a script
    step, not an agent's own label_request (a lifecycle status label like
    sizer:requested is only the orchestrator's to write) and not a
    post_steps hook (post_steps is reserved for pr-reviewer's
    mark-pr-ready.sh, per test_orchestrator_logic.py's own invariant).
  - prd-writer's trigger moves from issue-classifier:complete to
    sizer:complete, so build never starts while sizing is pending.

The structural tests verify pipeline.json encodes this correctly. The
eligibility tests verify _should_run behaviour against the scenarios.
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
    """Verify pipeline.json encodes the correct sizer->prd-writer chain
    without duplicating 00_ondemand/sizer across flows."""

    def test_sizer_is_not_duplicated_into_standard_delivery(self):
        """00_ondemand/sizer stays a single step, in its own standalone flow --
        not a second copy inside standard-delivery. Agent names are a global
        key throughout the orchestrator (pipeline_map, validate.py, the
        Mermaid generator); duplicating one across flows breaks all three."""
        import json
        raw = json.loads(PIPELINE_PATH.read_text())
        sd_agents = [s["agent"] for s in raw["flows"]["standard-delivery"]["steps"]]
        assert "00_ondemand/sizer" not in sd_agents

    def test_issue_classifier_does_not_request_sizing_itself(self):
        """sizer:requested is a lifecycle status label -- only the
        orchestrator may write it (pipeline/validate.py's lifecycle-label
        check); issue-classifier's own allowed_labels must not include it."""
        a = _agents_by_name()
        allowed = a["01_product_docs/issue-classifier"].allowed_labels.get("add", [])
        assert "sizer:requested" not in allowed

    def test_request_sizing_step_requests_sizing(self):
        """The scripted 01_product_docs/request-sizing step (not an agent's
        own label_request, not a post_steps hook -- post_steps is reserved
        for pr-reviewer's mark-pr-ready.sh) is what actually applies
        sizer:requested, triggered right after issue-classifier completes."""
        a = _agents_by_name()
        step = a["01_product_docs/request-sizing"]
        assert step.trigger["label"] == "issue-classifier:complete"
        assert step.dependencies == ["01_product_docs/issue-classifier"]

    def test_prd_writer_triggers_on_sizer_complete(self):
        """prd-writer must trigger on sizer:complete, not issue-classifier:complete."""
        a = _agents_by_name()
        assert a["01_product_docs/prd-writer"].trigger["label"] == "sizer:complete"

    def test_prd_writer_depends_on_request_sizing(self):
        """prd-writer's dependencies stay same-flow (request-sizing, not the
        cross-flow 00_ondemand/sizer -- pipeline.json's dependency validator
        requires a step's dependencies to be steps of its own flow); the
        actual sizer gate is expressed via trigger label."""
        a = _agents_by_name()
        assert a["01_product_docs/prd-writer"].dependencies == ["01_product_docs/request-sizing"]

    def test_standalone_sizer_flow_unchanged(self):
        """The standalone sizer flow's own trigger (sizer:requested) and
        self-gating behaviour are untouched by this fix."""
        import json
        raw = json.loads(PIPELINE_PATH.read_text())
        sizer_step = next(s for s in raw["flows"]["sizer"]["steps"]
                           if s["agent"] == "00_ondemand/sizer")
        assert sizer_step["trigger"]["label"] == "sizer:requested"
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
        wi = _wi({
            "classification: bug", "issue-classifier:complete",
            "request-sizing:complete", "sizer:wip",
        })
        result = _should_run(agent, wi, wi.labels, pm, None, gh=_noop_gh(), repo="x/y")
        assert result is False

    def test_prd_writer_not_eligible_while_sizer_is_in_review(self):
        """prd-writer must remain ineligible while sizer:review is on the issue
        (decomposition proposed, awaiting human approval)."""
        agent = self._prd_writer()
        pm = self._pipeline_map()
        wi = _wi({
            "classification: bug", "issue-classifier:complete",
            "request-sizing:complete", "sizer:review",
        })
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
            "request-sizing:complete",
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
            "request-sizing:complete",
            "sizer:complete",
            "epic",
        })
        result = _should_run(agent, wi, wi.labels, pm, None, gh=_noop_gh(), repo="x/y")
        assert result is False
