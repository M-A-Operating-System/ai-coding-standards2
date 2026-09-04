"""Resolve-only mode must return the allowlist a real spawn would get (#356).

`/maos-{agent}-i` prints `--print-prompt`'s `allowed_tools` to a person
working through the step directly (issue #402 -- no enforcement is attempted
in that mode, unlike the retired `/run-agent`/PreToolUse-hook mechanism this
test module originally guarded). A resolve-only list narrower than the real
one still matters: it is the person's only preview of what the same step
would be allowed to do as a real headless subprocess, and `/maos-{agent}`
spawns that subprocess through this exact allowlist -- if the two paths
drift, the preview lies about what the pipeline actually does (MI-3).

`_run_print_prompt` used to build a minimal AgentDef from the agent file's
frontmatter, which dropped `pipeline.json`'s `defaults.extra_allowedTools` and
per-agent `extra_allowedTools`. Since every registered agent's frontmatter
`extra_allowedTools` is empty (pipeline.json is canonical), that was where
essentially every grant lived: 24 tools resolved where the real spawn gets 93.
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

# An agent with substantial pipeline.json grants -- the point is to compare a
# list that would be badly wrong if the merge were skipped, not two short ones.
AGENT = "03_execute/coder"


def _args(**kwargs):
    args = MagicMock()
    args.repo = "test/repo"
    args.issue = 1
    args.kind = None
    args.agent = AGENT
    args.pipeline = PIPELINE
    args.print_prompt = True
    for key, value in kwargs.items():
        setattr(args, key, value)
    return args


def _gh(kind="issue"):
    gh = MagicMock()
    payload = {
        "number": 1,
        "title": "Test work item",
        "labels": [],
        "html_url": "https://github.com/test/repo/issues/1",
    }
    if kind == "pr":
        payload["pull_request"] = {"url": "https://api.github.com/pr/1"}
    gh._get.return_value = payload
    gh.repo = "test/repo"
    return gh


def _resolve_only(capsys, kind="issue", agent=AGENT):
    gh = _gh(kind)
    with patch.object(po, "GitHubClient", return_value=gh), \
         patch.object(po, "_discover_github_token", return_value="t"):
        po._run_print_prompt(_args(agent=agent))
    return json.loads(capsys.readouterr().out)


def _real_spawn_allowlist(agent=AGENT, kind="issue"):
    """What invoke_agent would pass as --allowedTools for the same agent.

    Both paths funnel through _resolve_agent_invocation; the drift was in how
    the AgentDef reaching it was built, so this reproduces the real path's
    construction exactly: load_pipeline, then the same resolve call.
    """
    agents, default_extra_tools = po.load_pipeline(PIPELINE)
    agent_def = po.pipeline_by_name(agents)[agent]
    work_item = po.WorkItem(
        number=1, kind=kind, title="Test work item", labels=set(),
        url="https://github.com/test/repo/issues/1",
    )
    resolved = po._resolve_agent_invocation(
        agent_def, work_item, "test/repo", default_extra_tools=default_extra_tools,
    )
    return resolved.allowed_tools


def test_resolve_only_matches_a_real_spawn_exactly(capsys):
    """The criterion #316 accepted and #328 shipped unmet: byte-identical."""
    assert _resolve_only(capsys)["allowed_tools"] == _real_spawn_allowlist()


def test_the_comparison_is_against_a_substantial_allowlist():
    """A parity test between two short lists proves nothing. Guard the guard:
    if the coder's grants ever shrink to near the pipeline-wide defaults, this
    test's subject is gone and the parity assertion above stops meaning
    anything."""
    _, default_extra_tools = po.load_pipeline(PIPELINE)
    assert len(_real_spawn_allowlist()) > len(default_extra_tools) + 40


def test_pipeline_defaults_are_included(capsys):
    allowed = _resolve_only(capsys)["allowed_tools"]
    for tool in ["Write", "Edit"]:
        assert tool in allowed, f"defaults.extra_allowedTools entry {tool} was dropped"


def test_per_agent_grants_are_included(capsys):
    allowed = _resolve_only(capsys)["allowed_tools"]
    for tool in ["Bash(git log *)", "Bash(rm *)", "Bash(sed *)", "Bash(pytest *)"]:
        assert tool in allowed, f"pipeline.json per-agent grant {tool} was dropped"


def test_an_unregistered_agent_still_resolves(capsys):
    """The agent_def is None fallback in _run_print_prompt handles agents that
    have an agent file but are absent from pipeline.json.  This exercises that
    branch by patching pipeline_by_name to return an empty mapping, which
    forces the lookup to miss regardless of what pipeline.json actually
    contains.  The agent name must round-trip and the pipeline defaults
    (Write, Edit) must still be applied via the frontmatter-only AgentDef."""
    gh = _gh()
    with patch.object(po, "GitHubClient", return_value=gh), \
         patch.object(po, "_discover_github_token", return_value="t"), \
         patch.object(po, "pipeline_by_name", return_value={}):
        po._run_print_prompt(_args(agent="00_ondemand/sizer"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent"] == "00_ondemand/sizer"
    for tool in ["Write", "Edit"]:
        assert tool in payload["allowed_tools"]


# --- Work-item kind (the second half of #356) --------------------------------


def test_a_pr_number_resolves_as_a_pr(capsys):
    """`--print-prompt --issue 360` on a PR number used to default to "issue"
    and export WORK_ITEM_KIND=issue, so the agent read the wrong object with no
    error anywhere. main()'s --issue path already probes; this must agree."""
    payload = _resolve_only(capsys, kind="pr")
    assert payload["env"]["WORK_ITEM_KIND"] == "pr"
    assert payload["env"]["PR_NUMBER"] == "1"
    assert "ISSUE_NUMBER" not in payload["env"]


def test_an_issue_number_still_resolves_as_an_issue(capsys):
    payload = _resolve_only(capsys)
    assert payload["env"]["WORK_ITEM_KIND"] == "issue"
    assert payload["env"]["ISSUE_NUMBER"] == "1"


def test_an_explicit_kind_still_wins(capsys):
    """--kind is an override, not a hint; probing must not overrule it."""
    gh = _gh(kind="pr")
    with patch.object(po, "GitHubClient", return_value=gh), \
         patch.object(po, "_discover_github_token", return_value="t"):
        po._run_print_prompt(_args(kind="issue"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["env"]["WORK_ITEM_KIND"] == "issue"
    assert "PR_NUMBER" not in payload["env"]


def test_a_kind_the_agent_does_not_handle_is_reported(capsys, caplog):
    """The coder runs on issues. Resolving it against a PR is not refused --
    the operator may mean it -- but it must not happen silently."""
    import logging
    with caplog.at_level(logging.WARNING, logger=po.log.name):
        _resolve_only(capsys, kind="pr")
    assert any(
        AGENT in record.getMessage() and "pr" in record.getMessage()
        for record in caplog.records
    ), "resolving an agent against an object kind it does not list must warn"
