"""Tests for coder tool scope simplification (issue #463).

Gherkin scenarios traced (docs/features/simplify-coder-tool-scope-using-broad-bash-access-and-grouped-deny-tools.md):

  Scenario: Coder step grants broad Bash access and inherits default tools
  Scenario: Direct form of a denied command is blocked
  Scenario: Denied command reached through an interpreter wrapper is not blocked
"""
import fnmatch
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"
SCHEMA_PATH = REPO_ROOT / "pipeline" / "schemas" / "pipeline.schema.json"
STEPS_MD = REPO_ROOT / "docs" / "product" / "orchestrator" / "generated" / "pipeline-steps.md"

_CODER_AGENT = "03_execute/coder"

_FULL_DENY_LIST = [
    "Bash(git reset --hard*)",
    "Bash(git commit --amend*)",
    "Bash(git commit * --amend*)",
    "Bash(git push --force*)",
    "Bash(git push * --force*)",
    "Bash(git push --force-with-lease*)",
    "Bash(git push * --force-with-lease*)",
    "Bash(git push --delete*)",
    "Bash(git push * --delete*)",
    "Bash(git push --mirror*)",
    "Bash(git push * --mirror*)",
    "Bash(git branch -D *)",
    "Bash(git branch --delete --force *)",
    "Bash(git update-ref -d *)",
    "Bash(git commit --no-verify*)",
    "Bash(git commit * --no-verify*)",
    "Bash(git push --no-verify*)",
    "Bash(git push * --no-verify*)",
    "Bash(git config *)",
    "Bash(env)",
    "Bash(env *)",
    "Bash(printenv)",
    "Bash(printenv *)",
    "Bash(ssh *)",
    "Bash(scp *)",
    "Bash(sftp *)",
]


def _pipeline() -> dict:
    with PIPELINE_JSON.open() as fh:
        return json.load(fh)


def _coder_step() -> dict:
    pipeline = _pipeline()
    for flow in pipeline["flows"].values():
        for step in flow.get("steps", []):
            if step.get("agent") == _CODER_AGENT:
                return step
    raise AssertionError(f"{_CODER_AGENT} not found in pipeline.json")


def _effective_denied(step: dict) -> list:
    """Resolve the coder's deny groups exactly as the pipeline loader does."""
    if "deniedTools" in step:
        return step["deniedTools"]
    catalog = _pipeline().get("entitlement_groups", {})
    denied = []
    for group in step.get("deny_groups", []):
        definition = catalog[group] if isinstance(group, str) else group
        denied.extend(definition.get("patterns", []))
    return denied


def _tool_arg(pattern: str) -> str:
    """Extract the argument glob from a Bash(arg) pattern string.

    'Bash(git reset --hard*)' -> 'git reset --hard*'
    'Bash(env)' -> 'env'
    """
    if pattern.startswith("Bash(") and pattern.endswith(")"):
        return pattern[len("Bash("):-1]
    return pattern


def _command_matches_deny_pattern(command: str, deny_pattern: str) -> bool:
    """True when 'command' matches the argument part of 'deny_pattern'.

    Mirrors the CLI's own matching: the pattern is tested against the command
    string as written, using glob semantics.
    """
    arg_glob = _tool_arg(deny_pattern)
    return fnmatch.fnmatchcase(command, arg_glob)


# ---------------------------------------------------------------------------
# Scenario: Coder step grants broad Bash access and inherits default tools
# ---------------------------------------------------------------------------

