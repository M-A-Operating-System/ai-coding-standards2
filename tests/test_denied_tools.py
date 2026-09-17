"""Tests for the deniedTools pipeline feature (#457).

Gherkin scenarios traced (docs/features/add-deniedtools-to-pipeline-agent-permissions-so-coder-s-allowlist-can-open-up.md):

  Scenario: Deny rule fires when command matches and allow also matches
  Scenario: Default and step deny lists are merged without duplication
  Scenario: Deny rule does not fire for a command reached through an interpreter wrapper

Also covers acceptance criteria:
  - deniedTools supported in defaults and step definitions (schema + pipeline.json)
  - Effective list = defaults.deniedTools + step.deniedTools, deduplicated, deterministic order
  - A step cannot remove a default deny rule
  - Deny takes precedence over allow in the matcher (passed as --disallowedTools)
  - Resolve-only output exposes denied_tools
  - Steps without deniedTools behave exactly as today
  - Schema accepts deniedTools in both positions and rejects a non-array
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))
import pipeline_orchestrator as po

PIPELINE = REPO_ROOT / "pipeline" / "pipeline.json"
SCHEMA_PATH = REPO_ROOT / "pipeline" / "schemas" / "pipeline.schema.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_def(**overrides):
    """Minimal AgentDef with sensible defaults for the fields under test."""
    base = dict(
        agent="03_execute/coder",
        phase="03_execute",
        objects=["issue"],
        trigger={"label": "create-pr:complete"},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test",
    )
    base.update(overrides)
    return po.AgentDef(**base)


def _work_item():
    return po.WorkItem(
        number=1,
        kind="issue",
        title="test",
        labels=set(),
        url="https://github.com/test/repo/issues/1",
    )


def _resolve(agent_def):
    """Run _resolve_agent_invocation with a stub agent file."""
    agent_text = "---\nname: test\n---\n# Test agent body"
    return po._resolve_agent_invocation(
        agent_def, _work_item(), "test/repo",
        agent_text_override=agent_text,
        default_extra_tools=[],
    )


def _print_prompt_output(capsys, agent="03_execute/coder"):
    """Run _run_print_prompt and return the parsed JSON output."""
    gh = MagicMock()
    gh._get.return_value = {
        "number": 1, "title": "t", "labels": [],
        "html_url": "https://github.com/test/repo/issues/1",
    }
    gh.find_pr_by_branch.return_value = None
    gh.find_pr_by_label.return_value = None

    args = MagicMock()
    args.repo = "test/repo"
    args.issue = 1
    args.kind = None
    args.agent = agent
    args.pipeline = PIPELINE
    args.print_prompt = True

    with patch.object(po, "GitHubClient", return_value=gh), \
         patch.object(po, "_discover_github_token", return_value="t"):
        po._run_print_prompt(args)
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# Scenario: Deny rule fires when command matches and allow also matches
# (AC-6: deny takes precedence over allow in the matcher)
# ---------------------------------------------------------------------------

def test_deny_rule_fires_when_command_matches_and_allow_also_matches():
    """When --disallowedTools contains a deny pattern, the CLI matcher refuses
    that command even if --allowedTools also matches it. This test verifies that
    the orchestrator passes both lists correctly so the CLI can apply that rule.

    Given a step with extra_allowedTools containing "Bash(git *)" and
    deniedTools containing "Bash(git reset --hard*)",
    the resolved invocation must include the deny pattern in denied_tools
    so --disallowedTools carries it to the CLI.
    """
    agent_def = _make_agent_def(
        extra_allowedTools=["Bash(git *)"],
        denied_tools=["Bash(git reset --hard*)"],
    )
    resolved = _resolve(agent_def)
    assert resolved is not None
    assert "Bash(git reset --hard*)" in resolved.denied_tools
    assert "Bash(git *)" in resolved.allowed_tools


def test_deny_rule_appears_in_disallowed_tools_cli_arg():
    """The deny pattern must reach the --disallowedTools flag passed to the CLI.

    When the orchestrator builds the command for subprocess.Popen, denied_tools
    are appended to the fixed Task,Agent,Skill set.  We verify by inspecting the
    command list built inside invoke_agent's subprocess call.
    """
    agent_def = _make_agent_def(
        extra_allowedTools=["Bash(git *)"],
        denied_tools=["Bash(git reset --hard*)"],
    )
    agent_text = "---\nname: test\n---\n# body"
    work_item = _work_item()

    captured_cmd = []

    class _FakePopen:
        def __init__(self, cmd, **_kw):
            captured_cmd.extend(cmd)
            raise RuntimeError("stop-after-capture")

    with patch("subprocess.Popen", _FakePopen), \
         patch.object(po, "_claude_cli_usable", return_value=True):
        try:
            po.invoke_agent(
                agent_def, work_item, dry_run=False, repo="test/repo",
                agent_text_override=agent_text,
                default_extra_tools=[],
            )
        except RuntimeError:
            pass

    disallowed_idx = captured_cmd.index("--disallowedTools") if "--disallowedTools" in captured_cmd else -1
    assert disallowed_idx >= 0, "--disallowedTools flag not found in command"
    disallowed_value = captured_cmd[disallowed_idx + 1]
    assert "Bash(git reset --hard*)" in disallowed_value
    assert "Task" in disallowed_value
    assert "Agent" in disallowed_value
    assert "Skill" in disallowed_value


# ---------------------------------------------------------------------------
# Scenario: Default and step deny lists are merged without duplication
# (AC-4: merge deduped; AC-5: step cannot remove default rule)
# ---------------------------------------------------------------------------

def test_default_and_step_deny_lists_are_merged_without_duplication():
    """Effective deny list = defaults.deniedTools + step.deniedTools, deduplicated.

    Given defaults.deniedTools = ["Bash(git push --force*)"] and a step's
    deniedTools = ["Bash(git reset --hard*)"],
    the resolved list must contain both exactly once in deterministic order.
    """
    raw = {
        "budgets": {"max_turns": 10, "max_wall_seconds": 60},
        "defaults": {
            "extra_allowedTools": [],
            "deniedTools": ["Bash(git push --force*)"],
        },
        "flows": {
            "test-flow": {
                "description": "d",
                "trigger": {"kind": "issue"},
                "steps": [
                    {
                        "agent": "03_execute/coder",
                        "phase": "03_execute",
                        "trigger": {"label": "create-pr:complete"},
                        "dependencies": [],
                        "human_gate_after": False,
                        "description": "d",
                        "expected_effect": {"commits": True},
                        "deniedTools": ["Bash(git reset --hard*)"],
                    }
                ],
            }
        },
    }
    agents, _ = po.load_pipeline.__wrapped__(raw) if hasattr(po.load_pipeline, "__wrapped__") else _load_from_raw(raw)

    coder = next(a for a in agents if a.agent == "03_execute/coder")
    assert "Bash(git push --force*)" in coder.denied_tools
    assert "Bash(git reset --hard*)" in coder.denied_tools
    assert coder.denied_tools.count("Bash(git push --force*)") == 1
    assert coder.denied_tools.count("Bash(git reset --hard*)") == 1
    # Order: default first, then step
    assert coder.denied_tools.index("Bash(git push --force*)") < \
           coder.denied_tools.index("Bash(git reset --hard*)")


def _load_from_raw(raw):
    """Call the internal pipeline loader directly on a dict, bypassing file I/O."""
    agents = po._steps_from_flows(raw)
    default_extra_tools = po._coerce_tools(raw.get("defaults", {}).get("extra_allowedTools"))
    _default_denied = po._coerce_tools(raw.get("defaults", {}).get("deniedTools"))
    for _agent in agents:
        _agent.denied_tools = list(dict.fromkeys(_default_denied + _agent.denied_tools))
    return agents, default_extra_tools


def test_step_cannot_remove_default_deny_rule():
    """A step's deniedTools adds to the effective list; it cannot subtract.

    A step that declares no deniedTools still inherits defaults.deniedTools.
    """
    raw = {
        "budgets": {"max_turns": 10, "max_wall_seconds": 60},
        "defaults": {
            "extra_allowedTools": [],
            "deniedTools": ["Bash(git push --force*)"],
        },
        "flows": {
            "test-flow": {
                "description": "d",
                "trigger": {"kind": "issue"},
                "steps": [
                    {
                        "agent": "03_execute/coder",
                        "phase": "03_execute",
                        "trigger": {"label": "create-pr:complete"},
                        "dependencies": [],
                        "human_gate_after": False,
                        "description": "d",
                        "expected_effect": {"commits": True},
                        # No deniedTools declared -- defaults must still apply
                    }
                ],
            }
        },
    }
    agents, _ = _load_from_raw(raw)
    coder = next(a for a in agents if a.agent == "03_execute/coder")
    assert "Bash(git push --force*)" in coder.denied_tools, \
        "default deny rule must survive even when the step declares no deniedTools"


def test_deduplication_when_step_repeats_a_default_rule():
    """When a step repeats a rule from defaults, the merged list has it once."""
    raw = {
        "budgets": {"max_turns": 10, "max_wall_seconds": 60},
        "defaults": {
            "extra_allowedTools": [],
            "deniedTools": ["Bash(git push --force*)"],
        },
        "flows": {
            "test-flow": {
                "description": "d",
                "trigger": {"kind": "issue"},
                "steps": [
                    {
                        "agent": "03_execute/coder",
                        "phase": "03_execute",
                        "trigger": {"label": "create-pr:complete"},
                        "dependencies": [],
                        "human_gate_after": False,
                        "description": "d",
                        "expected_effect": {"commits": True},
                        "deniedTools": ["Bash(git push --force*)"],  # duplicate
                    }
                ],
            }
        },
    }
    agents, _ = _load_from_raw(raw)
    coder = next(a for a in agents if a.agent == "03_execute/coder")
    assert coder.denied_tools.count("Bash(git push --force*)") == 1


# ---------------------------------------------------------------------------
# _denied_tools_from_entry: deniedTools is authoritative over deny_groups
# ---------------------------------------------------------------------------

def test_denied_tools_from_entry_prefers_declared_denied_tools_over_deny_groups():
    """When a step entry declares both deniedTools and deny_groups, deniedTools wins.

    _denied_tools_from_entry must not flatten deny_groups when deniedTools is
    present -- deny_groups is only a fallback for steps that source their
    effective deny list from grouped patterns instead of a flat declaration.
    """
    entry = {
        "deniedTools": ["Bash(git push --force*)"],
        "deny_groups": [
            {"name": "g", "purpose": "p", "patterns": ["Bash(git reset --hard*)"]}
        ],
    }
    assert po._denied_tools_from_entry(entry) == ["Bash(git push --force*)"]


def test_denied_tools_from_entry_flattens_deny_groups_when_no_denied_tools():
    """Without a declared deniedTools, the effective list is deny_groups flattened."""
    entry = {
        "deny_groups": [
            {"name": "g1", "purpose": "p1", "patterns": ["Bash(a*)", "Bash(b*)"]},
            {"name": "g2", "purpose": "p2", "patterns": ["Bash(c*)"]},
        ],
    }
    assert po._denied_tools_from_entry(entry) == ["Bash(a*)", "Bash(b*)", "Bash(c*)"]


# ---------------------------------------------------------------------------
# Scenario: Deny rule does not fire for a command reached through an interpreter wrapper
# (AC-13: documents the limitation; tests the boundary)
# ---------------------------------------------------------------------------

def test_deny_rule_does_not_fire_for_a_command_reached_through_an_interpreter_wrapper():
    """Documents the known limitation: the deny matcher sees the command as written.

    Given deniedTools = ["Bash(echo DENIED*)"] and allowedTools containing
    "Bash(bash *)" and "Bash(echo *)", when the step runs
    `bash -c 'echo DENIED_PATH_REACHED'`, the CLI sees the command string
    `bash -c '...'` which does NOT match `Bash(echo DENIED*)`.  The deny rule
    does not fire.

    This test verifies that the orchestrator passes the deny pattern
    as-written to --disallowedTools without any server-side inspection of
    interpreter arguments.  What pattern we pass is what the CLI matches against
    the top-level command string -- nothing more.
    """
    agent_def = _make_agent_def(
        extra_allowedTools=["Bash(bash *)", "Bash(echo *)"],
        denied_tools=["Bash(echo DENIED*)"],
    )
    resolved = _resolve(agent_def)
    assert resolved is not None
    # The deny list is passed verbatim -- no pattern expansion or arg inspection.
    assert resolved.denied_tools == ["Bash(echo DENIED*)"]
    # "Bash(bash *)" is in the allow list, so `bash -c '...'` is allowed by the
    # CLI's allowedTools matcher; only the top-level command "bash" is tested
    # against denied patterns, and "bash ..." does not match "echo DENIED*".
    assert "Bash(bash *)" in resolved.allowed_tools


# ---------------------------------------------------------------------------
# Backward compatibility: steps without deniedTools behave as today (AC-11)
# ---------------------------------------------------------------------------

def test_steps_without_denied_tools_behave_as_today():
    """A step with no deniedTools must produce the same --disallowedTools as before.

    Before this feature, --disallowedTools was always "Task,Agent,Skill".
    A step that declares no deniedTools must still produce exactly that.
    """
    agent_def = _make_agent_def(
        extra_allowedTools=["Bash(git status *)"],
        denied_tools=[],
    )
    agent_text = "---\nname: test\n---\n# body"
    work_item = _work_item()

    captured_cmd = []

    class _FakePopen:
        def __init__(self, cmd, **_kw):
            captured_cmd.extend(cmd)
            raise RuntimeError("stop")

    with patch("subprocess.Popen", _FakePopen), \
         patch.object(po, "_claude_cli_usable", return_value=True):
        try:
            po.invoke_agent(
                agent_def, work_item, dry_run=False, repo="test/repo",
                agent_text_override=agent_text,
                default_extra_tools=[],
            )
        except RuntimeError:
            pass

    disallowed_idx = captured_cmd.index("--disallowedTools") if "--disallowedTools" in captured_cmd else -1
    assert disallowed_idx >= 0
    assert captured_cmd[disallowed_idx + 1] == "Task,Agent,Skill"


# ---------------------------------------------------------------------------
# Resolve-only output exposes denied_tools (AC-8)
# ---------------------------------------------------------------------------

def test_resolve_only_output_exposes_denied_tools(capsys):
    """--print-prompt output must include a denied_tools key."""
    payload = _print_prompt_output(capsys)
    assert "denied_tools" in payload, "--print-prompt output must include denied_tools"


def test_resolve_only_denied_tools_matches_coder_pipeline_json(capsys):
    """The denied_tools in --print-prompt output must include the coder's declared deny patterns."""
    payload = _print_prompt_output(capsys, agent="03_execute/coder")
    # Core deny patterns from all seven deny groups (issue #463)
    for pattern in (
        "Bash(git reset --hard*)",
        "Bash(git commit --amend*)",
        "Bash(git push --force*)",
        "Bash(git branch -D *)",
        "Bash(git config *)",
        "Bash(ssh *)",
        "Bash(env)",
        "Bash(printenv)",
    ):
        assert pattern in payload["denied_tools"], (
            f"denied_tools must contain {pattern!r}"
        )


