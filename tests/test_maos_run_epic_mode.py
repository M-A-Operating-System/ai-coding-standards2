"""Tests for /maos-run epic mode -- issue #657.

Traces to docs/features/maos-run-epic-mode-detection-child-discovery-and-per-child-driving-loop.md:
  Scenario: maos-run drives each child of an epic issue in sub-issue order
  Scenario: maos-run on a non-epic issue follows the existing single-issue path
  Scenario: epic-driving loop stops at the first child that halts for a human gate
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DRIVE_ITEM = REPO_ROOT / "scripts" / "drive-item.sh"

SUB_ISSUES_API = "sub_issues"
EPIC_LABEL = '"epic"'
BLOCKED_LABEL = '"blocked"'


def _content():
    return DRIVE_ITEM.read_text()


class TestMaosRunDrivesEachChildOfAnEpicInSubIssueOrder:
    """R1: epic + blocked labels + non-empty sub-issue list -> drive each child."""

    def test_sub_issues_api_endpoint_is_referenced(self):
        assert SUB_ISSUES_API in _content(), (
            "drive-item.sh must reference the sub_issues API endpoint to discover "
            "an epic's child issues"
        )

    def test_epic_label_is_checked(self):
        assert "epic" in _content(), (
            "drive-item.sh must check for the 'epic' label to enter epic mode"
        )

    def test_blocked_label_is_checked(self):
        content = _content()
        assert 'grep -qx "blocked"' in content or "grep -qx 'blocked'" in content, (
            "drive-item.sh must check for the 'blocked' label as part of epic detection"
        )

    def test_children_are_driven_in_a_loop(self):
        assert "while IFS= read -r _child_num" in _content(), (
            "drive-item.sh must iterate over child issue numbers to drive each one"
        )

    def test_child_is_driven_via_drive_item_itself(self):
        assert 'bash "$0"' in _content(), (
            'drive-item.sh must call bash "$0" to drive each child through the '
            "same script, keeping the sub-issue path consistent"
        )


class TestMaosRunOnNonEpicIssueFollowsExistingSingleIssuePath:
    """R2: no epic label, or epic with no children -> existing tick loop unchanged."""

    def test_tick_loop_still_present(self):
        assert "while (( tick < MAX_TICKS ))" in _content(), (
            "drive-item.sh must retain the existing tick loop for non-epic issues"
        )

    def test_epic_block_exits_before_tick_loop(self):
        content = _content()
        epic_block_start = content.index("sub_issues")
        tick_loop_start = content.index("while (( tick < MAX_TICKS ))")
        exit_in_epic_block = content.index("exit 0", epic_block_start)
        assert exit_in_epic_block < tick_loop_start, (
            "drive-item.sh must exit from the epic block before reaching the tick "
            "loop, ensuring non-epic issues fall through to the existing path"
        )

    def test_children_guarded_by_non_empty_check(self):
        content = _content()
        assert 'if [[ -n "$_sub_issue_numbers" ]]' in content, (
            "drive-item.sh must guard epic-mode driving behind a non-empty "
            "sub-issue check so an epic with no children falls back to the "
            "single-issue tick loop"
        )


class TestEpicDrivingLoopStopsAtFirstChildHalt:
    """R3: first child that halts stops the loop; no further children are driven."""

    def test_child_exit_code_is_captured(self):
        assert "_child_rc=0" in _content(), (
            "drive-item.sh must initialise a variable to capture each child's "
            "exit code before calling bash"
        )

    def test_non_zero_child_exit_stops_the_loop(self):
        content = _content()
        assert "_child_rc=$?" in content, (
            "drive-item.sh must capture the child script's exit code via || to "
            "detect a halt without triggering set -e"
        )
        assert "exit $_child_rc" in content, (
            "drive-item.sh must propagate the child's non-zero exit code to stop "
            "the epic drive and surface the halt to the operator"
        )

    def test_stop_message_mentions_child_and_epic(self):
        assert "stopping epic drive" in _content(), (
            "drive-item.sh must print a clear message naming the child that halted "
            "and that the epic drive is stopping"
        )

    def test_script_parses_without_error(self):
        res = subprocess.run(
            ["bash", "-n", str(DRIVE_ITEM)], capture_output=True, text=True
        )
        assert res.returncode == 0, (
            f"drive-item.sh does not parse after epic mode additions: {res.stderr}"
        )
