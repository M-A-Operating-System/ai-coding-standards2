"""
Functional tests for the /run-agent tool-scope enforcement hook (issue #311).

Unlike tests/test_docs_operating_modes.py (which checks the docs describe the
rule), these tests exercise the actual hook script that enforces it: a
PreToolUse hook that denies any tool call outside the allowlist a /run-agent
invocation declares in .claude/.run-agent-scope.json.
"""
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = REPO_ROOT / ".claude" / "hooks" / "run-agent-scope.sh"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


def run_hook(cwd, tool_name):
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps({"tool_name": tool_name}),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )


def write_scope(tmp_path, agent, allowed):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / ".run-agent-scope.json").write_text(
        json.dumps({"agent": agent, "allowed": allowed})
    )


def test_hook_script_exists():
    assert HOOK_SCRIPT.exists(), ".claude/hooks/run-agent-scope.sh must exist"


def test_hook_registered_as_pretooluse_in_settings():
    settings = json.loads(SETTINGS.read_text())
    pre_tool_use = settings.get("hooks", {}).get("PreToolUse", [])
    commands = [
        h["command"]
        for entry in pre_tool_use
        for h in entry.get("hooks", [])
    ]
    assert any("run-agent-scope.sh" in c for c in commands), \
        ".claude/settings.json must register run-agent-scope.sh as a PreToolUse hook"


def test_allows_any_tool_when_no_scope_file_present(tmp_path):
    """Outside of a /run-agent run, no scope file exists, so nothing is restricted."""
    result = run_hook(tmp_path, "Glob")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_allows_tool_within_declared_allowlist(tmp_path):
    write_scope(tmp_path, "01_product_docs/prd-writer", ["Bash", "Read", "Grep"])
    result = run_hook(tmp_path, "Bash")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_denies_tool_outside_declared_allowlist(tmp_path):
    """This is the concrete Glob-through-symlink case issue #311 reported."""
    write_scope(tmp_path, "01_product_docs/prd-writer", ["Bash", "Read", "Grep"])
    result = run_hook(tmp_path, "Glob")
    assert result.returncode == 0

    output = json.loads(result.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse"
    assert hook_output["permissionDecision"] == "deny"
    assert "Glob" in hook_output["permissionDecisionReason"]
    assert "prd-writer" in hook_output["permissionDecisionReason"]


def test_denial_reason_names_the_declared_allowlist(tmp_path):
    write_scope(tmp_path, "03_execute/coder", ["Bash", "Read", "Edit", "Write", "Grep", "Glob"])
    result = run_hook(tmp_path, "WebFetch")
    output = json.loads(result.stdout)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    for tool in ["Bash", "Read", "Edit", "Write", "Grep", "Glob"]:
        assert tool in reason


def test_denies_disallowed_tool_error_path_empty_allowlist(tmp_path):
    """An agent declaring no tools denies everything -- confirms deny is the
    default, not allow-by-omission."""
    write_scope(tmp_path, "no-tools-agent", [])
    result = run_hook(tmp_path, "Bash")
    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
