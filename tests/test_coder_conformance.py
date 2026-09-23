"""Configuration conformance tests for coder agent.

Covers:
- PRD issue #100: coder must read unresolved human REQUEST_CHANGES reviews in Mode B
- Issue #463: coder uses bare Bash (replacing narrow git grants)
- Issue #467: coder reads AI_AGILE_INVOCATION_MODE instead of inspecting labels
- Issue #449: coder Mode B must address or rebut every pr-reviewer finding before
  a zero-commit "complete" exit
- Issue #445: the confirmed root-cause fast path -- declared before Step 2 (not
  discovered after a full Step 4 investigation), no unconditional repository-wide
  scan in the normal path, Step 3 does not re-fetch the parent issue, and repeated
  evidence gathering within one invocation is guarded against
- Issue #502: Mode B's Step 9 (read review feedback) must be the first
  instructed action, ahead of the working-tree check, so a run cannot reach
  a "nothing to do" conclusion from git log/git status/tests without ever
  reading the pr-reviewer artefact

Gherkin scenarios traced:
  - scenario_coder_reinvoked_with_human_review_context
  - scenario_coder_mode_b_description_updated
  - coder_consumes_orchestrator_supplied_invocation_mode
  - coder_md_mode_b_instructions_require_addressing_each_finding_before_no_commit_exit
  - coder_mode_b_does_not_exit_complete_with_no_commits_while_fixable_finding_remains_open
  - coder_md_mode_b_reads_feedback_before_any_other_action
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
        """With broad Bash, dangerous operations are gated by the effective
        deny list, not by the absence of an allowlist entry. Key patterns
        must be present, whether declared directly in deniedTools or
        flattened from deny_groups."""
        step = _coder_step()
        denied = step.get("deniedTools") or [
            p for group in step.get("deny_groups", []) for p in group.get("patterns", [])
        ]
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
                f"coder's effective deny list must contain {pattern!r} to compensate "
                "for the broad Bash grant"
            )


def _extract_mode_b_intro(text: str) -> str:
    m = re.search(r"## MODE B[^\n]*\n(.*?)(?=\n## Step 9|\Z)", text, re.DOTALL)
    return m.group(1) if m else ""


class TestCoderMdModeBInstructionsRequireAddressingEachReviewFindingBeforeANoCommitExit:
    """Scenario: coder.md Mode B instructions require addressing each review finding
    before a no-commit exit.

    Given coder.md contains a Mode B section describing when no-changes-needed is valid
    When a reader follows the instructions for a re-invocation where the original
    implementation is already present on the branch
    Then the instructions require the agent to read and process each finding in the
    pr-reviewer artefact, and only permit a zero-commit exit after each finding has
    either been addressed by an existing commit or explicitly rebutted with stated
    reasoning
    """

    def test_mode_b_intro_states_zero_commit_exit_rule(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        assert "zero-commit" in intro.lower() or "zero new commit" in intro.lower(), (
            "coder.md Mode B intro must state the zero-commit exit rule"
        )

    def test_mode_b_intro_requires_enumerating_each_finding(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        assert "every finding" in intro.lower() or "each finding" in intro.lower(), (
            "coder.md Mode B intro must require enumerating every finding in the "
            "pr-reviewer artefact before a zero-commit exit"
        )

    def test_mode_b_intro_requires_existing_commit_coverage_path(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        lower = intro.lower()
        assert "existing commit" in lower or "covered by" in lower, (
            "coder.md Mode B intro must require each finding to be covered by an "
            "existing commit or explicitly rebutted"
        )

    def test_mode_b_intro_requires_explicit_rebuttal_path(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        lower = intro.lower()
        assert "rebutted" in lower or "rebuttal" in lower, (
            "coder.md Mode B intro must require an explicit rebuttal path for findings "
            "that are not addressed by a commit"
        )

    def test_mode_b_intro_requires_stated_reasoning_in_summary(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        assert "stated reasoning" in intro.lower() or "result.json" in intro, (
            "coder.md Mode B intro must require stated reasoning in result.json summary "
            "for any rebutted finding"
        )


class TestCoderModeBDoesNotExitCompleteWithNoCommitsWhileAFixableRequestChangesFindingRemainsOpen:
    """Scenario: coder Mode B does not exit complete with no commits while a fixable
    REQUEST_CHANGES finding remains open.

    Given coder is re-invoked in Mode B with a pr-reviewer artefact listing at least
    one REQUEST_CHANGES finding
    When coder confirms the original issue's implementation commit is already present
    on the branch
    Then coder does not produce outcome complete with zero new commits unless every
    finding in the pr-reviewer artefact is either covered by an existing commit or
    explicitly rebutted with stated reasoning in the result
    """

    def test_mode_b_intro_prohibits_zero_commit_exit_without_per_finding_check(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        lower = intro.lower()
        assert "do not exit" in lower or "only valid after" in lower, (
            "coder.md Mode B intro must prohibit a zero-commit exit without a "
            "per-finding check, not merely state the happy-path shortcut"
        )

    def test_mode_b_intro_disallows_exit_based_solely_on_implementation_presence(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        lower = intro.lower()
        assert "already present" in lower or "original implementation" in lower, (
            "coder.md Mode B intro must explicitly state that finding the original "
            "implementation on the branch is not sufficient for a zero-commit exit"
        )


class TestCoderMdModeBReadsFeedbackBeforeAnyOtherAction:
    """Scenario: coder Mode B reads review feedback before any other action.

    Issue #502: a zero-commit-exit check applied only at exit does not stop a
    run that never reaches it -- two consecutive Mode B invocations declared
    `outcome: "complete"` after only `git log`/`git status`/the test suite,
    never calling the Step 9 `gh api` reads at all. Step 9 (reading the
    pr-reviewer artefact and PR reviews) must be the first instructed action
    of Mode B, ahead of any other check, with an explicit directive naming
    the shortcut it forbids.

    Given coder.md's Mode B section
    When a reader follows it in document order
    Then Step 9's reads are the first action, before the working-tree check,
    and the step explicitly forbids running git log/git status/git diff/tests
    first
    """

    def test_step_9_precedes_the_working_tree_check(self):
        text = _load_coder_text()
        step_9_idx = text.index("## Step 9 ")
        tree_check_idx = text.index("Confirm the working tree matches the PR head")
        assert step_9_idx < tree_check_idx, (
            "coder.md Step 9 (read review feedback) must appear before the "
            "working-tree-matches-PR-head check in Mode B, so reading "
            "feedback cannot be skipped by reaching that check first"
        )

    def test_step_9_is_stated_as_the_first_action(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        lower = b1.lower()
        assert "first" in lower, (
            "coder.md Step 9 must state that it is the first action of Mode B"
        )

    def test_step_9_forbids_git_status_and_tests_before_it(self):
        text = _load_coder_text()
        b1 = _extract_b1(text)
        lower = b1.lower()
        assert "git log" in lower and "git status" in lower, (
            "coder.md Step 9 must explicitly name git log/git status as "
            "commands not to run before its reads"
        )

    def test_zero_commit_exit_rule_cross_references_step_9(self):
        text = _load_coder_text()
        intro = _extract_mode_b_intro(text)
        assert "step 9" in intro.lower(), (
            "coder.md's zero-commit exit rule must reference Step 9 by name, "
            "so it reads as presuming Step 9 has already run rather than a "
            "rule that could be satisfied without having read anything"
        )


class TestCoderMdStep9ReadsPrReviewerArtefactFromIssueNotPr:
    """Issue #510: _post_artefact_if_present posts every step's artefact to
    work_item.number, which for the issue-kind pr-reviewer step is the
    issue -- never the PR. Step 9's pr-reviewer-artefact lookup queried
    issues/$PR_NUMBER/comments instead, so it found nothing on every
    REQUEST CHANGES cycle.

    Given coder.md's Step 9 pr-reviewer-artefact lookup
    When a reader inspects the gh api call carrying the
    "ai-agile/artefact/v1 by 03_execute/pr-reviewer" marker
    Then it queries issues/$ISSUE_NUMBER/comments, not issues/$PR_NUMBER/comments
    """

    def _artefact_lookup_line(self, text: str) -> str:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "ai-agile/artefact/v1 by 03_execute/pr-reviewer" in line:
                # The gh api call and its jq continuation may span two lines
                # joined by a trailing backslash -- join with the preceding
                # line when that's the case, so the whole logical statement
                # is checked together.
                if i > 0 and lines[i - 1].rstrip().endswith("\\"):
                    return lines[i - 1] + " " + line
                return line
        return ""

    def test_artefact_lookup_queries_issue_number(self):
        text = _load_coder_text()
        line = self._artefact_lookup_line(_extract_b1(text))
        assert "issues/$ISSUE_NUMBER/comments" in line, (
            "coder.md Step 9's pr-reviewer-artefact lookup must query "
            "issues/$ISSUE_NUMBER/comments -- pr-reviewer's artefact is "
            "posted to the issue, not the PR (issue #510)"
        )

    def test_artefact_lookup_does_not_query_pr_number(self):
        text = _load_coder_text()
        line = self._artefact_lookup_line(_extract_b1(text))
        assert "issues/$PR_NUMBER/comments" not in line, (
            "coder.md Step 9 must not look for pr-reviewer's artefact under "
            "issues/$PR_NUMBER/comments -- that thread never receives it "
            "(issue #510)"
        )


# ---------------------------------------------------------------------------
# Issue #445 -- confirmed root-cause fast path
# ---------------------------------------------------------------------------

def _extract_numbered_step(text: str, step_number: int) -> str:
    match = re.search(
        rf"## Step {step_number} [^\n]*\n(.*?)(?=\n---\n|\n## Step |\n## MODE |\Z)",
        text, re.DOTALL,
    )
    return match.group(1) if match else ""


class TestFastPathDeclaredBeforeStep2:
    """The confirmed root-cause gate must be evaluated once, right after
    reading the issue in Step 1 -- not rediscovered partway through the
    normal investigation (Step 4), which would defeat the point of skipping
    that investigation."""

    def test_confirmed_root_cause_section_exists(self):
        text = _load_coder_text()
        assert "CONFIRMED_ROOT_CAUSE_FAST_PATH" in text, (
            "coder.md must declare CONFIRMED_ROOT_CAUSE_FAST_PATH"
        )

    def test_gate_declaration_appears_before_step_2(self):
        text = _load_coder_text()
        gate_idx = text.find("### Confirmed root-cause fast path")
        step_2_idx = text.find("## Step 2 ")
        assert gate_idx != -1, "fast-path gate subsection not found"
        assert step_2_idx != -1, "Step 2 heading not found"
        assert gate_idx < step_2_idx, (
            "the fast-path gate must be declared before Step 2, not "
            "discovered later in the investigation"
        )

    def test_gate_declaration_is_within_step_1(self):
        text = _load_coder_text()
        step_1 = _extract_numbered_step(text, 1)
        assert step_1, "Step 1 section not found"
        assert "CONFIRMED_ROOT_CAUSE_FAST_PATH" in step_1, (
            "the fast-path gate must be set within Step 1, immediately after "
            "reading the issue"
        )


class TestNoUnconditionalRepositoryScan:
    """An unconditional `find . -maxdepth 3` or `git log --oneline` in the
    normal investigation path defeats the fast path's purpose even when it
    isn't taken, and burns turns on every invocation regardless of mode."""

    def test_no_unconditional_find_maxdepth_scan(self):
        text = _load_coder_text()
        assert "find . -maxdepth 3" not in text, (
            "coder.md must not run an unconditional repository-wide "
            "'find . -maxdepth 3' scan"
        )

    def test_no_unconditional_git_log_oneline_scan(self):
        text = _load_coder_text()
        assert "git log --oneline" not in text, (
            "coder.md must not run an unconditional 'git log --oneline' scan"
        )