class TestCoderStepGrantsBroadBashAccessAndInheritsDefaultTools:
    """Scenario: extra_allowedTools is bare 'Bash'; defaults include Read/Write/Edit/Glob/Grep."""

    def test_coder_extra_allowed_tools_contains_bash(self):
        """extra_allowedTools for the coder step must contain 'Bash'."""
        step = _coder_step()
        extra = step.get("extra_allowedTools", [])
        assert "Bash" in extra, (
            "coder step extra_allowedTools must contain 'Bash' (bare, not 'Bash(*)'). "
            f"Found: {extra}"
        )

    def test_coder_extra_allowed_tools_is_only_bash(self):
        """The coder's per-step extra_allowedTools should be the single bare 'Bash' entry."""
        step = _coder_step()
        extra = step.get("extra_allowedTools", [])
        assert extra == ["Bash"], (
            f"coder extra_allowedTools must be ['Bash'], found: {extra}"
        )

    def test_pipeline_defaults_include_read(self):
        pipeline = _pipeline()
        defaults = pipeline.get("defaults", {}).get("extra_allowedTools", [])
        assert "Read" in defaults, "pipeline defaults must include 'Read'"

    def test_pipeline_defaults_include_write(self):
        pipeline = _pipeline()
        defaults = pipeline.get("defaults", {}).get("extra_allowedTools", [])
        assert "Write" in defaults, "pipeline defaults must include 'Write'"

    def test_pipeline_defaults_include_edit(self):
        pipeline = _pipeline()
        defaults = pipeline.get("defaults", {}).get("extra_allowedTools", [])
        assert "Edit" in defaults, "pipeline defaults must include 'Edit'"

    def test_pipeline_defaults_include_glob(self):
        pipeline = _pipeline()
        defaults = pipeline.get("defaults", {}).get("extra_allowedTools", [])
        assert "Glob" in defaults, "pipeline defaults must include 'Glob'"

    def test_pipeline_defaults_include_grep(self):
        pipeline = _pipeline()
        defaults = pipeline.get("defaults", {}).get("extra_allowedTools", [])
        assert "Grep" in defaults, "pipeline defaults must include 'Grep'"


# ---------------------------------------------------------------------------
# Scenario: Direct form of a denied command is blocked
# ---------------------------------------------------------------------------

class TestDirectFormOfADeniedCommandIsBlocked:
    """Scenario: Bash(git reset --hard*) in deniedTools blocks the direct call."""

    def test_coder_denied_tools_contains_git_reset_hard(self):
        """The coder step's effective deny list must contain 'Bash(git reset --hard*)'."""
        step = _coder_step()
        denied = _effective_denied(step)
        assert "Bash(git reset --hard*)" in denied, (
            f"coder's effective deny list must contain 'Bash(git reset --hard*)'. Found: {denied}"
        )

    def test_full_deny_list_declared(self):
        """Every semantic deny group's patterns must remain in the effective deny list."""
        step = _coder_step()
        denied = _effective_denied(step)
        for pattern in _FULL_DENY_LIST:
            assert pattern in denied, (
                f"coder's effective deny list missing expected pattern: {pattern}"
            )

    def test_direct_command_matches_deny_pattern(self):
        """The argument 'git reset --hard HEAD' matches 'Bash(git reset --hard*)'."""
        assert _command_matches_deny_pattern(
            "git reset --hard HEAD",
            "Bash(git reset --hard*)",
        ), "direct form must match the deny pattern"

    def test_direct_git_commit_amend_is_denied(self):
        """'git commit --amend' direct call matches its deny pattern."""
        assert _command_matches_deny_pattern(
            "git commit --amend",
            "Bash(git commit --amend*)",
        )

    def test_direct_git_push_force_is_denied(self):
        """'git push --force' direct call matches its deny pattern."""
        assert _command_matches_deny_pattern(
            "git push --force origin main",
            "Bash(git push --force*)",
        )

    def test_direct_env_is_denied(self):
        """Bare 'env' command matches its deny pattern (exact match)."""
        assert _command_matches_deny_pattern("env", "Bash(env)")

    def test_direct_printenv_is_denied(self):
        """Bare 'printenv' command matches its deny pattern (exact match)."""
        assert _command_matches_deny_pattern("printenv", "Bash(printenv)")

    def test_direct_ssh_is_denied(self):
        """'ssh host' matches its deny pattern."""
        assert _command_matches_deny_pattern("ssh host", "Bash(ssh *)")

    def test_normal_git_commit_is_not_denied(self):
        """Normal 'git commit -m msg' must NOT match any deny pattern."""
        command = "git commit -m 'fix bug'"
        for pattern in _FULL_DENY_LIST:
            assert not _command_matches_deny_pattern(command, pattern), (
                f"'git commit' must not be denied; matched by {pattern}"
            )

    def test_normal_git_add_is_not_denied(self):
        """'git add .' must NOT match any deny pattern."""
        command = "git add ."
        for pattern in _FULL_DENY_LIST:
            assert not _command_matches_deny_pattern(command, pattern), (
                f"'git add' must not be denied; matched by {pattern}"
            )

    def test_normal_git_push_is_not_denied(self):
        """'git push origin branch' (no dangerous flags) must NOT match any deny pattern."""
        command = "git push origin issue-42"
        for pattern in _FULL_DENY_LIST:
            assert not _command_matches_deny_pattern(command, pattern), (
                f"normal git push must not be denied; matched by {pattern}"
            )


