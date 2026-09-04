"""Tests for merge-conflict agent pipeline integration.

Covers the five Gherkin acceptance criteria from issue #79:
  1. merge_conflict_agent_triggered_when_pr_has_conflicts_at_ready_for_review
  2. resolution_recommendations_posted_as_pr_comments
  3. pipeline_pauses_awaiting_human_approval_of_resolution_plan
  4. coding_agent_tasked_after_plan_approval
  5. clean_pr_is_not_affected_by_the_merge_conflict_agent
"""

import sys
import os
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import pipeline_orchestrator as orch
from pipeline_orchestrator import (
    AgentDef,
    AgentRunResult,
    WorkItem,
    dependencies_complete,
    load_pipeline,
    pipeline_by_name,
    process_work_item,
    promote_gated_agents,
    trigger_label_present,
    get_work_item_classification,
    _parse_agent_sentinel,
    STATUS_COMPLETE,
)

PIPELINE_JSON_PATH = Path(__file__).parent.parent / "pipeline" / "pipeline.json"


def _load_agent_from_pipeline(agent_name: str) -> AgentDef:
    """Load a real AgentDef from pipeline.json via the production loader.

    Used by trigger/dependency/exclusion/auto_approve assertions so they
    verify the shipped configuration rather than a hand-built fixture that
    the test itself populated (which would be tautological).
    """
    agents, _ = load_pipeline(PIPELINE_JSON_PATH)
    return pipeline_by_name(agents)[agent_name]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_merge_conflict_agent() -> AgentDef:
    """Build the merge-conflict AgentDef matching the pipeline.json entry."""
    return AgentDef(
        agent="03_execute/merge-conflict",
        phase="03_execute",
        objects=["issue"],
        trigger={"label": "ci-gate:complete"},
        dependencies=["03_execute/ci-gate"],
        human_gate_after=True,
        human_gate_label="merge-conflict:approved",
        description="Checks for merge conflicts on the issue PR after CI passes.",
        exclude_classifications=["spike"],
    )


def _make_ci_gate_agent() -> AgentDef:
    return AgentDef(
        agent="03_execute/ci-gate",
        phase="03_execute",
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="CI gate agent",
    )


def _make_pr_reviewer_agent() -> AgentDef:
    """Build the pr-reviewer AgentDef matching the pipeline.json entry.

    pr-reviewer depends on merge-conflict and its human gate.
    Its trigger is merge-conflict:complete.
    """
    return AgentDef(
        agent="03_execute/pr-reviewer",
        phase="03_execute",
        objects=["issue"],
        trigger={"label": "merge-conflict:complete"},
        dependencies=["03_execute/merge-conflict"],
        human_gate_after=False,
        human_gate_label=None,
        description="Reviews the draft PR after CI and merge-conflict pass.",
        exclude_classifications=["spike"],
    )


def _make_work_item(number: int = 42, labels: set = None, title: str = "Test issue") -> WorkItem:
    return WorkItem(
        number=number,
        kind="issue",
        title=title,
        labels=labels or set(),
        url=f"https://github.com/test/repo/issues/{number}",
    )


def _make_gh() -> MagicMock:
    gh = MagicMock()
    gh.add_label = MagicMock()
    gh.remove_label = MagicMock()
    gh.post_comment = MagicMock()
    # _gate_label_human_applied (issue #403, fail-closed) needs a genuine
    # human-authored 'labeled' event for merge-conflict:approved, the only
    # gate label this file exercises, so promotion tests don't each have to
    # configure gh._get themselves.
    gh._get = MagicMock(return_value=[
        {"event": "labeled", "label": {"name": "merge-conflict:approved"},
         "actor": {"login": "andrew", "type": "User"}},
    ])
    return gh


def merge_conflict_review_label() -> str:
    """The merge-conflict :review label, derived from the real AgentDef."""
    return _load_agent_from_pipeline("03_execute/merge-conflict").review_label


# ---------------------------------------------------------------------------
# Scenario 1: merge_conflict_agent_triggered_when_pr_has_conflicts_at_ready_for_review
# ---------------------------------------------------------------------------