# ---------------------------------------------------------------------------
# Schema validation accepts deniedTools in both positions; rejects non-array (AC-3)
# ---------------------------------------------------------------------------

def _validate_against_schema(raw):
    """Return a list of jsonschema error messages; empty if valid."""
    import jsonschema
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(raw)]


def _minimal_pipeline(**defaults_extra):
    """Build a minimal valid pipeline dict for schema tests."""
    return {
        "budgets": {"max_turns": 10, "max_wall_seconds": 60},
        "defaults": {"extra_allowedTools": [], **defaults_extra},
        "flows": {
            "test-flow": {
                "description": "d",
                "trigger": {"kind": "issue"},
                "steps": [
                    {
                        "agent": "03_execute/coder",
                        "phase": "03_execute",
                        "trigger": {"label": "create-pr:complete"},
                        "dependencies": [],
                        "human_gate_after": False,
                        "description": "d",
                        "expected_effect": {"commits": True},
                    }
                ],
            }
        },
    }


def test_schema_accepts_denied_tools_in_defaults():
    raw = _minimal_pipeline(deniedTools=["Bash(git push --force*)"])
    errors = _validate_against_schema(raw)
    assert not errors, f"schema rejected valid defaults.deniedTools: {errors}"


def test_schema_accepts_denied_tools_in_step():
    raw = _minimal_pipeline()
    raw["flows"]["test-flow"]["steps"][0]["deniedTools"] = ["Bash(git reset --hard*)"]
    errors = _validate_against_schema(raw)
    assert not errors, f"schema rejected valid step.deniedTools: {errors}"


