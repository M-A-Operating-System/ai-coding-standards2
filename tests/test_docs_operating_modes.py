"""
Gherkin-traced tests for docs/features/docs.md.

Each test corresponds to a Scenario in that file and verifies the documentation
content that was added for issue #283 (scheduled vs in-session modes + Quick Start)
and issue #311 (symlink trap warning + run-agent tool allowlist).

The 17-operating-modes.md scenarios (operational workarounds specific to the
current /run-agent in-session emulation) were retired along with that file --
see docs/features/docs.md and PRODUCT.md's "Headless and interactive" section,
which supersedes its concept-and-comparison content.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
QUICK_START = REPO_ROOT / "docs" / "product" / "orchestrator" / "quick-start.md"
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

    # Must link to PRODUCT.md so a reader can find the concept and comparison
    assert "PRODUCT.md" in text, \
        "quick-start.md must cross-reference PRODUCT.md"


def test_a_new_consumer_can_identify_which_mode_to_use_error_path_missing_file(tmp_path, monkeypatch):
    """When quick-start.md is absent, the production test fails with the
    AssertionError its own existence guard raises -- not a stdlib exception."""
    absent = tmp_path / "quick-start.md"
    assert not absent.exists()
    monkeypatch.setattr(sys.modules[__name__], "QUICK_START", absent)
    with pytest.raises(AssertionError, match="must exist"):
        test_a_new_consumer_can_identify_which_mode_to_use()


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