class TestMergeConflictAgentTriggeredWhenPrHasConflicts:
    """Verify the merge-conflict agent becomes eligible when ci-gate:complete is on the issue.

    Trigger / dependency / exclusion assertions load the real AgentDef from
    pipeline.json so they verify the shipped configuration, not a literal the
    test itself wrote into a hand-built fixture.
    """

    def test_fixture_matches_pipeline_json(self):
        """Cross-check the hand-built fixture against the loaded pipeline.json entry.

        The fixture is still used by scenario tests that need an AgentDef with
        specific overrides; this guards it against drifting from the real config.
        """
        fixture = _make_merge_conflict_agent()
        real = _load_agent_from_pipeline("03_execute/merge-conflict")
        assert fixture.agent == real.agent
        assert fixture.trigger == real.trigger
        assert fixture.dependencies == real.dependencies
        assert fixture.human_gate_after == real.human_gate_after
        assert fixture.human_gate_label == real.human_gate_label
        assert fixture.exclude_classifications == real.exclude_classifications

    def test_trigger_met_when_ci_gate_complete(self):
        """Given ci-gate:complete is on the issue, the merge-conflict trigger is satisfied."""
        merge_conflict = _load_agent_from_pipeline("03_execute/merge-conflict")
        assert trigger_label_present({"ci-gate:complete"}, merge_conflict) is True

    def test_trigger_not_met_without_ci_gate_complete(self):
        """Without ci-gate:complete, the trigger is not satisfied."""
        merge_conflict = _load_agent_from_pipeline("03_execute/merge-conflict")
        assert trigger_label_present({"coder:complete"}, merge_conflict) is False

    def test_trigger_not_met_with_empty_labels(self):
        """Empty label set yields no trigger."""
        merge_conflict = _load_agent_from_pipeline("03_execute/merge-conflict")
        assert trigger_label_present(set(), merge_conflict) is False

    def test_dependencies_complete_when_ci_gate_done(self):
        """dependencies_complete returns True when ci-gate:complete is present."""
        agents, _ = load_pipeline(PIPELINE_JSON_PATH)
        pipeline_map = pipeline_by_name(agents)
        merge_conflict = pipeline_map["03_execute/merge-conflict"]
        labels = {"ci-gate:complete"}
        assert dependencies_complete(labels, merge_conflict, pipeline_map) is True

    def test_dependencies_not_complete_without_ci_gate(self):
        """dependencies_complete returns False when ci-gate:complete is absent."""
        agents, _ = load_pipeline(PIPELINE_JSON_PATH)
        pipeline_map = pipeline_by_name(agents)
        merge_conflict = pipeline_map["03_execute/merge-conflict"]
        assert dependencies_complete(set(), merge_conflict, pipeline_map) is False

    def test_spike_classification_excluded(self):
        """Spike issues are excluded from the merge-conflict agent (exclude_classifications)."""
        spike_issue = _make_work_item(title="[SPIKE] - Research approach")
        merge_conflict = _load_agent_from_pipeline("03_execute/merge-conflict")
        assert get_work_item_classification(spike_issue) == "spike"
        assert "spike" in merge_conflict.exclude_classifications

    def test_feature_classification_not_excluded(self):
        """Feature issues are not excluded from the merge-conflict agent."""
        feature_issue = _make_work_item(title="[FEATURE] - Add merge-conflict agent")
        merge_conflict = _load_agent_from_pipeline("03_execute/merge-conflict")
        assert get_work_item_classification(feature_issue) == "feature"
        assert "feature" not in merge_conflict.exclude_classifications

    def test_bug_classification_not_excluded(self):
        """Bug issues are not excluded from the merge-conflict agent."""
        bug_issue = _make_work_item(title="[BUG] - Pipeline stops on conflict")
        merge_conflict = _load_agent_from_pipeline("03_execute/merge-conflict")
        assert get_work_item_classification(bug_issue) == "bug"
        assert "bug" not in merge_conflict.exclude_classifications


# ---------------------------------------------------------------------------
# Scenario 2: resolution_recommendations_posted_as_pr_comments
# ---------------------------------------------------------------------------

