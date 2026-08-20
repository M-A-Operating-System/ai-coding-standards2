"""
Functional tests for the /run-agent tool-scope enforcement hook (issue #311).

Unlike tests/test_docs_operating_modes.py (which checks the docs describe the
rule), these tests exercise the actual hook script that enforces it: a
PreToolUse hook that denies any tool call outside the allowlist a /run-agent
invocation declares in .claude/.run-agent-scope.json.

The allowlist holds two entry forms and the hook must honour both (issue #335):
bare tool names ("Read") granting a whole tool, and fine-grained patterns
("Bash(gh pr diff *)") granting only matching commands. BASE_AGENT_TOOLS uses
the pattern form exclusively for Bash.
"""
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = REPO_ROOT / ".claude" / "hooks" / "run-agent-scope.sh"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


def run_hook(cwd, tool_name, command=None):
    payload = {"tool_name": tool_name}
    if command is not None:
        payload["tool_input"] = {"command": command}
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )


def assert_allowed(result):
    assert result.returncode == 0
    assert result.stdout.strip() == "", f"expected allow, got: {result.stdout}"


def deny_reason(result):
    assert result.returncode == 0
    output = json.loads(result.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse"
    assert hook_output["permissionDecision"] == "deny"
    return hook_output["permissionDecisionReason"]


# The Bash slice of BASE_AGENT_TOOLS (pipeline_orchestrator.py), i.e. the shape
# /run-agent writes to the scope file once it sources the allowlist from the
# orchestrator's resolve-only mode rather than the agent's `tools:` frontmatter.
RESOLVED_ALLOWLIST = [
    "Bash(gh issue view *)",
    "Bash(gh issue comment *)",
    "Bash(gh pr diff *)",
    "Bash(gh api repos/*/issues/*)",
    'Bash(gh api "repos/*/issues/*)',
    "Bash(gh api --method * repos/*/issues*)",
    'Bash(gh api --method * "repos/*/issues*)',
    "Bash(cat *)",
    "Bash(grep *)",
    "Read",
    "Grep",
]


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


# --- Fine-grained "Bash(pattern)" entries (issue #335) -----------------------


def test_allows_bash_command_matching_a_declared_pattern(tmp_path):
    """The regression #335 reports: a command the allowlist explicitly grants
    was denied, because the hook only tested for the bare string "Bash"."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    assert_allowed(run_hook(tmp_path, "Bash", "gh pr diff 328"))


def test_denies_bash_command_matching_no_declared_pattern(tmp_path):
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    reason = deny_reason(run_hook(tmp_path, "Bash", "gh pr merge 328 --squash"))
    assert "gh pr merge 328 --squash" in reason, \
        "the denial must name the rejected command, not just the tool"
    assert "pr-reviewer" in reason


def test_wildcard_spans_characters_mid_pattern(tmp_path):
    """BASE_AGENT_TOOLS relies on `*` matching any characters mid-pattern, not
    just as a trailing prefix marker (issue #326)."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    assert_allowed(
        run_hook(tmp_path, "Bash", "gh api repos/OWNER/REPO/issues/316 --jq .title")
    )


def test_allows_quoted_url_form_of_gh_api(tmp_path):
    """The quoted-URL counterpart patterns added by issue #326 must match."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    assert_allowed(
        run_hook(tmp_path, "Bash", 'gh api "repos/OWNER/REPO/issues/316"')
    )
    assert_allowed(
        run_hook(
            tmp_path,
            "Bash",
            'gh api --method POST "repos/OWNER/REPO/issues/316/comments" -f body=@/tmp/b.txt',
        )
    )


def test_patterns_do_not_widen_scope_beyond_issue_and_pr_endpoints(tmp_path):
    """Pattern matching must not become a blanket `gh api` grant."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    deny_reason(run_hook(tmp_path, "Bash", "gh api repos/OWNER/REPO/actions/runs"))


def test_bash_patterns_do_not_grant_other_tools(tmp_path):
    """The original #311 case must not regress: Glob is absent from the
    allowlist, and no amount of Bash patterns may let it through."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    reason = deny_reason(run_hook(tmp_path, "Glob"))
    assert "Glob" in reason


def test_bare_bash_entry_still_grants_any_command(tmp_path):
    """Back-compat with the pre-#328 frontmatter form of the scope file."""
    write_scope(tmp_path, "01_product_docs/prd-writer", ["Bash", "Read", "Grep"])
    assert_allowed(run_hook(tmp_path, "Bash", "anything at all"))


def test_empty_allowlist_denies_bash_commands(tmp_path):
    write_scope(tmp_path, "no-tools-agent", [])
    deny_reason(run_hook(tmp_path, "Bash", "gh pr diff 328"))


def test_no_scope_file_allows_bash_commands(tmp_path):
    assert_allowed(run_hook(tmp_path, "Bash", "rm -rf /"))
