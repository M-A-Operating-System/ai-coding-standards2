"""Tests for issue #694: patch-tag pipeline step and push-patch-tag.sh.

Covers:
- Scenario R1 (pipeline shape): patch-tag flow is in pipeline.json with an
  event: pull_request.closed trigger, type script, stopOnLevel 3,
  expected_effect.commits false.
- Scenario R2 (dispatch isolation): the step is not reachable by the per-item
  work loop, but is reachable with --manual-override.
- Scenario R3 (idempotency): when HEAD of main is already tagged with a vX.Y.Z
  tag, the script outputs AI_AGILE_STATUS: complete and does not create a new tag.
- Scenario R4 (no prior tags): when no vX.Y.Z tags exist, the script starts at
  v2.0.0 and pushes v2.0.1.
- Scenario R5 (PATCH bump): when prior tags exist, the script bumps the PATCH
  component of the highest existing tag.
"""
import json
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

import pipeline_orchestrator as orch
from pipeline_orchestrator import AgentDef, WorkItem, load_pipeline

_PIPELINE_PATH = Path(__file__).parent.parent / "pipeline" / "pipeline.json"
_SCRIPT = Path(__file__).parent.parent / "scripts" / "push-patch-tag.sh"

_HEAD_SHA = "aabbccdd" * 5  # 40-char fake SHA

# gh api ... --jq '.object.sha' returns the bare SHA string (no JSON wrapper).
_HEAD_REF_JQ = _HEAD_SHA

# A tag pointing at HEAD (for the idempotency scenario).
# The /repos/{repo}/tags endpoint (--paginate --slurp, no --jq) returns full JSON.
_TAGS_HEAD_TAGGED = json.dumps([[{
    "name": "v2.3.5",
    "commit": {"sha": _HEAD_SHA},
}]])

# Tags pointing at a different commit (HEAD is not yet tagged)
_OTHER_SHA = "11223344" * 5
_TAGS_NO_HEAD = json.dumps([[{
    "name": "v2.3.5",
    "commit": {"sha": _OTHER_SHA},
}]])

# No tags at all
_TAGS_EMPTY = json.dumps([[]])