class TestStep3DoesNotRefetchParentIssue:
    """Step 1 already read the issue body and its sub-issue references;
    Step 3 re-fetching the same issue to rediscover sub-issue numbers is
    the same wasted-turn pattern the fast path exists to avoid."""

    def test_step_3_has_no_refetch_of_parent_issue(self):
        text = _load_coder_text()
        step_3 = _extract_numbered_step(text, 3)
        assert step_3, "Step 3 section not found"
        assert "issues/$ISSUE_NUMBER" not in step_3, (
            "Step 3 must not re-fetch the parent issue via $ISSUE_NUMBER -- "
            "sub-issue numbers come from Step 1's already-read body"
        )

    def test_step_3_says_not_to_refetch(self):
        text = _load_coder_text()
        step_3 = _extract_numbered_step(text, 3)
        assert step_3, "Step 3 section not found"
        assert "second time" in step_3 or "do not fetch" in step_3.lower(), (
            "Step 3 must explicitly say not to re-fetch the parent issue "
            "Step 1 already read"
        )


class TestRepeatedEvidenceGatheringGuard:
    """Without an explicit guard, an agent can re-Grep and re-Read the same
    file across a long investigation, burning turns re-discovering what it
    already established this same invocation."""

    def test_repeated_read_guard_section_exists(self):
        text = _load_coder_text()
        assert "### Avoid repeated evidence gathering" in text, (
            "coder.md must contain a section guarding against repeated "
            "evidence gathering"
        )

    def test_guard_names_when_a_re_read_is_allowed(self):
        text = _load_coder_text()
        match = re.search(
            r"### Avoid repeated evidence gathering\n(.*?)(?=\n---\n|\n## |\Z)",
            text, re.DOTALL,
        )
        assert match, "Avoid repeated evidence gathering section not found"
        section = match.group(1)
        assert "repeated" in section.lower() and "re-read" in section.lower(), (
            "the guard must name what counts as a repeated read and when "
            "re-reading a file already established this invocation is allowed"
        )