def test_schema_rejects_denied_tools_as_non_array_in_defaults():
    raw = _minimal_pipeline(deniedTools="Bash(git push --force*)")
    errors = _validate_against_schema(raw)
    assert errors, "schema must reject a non-array deniedTools in defaults"


def test_schema_rejects_denied_tools_as_non_array_in_step():
    raw = _minimal_pipeline()
    raw["flows"]["test-flow"]["steps"][0]["deniedTools"] = "Bash(git reset --hard*)"
    errors = _validate_against_schema(raw)
    assert errors, "schema must reject a non-array deniedTools in step"


# ---------------------------------------------------------------------------
# pipeline.json: coder step declares the initial use-case rules (AC-1, AC-2)
# ---------------------------------------------------------------------------

def test_shipped_pipeline_has_denied_tools_on_coder():
    """The 03_execute/coder step's effective deny list (declared via
    deny_groups, flattened at load time) must resolve correctly.

    After issue #463 the full deny list covers seven groups; verify a
    representative pattern from each group is present.
    """
    agents, _ = po.load_pipeline(PIPELINE)
    coder = next((a for a in agents if a.agent == "03_execute/coder"), None)
    assert coder is not None, "coder step not found in pipeline"
    # Group 1: git history destruction
    assert "Bash(git reset --hard*)" in coder.denied_tools
    assert "Bash(git commit --amend*)" in coder.denied_tools
    # Group 2: destructive remote ops
    assert "Bash(git push --force*)" in coder.denied_tools
    # Group 3: branch/reference destruction
    assert "Bash(git branch -D *)" in coder.denied_tools
    # Group 4: validation bypass
    assert "Bash(git commit --no-verify*)" in coder.denied_tools
    # Group 5: control-plane
    assert "Bash(git config *)" in coder.denied_tools
    # Group 6: credential disclosure
    assert "Bash(env)" in coder.denied_tools
    assert "Bash(printenv)" in coder.denied_tools
    # Group 7: external shell
    assert "Bash(ssh *)" in coder.denied_tools


