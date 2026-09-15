"""Configuration conformance tests for coder agent.

Covers:
- PRD issue #100: coder must read unresolved human REQUEST_CHANGES reviews in Mode B
- Issue #463: coder uses bare Bash (replacing narrow git grants)
- Issue #467: coder reads AI_AGILE_INVOCATION_MODE instead of inspecting labels

Gherkin scenarios traced:
  - scenario_coder_reinvoked_with_human_review_context
  - scenario_coder_mode_b_description_updated
  - coder_consumes_orchestrator_supplied_invocation_mode
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CODER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "coder.md"


def _load_coder_text() -> str:
    assert CODER_MD.exists(), f"coder agent file not found: {CODER_MD}"
    return CODER_MD.read_text()


def _extract_step_0(text: str) -> str:
    match = re.search(r"## Step 0[^\n]*\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_b1(text: str) -> str:
    match = re.search(r"## Step 9[^\n]*\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_b2(text: str) -> str:
    match = re.search(r"## Step 10[^\n]*\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    return match.group(1) if match else ""


class TestCoderConsumesOrchestratorSuppliedInvocationMode:
    """Scenario: coder consumes orchestrator-supplied invocation mode

    Given the orchestrator has dispatched the coder with AI_AGILE_INVOCATION_MODE
    set to initial or review
    When the coder begins its run
    Then the coder uses that environment variable to determine its operating mode
    without inspecting human-review-pending, review-cycle:N, reviewer artefacts,
    PR existence, branch names, or issue labels
    """

    def test_step_0_reads_invocation_mode_env_var(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        assert "AI_AGILE_INVOCATION_MODE" in step, (
            "coder.md Step 0 must read AI_AGILE_INVOCATION_MODE from the environment"
        )

    def test_step_0_does_not_check_human_review_pending_label(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        assert "human-review-pending" not in step, (
            "coder.md Step 0 must not inspect human-review-pending; "
            "the orchestrator injects AI_AGILE_INVOCATION_MODE instead"
        )

    def test_step_0_does_not_check_review_cycle_label(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        assert "review-cycle" not in step, (
            "coder.md Step 0 must not inspect review-cycle:N labels; "
            "the orchestrator injects AI_AGILE_INVOCATION_MODE instead"
        )

    def test_step_0_does_not_check_reviewer_artefact(self):
        text = _load_coder_text()
        step = _extract_step_0(text)
        assert "pr-reviewer" not in step, (
            "coder.md Step 0 must not check for a pr-reviewer artefact; "
            "the orchestrator injects AI_AGILE_INVOCATION_MODE instead"
        )

    def test_frontmatter_description_references_invocation_mode(self):
        text = _load_coder_text()
        frontmatter_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert frontmatter_match, "No frontmatter found in coder.md"
        frontmatter = frontmatter_match.group(1)
        assert "AI_AGILE_INVOCATION_MODE" in frontmatter, (
            "coder.md frontmatter must reference AI_AGILE_INVOCATION_MODE "
            "as the invocation mode mechanism"
        )


class TestCoderB1FetchesHumanBlockReviewers:
    """Scenario: coder reads unresolved human REQUEST_CHANGES reviews"""

    def test_b1_fetches_human_block_reviewers_via_api(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "HUMAN_BLOCK_REVIEWERS" in b1, (
            "coder.md Step 9 must define HUMAN_BLOCK_REVIEWERS. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_b1_uses_gh_api_for_rest_reviews_endpoint(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "gh api" in b1, (
            "coder.md Step 9 must use 'gh api' to fetch the PR reviews endpoint. "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_b1_excludes_bots(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "Bot" in b1, (
            "coder.md Step 9 must exclude bot accounts (.user.type != 'Bot'). "
            "Run: python3 scripts/update_agent_files.py"
        )

    def test_b1_uses_reviews_endpoint_path(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        assert b1, "Step 9 (B1) section not found in coder.md"
        assert "reviews" in b1, (
            "coder.md Step 9 must reference the /reviews REST endpoint. "
            "Run: python3 scripts/update_agent_files.py"
        )


class TestCoderB2ClassifiesHumanReviewsAsRequired:
    """Scenario: coder classifies human REQUEST_CHANGES as Required feedback"""

    def test_b2_required_row_includes_human_reviews(self):
        text = _load_coder_text()
        b2 = _extract_b2(text)
        assert b2, "Step 10 (B2) section not found in coder.md"
        required_rows = [l for l in b2.splitlines() if "Required" in l]
        assert required_rows, "Step 10 (B2) must have a Required row in its feedback table"
        combined = " ".join(required_rows)
        assert "HUMAN_BLOCK_REVIEWERS" in combined or "human REQUEST_CHANGES" in combined.lower(), (
            "coder.md Step 10 Required row must include human REQUEST_CHANGES reviews as Required feedback. "
            "Run: python3 scripts/update_agent_files.py"
        )


# ---------------------------------------------------------------------------
# Issue #463 -- coder uses bare Bash (replacing issue #407's narrow git grants)
# ---------------------------------------------------------------------------

import json  # noqa: E402

PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"


def _coder_step() -> dict:
    pipeline = json.loads(PIPELINE_JSON.read_text())
    for flow in pipeline["flows"].values():
        for step in flow.get("steps", []):
            if step.get("agent") == "03_execute/coder":
                return step
    raise AssertionError("03_execute/coder is not declared in pipeline.json")


class TestCoderBroadBashGrantDesign:
    """Issue #463: coder now uses bare 'Bash' rather than a narrow per-executable list."""

    def test_coder_uses_bare_bash_not_narrow_list(self):
        """extra_allowedTools must be exactly ['Bash'] -- the broad grant that
        replaced the per-executable list (issue #463)."""
        step = _coder_step()
        extra = step.get("extra_allowedTools", [])
        assert extra == ["Bash"], (
            f"coder extra_allowedTools must be ['Bash'] after issue #463 simplification; "
            f"found: {extra}"
        )

    def test_no_specific_git_patterns_in_extra_allowed_tools(self):
        """With bare 'Bash', individual git subcommand patterns are redundant and
        must not appear in extra_allowedTools."""
        step = _coder_step()
        extra = step.get("extra_allowedTools", [])
        git_specific = [t for t in extra if t.startswith("Bash(git")]
        assert not git_specific, (
            f"extra_allowedTools must not contain individual git patterns when bare "
            f"'Bash' is already granted; found: {git_specific}"
        )

    def test_prompt_still_forbids_dangerous_git_commands(self):
        """Widening the grant does not relax the instruction.

        coder.md must still forbid git push, checkout, merge, and rebase --
        the deny list and the prompt must agree on what the coder must not do
        (AS-1/P-16).
        """
        text = " ".join(_load_coder_text().split())
        for forbidden in ("git push", "git checkout", "git merge", "git rebase"):
            assert f"Never run `{forbidden}`" in text or (
                "Never run" in text and f"`{forbidden}`" in text
            ), f"coder.md no longer forbids {forbidden}"
        assert "the orchestrator's" in text or "the orchestrator pushes" in text, (
            "coder.md no longer says who owns pushing"
        )

    def test_dangerous_operations_controlled_via_denied_tools(self):
        """With broad Bash, dangerous operations are gated by deniedTools, not
        by the absence of an allowlist entry. Key patterns must be declared."""
        step = _coder_step()
        denied = step.get("deniedTools", [])
        required_denials = [
            "Bash(git reset --hard*)",
            "Bash(git commit --amend*)",
            "Bash(git push --force*)",
            "Bash(git branch -D *)",
            "Bash(git config *)",
            "Bash(ssh *)",
        ]
        for pattern in required_denials:
            assert pattern in denied, (
                f"coder deniedTools must contain {pattern!r} to compensate for "
                "the broad Bash grant"
            )
