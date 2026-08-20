"""Tests for issue #348 -- STD-SEC-022 env allowlists for the five non-agent call sites.

Scenarios traced from docs/features/orchestrator.md:
- Each call site builds env from a named variable list
- An ADR exception requires demonstrated necessity (no ADR needed -- all sites narrowed)
- A narrowed script still works (verified via allowlist completeness)
- The agent path is untouched
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
from pipeline_orchestrator import (
    AGENT_ENV_PASSTHROUGH,
    _build_agent_env,
    _GIT_PLUMBING_ENV_VARS,
    _SCRIPT_AGENT_ENV_VARS,
    _COMMIT_AFTER_ENV_VARS,
    _POST_STEPS_ENV_VARS,
    _DELETE_BRANCH_ENV_VARS,
)

_ALL_SITE_VARS = [
    ("git_plumbing", _GIT_PLUMBING_ENV_VARS),
    ("script_agent", _SCRIPT_AGENT_ENV_VARS),
    ("commit_after", _COMMIT_AFTER_ENV_VARS),
    ("post_steps", _POST_STEPS_ENV_VARS),
    ("delete_branch", _DELETE_BRANCH_ENV_VARS),
]

_POISON_ENV = {
    "PATH": "/usr/bin",
    "HOME": "/root",
    "ANTHROPIC_API_KEY": "sk-ant-secret",
    "AI_AGILE_BOT_TOKEN": "bot-secret",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
    "GIT_CONFIG_VALUE_0": "Authorization: Basic c2VjcmV0",
    "GH_TOKEN": "gh-secret",
    "GITHUB_TOKEN": "github-secret",
    "LANG": "en_US.UTF-8",
    "EXTRA_SECRET": "should-never-appear",
    "AWS_SECRET_ACCESS_KEY": "aws-secret",
}


# ---------------------------------------------------------------------------
# Scenario: Each call site builds env from a named variable list
# ---------------------------------------------------------------------------

class TestEachCallSiteBuildsEnvFromANamedVariableList:
    def test_all_constants_are_tuples_of_strings(self):
        for name, var_set in _ALL_SITE_VARS:
            assert isinstance(var_set, tuple), f"{name}: expected tuple, got {type(var_set)}"
            for v in var_set:
                assert isinstance(v, str), f"{name}: element {v!r} is not a string"

    def test_each_site_has_its_own_distinct_named_constant(self):
        # Each call site must reference a separately-named module-level constant
        # (not a hard-coded inline literal or shared alias), so the five lists
        # are independently revisable. We verify the expected names are importable
        # and are all proper tuples.
        import pipeline.pipeline_orchestrator as _orch
        expected_names = [
            "_GIT_PLUMBING_ENV_VARS",
            "_SCRIPT_AGENT_ENV_VARS",
            "_COMMIT_AFTER_ENV_VARS",
            "_POST_STEPS_ENV_VARS",
            "_DELETE_BRANCH_ENV_VARS",
        ]
        for name in expected_names:
            assert hasattr(_orch, name), f"Module is missing {name}"
            val = getattr(_orch, name)
            assert isinstance(val, tuple), f"{name} must be a tuple, got {type(val)}"

    def test_allowlist_filter_excludes_unlisted_vars(self):
        for name, var_set in _ALL_SITE_VARS:
            result = {k: _POISON_ENV[k] for k in var_set if k in _POISON_ENV}
            assert "EXTRA_SECRET" not in result, f"{name}: EXTRA_SECRET leaked through"
            assert "AWS_SECRET_ACCESS_KEY" not in result, (
                f"{name}: AWS_SECRET_ACCESS_KEY leaked through"
            )
            assert "ANTHROPIC_API_KEY" not in result, (
                f"{name}: ANTHROPIC_API_KEY leaked into non-agent site {name}"
            )

    def test_git_plumbing_excludes_auth_tokens(self):
        result = {k: _POISON_ENV[k] for k in _GIT_PLUMBING_ENV_VARS if k in _POISON_ENV}
        assert "GH_TOKEN" not in result
        assert "GITHUB_TOKEN" not in result
        assert "AI_AGILE_BOT_TOKEN" not in result

    def test_git_plumbing_contains_only_path_and_home(self):
        assert set(_GIT_PLUMBING_ENV_VARS) == {"PATH", "HOME"}

    def test_allowlists_do_not_include_orchestrator_only_secrets(self):
        for name, var_set in _ALL_SITE_VARS:
            var_names = set(var_set)
            assert "GIT_CONFIG_COUNT" not in var_names, (
                f"{name}: GIT_CONFIG_COUNT (git auth header) must not be forwarded"
            )
            assert "GIT_CONFIG_KEY_0" not in var_names, (
                f"{name}: GIT_CONFIG_KEY_0 must not be forwarded"
            )
            assert "GIT_CONFIG_VALUE_0" not in var_names, (
                f"{name}: GIT_CONFIG_VALUE_0 (embedded auth) must not be forwarded"
            )


# ---------------------------------------------------------------------------
# Scenario: A narrowed script still works (allowlist completeness)
# ---------------------------------------------------------------------------

class TestANarrowedScriptStillWorks:
    def test_script_agent_allowlist_includes_gh_auth_vars(self):
        var_names = set(_SCRIPT_AGENT_ENV_VARS)
        assert "GH_TOKEN" in var_names
        assert "GITHUB_TOKEN" in var_names
        assert "PATH" in var_names
        assert "HOME" in var_names

    def test_commit_after_allowlist_includes_bot_token_for_git_auth(self):
        var_names = set(_COMMIT_AFTER_ENV_VARS)
        assert "AI_AGILE_BOT_TOKEN" in var_names
        assert "GH_TOKEN" in var_names
        assert "GITHUB_TOKEN" in var_names
        assert "PATH" in var_names
        assert "HOME" in var_names

    def test_post_steps_allowlist_includes_gh_auth(self):
        var_names = set(_POST_STEPS_ENV_VARS)
        assert "GH_TOKEN" in var_names
        assert "GITHUB_TOKEN" in var_names

    def test_post_steps_excludes_bot_token_not_needed_for_gh_api(self):
        assert "AI_AGILE_BOT_TOKEN" not in set(_POST_STEPS_ENV_VARS)

    def test_delete_branch_excludes_bot_token_not_needed(self):
        assert "AI_AGILE_BOT_TOKEN" not in set(_DELETE_BRANCH_ENV_VARS)

    def test_all_network_sites_include_ca_and_proxy_vars(self):
        ca_and_proxy = {
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "no_proxy",
            "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
        }
        network_sites = [
            ("script_agent", _SCRIPT_AGENT_ENV_VARS),
            ("commit_after", _COMMIT_AFTER_ENV_VARS),
            ("post_steps", _POST_STEPS_ENV_VARS),
            ("delete_branch", _DELETE_BRANCH_ENV_VARS),
        ]
        for name, var_set in network_sites:
            var_names = set(var_set)
            missing = ca_and_proxy - var_names
            assert not missing, (
                f"{name}: missing proxy/CA vars {missing} -- "
                "network-calling scripts need these to work in proxied environments"
            )


# ---------------------------------------------------------------------------
# Scenario: The agent path is untouched
# ---------------------------------------------------------------------------

class TestTheAgentPathIsUntouched:
    def test_agent_env_passthrough_excludes_orchestrator_secrets(self):
        assert "AI_AGILE_BOT_TOKEN" not in AGENT_ENV_PASSTHROUGH
        assert "GIT_CONFIG_COUNT" not in AGENT_ENV_PASSTHROUGH
        assert "GIT_CONFIG_KEY_0" not in AGENT_ENV_PASSTHROUGH
        assert "GIT_CONFIG_VALUE_0" not in AGENT_ENV_PASSTHROUGH

    def test_agent_env_passthrough_includes_anthropic_key(self):
        assert "ANTHROPIC_API_KEY" in AGENT_ENV_PASSTHROUGH

    def test_build_agent_env_still_drops_orchestrator_secrets(self):
        env = _build_agent_env(
            _POISON_ENV,
            repo="owner/repo",
            work_item=type("W", (), {
                "number": 348, "kind": "issue", "title": "t",
                "labels": set(), "url": "https://example.invalid/348",
            })(),
            agent_session_id="sess-348",
            session_scope="per_issue",
        )
        assert "AI_AGILE_BOT_TOKEN" not in env
        assert "GIT_CONFIG_COUNT" not in env
        assert "EXTRA_SECRET" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env

    def test_agent_env_passthrough_includes_anthropic_key_for_headless_runs(self):
        # ANTHROPIC_API_KEY must be in the passthrough list so CI/headless runs
        # can authenticate agents. The probe-based removal is a separate feature
        # (tested in test_agent_env_hardening.py); this test verifies only that
        # the allowlist constant was not stripped of the key.
        assert "ANTHROPIC_API_KEY" in AGENT_ENV_PASSTHROUGH

    def test_non_agent_allowlists_do_not_include_anthropic_key(self):
        for name, var_set in _ALL_SITE_VARS:
            assert "ANTHROPIC_API_KEY" not in var_set, (
                f"{name}: ANTHROPIC_API_KEY must not appear in a non-agent env allowlist"
            )


# ---------------------------------------------------------------------------
# Scenario: the bot PAT reaches only the script steps that consume it
# ---------------------------------------------------------------------------

class TestBotTokenIsScopedToPrWritingScripts:
    """AI_AGILE_BOT_TOKEN is a classic PAT with repo+workflow scopes -- the
    broadest credential the orchestrator holds. Only the script steps that
    demonstrably reference it should receive it."""

    from pipeline_orchestrator import _script_step_env_vars as _resolve

    def test_pr_writing_scripts_receive_the_bot_token(self):
        for script in ("create-pr.sh", "create-docs-pr.sh", "merge-docs-pr.sh"):
            got = type(self)._resolve(f".github/scripts/{script}")
            assert "AI_AGILE_BOT_TOKEN" in got, (
                f"{script} opens or merges a PR and needs the bot PAT"
            )

    def test_ci_gate_does_not_receive_the_bot_token(self):
        """ci-gate.sh only reads check runs; it never references the variable."""
        got = type(self)._resolve(".github/scripts/ci-gate.sh")
        assert "AI_AGILE_BOT_TOKEN" not in got

    def test_unknown_or_missing_script_does_not_receive_the_bot_token(self):
        """Fail closed: a step whose script is unrecognised gets the base list."""
        for path in (None, "", ".github/scripts/some-future-step.sh"):
            got = type(self)._resolve(path)
            assert "AI_AGILE_BOT_TOKEN" not in got, f"{path!r} should not be granted the PAT"

    def test_matching_is_on_file_name_not_full_path(self):
        """A repo that relocates the scripts directory must still resolve."""
        got = type(self)._resolve("vendor/ai-coding-standards2/.github/scripts/create-pr.sh")
        assert "AI_AGILE_BOT_TOKEN" in got

    def test_base_list_is_otherwise_unchanged(self):
        base = type(self)._resolve(".github/scripts/ci-gate.sh")
        assert set(base) == set(_SCRIPT_AGENT_ENV_VARS)
        granted = type(self)._resolve(".github/scripts/create-pr.sh")
        assert set(granted) - set(base) == {"AI_AGILE_BOT_TOKEN"}, (
            "the split must add exactly the bot token, nothing else"
        )

    def test_every_script_step_in_pipeline_json_is_classified_deliberately(self):
        """Any new script step defaults to no bot token -- and if it needs one,
        this test is where that decision becomes visible."""
        import json
        from pathlib import Path as _P
        spec = json.loads((_P(__file__).parent.parent / "pipeline" / "pipeline.json").read_text())
        script_steps = [s for s in spec["pipeline"] if s.get("type") == "script"]
        assert script_steps, "expected at least one script-type step"
        granted = {
            s["agent"] for s in script_steps
            if "AI_AGILE_BOT_TOKEN" in type(self)._resolve(s.get("script"))
        }
        assert granted == {
            "01_product_docs/create-pr",
            "01_product_docs/create-docs-pr",
            "01_product_docs/merge-docs-pr",
        }, f"unexpected set of steps granted the bot PAT: {granted}"
