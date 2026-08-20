"""Tests for issue #259 security hardening of agent subprocesses.

CR-01: the Claude agent subprocess must not inherit the orchestrator's full
environment, so orchestrator-only secrets (AI_AGILE_BOT_TOKEN, the GIT_CONFIG_*
git-auth header that embeds GITHUB_TOKEN) cannot be exfiltrated by a
prompt-injected agent reading its own /proc/self/environ.

CR-02: the base agent tool allowlist must not grant broad `gh issue edit *` /
`gh pr edit *`, which would let an injected agent self-approve its gate or fake
a dependency :complete by adding/removing reserved control labels.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
from pipeline_orchestrator import (
    AGENT_ENV_PASSTHROUGH,
    BASE_AGENT_TOOLS,
    WorkItem,
    _build_agent_env,
)


def _work_item(kind="issue", number=259):
    return WorkItem(
        number=number,
        kind=kind,
        title="t",
        labels=set(),
        url="https://example.invalid/259",
    )


# ---------------------------------------------------------------------------
# CR-01: agent env allowlist
# ---------------------------------------------------------------------------

class TestAgentEnvAllowlist:
    def test_passthrough_constant_excludes_orchestrator_secrets(self):
        assert "AI_AGILE_BOT_TOKEN" not in AGENT_ENV_PASSTHROUGH
        assert "GIT_CONFIG_COUNT" not in AGENT_ENV_PASSTHROUGH
        assert "GIT_CONFIG_KEY_0" not in AGENT_ENV_PASSTHROUGH
        assert "GIT_CONFIG_VALUE_0" not in AGENT_ENV_PASSTHROUGH

    def test_passthrough_constant_includes_essentials(self):
        assert "ANTHROPIC_API_KEY" in AGENT_ENV_PASSTHROUGH
        assert "PATH" in AGENT_ENV_PASSTHROUGH
        assert "HOME" in AGENT_ENV_PASSTHROUGH

    def test_build_agent_env_drops_secrets_present_in_source_env(self):
        source_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/agent",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "GH_TOKEN": "gh-agent-token",
            # Orchestrator-only secrets that must NOT leak to the agent:
            "AI_AGILE_BOT_TOKEN": "bot-secret",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
            "GIT_CONFIG_VALUE_0": "Authorization: Basic c2VjcmV0",
        }
        env = _build_agent_env(
            source_env,
            repo="owner/repo",
            work_item=_work_item(),
            agent_session_id="sess-259",
            session_scope="per_issue",
        )
        assert "AI_AGILE_BOT_TOKEN" not in env
        assert "GIT_CONFIG_COUNT" not in env
        assert "GIT_CONFIG_KEY_0" not in env
        assert "GIT_CONFIG_VALUE_0" not in env

    def test_build_agent_env_keeps_agent_essentials(self):
        source_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/agent",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "GH_TOKEN": "gh-agent-token",
            "AI_AGILE_BOT_TOKEN": "bot-secret",
        }
        env = _build_agent_env(
            source_env,
            repo="owner/repo",
            work_item=_work_item(),
            agent_session_id="sess-259",
            session_scope="per_issue",
        )
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-secret"
        assert env["GH_TOKEN"] == "gh-agent-token"
        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/home/agent"

    def test_build_agent_env_sets_context_vars(self):
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(kind="issue", number=259),
            agent_session_id="sess-259",
            session_scope="per_issue",
        )
        assert env["REPO"] == "owner/repo"
        assert env["WORK_ITEM_KIND"] == "issue"
        assert env["WORK_ITEM_NUMBER"] == "259"
        assert env["SESSION_ID"] == "sess-259"
        assert env["SESSION_SCOPE"] == "per_issue"
        assert env["ISSUE_NUMBER"] == "259"
        assert "PR_NUMBER" not in env

    def test_build_agent_env_sets_pr_number_for_pr_work_item(self):
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(kind="pr", number=42),
            agent_session_id="sess-pr-42",
            session_scope="per_issue",
        )
        assert env["PR_NUMBER"] == "42"
        assert "ISSUE_NUMBER" not in env

    def test_build_agent_env_sets_ai_agile_scratch_under_tmp(self):
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(kind="issue", number=321),
            agent_session_id="ais-v1-coder-issue-321",
            session_scope="per_issue",
        )
        assert env["AI_AGILE_SCRATCH"] == "/tmp/ais-v1-coder-issue-321"

    def test_build_agent_env_scratch_path_contains_session_id(self):
        session_id = "ais-v1-01-product-docs-prd-writer-issue-42"
        env = _build_agent_env(
            {"PATH": "/usr/bin"},
            repo="owner/repo",
            work_item=_work_item(kind="issue", number=42),
            agent_session_id=session_id,
            session_scope="per_issue",
        )
        assert env["AI_AGILE_SCRATCH"].startswith("/tmp/")
        assert session_id in env["AI_AGILE_SCRATCH"]


# ---------------------------------------------------------------------------
# CR-02: base tool allowlist must not grant broad label edits
# ---------------------------------------------------------------------------

class TestBaseAgentTools:
    def test_no_gh_pr_edit_grant(self):
        # gh pr edit has no legitimate agent use; removing it blocks the
        # PR-side gate-label self-approval vector (CR-02).
        assert not any(t.startswith("Bash(gh pr edit") for t in BASE_AGENT_TOOLS)

    def test_gh_issue_edit_granted_for_routing_labels(self):
        # gh issue edit stays granted: issue-classifier applies the routing
        # `classification:` label and sizer applies `epic,blocked` at runtime.
        # The residual gate-label self-approval vector is closed orchestrator-side
        # (see BASE_AGENT_TOOLS comment), not via a positive-glob allowlist.
        assert "Bash(gh issue edit *)" in BASE_AGENT_TOOLS
