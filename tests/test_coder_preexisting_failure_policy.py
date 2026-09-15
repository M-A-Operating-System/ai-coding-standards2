"""Conformance tests for coder pre-existing test failure policy (issue #467).

Gherkin scenario traced:
  - confirmed_pre_existing_unrelated_test_failure_does_not_block_completion
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CODER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "coder.md"


def _load_coder() -> str:
    assert CODER_MD.exists(), f"coder.md not found at {CODER_MD}"
    return CODER_MD.read_text()


def _extract_validation_section(text: str) -> str:
    """Extract the validation/Step 6 section."""
    m = re.search(r"## Step 6[^\n]*\n(.*?)(?=\n---|\n## Step 7|\Z)", text, re.DOTALL)
    return m.group(1) if m else ""


class TestConfirmedPreExistingUnrelatedTestFailureDoesNotBlockCompletion:
    """Scenario: confirmed pre-existing unrelated test failure does not block completion.

    Given a test failure exists after the coder's change, the failure reproduces
    against the pre-change baseline with one targeted verification, and no file or
    behaviour touched by the coder's diff is exercised by that failing test
    When the coder has recorded the failure in result.json with baseline verification evidence
    Then the coder sets outcome: complete without further investigation or reverification
    of that failure in the same invocation
    """

    def test_coder_documents_pre_existing_failure_exception(self):
        """coder.md must document the pre-existing failure exception."""
        text = _load_coder()
        assert "pre-existing" in text.lower(), (
            "coder.md must document the pre-existing unrelated test failure exception"
        )

    def test_pre_existing_failure_requires_unrelated_to_diff(self):
        """The exception only applies to failures unrelated to the diff."""
        text = _load_coder()
        section = _extract_validation_section(text)
        assert section, "Step 6 validation section not found in coder.md"
        lower = section.lower()
        assert "diff" in lower or "changed" in lower, (
            "coder.md Step 6 must state that the pre-existing exception only applies "
            "to failures unrelated to the coder's diff"
        )

    def test_pre_existing_failure_requires_baseline_verification(self):
        """A pre-existing failure requires baseline verification -- not just a claim."""
        text = _load_coder()
        section = _extract_validation_section(text)
        assert section, "Step 6 validation section not found in coder.md"
        lower = section.lower()
        assert "baseline" in lower or "pre-change" in lower or "before" in lower, (
            "coder.md Step 6 must require verifying the failure against the pre-change state"
        )

    def test_one_targeted_verification_suffices(self):
        """One baseline verification is enough -- no requirement for exhaustive checking."""
        text = _load_coder()
        section = _extract_validation_section(text)
        assert section, "Step 6 validation section not found in coder.md"
        lower = section.lower()
        assert "one" in lower or "single" in lower or "suffic" in lower, (
            "coder.md Step 6 must state that one targeted baseline verification suffices"
        )

    def test_pre_existing_failure_does_not_prevent_complete(self):
        """A confirmed pre-existing failure does not prevent outcome: complete."""
        text = _load_coder()
        section = _extract_validation_section(text)
        assert section, "Step 6 validation section not found in coder.md"
        lower = " ".join(section.lower().split())
        assert "does not prevent" in lower or "not prevent" in lower, (
            "coder.md Step 6 must state a confirmed pre-existing failure does not "
            "prevent outcome: complete"
        )

    def test_coder_must_not_reinvestigate_confirmed_pre_existing_failure(self):
        """Once confirmed, the failure is recorded and not investigated further."""
        text = _load_coder()
        section = _extract_validation_section(text)
        assert section, "Step 6 validation section not found in coder.md"
        lower = section.lower()
        assert "do not investigate" in lower or "not investigate" in lower or "not re-verify" in lower, (
            "coder.md Step 6 must state not to investigate or re-verify a confirmed "
            "pre-existing failure"
        )

    def test_exception_does_not_apply_to_diff_touched_tests(self):
        """The exception cannot be used for tests or behaviour touched by the diff."""
        text = _load_coder()
        section = _extract_validation_section(text)
        assert section, "Step 6 validation section not found in coder.md"
        lower = section.lower()
        assert "touched by your diff" in lower or "touched by the diff" in lower or (
            "classify" in lower and "touched" in lower
        ), (
            "coder.md Step 6 must state the pre-existing exception does not apply "
            "if the test or code it exercises was touched by the diff"
        )
