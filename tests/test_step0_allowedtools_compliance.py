"""Conformance tests for issue #438: Step 0 gh api calls must be standalone.

The Claude CLI's native --allowedTools matcher requires a command string to
start with an allowed prefix; it does not decompose compound Bash commands
(variable assignment, && chains, if conditionals wrapping a gh api call). A
real orchestrator-spawned coder run on issue #433 exhausted its full turn
budget and committed nothing as a direct result (see issue #438).

Gherkin scenarios traced (from the approved PRD):
  - Step 0 standalone gh api call is permitted under allowedTools
  - No multi-statement Bash blocks remain in documented Step 0 scripts
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# Step 0 section heading varies slightly per file ("Detect mode",
# "Orient and find the PR", "Detect revision run") -- match any of them.
STEP0_FILES = [
    AGENTS_DIR / "03_execute" / "coder.md",
    AGENTS_DIR / "03_execute" / "pr-reviewer.md",
    AGENTS_DIR / "03_execute" / "merge-conflict.md",
    AGENTS_DIR / "01_product_docs" / "prd-writer.md",
    AGENTS_DIR / "01_product_docs" / "prd-docs-updater.md",
]


def _extract_step0(text: str) -> str:
    match = re.search(r"## Step 0[^\n]*\n(.*?)(?=\n---|\n## Step 1|\Z)", text, re.DOTALL)
    assert match, "Step 0 section not found"
    return match.group(1)


def _bash_blocks(step_text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", step_text, re.DOTALL)


@pytest.mark.parametrize("agent_file", STEP0_FILES, ids=lambda p: p.stem)
class TestStep0GhApiCallsAreStandalone:
    def test_no_gh_api_call_preceded_by_variable_assignment(self, agent_file):
        text = agent_file.read_text()
        step = _extract_step0(text)
        for block in _bash_blocks(step):
            lines = [l.strip() for l in block.splitlines() if l.strip() and not l.strip().startswith("#")]
            for line in lines:
                if "gh api" in line:
                    assert not re.match(r"^\w+=", line), (
                        f"{agent_file.name} Step 0 has a gh api call preceded by a "
                        f"variable assignment in the same invocation: {line!r}"
                    )

    def test_no_gh_api_call_wrapped_in_if_conditional(self, agent_file):
        text = agent_file.read_text()
        step = _extract_step0(text)
        for block in _bash_blocks(step):
            if "gh api" in block:
                assert not re.search(r"^\s*if\s", block, re.MULTILINE), (
                    f"{agent_file.name} Step 0 has a gh api call wrapped in an "
                    f"if conditional in the same invocation"
                )

    def test_no_gh_api_call_chained_with_and_and(self, agent_file):
        text = agent_file.read_text()
        step = _extract_step0(text)
        for block in _bash_blocks(step):
            if "gh api" in block and "&&" in block:
                pytest.fail(
                    f"{agent_file.name} Step 0 has a gh api call chained with "
                    f"&& in the same invocation"
                )
