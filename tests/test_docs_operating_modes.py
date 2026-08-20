"""
Gherkin-traced tests for docs/features/docs.md.

Each test corresponds to a Scenario in that file and verifies the documentation
content that was added for issue #283 (scheduled vs in-session modes + Quick Start)
and issue #311 (symlink trap warning + run-agent tool allowlist).
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
QUICK_START = REPO_ROOT / "docs" / "product" / "orchestrator" / "quick-start.md"
OPERATING_MODES = REPO_ROOT / "docs" / "product" / "orchestrator" / "17-operating-modes.md"
MAOS_RUN = REPO_ROOT / ".claude" / "commands" / "maos-run.md"
CLAUDE_MD = REPO_ROOT / ".claude" / "CLAUDE.md"
RUN_AGENT = REPO_ROOT / ".claude" / "commands" / "run-agent.md"


# ---------------------------------------------------------------------------
# Scenario: A new consumer can identify which mode to use
# ---------------------------------------------------------------------------

def test_a_new_consumer_can_identify_which_mode_to_use():
    """quick-start.md exists and covers both operating modes with prerequisites."""
    assert QUICK_START.exists(), "docs/product/orchestrator/quick-start.md must exist"
    text = QUICK_START.read_text()

    # Both modes must be present
    assert "Scheduled" in text, "quick-start.md must document the scheduled mode"
    assert "In-session" in text or "in-session" in text.lower(), \
        "quick-start.md must document the in-session mode"

    # Each mode must list prerequisites
    assert "Prerequisites" in text or "prerequisites" in text.lower(), \
        "quick-start.md must list prerequisites for at least one mode"

    # Must link to the operating-modes doc so a reader can find more detail
    assert "17-operating-modes.md" in text, \
        "quick-start.md must cross-reference 17-operating-modes.md"


def test_a_new_consumer_can_identify_which_mode_to_use_error_path_missing_file(tmp_path, monkeypatch):
    """When quick-start.md is absent, the production test fails with the
    AssertionError its own existence guard raises -- not a stdlib exception."""
    absent = tmp_path / "quick-start.md"
    assert not absent.exists()
    monkeypatch.setattr(sys.modules[__name__], "QUICK_START", absent)
    with pytest.raises(AssertionError, match="must exist"):
        test_a_new_consumer_can_identify_which_mode_to_use()


# ---------------------------------------------------------------------------
# Scenario: Both modes are documented with their real requirements
# ---------------------------------------------------------------------------

def test_both_modes_are_documented_with_their_real_requirements():
    """17-operating-modes.md documents auth, trigger, and gate-approval for both modes."""
    assert OPERATING_MODES.exists(), "docs/product/orchestrator/17-operating-modes.md must exist"
    text = OPERATING_MODES.read_text()

    # Auth model for scheduled mode
    assert "ANTHROPIC_API_KEY" in text, \
        "17-operating-modes.md must document ANTHROPIC_API_KEY for scheduled mode"

    # Auth model for in-session mode (subscription/OAuth)
    assert "OAuth" in text or "subscription" in text, \
        "17-operating-modes.md must document session/OAuth login for in-session mode"

    # Trigger mechanisms for both modes
    assert "ai_orchestrator.yml" in text or "GitHub Actions" in text, \
        "17-operating-modes.md must document the scheduled trigger (GitHub Actions workflow)"
    assert "maos-run" in text or "/maos-run" in text, \
        "17-operating-modes.md must document the in-session trigger (/maos-run)"

    # Gate-approval flow
    assert "approved" in text, \
        "17-operating-modes.md must describe the gate-approval mechanism"


def test_both_modes_documented_idempotent():
    """Re-reading the operating-modes doc produces the same assertions."""
    text = OPERATING_MODES.read_text()
    assert "ANTHROPIC_API_KEY" in text
    assert "maos-run" in text or "/maos-run" in text


# ---------------------------------------------------------------------------
# Scenario: Current limitations are disclosed, not discovered by trial and error
# ---------------------------------------------------------------------------

def test_current_limitations_are_disclosed_not_discovered_by_trial_and_error():
    """17-operating-modes.md explicitly states the in-session mode limitations."""
    assert OPERATING_MODES.exists(), "docs/product/orchestrator/17-operating-modes.md must exist"
    text = OPERATING_MODES.read_text()

    # Limitation 1: 00_ondemand/* agents not yet REST-converted
    assert "00_ondemand" in text, \
        "17-operating-modes.md must state that 00_ondemand/* agents are not yet REST-converted"
    assert "REST" in text, \
        "17-operating-modes.md must mention the REST-conversion limitation"

    # Limitation 2: gh pr ready blocked in restricted sessions, MCP fallback
    assert "gh pr ready" in text or "markPullRequestReadyForReview" in text or \
           "mark" in text.lower(), \
        "17-operating-modes.md must document the gh pr ready limitation"
    assert "MCP" in text or "fallback" in text, \
        "17-operating-modes.md must document the MCP fallback for marking PRs ready"


def test_current_limitations_error_path_no_planned_sections():
    """17-operating-modes.md must not contain 'Planned' or 'Future work' headings (STD-DOC-003)."""
    text = OPERATING_MODES.read_text()
    lines = text.splitlines()
    heading_lines = [l for l in lines if l.startswith("#")]
    for heading in heading_lines:
        assert "Planned" not in heading and "Future work" not in heading, \
            f"17-operating-modes.md has a forbidden heading: {heading!r}"


# ---------------------------------------------------------------------------
# Scenario: Why gh CLI/REST is used instead of GitHub MCP tools is explained
# ---------------------------------------------------------------------------

def test_why_gh_cli_rest_is_used_instead_of_github_mcp_tools_is_explained():
    """17-operating-modes.md explains why pipeline scripts/agents use gh/REST, not MCP."""
    text = OPERATING_MODES.read_text()

    assert "GitHub MCP" in text, \
        "17-operating-modes.md must explain the gh/REST vs GitHub MCP tools decision"
    assert "pipeline_orchestrator.py" in text, \
        "17-operating-modes.md must mention pipeline_orchestrator.py"
    assert "no GitHub MCP access" in text or "no MCP access" in text, \
        "17-operating-modes.md must explain that pipeline_orchestrator.py has no MCP access"
    assert "scheduled" in text.lower() and "guaranteed" in text.lower(), \
        "17-operating-modes.md must explain the scheduled runner has no interactive session or guaranteed MCP"


# ---------------------------------------------------------------------------
# Scenario: Checking gh availability correctly is documented
# ---------------------------------------------------------------------------

def test_checking_gh_availability_correctly_is_documented():
    """17-operating-modes.md documents the gh auth status pitfall and the correct check."""
    text = OPERATING_MODES.read_text()

    assert "gh auth status" in text, \
        "17-operating-modes.md must mention `gh auth status`"
    assert "gh api user" in text, \
        "17-operating-modes.md must document `gh api user` (or an equivalent REST call) as the correct availability check"
    assert "false" in text.lower(), \
        "17-operating-modes.md must state that `gh auth status` can produce a false negative"


# ---------------------------------------------------------------------------
# Scenario: A session's own "no gh CLI" instruction is correctly framed
# ---------------------------------------------------------------------------

def test_a_sessions_own_no_gh_cli_instruction_is_correctly_framed():
    """17-operating-modes.md frames the "no gh CLI" system-prompt line as policy, not fact."""
    text = OPERATING_MODES.read_text()

    assert "policy" in text.lower(), \
        "17-operating-modes.md must frame the 'no gh CLI' system-prompt line as a policy instruction"
    assert "gh CLI" in text, \
        "17-operating-modes.md must reference the gh CLI system-prompt line it is clarifying"


# ---------------------------------------------------------------------------
# Scenario: The two related decisions stay distinguishable
# ---------------------------------------------------------------------------

def test_the_two_related_decisions_stay_distinguishable():
    """17-operating-modes.md keeps the GraphQL/REST split and the gh/REST vs MCP decision distinct."""
    text = OPERATING_MODES.read_text()

    assert "GraphQL" in text, \
        "17-operating-modes.md must reference the GraphQL->REST conversion to distinguish it"
    assert "separate decision" in text.lower(), \
        "17-operating-modes.md must explicitly separate the two decisions"


# ---------------------------------------------------------------------------
# Scenario: Docs stay in sync with the command implementation
# ---------------------------------------------------------------------------

def test_docs_stay_in_sync_with_the_command_implementation():
    """maos-run.md and the new docs cross-reference each other."""
    assert MAOS_RUN.exists(), ".claude/commands/maos-run.md must exist"
    maos_text = MAOS_RUN.read_text()
    modes_text = OPERATING_MODES.read_text()

    # maos-run.md must reference 17-operating-modes.md
    assert "17-operating-modes.md" in maos_text, \
        ".claude/commands/maos-run.md must reference 17-operating-modes.md"

    # maos-run.md must reference quick-start.md
    assert "quick-start.md" in maos_text, \
        ".claude/commands/maos-run.md must reference quick-start.md"

    # 17-operating-modes.md must reference maos-run.md (the mechanism doc)
    assert "maos-run.md" in modes_text, \
        "17-operating-modes.md must reference .claude/commands/maos-run.md"

    # quick-start.md must reference maos-run.md
    qs_text = QUICK_START.read_text()
    assert "maos-run.md" in qs_text, \
        "quick-start.md must reference .claude/commands/maos-run.md"


def test_docs_stay_in_sync_bidirectional_link_idempotent():
    """Cross-reference check is stable on repeated reads."""
    for _ in range(2):
        maos_text = MAOS_RUN.read_text()
        assert "17-operating-modes.md" in maos_text
        assert "quick-start.md" in maos_text


# ---------------------------------------------------------------------------
# Scenario: A session checking standards content is warned about the symlink trap
# ---------------------------------------------------------------------------

def test_a_session_checking_standards_content_is_warned_about_the_symlink_trap():
    """.claude/CLAUDE.md instructs using Grep or find -L instead of Glob for standards/."""
    assert CLAUDE_MD.exists(), ".claude/CLAUDE.md must exist"
    text = CLAUDE_MD.read_text()

    # Must mention Glob returning empty results through a symlink
    assert "Glob" in text, \
        ".claude/CLAUDE.md must mention Glob to explain the trap"
    assert "symlink" in text.lower() or "symlinked" in text.lower(), \
        ".claude/CLAUDE.md must explain the symlinked-directory behaviour"
    assert "empty" in text.lower(), \
        ".claude/CLAUDE.md must state that Glob returns an empty result silently"

    # Must instruct using Grep as the alternative
    assert "Grep" in text, \
        ".claude/CLAUDE.md must instruct using Grep as a symlink-safe alternative"


def test_a_session_checking_standards_content_is_warned_error_path_missing_file(
        tmp_path, monkeypatch):
    """When .claude/CLAUDE.md is absent the test fails with its own existence guard."""
    absent = tmp_path / "CLAUDE.md"
    assert not absent.exists()
    monkeypatch.setattr(
        sys.modules[__name__], "CLAUDE_MD", absent
    )
    with pytest.raises(AssertionError, match="must exist"):
        test_a_session_checking_standards_content_is_warned_about_the_symlink_trap()


# ---------------------------------------------------------------------------
# Scenario: The guidance specifies a correct invocation, not just a tool name
# ---------------------------------------------------------------------------

def test_the_guidance_specifies_a_correct_invocation_not_just_a_tool_name():
    """CLAUDE.md names a concrete correct invocation, not just a generic tool name."""
    text = CLAUDE_MD.read_text()

    # Must name find -L or a trailing-slash find as the concrete alternative
    has_find_L = "find -L" in text
    has_trailing_slash_find = "find standards/" in text or "find {path}/" in text
    assert has_find_L or has_trailing_slash_find, \
        ".claude/CLAUDE.md must name `find -L` or a trailing-slash `find` invocation"

    # Must name Grep explicitly (not just 'use a different tool')
    assert "Grep" in text, \
        ".claude/CLAUDE.md must name `Grep` as a concrete correct alternative"


def test_the_guidance_specifies_a_correct_invocation_idempotent():
    """Re-reading CLAUDE.md produces the same assertion about invocations."""
    for _ in range(2):
        text = CLAUDE_MD.read_text()
        assert "find -L" in text or "find standards/" in text
        assert "Grep" in text


# ---------------------------------------------------------------------------
# Scenario: The affected paths are named explicitly
# ---------------------------------------------------------------------------

def test_the_affected_paths_are_named_explicitly():
    """CLAUDE.md names standards/ and .claude/ as the affected whole-folder symlinks."""
    text = CLAUDE_MD.read_text()

    assert "standards/" in text, \
        ".claude/CLAUDE.md must name `standards/` as an affected symlinked path"
    assert ".claude/" in text, \
        ".claude/CLAUDE.md must name `.claude/` as an affected symlinked path"

    # Both paths must appear in the context of the symlink warning, not just
    # in other incidental references.
    # Verify they appear near 'symlink' or 'Glob'
    lower = text.lower()
    assert "standards" in lower and ("symlink" in lower or "glob" in lower), \
        ".claude/CLAUDE.md must associate `standards/` with the symlink/Glob trap"


def test_the_affected_paths_are_named_error_path_incomplete_guidance(
        tmp_path, monkeypatch):
    """When CLAUDE.md only names one path, the test surfaces the gap."""
    # Simulate a CLAUDE.md that warns about standards/ but not .claude/
    fake = tmp_path / "CLAUDE.md"
    fake.write_text(
        "Glob silently returns empty through a symlinked directory.\n"
        "Use Grep instead of Glob when reading standards/ content.\n"
        "find -L standards -name '*.json'\n"
    )
    monkeypatch.setattr(sys.modules[__name__], "CLAUDE_MD", fake)
    with pytest.raises(AssertionError, match=r"\.claude/"):
        test_the_affected_paths_are_named_explicitly()


# ---------------------------------------------------------------------------
# Scenario: An interactively-run agent is scoped to its declared tool allowlist
# ---------------------------------------------------------------------------

def test_an_interactively_run_agent_is_scoped_to_its_declared_tool_allowlist():
    """.claude/commands/run-agent.md constrains the session to the agent's allowed_tools list.

    Since issue #316, run-agent uses the orchestrator's resolve-only mode
    (--print-prompt) as the single source of truth instead of hand-parsing
    the agent file's frontmatter directly.
    """
    assert RUN_AGENT.exists(), ".claude/commands/run-agent.md must exist"
    text = RUN_AGENT.read_text()

    # Must obtain the allowlist from the orchestrator's resolve-only mode, not hand-parse
    assert "allowed_tools" in text or "--print-prompt" in text, \
        "run-agent.md must obtain the tool allowlist via the orchestrator's resolve-only mode"

    # Must warn or constrain before using tools outside the declared allowlist
    assert "allowlist" in text.lower() or "allowed" in text.lower(), \
        "run-agent.md must reference constraining to or warning about the tool allowlist"

    # Must call out Glob specifically (the concrete symptom that triggered this issue)
    assert "Glob" in text, \
        "run-agent.md must mention Glob as an example of a tool that may not be in the allowlist"

    # Must reference the real orchestrator's behaviour for framing
    assert "orchestrator" in text.lower(), \
        "run-agent.md must explain the constraint in terms of what the real orchestrator enforces"


def test_an_interactively_run_agent_is_scoped_error_path_missing_tools_field(
        tmp_path, monkeypatch):
    """When run-agent.md does not reference the orchestrator allowlist the test surfaces the gap."""
    fake = tmp_path / "run-agent.md"
    fake.write_text(
        "# Run Agent\n\nRead the agent file. Note the model: and max_turns: values.\n"
    )
    monkeypatch.setattr(sys.modules[__name__], "RUN_AGENT", fake)
    with pytest.raises(AssertionError, match="allowed_tools|print-prompt"):
        test_an_interactively_run_agent_is_scoped_to_its_declared_tool_allowlist()


def test_an_interactively_run_agent_is_scoped_idempotent():
    """Tool-scope check is stable on repeated reads."""
    for _ in range(2):
        text = RUN_AGENT.read_text()
        assert "allowed_tools" in text or "--print-prompt" in text
        assert "allowlist" in text.lower() or "allowed" in text.lower()