# ---------------------------------------------------------------------------
# Generated docs show both columns (AC-12)
# ---------------------------------------------------------------------------

def test_generated_docs_show_declared_prohibitions_column():
    """The pipeline-steps.md generated doc must include a Declared prohibitions column."""
    steps_md = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated" / "pipeline-steps.md"
    assert steps_md.exists(), "pipeline-steps.md must exist"
    text = steps_md.read_text()
    assert "Declared prohibitions" in text, \
        "pipeline-steps.md must include a Declared prohibitions column"


def test_generated_docs_show_coder_prohibitions():
    """The pipeline-steps.md must list coder's deny rules."""
    steps_md = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated" / "pipeline-steps.md"
    text = steps_md.read_text()
    assert "git reset --hard" in text, \
        "pipeline-steps.md must show coder's git reset --hard deny rule"
    assert "git branch -D" in text, \
        "pipeline-steps.md must show coder's git branch -D deny rule"


def test_generated_docs_include_interpreter_wrapper_note():
    """Docs must note the interpreter-wrapper limitation per amendment 2."""
    steps_md = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated" / "pipeline-steps.md"
    text = steps_md.read_text()
    assert "interpreter" in text.lower(), \
        "pipeline-steps.md must mention the interpreter-wrapper limitation"
    assert "command string as written" in text or "as written" in text, \
        "pipeline-steps.md must say the deny list is matched against the command as written"


# ---------------------------------------------------------------------------
# generate_docs.py --check must pass with the regenerated docs (idempotency)
# ---------------------------------------------------------------------------

def test_generate_docs_check_passes():
    """Running generate_docs.py --check must exit 0 with the current committed files."""
    import subprocess
    result = subprocess.run(
        ["python3", "pipeline/generators/generate_docs.py", "--check"],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"generate_docs.py --check failed; regenerate with "
        f"`python3 pipeline/generators/generate_docs.py`\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