class TestResolutionRecommendationsPostedAsPrComments:
    """When the agent finds conflicts it emits review; clean PRs emit complete.

    The agent's LLM behaviour (posting comments) is not unit-testable here;
    these tests verify that the orchestrator correctly interprets the sentinel
    the agent emits in each case.
    """

    def test_review_sentinel_parsed_when_conflicts_found(self):
        """When the agent emits AI_AGILE_STATUS: review, sentinel is parsed correctly."""
        agent_output = (
            "Conflict assessment complete. Resolution plan posted as PR comment.\n"
            'AI_AGILE_STATUS: review "Conflict resolution plan posted on PR"'
        )
        status, message = _parse_agent_sentinel(agent_output)
        assert status == "review"
        assert message == "Conflict resolution plan posted on PR"

    def test_complete_sentinel_parsed_when_no_conflicts(self):
        """When the PR is clean the agent emits complete and no review is needed."""
        agent_output = "No merge conflicts found. Branch is clean.\nAI_AGILE_STATUS: complete"
        status, message = _parse_agent_sentinel(agent_output)
        assert status == "complete"
        assert message == ""

    def test_blocked_sentinel_parsed_generically(self):
        """The sentinel parser handles a blocked sentinel with a quoted message.

        NOTE: the merge-conflict agent does not itself emit blocked — on a
        persistently UNKNOWN mergeability it posts a warning and emits
        complete (so pr-reviewer flags any conflicts downstream), and on
        CONFLICTING it emits review. This test only exercises the generic
        sentinel-parsing path for the blocked status, which the orchestrator
        shares across all agents.
        """
        agent_output = (
            "Some agent could not proceed.\n"
            'AI_AGILE_STATUS: blocked "Blocked — investigate"'
        )
        status, message = _parse_agent_sentinel(agent_output)
        assert status == "blocked"
        assert "investigate" in message.lower()

    def test_complete_sentinel_parsed_on_unknown_mergeability(self):
        """On persistently UNKNOWN mergeability the merge-conflict agent emits complete.

        Per the agent definition, an UNKNOWN-after-retry result posts a warning
        comment and advances with complete — it never emits blocked.
        """
        agent_output = (
            "GitHub mergeability check returned UNKNOWN after retry. Advancing.\n"
            "AI_AGILE_STATUS: complete"
        )
        status, message = _parse_agent_sentinel(agent_output)
        assert status == "complete"
        assert message == ""

    def test_no_sentinel_returns_none(self):
        """If the agent exits without emitting a sentinel, _parse_agent_sentinel returns None."""
        agent_output = "Agent ran but forgot to emit sentinel."
        status, _ = _parse_agent_sentinel(agent_output)
        assert status is None


# ---------------------------------------------------------------------------
# Scenario 3: pipeline_pauses_awaiting_human_approval_of_resolution_plan
# ---------------------------------------------------------------------------

class TestPipelinePausesAwaitingHumanApproval:
    """Verify the pipeline halts at the merge-conflict gate until a human approves."""

    def test_review_not_promoted_without_gate_label(self):
        """When :review exists but gate label is absent, promote_gated_agents takes no action."""
        merge_conflict = _make_merge_conflict_agent()
        labels = {"merge-conflict:review"}
        work_item = _make_work_item(labels=labels.copy())
        gh = _make_gh()

        result = promote_gated_agents(labels, [merge_conflict], work_item, gh)

        assert "merge-conflict:complete" not in result
        gh.add_label.assert_not_called()

    def test_pr_reviewer_blocked_when_merge_conflict_in_review(self):
        """pr-reviewer dependencies_complete returns False while merge-conflict is in :review."""
        pipeline_map = {"03_execute/merge-conflict": _make_merge_conflict_agent()}
        labels = {"merge-conflict:review"}
        assert dependencies_complete(labels, _make_pr_reviewer_agent(), pipeline_map) is False

    def test_pr_reviewer_blocked_when_merge_conflict_not_yet_run(self):
        """pr-reviewer is blocked when merge-conflict has not run at all (no labels)."""
        pipeline_map = {"03_execute/merge-conflict": _make_merge_conflict_agent()}
        assert dependencies_complete(set(), _make_pr_reviewer_agent(), pipeline_map) is False

    def test_promote_does_not_fire_for_other_agents(self):
        """promote_gated_agents only promotes agents that have both :review and gate label."""
        merge_conflict = _make_merge_conflict_agent()
        # Only :review present, no gate
        labels = {"merge-conflict:review", "coder:complete"}
        work_item = _make_work_item(labels=labels.copy())
        gh = _make_gh()

        result = promote_gated_agents(labels, [merge_conflict], work_item, gh)

        # coder:complete is unrelated — must not be touched
        assert "coder:complete" in result
        # merge-conflict stays in :review
        assert "merge-conflict:complete" not in result

    def test_rejection_clears_review_when_requested_applied(self):
        """Rejection branch: :requested applied while in :review (no gate, no complete).

        promote_gated_agents removes :review so :requested becomes the highest
        priority status on the next pass, triggering a re-run in the per-agent
        loop. The work item is NOT promoted to :complete.
        """
        merge_conflict = _make_merge_conflict_agent()
        labels = {"merge-conflict:review", "merge-conflict:requested"}
        work_item = _make_work_item(labels=labels.copy())
        gh = _make_gh()

        result = promote_gated_agents(labels, [merge_conflict], work_item, gh)

        # :review is cleared so :requested wins on the next tick
        assert "merge-conflict:review" not in result
        gh.remove_label.assert_called_once_with(work_item.number, "merge-conflict:review")
        # :requested is left in place to drive the re-run
        assert "merge-conflict:requested" in result
        # No promotion to :complete
        assert "merge-conflict:complete" not in result
        gh.add_label.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 4: coding_agent_tasked_after_plan_approval
