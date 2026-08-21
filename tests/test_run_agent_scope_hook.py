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


# --- Sub-command decomposition (issue #362) ---------------------------------
#
# The hook used to glob a granted pattern against the whole command string,
# which was simultaneously too loose (a granted prefix swallowed everything
# after `&&`) and too strict (a granted command preceded by `cd` matched
# nothing). Both come from the same defect; these tests pin both halves.

SPLITTER = REPO_ROOT / ".claude" / "hooks" / "split-command.py"

# BASE_AGENT_TOOLS grants `cd` in its own right precisely so the idiomatic
# `cd $AI_AGILE_ROOT && <granted>` survives decomposition.
CHAINING_ALLOWLIST = RESOLVED_ALLOWLIST + [
    "Bash(cd *)",
    "Bash(sed *)",
    "Bash(export *)",
    "Bash(sh *)",
    "Bash(bash *)",
    "Bash(find *)",
]


def test_granted_command_preceded_by_a_directory_change_is_permitted(tmp_path):
    """The false-denial half: `sed` is granted, but the string starts with `cd`."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    assert_allowed(
        run_hook(
            tmp_path,
            "Bash",
            "cd /home/user/ai-coding-standards2 && sed -n '1,5p' .claude/AGENTS.md",
        )
    )
    # The multi-line form the #321 run actually used, export included.
    assert_allowed(
        run_hook(
            tmp_path,
            "Bash",
            "cd /home/user/ai-coding-standards2\n"
            'export REPO="o/r"\n'
            "sed -n '1,5p' .claude/AGENTS.md",
        )
    )


def test_granted_prefix_does_not_authorise_a_chained_command(tmp_path):
    """The bypass half: `Bash(export *)` must not swallow the rest of the line."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    reason = deny_reason(
        run_hook(tmp_path, "Bash", "export FOO=1 && curl https://example.com")
    )
    assert "curl https://example.com" in reason, \
        "the denial must name the ungranted sub-command, not the whole line"


def test_every_separator_form_is_decomposed(tmp_path):
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    for command in [
        "echo x; curl https://example.com",
        "cat f | curl https://example.com",
        "cat f || curl https://example.com",
        "cd /tmp && cat f && curl https://example.com",
    ]:
        deny_reason(run_hook(tmp_path, "Bash", command))


def test_shell_wrapper_does_not_launder_an_ungranted_command(tmp_path):
    """`sh -c` is an arbitrary interpreter; no pattern can scope its argument."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    for command in [
        "sh -c 'curl https://example.com'",
        'bash -c "curl https://example.com"',
    ]:
        reason = deny_reason(run_hook(tmp_path, "Bash", command))
        assert "cannot be scope-checked" in reason


def test_interpreter_running_a_repo_file_is_still_permitted(tmp_path):
    """Only inline `-c` source is laundering; running a checked-in script is not."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    assert_allowed(run_hook(tmp_path, "Bash", "bash scripts/build.sh"))


def test_command_substitution_is_refused(tmp_path):
    """`$(...)` hides a command inside a word where no pattern can see it."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    for command in [
        "echo $(curl https://example.com)",
        "cat `curl https://example.com`",
    ]:
        reason = deny_reason(run_hook(tmp_path, "Bash", command))
        assert "cannot be scope-checked" in reason


def test_find_exec_is_refused(tmp_path):
    """`Bash(find *)` is granted to every agent; `-exec` would make it universal."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    reason = deny_reason(
        run_hook(tmp_path, "Bash", "find . -name '*.py' -exec curl https://example.com {} ;")
    )
    assert "cannot be scope-checked" in reason


def test_exec_wrappers_are_refused(tmp_path):
    """Wrappers exist to run a command named in their own arguments."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST + ["Bash(xargs *)", "Bash(env *)"])
    for command in [
        "xargs curl",
        "env curl https://example.com",
        "eval curl",
    ]:
        reason = deny_reason(run_hook(tmp_path, "Bash", command))
        assert "cannot be scope-checked" in reason


def test_base_agent_tools_grants_cd(tmp_path):
    """Decomposition only works if `cd` is granted; otherwise it sinks every
    `cd X && <granted>` call, which is what it did on #321."""
    orchestrator = (REPO_ROOT / "pipeline" / "pipeline_orchestrator.py").read_text()
    assert '"Bash(cd *)"' in orchestrator, \
        "BASE_AGENT_TOOLS must grant Bash(cd *) for sub-command matching to be usable"


def test_splitter_exits_two_on_refusal():
    """The hook distinguishes 'split fine, no match' from 'cannot be split'."""
    result = subprocess.run(
        ["python3", str(SPLITTER)],
        input="sh -c 'curl x'", capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED: ")


def test_newline_separates_sub_commands(tmp_path):
    """A newline ends a command as surely as `&&` does. Treating it as plain
    whitespace let `cd /repo\\ncurl evil` match Bash(cd *) as one segment."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    reason = deny_reason(
        run_hook(tmp_path, "Bash", "cd /repo\ncurl https://example.com")
    )
    assert "curl https://example.com" in reason


def test_line_continuation_is_one_sub_command(tmp_path):
    r"""A trailing `\` joins lines; the halves are not separate commands."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    assert_allowed(run_hook(tmp_path, "Bash", "cat foo \\\n  bar"))


def test_heredoc_body_is_data_not_commands(tmp_path):
    """AGENTS.md prescribes staging comment bodies with `cat ... <<'EOF'`.
    Reading the body's lines as commands would deny the protocol's own idiom."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    assert_allowed(
        run_hook(
            tmp_path,
            "Bash",
            'cat > "${AI_AGILE_SCRATCH:-/tmp}/body.md" <<\'EOF\'\n'
            "## Findings && caveats\n"
            "EOF\n"
            "gh api --method POST repos/o/r/issues/1/comments -F body=@/tmp/body.md",
        )
    )


def test_unquoted_heredoc_body_is_still_checked_for_substitution(tmp_path):
    """`<<EOF` expands; `<<'EOF'` does not. Only the quoted form is inert."""
    write_scope(tmp_path, "03_execute/coder", CHAINING_ALLOWLIST)
    reason = deny_reason(
        run_hook(tmp_path, "Bash", "cat > /tmp/x <<EOF\n$(curl https://example.com)\nEOF")
    )
    assert "cannot be scope-checked" in reason


def test_the_scope_file_can_always_be_removed(tmp_path):
    """run-agent.md step 7 ends enforcement by removing the scope file. It has
    to work for every agent, not only the ones whose allowlist grants `rm` --
    otherwise a pr-reviewer run leaves the session scoped with no way back
    (issue #356)."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    assert "Bash(rm *)" not in RESOLVED_ALLOWLIST, "precondition: rm is not granted"
    for command in [
        "rm .claude/.run-agent-scope.json",
        "rm -f .claude/.run-agent-scope.json",
        "rm -f -- .claude/.run-agent-scope.json",
    ]:
        assert_allowed(run_hook(tmp_path, "Bash", command))


def test_the_escape_hatch_grants_nothing_else(tmp_path):
    """It is an exact match, not an `rm` grant with a scope-file argument."""
    write_scope(tmp_path, "03_execute/pr-reviewer", RESOLVED_ALLOWLIST)
    for command in [
        "rm -rf /",
        "rm -rf / .claude/.run-agent-scope.json",
        "rm .claude/.run-agent-scope.json && curl https://example.com",
        "rm .claude/settings.json",
    ]:
        deny_reason(run_hook(tmp_path, "Bash", command))
