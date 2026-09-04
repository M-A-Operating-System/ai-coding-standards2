"""The principle table in .claude/AGENTS.md is the list agents are held to.

Issue #407: two live citations treated P-16 as real -- `pr-reviewer.md`
("the P-1 to P-16 principles in `AGENTS.md` are the only standards in force")
and the orchestrator's own mark-ready comment ("if the agent declares it
(P-16)") -- while the table defined no P-16 at all. A principle a reviewer is
told to cite but cannot read is a contradiction, not a gap in wording, so the
principle is written down.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
AGENTS_MD = REPO_ROOT / ".claude" / "AGENTS.md"
PR_REVIEWER_MD = REPO_ROOT / ".claude" / "agents" / "03_execute" / "pr-reviewer.md"
ORCHESTRATOR = REPO_ROOT / "pipeline" / "pipeline_orchestrator.py"


def _principle_rows() -> dict:
    """{"P-1": "what it means for you", ...} from the principle table."""
    rows = {}
    for line in AGENTS_MD.read_text().splitlines():
        match = re.match(r"\|\s*\*\*(P-\d+)\*\*\s*(.*?)\s*\|\s*(.*?)\s*\|$", line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


class TestEveryCitedPrincipleIsDefined:
    def test_p16_is_in_the_table(self):
        assert "P-16" in _principle_rows(), (
            "pr-reviewer.md and pipeline_orchestrator.py both cite P-16; "
            "AGENTS.md must define it"
        )

    def test_the_citations_that_needed_it_are_still_there(self):
        assert "P-1 to P-16 principles" in PR_REVIEWER_MD.read_text()
        assert "(P-16)" in ORCHESTRATOR.read_text()

    def test_no_gap_between_the_lowest_and_highest_cited_principle(self):
        """P-16 is the upper bound pr-reviewer.md names, so it must exist;
        the numbering below it is deliberately sparse (retired principles are
        not renumbered, so citations elsewhere stay valid)."""
        ids = {int(k.split("-")[1]) for k in _principle_rows()}
        assert max(ids) == 16


class TestWhatP16Says:
    def test_it_gives_the_orchestrator_the_git_and_pr_mechanics(self):
        _title, meaning = _principle_rows()["P-16"]
        assert "orchestrator" in meaning.lower()
        for op in ("commit", "push", "ready for review"):
            assert op in meaning.lower(), f"P-16 does not mention {op}"

    def test_it_forbids_the_commands_coder_md_forbids(self):
        _title, meaning = _principle_rows()["P-16"]
        for command in ("git commit", "git push", "git checkout"):
            assert command in meaning

    def test_it_ties_the_grant_to_the_instruction(self):
        """AS-1/P-16 pairing: a step's allowed commands say the same thing its
        prompt does."""
        _title, meaning = _principle_rows()["P-16"]
        assert "allowed commands" in meaning