# gh api repos/.../git/tags --method POST ... --jq '.sha' returns the bare SHA.
_TAG_OBJ_SHA = "deadbeef" * 5
_TAG_OBJ_RESP_JQ = _TAG_OBJ_SHA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_gh(tmp_path, responses: dict) -> Path:
    """Write a fake gh binary that returns canned responses for each path fragment.

    responses: {path_fragment: str|None}.
    None simulates a gh error (non-zero exit, no output).
    Unmatched calls return '[]' with exit 0.

    The real `gh api --jq EXPR` returns the extracted value as plain text.
    Pass the already-extracted value as the response body so the fake gh
    produces the same output the script expects.
    """
    lines = ["#!/usr/bin/env bash", "ARGS=\"$*\""]
    for fragment, body in responses.items():
        safe_frag = fragment.replace("'", "'\\''")
        lines.append(f"if [[ \"$ARGS\" == *'{safe_frag}'* ]]; then")
        if body is None:
            lines.append("  exit 1")
        else:
            safe_body = body.replace("'", "'\\''").replace("\n", "\\n")
            lines.append(f"  printf '%s' '{safe_body}'")
            lines.append("  exit 0")
        lines.append("fi")
    lines.append("printf '%s' '[]'")
    lines.append("exit 0")
    script = tmp_path / "gh"
    script.write_text("\n".join(lines) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return tmp_path


def _run_script(fake_gh_dir: Path, env_extra: dict = None) -> subprocess.CompletedProcess:
    env = {
        "PATH": f"{fake_gh_dir}:{os.environ['PATH']}",
        "REPO": "org/repo",
        "GH_TOKEN": "fake-token",
        "HOME": str(fake_gh_dir),
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Scenario R1: pipeline shape
# ---------------------------------------------------------------------------

class TestPatchTagPipelineShape:
    """The patch-tag flow must be registered in pipeline.json with the right shape."""

    def _load_patch_tag_step(self):
        agents, _ = load_pipeline(_PIPELINE_PATH)
        matches = [a for a in agents if a.flow == "patch-tag"]
        assert matches, "patch-tag flow not found in pipeline.json"
        assert len(matches) == 1, "expected exactly one step in patch-tag flow"
        return matches[0]

    def test_patch_tag_flow_exists(self):
        """Scenario R1: patch-tag flow is present in pipeline.json."""
        self._load_patch_tag_step()

    def test_patch_tag_has_event_trigger(self):
        """Scenario R1: flow trigger must be pull_request.closed event."""
        step = self._load_patch_tag_step()
        assert step.flow_event == "pull_request.closed", (
            f"patch-tag flow must declare event trigger 'pull_request.closed', "
            f"got flow_event={step.flow_event!r}"
        )

    def test_patch_tag_has_no_schedule_trigger(self):
        """patch-tag is event-triggered, not schedule-triggered."""
        step = self._load_patch_tag_step()
        assert step.flow_schedule is None, (
            "patch-tag flow must not have a schedule trigger"
        )

    def test_patch_tag_is_script_type(self):
        """Scenario R1: step must be type 'script'."""
        step = self._load_patch_tag_step()
        assert step.step_type == "script", (
            f"patch-tag step must be type 'script', got {step.step_type!r}"
        )

    def test_patch_tag_script_path_exists(self):
        """The declared script must exist on disk."""
        step = self._load_patch_tag_step()
        script_file = Path(__file__).parent.parent / step.script_path
        assert script_file.exists(), (
            f"patch-tag script {step.script_path!r} not found at {script_file}"
        )

    def test_patch_tag_stop_on_level_3(self):
        """Scenario R1: step must declare stopOnLevel 3."""
        step = self._load_patch_tag_step()
        assert step.stop_on_level == 3, (
            f"patch-tag step must have stopOnLevel 3, got {step.stop_on_level!r}"
        )

    def test_patch_tag_commits_false(self):
        """Scenario R1: expected_effect.commits must be false."""
        step = self._load_patch_tag_step()
        assert step.expected_effect.get("commits") is False, (
            f"patch-tag expected_effect.commits must be false, "
            f"got {step.expected_effect!r}"
        )

    def test_patch_tag_trigger_event_is_pull_request_closed(self):
        """The step-level trigger must declare event: pull_request.closed."""
        step = self._load_patch_tag_step()
        assert step.trigger.get("event") == "pull_request.closed", (
            f"patch-tag step trigger must be {{event: pull_request.closed}}, "
            f"got {step.trigger!r}"
        )

    def test_patch_tag_trigger_has_no_label(self):
        """patch-tag is not triggered by a label."""
        step = self._load_patch_tag_step()
        assert step.trigger.get("label") is None, (
            "patch-tag step must not have a label trigger"
        )


# ---------------------------------------------------------------------------
# Scenario R2: dispatch isolation
# ---------------------------------------------------------------------------

class TestPatchTagDispatchIsolation:
    """patch-tag must not be reachable by the per-item work loop."""

    def _load_patch_tag_step(self):
        agents, _ = load_pipeline(_PIPELINE_PATH)
        matches = [a for a in agents if a.flow == "patch-tag"]
        assert matches, "patch-tag flow not found in pipeline.json"
        return matches[0]

    def test_patch_tag_not_reachable_by_work_item_loop(self):
        """Scenario R2: _should_run must return False for any work item."""
        step = self._load_patch_tag_step()
        item = WorkItem(number=1, kind="issue", title="t", labels=set(), url="u")
        assert orch._should_run(
            step, item, item.labels, {}, None, gh=MagicMock(), repo="org/repo"
        ) is False, "patch-tag must never be triggered by a work item"

    def test_patch_tag_reachable_with_manual_override(self):
        """Scenario R2: --manual-override must allow the step to run."""
        step = self._load_patch_tag_step()
        item = WorkItem(number=1, kind="issue", title="t", labels=set(), url="u")
        assert orch._should_run(
            step, item, item.labels, {}, None, gh=MagicMock(), repo="org/repo",
            manual_override=True,
        ) is True, "patch-tag must be reachable with --manual-override"

    def test_patch_tag_in_pr_merge_flows(self):
        """The step must be collected by _pr_merge_flows."""
        agents, _ = load_pipeline(_PIPELINE_PATH)
        flows = orch._pr_merge_flows(agents)
        assert "patch-tag" in flows, (
            "patch-tag flow must appear in _pr_merge_flows output"
        )

    def test_patch_tag_not_in_scheduled_flows(self):
        """patch-tag must not appear in _scheduled_flows (it has no cron)."""
        agents, _ = load_pipeline(_PIPELINE_PATH)
        flows = orch._scheduled_flows(agents)
        assert "patch-tag" not in flows, (
            "patch-tag flow must not appear in _scheduled_flows output"
        )


# ---------------------------------------------------------------------------
# Scenario R3: idempotency guard
# ---------------------------------------------------------------------------

class TestPatchTagIdempotency:
    """When HEAD of main is already tagged with a vX.Y.Z tag, skip and report complete."""

    def test_head_already_tagged_outputs_complete(self, tmp_path):
        """Scenario R3: AI_AGILE_STATUS: complete when HEAD already tagged."""
        _fake_gh(tmp_path, {
            "git/refs/heads/main": _HEAD_REF_JQ,
            "repos/org/repo/tags": _TAGS_HEAD_TAGGED,
        })
        result = _run_script(tmp_path)
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: complete" in result.stdout

    def test_head_already_tagged_does_not_create_tag(self, tmp_path):
        """Scenario R3: script must not call git/tags POST when HEAD is tagged."""
        # Track whether a POST to git/tags was attempted
        # We do this by checking that the fake gh never reached that path.
        # Inject a marker into the fake gh to detect POST calls.
        lines = [
            "#!/usr/bin/env bash",
            "ARGS=\"$*\"",
            # Return HEAD ref (simulate --jq '.object.sha' output: bare SHA)
            "if [[ \"$ARGS\" == *'git/refs/heads/main'* ]]; then",
            f"  printf '%s' '{_HEAD_REF_JQ}'",
            "  exit 0",
            "fi",
            # Return tags with HEAD already tagged
            "if [[ \"$ARGS\" == *'repos/org/repo/tags'* ]]; then",
            f"  printf '%s' '{_TAGS_HEAD_TAGGED}'",
            "  exit 0",
            "fi",
            # Fail loudly if a POST to git/tags is attempted
            "if [[ \"$ARGS\" == *'git/tags'* && \"$ARGS\" == *'POST'* ]]; then",
            "  echo 'UNEXPECTED_TAG_CREATE' >&2",
            "  exit 1",
            "fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        (tmp_path / "gh").write_text("\n".join(lines) + "\n")
        (tmp_path / "gh").chmod((tmp_path / "gh").stat().st_mode | stat.S_IEXEC)
        result = _run_script(tmp_path)
        assert result.returncode == 0
        assert "UNEXPECTED_TAG_CREATE" not in result.stderr
        assert "AI_AGILE_STATUS: complete" in result.stdout


# ---------------------------------------------------------------------------
# Scenario R4: no prior tags -> starts at v2.0.1
# ---------------------------------------------------------------------------

class TestPatchTagNoPriorTags:
    """When no vX.Y.Z tags exist, the script should start at v2.0.1."""

    def test_no_prior_tags_pushes_v2_0_1(self, tmp_path):
        """Scenario R4: no tags -> next tag is v2.0.1 (baseline is v2.0.0)."""
        calls = []

        lines = [
            "#!/usr/bin/env bash",
            "ARGS=\"$*\"",
            "if [[ \"$ARGS\" == *'git/refs/heads/main'* ]]; then",
            f"  printf '%s' '{_HEAD_REF_JQ}'",
            "  exit 0",
            "fi",
            # Empty tags list
            "if [[ \"$ARGS\" == *'repos/org/repo/tags'* ]]; then",
            f"  printf '%s' '{_TAGS_EMPTY}'",
            "  exit 0",
            "fi",
            # Tag object creation (simulate --jq '.sha' output: bare SHA)
            "if [[ \"$ARGS\" == *'git/tags'* ]]; then",
            f"  printf '%s' '{_TAG_OBJ_RESP_JQ}'",
            "  exit 0",
            "fi",
            # Ref creation -- record the tag name in a marker file
            "if [[ \"$ARGS\" == *'git/refs'* && \"$ARGS\" == *'POST'* ]]; then",
            f"  echo \"$ARGS\" >> {tmp_path}/ref_calls.txt",
            "  exit 0",
            "fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        (tmp_path / "gh").write_text("\n".join(lines) + "\n")
        (tmp_path / "gh").chmod((tmp_path / "gh").stat().st_mode | stat.S_IEXEC)

        result = _run_script(tmp_path)
        assert result.returncode == 0, f"script failed: {result.stderr}"
        assert "AI_AGILE_STATUS: complete" in result.stdout

        ref_calls = (tmp_path / "ref_calls.txt").read_text()
        assert "v2.0.1" in ref_calls, (
            f"expected v2.0.1 to be pushed; ref creation args: {ref_calls}"
        )

    def test_no_prior_tags_next_tag_logged(self, tmp_path):
        """Scenario R4: script must log the next PATCH tag to stderr."""
        lines = [
            "#!/usr/bin/env bash",
            "ARGS=\"$*\"",
            "if [[ \"$ARGS\" == *'git/refs/heads/main'* ]]; then",
            f"  printf '%s' '{_HEAD_REF_JQ}'",
            "  exit 0",
            "fi",
            "if [[ \"$ARGS\" == *'repos/org/repo/tags'* ]]; then",
            f"  printf '%s' '{_TAGS_EMPTY}'",
            "  exit 0",
            "fi",
            "if [[ \"$ARGS\" == *'git/tags'* ]]; then",
            f"  printf '%s' '{_TAG_OBJ_RESP_JQ}'",
            "  exit 0",
            "fi",
            "exit 0",
        ]
        (tmp_path / "gh").write_text("\n".join(lines) + "\n")
        (tmp_path / "gh").chmod((tmp_path / "gh").stat().st_mode | stat.S_IEXEC)

        result = _run_script(tmp_path)
        assert "v2.0.1" in result.stderr, (
            f"script should log 'v2.0.1' to stderr; got: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Scenario R5: prior tags exist -> bump PATCH
# ---------------------------------------------------------------------------

class TestPatchTagBump:
    """When vX.Y.Z tags exist, the script bumps the PATCH of the highest one."""

    def _make_tags_json(self, tag_names):
        """Build a fake --paginate --slurp tags response."""
        tags = [{"name": n, "commit": {"sha": _OTHER_SHA}} for n in tag_names]
        return json.dumps([tags])

    def _run_with_tags(self, tmp_path, tag_names):
        tags_json = self._make_tags_json(tag_names)
        lines = [
            "#!/usr/bin/env bash",
            "ARGS=\"$*\"",
            "if [[ \"$ARGS\" == *'git/refs/heads/main'* ]]; then",
            f"  printf '%s' '{_HEAD_REF_JQ}'",
            "  exit 0",
            "fi",
            "if [[ \"$ARGS\" == *'repos/org/repo/tags'* ]]; then",
            f"  printf '%s' '{tags_json.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'",
            "  exit 0",
            "fi",
            # Tag object creation (simulate --jq '.sha' output: bare SHA)
            "if [[ \"$ARGS\" == *'git/tags'* ]]; then",
            f"  printf '%s' '{_TAG_OBJ_RESP_JQ}'",
            "  exit 0",
            "fi",
            "if [[ \"$ARGS\" == *'git/refs'* && \"$ARGS\" == *'POST'* ]]; then",
            f"  echo \"$ARGS\" >> {tmp_path}/ref_calls.txt",
            "  exit 0",
            "fi",
            "printf '%s' '[]'",
            "exit 0",
        ]
        (tmp_path / "gh").write_text("\n".join(lines) + "\n")
        (tmp_path / "gh").chmod((tmp_path / "gh").stat().st_mode | stat.S_IEXEC)
        return _run_script(tmp_path)

    def test_bumps_patch_from_highest_tag(self, tmp_path):
        """Scenario R5: v2.3.5 (highest) -> push v2.3.6."""
        result = self._run_with_tags(tmp_path, ["v2.1.0", "v2.3.5", "v2.2.0"])
        assert result.returncode == 0, f"script failed: {result.stderr}"
        assert "AI_AGILE_STATUS: complete" in result.stdout
        ref_calls = (tmp_path / "ref_calls.txt").read_text()
        assert "v2.3.6" in ref_calls, (
            f"expected v2.3.6 to be pushed; got: {ref_calls}"
        )

    def test_does_not_bump_minor_or_major(self, tmp_path):
        """Scenario R5: only the PATCH component is incremented."""
        result = self._run_with_tags(tmp_path, ["v3.1.2"])
        assert result.returncode == 0, f"script failed: {result.stderr}"
        ref_calls = (tmp_path / "ref_calls.txt").read_text()
        # Must be v3.1.3, not v3.2.0 or v4.0.0
        assert "v3.1.3" in ref_calls, (
            f"expected v3.1.3 to be pushed; got: {ref_calls}"
        )
        assert "v3.2.0" not in ref_calls
        assert "v4.0.0" not in ref_calls

    def test_handles_single_tag(self, tmp_path):
        """Scenario R5: single tag v1.0.0 -> push v1.0.1."""
        result = self._run_with_tags(tmp_path, ["v1.0.0"])
        assert result.returncode == 0, f"script failed: {result.stderr}"
        ref_calls = (tmp_path / "ref_calls.txt").read_text()
        assert "v1.0.1" in ref_calls, (
            f"expected v1.0.1 to be pushed; got: {ref_calls}"
        )

    def test_uses_highest_version_not_latest_by_date(self, tmp_path):
        """Scenario R5: tags in arbitrary order -> highest semver wins."""
        # v2.0.9 is listed first but v2.1.0 is higher
        result = self._run_with_tags(tmp_path, ["v2.0.9", "v2.1.0", "v1.9.9"])
        assert result.returncode == 0, f"script failed: {result.stderr}"
        ref_calls = (tmp_path / "ref_calls.txt").read_text()
        assert "v2.1.1" in ref_calls, (
            f"expected v2.1.1 (highest=v2.1.0); got: {ref_calls}"
        )


# ---------------------------------------------------------------------------
# Error / blocked scenarios
# ---------------------------------------------------------------------------

class TestPatchTagBlocked:
    """Script must output AI_AGILE_STATUS: blocked on failure, not crash."""

    def test_no_gh_token_outputs_blocked(self, tmp_path):
        """Missing token -> AI_AGILE_STATUS: blocked."""
        lines = ["#!/usr/bin/env bash", "exit 0"]
        (tmp_path / "gh").write_text("\n".join(lines) + "\n")
        (tmp_path / "gh").chmod((tmp_path / "gh").stat().st_mode | stat.S_IEXEC)

        env = {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "REPO": "org/repo",
            "HOME": str(tmp_path),
        }
        result = subprocess.run(
            ["bash", str(_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: blocked" in result.stdout

    def test_head_sha_failure_outputs_blocked(self, tmp_path):
        """When HEAD SHA cannot be fetched, output AI_AGILE_STATUS: blocked."""
        lines = [
            "#!/usr/bin/env bash",
            "ARGS=\"$*\"",
            # Fail on HEAD ref fetch
            "if [[ \"$ARGS\" == *'git/refs/heads/main'* ]]; then",
            "  exit 1",
            "fi",
            "exit 0",
        ]
        (tmp_path / "gh").write_text("\n".join(lines) + "\n")
        (tmp_path / "gh").chmod((tmp_path / "gh").stat().st_mode | stat.S_IEXEC)

        result = _run_script(tmp_path)
        assert result.returncode == 0
        assert "AI_AGILE_STATUS: blocked" in result.stdout