# ---------------------------------------------------------------------------

class TestCodingAgentTaskedAfterPlanApproval:
    """After human approval, the pipeline advances through merge-conflict to pr-reviewer."""

    def test_review_promoted_to_complete_when_gate_applied(self):
        """promote_gated_agents transitions :review → :complete when gate label is applied."""
        merge_conflict = _make_merge_conflict_agent()
        labels = {"merge-conflict:review", "merge-conflict:approved"}
        work_item = _make_work_item(labels=labels.copy())
        gh = _make_gh()

        result = promote_gated_agents(labels, [merge_conflict], work_item, gh)

        assert "merge-conflict:complete" in result
        assert "merge-conflict:review" not in result
        gh.add_label.assert_called_once_with(work_item.number, "merge-conflict:complete")
        gh.remove_label.assert_called_once_with(work_item.number, "merge-conflict:review")

    def test_pr_reviewer_eligible_after_approval(self):
        """After gate approval, merge-conflict:complete + gate → pr-reviewer dependencies_complete."""
        pipeline_map = {"03_execute/merge-conflict": _make_merge_conflict_agent()}
        labels = {"merge-conflict:complete", "merge-conflict:approved"}
        assert dependencies_complete(labels, _make_pr_reviewer_agent(), pipeline_map) is True

    def test_pr_reviewer_trigger_satisfied_after_complete(self):
        """pr-reviewer trigger label (merge-conflict:complete) is present after promotion."""
        assert trigger_label_present(
            {"merge-conflict:complete"}, _make_pr_reviewer_agent()
        ) is True

    def test_pr_reviewer_blocked_without_gate_even_when_complete(self):
        """pr-reviewer is blocked when merge-conflict:complete is present but gate is absent."""
        pipeline_map = {"03_execute/merge-conflict": _make_merge_conflict_agent()}
        labels = {"merge-conflict:complete"}
        assert dependencies_complete(labels, _make_pr_reviewer_agent(), pipeline_map) is False

    def test_promote_idempotent_when_already_complete(self):
        """promote_gated_agents does not re-add :complete when it already exists."""
        merge_conflict = _make_merge_conflict_agent()
        labels = {"merge-conflict:complete", "merge-conflict:approved"}
        work_item = _make_work_item(labels=labels.copy())
        gh = _make_gh()

        promote_gated_agents(labels, [merge_conflict], work_item, gh)

        # :complete was already there — add_label must not be called again
        gh.add_label.assert_not_called()

    def test_promote_cleans_stale_review_after_mid_crash(self):
        """When both :complete and :review exist (mid-promotion crash), stale :review is removed."""
        merge_conflict = _make_merge_conflict_agent()
        labels = {
            "merge-conflict:complete",
            "merge-conflict:approved",
            "merge-conflict:review",
        }
        work_item = _make_work_item(labels=labels.copy())
        gh = _make_gh()

        result = promote_gated_agents(labels, [merge_conflict], work_item, gh)

        assert "merge-conflict:review" not in result
        assert "merge-conflict:complete" in result


# ---------------------------------------------------------------------------
# Scenario 5: clean_pr_is_not_affected_by_the_merge_conflict_agent
# ---------------------------------------------------------------------------

