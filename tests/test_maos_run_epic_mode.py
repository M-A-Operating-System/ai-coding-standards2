"""Structural guard for /maos-run epic mode -- issue #657.

Behavioral coverage of R1-R3 (drives each child in sub-issue order, falls
through to the single-issue path for a non-epic issue, and stops at the
first child that halts) lives in tests/test_drive_item_epic_mode.sh, which
drives the real script end to end through mocked gh/python3 rather than
asserting on source text. This file keeps only the one check a behavioral
subprocess test cannot usefully give: that the script is valid bash after
the epic-mode edit.
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DRIVE_ITEM = REPO_ROOT / "scripts" / "drive-item.sh"


def test_script_parses_without_error():
    res = subprocess.run(
        ["bash", "-n", str(DRIVE_ITEM)], capture_output=True, text=True
    )
    assert res.returncode == 0, (
        f"drive-item.sh does not parse after epic mode additions: {res.stderr}"
    )
