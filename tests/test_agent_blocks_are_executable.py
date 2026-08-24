"""
Every bash block in an agent prompt must survive the scope splitter.

An agent prompt is not documentation -- it is the command the agent runs. A
block that `split-command.py` refuses is an instruction the agent physically
cannot follow, and the failure is silent: the agent improvises, and what it
improvises is what leaked files into the repo root (issue #376).

This is the check that was missing. Three separate rounds of "fix the scratch
rule" shipped without it, each time by reading the prompts rather than running
them. `pr-reviewer` prescribed a correct-looking heredoc whose body contained
```json fences, so the whole block was refused for command substitution -- and
nobody noticed until the splitter was pointed at it.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
SPLITTER = REPO_ROOT / ".claude" / "hooks" / "split-command.py"

# Command substitution in general agent logic (`N=$(gh api ...)`) is refused
# too, but that is a separate, systemic defect: agents cannot capture command
# output at all. It is not this file's subject. Pin the count so the number
# cannot grow silently while that is resolved, and so a fix shows up here.
KNOWN_SUBSTITUTION_REFUSALS = 34


def _bash_blocks():
    for path in sorted(AGENTS_DIR.rglob("*.md")):
        text = path.read_text()
        for m in re.finditer(r"```bash\n(.*?)\n```", text, re.DOTALL):
            line = text[: m.start()].count("\n") + 2
            yield f"{path.relative_to(AGENTS_DIR)}:{line}", m.group(1)


def _refusal(block):
    """Return the splitter's refusal reason, or None if it accepts the block."""
    result = subprocess.run(
        [sys.executable, str(SPLITTER)],
        input=block, capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 2 else None


def test_splitter_is_present():
    assert SPLITTER.exists(), "the scope splitter must exist to check anything"


def test_no_agent_block_is_refused_for_a_backtick():
    """A body containing backticks cannot go in an unquoted heredoc.

    The heredoc body is scanned for command substitution, and a backtick is a
    substitution marker. Bodies with markdown fences must be staged with the
    `Write` tool instead. This is the specific regression that made
    prd-writer, pr-reviewer and issue-classifier leak.
    """
    offenders = [
        where for where, block in _bash_blocks()
        if (r := _refusal(block)) and "uses ```" in r
    ]
    assert offenders == [], (
        "these blocks are refused because their body contains a backtick; "
        f"stage them with the Write tool instead: {offenders}"
    )


def test_substitution_refusals_do_not_grow():
    """Guard the systemic `$(` problem without pretending it is fixed."""
    offenders = [
        where for where, block in _bash_blocks()
        if (r := _refusal(block)) and "$(" in r
    ]
    assert len(offenders) <= KNOWN_SUBSTITUTION_REFUSALS, (
        f"command-substitution refusals rose to {len(offenders)} "
        f"(was {KNOWN_SUBSTITUTION_REFUSALS}). New blocks must not use $(...): "
        f"{sorted(set(offenders))}"
    )


@pytest.mark.parametrize("where,block", [
    (w, b) for w, b in _bash_blocks()
    if "gh api --method POST" in b and "issues/" in b
])
def test_every_posting_block_is_executable(where, block):
    """The comment-posting path must work for every agent, with no exceptions.

    This is the one thing every agent does, and the thing all three leaking
    agents failed at.
    """
    reason = _refusal(block)
    if reason and "$(" in reason:
        pytest.skip(
            "refused for command substitution elsewhere in the block -- the "
            "systemic $( ) defect, covered by test_substitution_refusals_do_not_grow"
        )
    assert reason is None, f"{where} cannot post: {reason}"