class TestCleanPrIsNotAffectedByMergeConflictAgent:
    """For a clean PR (no conflicts), the agent emits complete immediately.

    The orchestrator's auto_approve_on_complete=True on the merge-conflict entry
    causes it to auto-apply merge-conflict:approved alongside :complete, so the
    pipeline advances to pr-reviewer without any human action required.
    promote_gated_agents is a no-op because :review is never set.
    """

    def test_complete_without_review_does_not_trigger_promote(self):
        """Clean PR: merge-conflict emits complete directly; promote_gated_agents is a no-op."""
        merge_conflict = _make_merge_conflict_agent()
        labels = {"merge-conflict:complete"}
        work_item = _make_work_item(labels=labels.copy())
        gh = _make_gh()

        result = promote_gated_agents(labels, [merge_conflict], work_item, gh)

        # No :review present — nothing to promote
        gh.add_label.assert_not_called()
        gh.remove_label.assert_not_called()
        assert result == labels

    def test_pr_reviewer_eligible_after_clean_pr_auto_approve(self):
        """Clean PR: auto_approve_on_complete sets both :complete and :approved; pr-reviewer runs."""
        pipeline_map = {"03_execute/merge-conflict": _make_merge_conflict_agent()}
        # Both labels are present after orchestrator auto-approve
        labels = {"merge-conflict:complete", "merge-conflict:approved"}
        assert dependencies_complete(labels, _make_pr_reviewer_agent(), pipeline_map) is True

    def test_pr_reviewer_still_blocked_without_gate_label(self):
        """dependencies_complete correctly blocks pr-reviewer when :approved is absent.

        This scenario can't arise for auto_approve_on_complete agents in normal flow,
        but the guard in dependencies_complete must remain correct for all agent types.
        """
        pipeline_map = {"03_execute/merge-conflict": _make_merge_conflict_agent()}
        labels = {"merge-conflict:complete"}
        assert dependencies_complete(labels, _make_pr_reviewer_agent(), pipeline_map) is False

    def test_pr_reviewer_trigger_satisfied_after_clean_pr(self):
        """merge-conflict:complete satisfies pr-reviewer's trigger."""
        assert trigger_label_present(
            {"merge-conflict:complete"}, _make_pr_reviewer_agent()
        ) is True

    def test_pr_reviewer_trigger_not_satisfied_without_merge_conflict_complete(self):
        """Without merge-conflict:complete, pr-reviewer trigger is not met."""
        assert trigger_label_present(
            {"merge-conflict:wip"}, _make_pr_reviewer_agent()
        ) is False

    def test_auto_approve_on_complete_applies_gate_label(self):
        """Orchestrator auto-applies human_gate_label when auto_approve_on_complete=True."""
        from unittest.mock import MagicMock, patch
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
        from pipeline_orchestrator import AgentDef, STATUS_COMPLETE

        agent = AgentDef(
            agent="03_execute/merge-conflict",
            phase="03_execute",
            objects=["issue"],
            trigger={"label": "ci-gate:complete"},
            dependencies=[],
            human_gate_after=True,
            human_gate_label="merge-conflict:approved",
            description="test",
            auto_approve_on_complete=True,
        )
        assert agent.auto_approve_on_complete is True
        assert agent.human_gate_label == "merge-conflict:approved"

    def test_auto_approve_on_complete_loaded_from_pipeline_json(self):
        """pipeline.json merge-conflict entry has auto_approve_on_complete: true."""
        import json
        from pathlib import Path
        pipeline_path = Path(__file__).parent.parent / "pipeline" / "pipeline.json"
        data = json.loads(pipeline_path.read_text())
        steps = [
            step
            for flow in data["flows"].values()
            for step in flow["steps"]
        ]
        mc = next(e for e in steps if e["agent"] == "03_execute/merge-conflict")
        assert mc.get("auto_approve_on_complete") is True


# ---------------------------------------------------------------------------
# Scenario 5 (orchestrator drive): auto_approve_on_complete actually applies
# the gate label through process_work_item
# ---------------------------------------------------------------------------

