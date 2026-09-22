"""Configuration conformance tests for pr-reviewer's verdict mechanism.

Originally covered PRD issue #99 (REQUEST_CHANGES threshold lowered to
include Medium findings), enforced via a fixed severity-to-verdict rule
table in pr-reviewer.md's own Step 10. Issue #512 Part 2 replaces that
prompt-level rule table with a code-computed verdict
(pipeline/review_outcome.py::derive_review_verdict, tested in
tests/test_review_outcome.py) -- Step 10 is advisory prose now, and
`outcome_policy: review_findings` in pipeline.json is what actually wires
the computation in. These tests were rewritten accordingly; the severity/
confidence/ADR partition issue #99 established is still enforced, just by
code instead of prompt rules, and is verified there, not here.

Gherkin scenarios traced:
  - Scenario: Other steps unaffected / outcome_policy declared for pr-reviewer
  - Scenario: Coder reads the rendered findings (Step 9 assigns unified ids)
  - scenario_verdict_present_in_closing_announcement (result.review, not a
    hardcoded verdict)
  - scenario_agent_description_reflects_updated_threshold
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PR_REVIEWER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"


def _load_pr_reviewer_text() -> str:
    assert PR_REVIEWER_MD.exists(), f"pr-reviewer agent file not found: {PR_REVIEWER_MD}"
    return PR_REVIEWER_MD.read_text()


def _load_pipeline_json() -> dict:
    assert PIPELINE_JSON.exists(), f"pipeline.json not found: {PIPELINE_JSON}"
    with open(PIPELINE_JSON) as f:
        return json.load(f)


def _find_pr_reviewer_entry(pipeline: dict) -> dict:
    def search(obj):
        if isinstance(obj, dict):
            if obj.get("agent") == "03_execute/pr-reviewer":
                return obj
            for v in obj.values():
                result = search(v)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = search(item)
                if result is not None:
                    return result
        return None
    entry = search(pipeline)
    assert entry is not None, "03_execute/pr-reviewer not found in pipeline.json"
    return entry


def _extract_frontmatter_description(text: str) -> str:
    match = re.search(r"^description: >(.+?)(?=^\w|\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "description frontmatter not found in pr-reviewer.md"
    return match.group(1)


def _extract_step_9(text: str) -> str:
    match = re.search(r"## Step 9 \u2014 Consolidate(.+?)(?=\n## Step \d|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_step_11(text: str) -> str:
    match = re.search(
        r"## Step 11 \u2014 Write the result(.+?)(?=\n## (?:Step \d|Rules)|\Z)",
        text,
        re.DOTALL,
    )
    return match.group(1) if match else ""


class TestPipelineJsonDeclaresOutcomePolicy:
    """Scenario: Other steps unaffected -- outcome_policy is declared per
    step (AS-1/AS-2: the orchestrator keys off this field, never the agent
    name), and pr-reviewer is the one step that currently declares it."""

    def test_pr_reviewer_declares_outcome_policy(self):
        pipeline = _load_pipeline_json()
        entry = _find_pr_reviewer_entry(pipeline)
        policy = entry.get("outcome_policy")
        assert policy is not None, (
            "pr-reviewer's pipeline.json entry must declare outcome_policy "
            "so the orchestrator computes its verdict from result.review "
            "(issue #512 Part 2)"
        )
        assert policy.get("kind") == "review_findings"
        assert policy.get("schema"), "outcome_policy.schema must name a schema path"

    def test_outcome_policy_schema_path_exists(self):
        pipeline = _load_pipeline_json()
        entry = _find_pr_reviewer_entry(pipeline)
        schema_path = REPO_ROOT / entry["outcome_policy"]["schema"]
        assert schema_path.exists(), f"outcome_policy.schema path does not exist: {schema_path}"


class TestStep9UnifiedFindingIds:
    """Scenario: Coder reads the rendered findings -- findings carry one
    unified RV-NNN id across every persona, not per-persona prefixes, so
    coder.md can parse them without knowing which persona raised which."""

    def test_step_9_exists(self):
        text = _load_pr_reviewer_text()
        assert _extract_step_9(text), "Step 9 section not found"

    def test_step_9_specifies_rv_id_scheme(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_9(text)
        assert step, "Step 9 section is missing"
        assert "RV-" in step, (
            "Step 9 must specify the unified RV-NNN finding id scheme (issue #512)"
        )

    def test_step_9_specifies_confidence_field(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_9(text)
        assert step, "Step 9 section is missing"
        assert "confidence" in step, (
            "Step 9 must ask for a confidence field -- a non-Critical finding "
            "below 0.8 confidence does not block (issue #512)"
        )

    def test_step_9_specifies_category_field(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_9(text)
        assert step, "Step 9 section is missing"
        assert "improvement" in step, (
            "Step 9 must document the \"improvement\" category, which never blocks"
        )


class TestStep10IsAdvisoryNotARuleTable:
    """Step 10 no longer decides the verdict -- it states that the
    orchestrator does, from result.review.findings (issue #512 Part 2)."""

    def test_step_10_states_orchestrator_computes_verdict(self):
        text = _load_pr_reviewer_text()
        match = re.search(r"## Step 10.*?\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
        assert match, "Step 10 section not found"
        section = match.group(1)
        assert "orchestrator computes" in section, (
            "Step 10 must state plainly that the orchestrator computes the verdict"
        )

    def test_step_10_heading_marked_advisory(self):
        text = _load_pr_reviewer_text()
        heading = "## Step 10 \u2014 Verdict (advisory)"
        assert heading in text, (
            "Step 10's heading should mark it advisory -- the model's own "
            "outcome/verdict fields are no longer authoritative (issue #512)"
        )


class TestScenarioVerdictInClosingAnnouncement:
    """Scenario: the verdict is traceable from the structured result the
    step writes -- since issue #512 Part 2, via result.review.findings,
    not a hardcoded or free-text verdict."""

    def test_step_11_writes_review_object(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_11(text)
        assert step, "Step 11 section not found"
        assert '"review"' in step and '"head_sha"' in step and '"findings"' in step, (
            "Step 11 must write a result.review object with head_sha and "
            "findings -- this is what the orchestrator actually acts on "
            "(issue #512 Part 2)"
        )

    def test_step_11_advisory_verdict_bound_to_a_variable(self):
        text = _load_pr_reviewer_text()
        step = _extract_step_11(text)
        assert step, "Step 11 section is missing"
        assert re.search(r'"verdict":\s*"\$\{?\w+\}?"', step), (
            "the advisory verdict must be bound to a shell variable (e.g. "
            "$VERDICT), not hardcoded, in the Step 11 result.json write"
        )

    def test_step_11_does_not_write_output(self):
        """The orchestrator renders the artefact body now (issue #512 Part 2)
        -- the step has nothing to put in `output`."""
        text = _load_pr_reviewer_text()
        step = _extract_step_11(text)
        assert step, "Step 11 section is missing"
        assert '"output"' not in step, (
            "Step 11 must not write result.output -- the orchestrator renders "
            "the artefact body from result.review itself"
        )


class TestScenarioAgentDescriptionReflectsThreshold:
    """Scenario: Agent description reflects the verdict mechanism."""

    def test_frontmatter_description_mentions_outcome_policy(self):
        text = _load_pr_reviewer_text()
        desc = _extract_frontmatter_description(text)
        assert "outcome_policy" in desc or "orchestrator computes" in desc, (
            "Frontmatter description must reflect that the orchestrator "
            "computes the verdict (issue #512 Part 2)"
        )

    def test_frontmatter_description_mentions_confidence_threshold(self):
        text = _load_pr_reviewer_text()
        desc = _extract_frontmatter_description(text)
        assert "confidence" in desc, (
            "Frontmatter description must mention the confidence threshold "
            "that keeps a low-confidence non-Critical finding from blocking"
        )

    def test_pipeline_json_description_mentions_outcome_policy(self):
        pipeline = _load_pipeline_json()
        entry = _find_pr_reviewer_entry(pipeline)
        desc = entry.get("description", "")
        assert "outcome_policy" in desc or "orchestrator computes" in desc, (
            "pipeline.json pr-reviewer description must reflect that the "
            "orchestrator computes the verdict (issue #512 Part 2)"
        )

    def test_pipeline_json_description_mentions_critical_always_blocks(self):
        pipeline = _load_pipeline_json()
        entry = _find_pr_reviewer_entry(pipeline)
        desc = entry.get("description", "")
        assert "Critical" in desc, (
            "pipeline.json pr-reviewer description must mention that a "
            "Critical finding always blocks"
        )