# ---------------------------------------------------------------------------
# Scenario: Denied command reached through an interpreter wrapper is not blocked
# ---------------------------------------------------------------------------

class TestDeniedCommandReachedThroughInterpreterWrapperIsNotBlocked:
    """Scenario: bash -c 'git reset --hard HEAD' is not matched by the deny pattern."""

    def test_wrapped_command_does_not_match_deny_pattern(self):
        """The argument 'bash -c git reset --hard HEAD' does NOT match 'Bash(git reset --hard*)'."""
        assert not _command_matches_deny_pattern(
            "bash -c 'git reset --hard HEAD'",
            "Bash(git reset --hard*)",
        ), (
            "the deny matcher sees the command string as written; "
            "a wrapper invocation must not match a deny pattern for the wrapped command"
        )

    def test_bash_is_in_extra_allowed_tools_enabling_wrapper_path(self):
        """Bare 'Bash' in extra_allowedTools means bash -c '...' is allowed at the top level."""
        step = _coder_step()
        extra = step.get("extra_allowedTools", [])
        assert "Bash" in extra, (
            "'Bash' must be in extra_allowedTools for the interpreter wrapper path to be available"
        )

    def test_limitation_is_documented_in_pipeline_steps_md(self):
        """The generated docs must document the interpreter-wrapper limitation."""
        assert STEPS_MD.exists(), "pipeline-steps.md must exist"
        text = STEPS_MD.read_text()
        assert "interpreter wrapper" in text or "interpreter" in text.lower(), (
            "pipeline-steps.md must mention the interpreter-wrapper limitation"
        )
        assert "as written" in text, (
            "pipeline-steps.md must state that the deny pattern is matched against "
            "the command string as written"
        )

    def test_deny_groups_section_present_in_pipeline_steps_md(self):
        """The generated docs must contain the deny rule groups section for the coder."""
        assert STEPS_MD.exists()
        text = STEPS_MD.read_text()
        assert "Deny rule groups" in text, (
            "pipeline-steps.md must include the 'Deny rule groups' section"
        )

    def test_deny_groups_section_names_all_semantic_groups(self):
        """All six semantic capability group names must appear in the generated docs."""
        expected_group_names = [
            "local-git-history-control",
            "remote-git-control",
            "git-configuration-control",
            "repository-policy-enforcement",
            "environment-and-credential-access",
            "external-host-access",
        ]
        text = STEPS_MD.read_text()
        for name in expected_group_names:
            assert name in text, (
                f"pipeline-steps.md must include deny group '{name}'"
            )

    def test_deny_groups_section_states_groups_are_authoritative(self):
        """Coder has no flat deniedTools, so its deny groups are the authoritative list."""
        text = STEPS_MD.read_text()
        assert "authoritative deny list" in text, (
            "pipeline-steps.md must state that coder's deny groups are the "
            "authoritative deny list, since coder declares no separate deniedTools"
        )

    def test_other_agents_retain_narrow_allowlists(self):
        """No other agent must have its extra_allowedTools widened to bare 'Bash'."""
        pipeline = _pipeline()
        for flow in pipeline["flows"].values():
            for step in flow.get("steps", []):
                if step.get("agent") == _CODER_AGENT:
                    continue
                extra = step.get("extra_allowedTools", [])
                assert "Bash" not in extra, (
                    f"{step['agent']} must not have bare 'Bash' in extra_allowedTools; "
                    "only the coder step uses this broad grant"
                )


# ---------------------------------------------------------------------------
# Schema: top-level entitlement_groups and deny_group references are accepted
# ---------------------------------------------------------------------------


def test_coder_references_top_level_semantic_entitlement_groups():
    pipeline = _pipeline()
    catalog = pipeline.get("entitlement_groups", {})
    step = _coder_step()
    refs = step.get("deny_groups", [])
    assert refs
    assert all(isinstance(ref, str) for ref in refs)
    assert all(ref in catalog for ref in refs)


def test_schema_accepts_deny_groups_on_coder_step():
    """The pipeline schema must accept deny_groups as a valid optional step field."""
    import jsonschema

    with SCHEMA_PATH.open() as fh:
        schema = json.load(fh)

    pipeline = _pipeline()
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(pipeline))
    assert not errors, (
        f"pipeline.json with deny_groups failed schema validation: "
        + ", ".join(e.message for e in errors)
    )