class TestAutoApproveOnCompleteDrivesProcessWorkItem:
    """Drive the real process_work_item branch that auto-applies the gate label.

    The attribute-only test above proves the AgentDef carries the flag; these
    tests prove the orchestrator actually calls gh.add_label(human_gate_label)
    when an auto_approve agent emits :complete. invoke_agent is patched to
    return a success AgentRunResult whose captured_tail carries the
    AI_AGILE_STATUS: complete sentinel; gh is a MagicMock so all label/comment
    calls are absorbed and inspectable.
    """

    def _run(self, gh):
        """Drive process_work_item for the merge-conflict agent on a clean PR.

        Loads the shipped pipeline so dependency resolution uses the real
        config, makes the merge-conflict agent eligible (ci-gate:complete is
        both its trigger and its sole dependency), and patches invoke_agent to
        emit a complete sentinel. Returns the agent label_key for convenience.
        """
        agents, default_extra_tools = load_pipeline(PIPELINE_JSON_PATH)
        pipeline_map = pipeline_by_name(agents)
        merge_conflict = pipeline_map["03_execute/merge-conflict"]

        # Only ci-gate:complete present → merge-conflict trigger satisfied and
        # its single dependency (03_execute/ci-gate, no human gate) is complete.
        work_item = _make_work_item(labels={"ci-gate:complete"})

        complete_result = AgentRunResult(success=True, returncode=0)

        def _invoke_writing_result(agent_def, work_item, dry_run, repo, attempt=0,
                                    agent_text_override=None, default_extra_tools=None, cwd=None,
                                    flow_env=None):
            # merge-conflict is an agent-type step (issue #400): it signals
            # outcome via a real result.json in its scratch dir, not a stdout
            # sentinel. Write one so the unmocked _read_step_result finds it.
            session_id = orch._compute_agent_session_id(agent_def, work_item, repo)
            scratch = orch._scratch_path(session_id)
            os.makedirs(scratch, exist_ok=True)
            payload = {
                "outcome": "complete",
                "summary": "No merge conflicts found. Branch is clean.",
            }
            with open(orch._result_file_path(scratch), "w") as f:
                json.dump(payload, f)
            return complete_result

        # Pass only the merge-conflict agent in the eligibility loop so no other
        # agent is invoked; pipeline_map stays complete for dependency lookups.
        with patch("pipeline_orchestrator.invoke_agent", side_effect=_invoke_writing_result) as mock_invoke:
            process_work_item(
                work_item,
                [merge_conflict],
                pipeline_map,
                gh,
                dry_run=False,
                repo="test/repo",
                session_id="ais-test",
                default_extra_tools=default_extra_tools,
            )

        mock_invoke.assert_called_once()
        return merge_conflict.human_gate_label, merge_conflict.complete_label

    def test_gate_label_applied_on_complete(self):
        """auto_approve_on_complete=True → orchestrator applies merge-conflict:approved."""
        gh = _make_gh()

        gate_label, complete_label = self._run(gh)

        added = [c.args[1] for c in gh.add_label.call_args_list]
        # The gate label is auto-applied, and the agent ends :complete (not :review).
        assert gate_label in added
        assert complete_label in added
        # It must NOT land in :review — auto_approve bypasses the human gate.
        assert merge_conflict_review_label() not in added

    def test_complete_state_not_demoted_to_review(self):
        """The work item is left in :complete (auto-approved), never halted at :review."""
        gh = _make_gh()

        gate_label, complete_label = self._run(gh)

        added = [c.args[1] for c in gh.add_label.call_args_list]
        assert complete_label in added
        assert merge_conflict_review_label() not in added

    def test_add_label_exception_on_gate_does_not_crash(self):
        """If gh.add_label raises on the gate label, the branch swallows it and still completes.

        The orchestrator logs a warning and proceeds — the agent must still be
        driven to its terminal :complete via _apply_terminal_status, which uses
        its own add_label call. We make only the gate-label add raise.
        """
        gh = _make_gh()
        gate_label = "merge-conflict:approved"

        def _raise_on_gate(number, label):
            if label == gate_label:
                raise RuntimeError("simulated GitHub 500 on gate label")
            return None

        gh.add_label.side_effect = _raise_on_gate

        returned_gate, complete_label = self._run(gh)
        assert returned_gate == gate_label

        attempted = [c.args[1] for c in gh.add_label.call_args_list]
        # The gate add was attempted (and raised)...
        assert gate_label in attempted
        # ...and the terminal :complete was still applied afterwards.
        assert complete_label in attempted
