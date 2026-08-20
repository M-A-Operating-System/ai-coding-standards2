#!/usr/bin/env python3
"""
pipeline_orchestrator.py

Reads pipeline.json and orchestrates agent execution  by inspecting GitHub
issue and PR labels of the form:

    {agent-name}:complete     — agent finished successfully
    {agent-name}:wip          — agent is currently running
    {agent-name}:review       — agent completed work and requests formal human
                                review/approval; remove label once approved
    {agent-name}:blocked      — agent cannot proceed (ambiguous spec, missing
                                data, conflict); remove label once resolved
    {agent-name}:failed       — agent exited with an error
    {agent-name}:skipped      — agent was bypassed by a human

For each open issue or PR, the orchestrator:
  1. Reads current labels to determine which agents have completed.
  2. Identifies agents whose dependencies are all complete (including any
     required human gate labels).
  3. Triggers eligible agents via the Claude CLI, applying {agent-name}:wip.
  4. Skips agents that are complete, wip, review, blocked, failed, or
     skipped, or whose dependencies are unmet.
  5. On blocked: posts a comment requesting human intervention and halts.
  6. On review: posts a comment requesting formal approval and waits for
     the label to be removed before the pipeline advances.

Usage:
    python pipeline_orchestrator.py [--repo OWNER/REPO] [--issue N] [--dry-run]

Requirements:
    pip install requests
    gh CLI authenticated
    ANTHROPIC_API_KEY set in environment (for agent execution; in CI
        this comes from a secret on the consuming repo, not this repo)
    GITHUB_TOKEN set in environment (or gh CLI authenticated)
"""

import argparse
import base64
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Mapping, Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("orchestrator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIPELINE_PATH = Path(__file__).parent / "pipeline.json"
STATUS_COMPLETE    = "complete"
STATUS_WIP         = "wip"
STATUS_REVIEW      = "review"
STATUS_BLOCKED     = "blocked"
STATUS_FAILED      = "failed"
STATUS_SKIPPED     = "skipped"
STATUS_REQUESTED   = "requested"

# Alias kept for internal use
STATUS_IN_PROGRESS = STATUS_WIP

ALL_STATUSES: list[str] = [
    STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED,   # terminal — highest priority
    STATUS_REVIEW, STATUS_BLOCKED,                     # halt
    STATUS_WIP,                                        # running
    STATUS_REQUESTED,                                  # manual trigger
]

# Statuses where the orchestrator takes no further action on this agent.
# review and blocked halt the pipeline but are NOT terminal — a human
# removes the label to resume. failed and skipped are terminal.
HALT_STATUSES    = {STATUS_REVIEW, STATUS_BLOCKED}
TERMINAL_STATUSES = {STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED}

# Label applied by the orchestrator when the pr-reviewer APPROVE path detects
# unresolved human REQUEST_CHANGES reviews and triggers a free coder re-invoke.
# Serves two purposes: (1) signals Mode B to the coder so it addresses human
# feedback, and (2) guards against repeated free re-invokes (the edge-case check
# in process_work_item skips a second free cycle when this label is present).
HUMAN_REVIEW_PENDING_LABEL = "human-review-pending"

STATUSES_JSON = Path(__file__).parent / "statuses.json"

# Submodule root — the directory containing this repo's .github/ and
# pipeline/. Always derived from __file__ so it reliably points at the
# submodule regardless of where the consuming repo mounts it.
# Do NOT derive from AI_AGILE_ROOT: that env var now points at the
# consuming repo root (where standards/ and .claude/ live after sync),
# which is a different directory when installed as a submodule.
SUBMODULE_ROOT = Path(__file__).resolve().parent.parent

def load_statuses() -> tuple[list[dict], list[dict], list[str]]:
    """Load status, standalone-label, and priority-ordering definitions from statuses.json."""
    if not STATUSES_JSON.exists():
        log.error("statuses.json not found at %s — cannot start", STATUSES_JSON)
        sys.exit(1)
    try:
        with open(STATUSES_JSON) as f:
            data = json.load(f)
        return data["statuses"], data.get("standalone_labels", []), data.get("priority_ordering", [])
    except (KeyError, json.JSONDecodeError) as e:
        log.error("statuses.json is malformed: %s", e)
        sys.exit(1)

STATUSES, STANDALONE_LABELS, PRIORITY_LABEL_ORDERING = load_statuses()
LABEL_COLOURS = {s["status"]: s["colour"] for s in STATUSES}
# Standalone labels (no {agent}:{suffix} pattern) keyed by full label name.
STANDALONE_LABEL_COLOURS = {sl["label"]: sl["colour"] for sl in STANDALONE_LABELS}

# Maximum wall-clock time for a single script invocation.
SCRIPT_TIMEOUT_SECONDS = 300

# Maximum agent instances launched across ALL agent types in a single tick.
# Prevents unbounded resource consumption when many issues become eligible
# simultaneously. Per-agent max_concurrent values may permit more in total,
# but this aggregate cap is the backstop.
PIPELINE_MAX_CONCURRENT = 20

# Maximum wall-clock time for a single agent invocation.
AGENT_TIMEOUT_SECONDS = 1800

# Controls stderr verbosity for the invoke_agent stdout read loop.
# False (default): only result-type stream-json events are forwarded.
# True (--verbose): all non-system events are forwarded.
# Set once in main() after arg parsing; non-JSON lines are always forwarded.
_VERBOSE: bool = False

# True when the orchestrator was invoked with --headless (the scheduled/CI path).
# Set once in main() after arg parsing; read by _make_audit_event to populate actor.
_HEADLESS: bool = False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AgentDef:
    agent: str
    phase: str
    objects: list[str]
    trigger: dict
    dependencies: list[str]
    human_gate_after: bool
    human_gate_label: Optional[str]
    description: str
    step_type: str = "agent"           # "agent" | "script"
    script_path: Optional[str] = None  # repo-relative path to script when step_type == "script"
    max_retries: int = 0               # how many times to re-invoke after :failed before giving up
    session_scope: str = "per_issue"   # "per_issue" | "global"
    session_id_pattern: Optional[str] = None  # None → use built-in default for scope
    post_steps: list = field(default_factory=list)  # repo-relative script paths run after :complete
    review_gate: bool = False             # True only for the agent that gates human review (pr-reviewer); controls free-reinvoke on unresolved human REQUEST_CHANGES
    commit_after: bool = False            # True when git_ops.commit_after is true; drives branch checkout + commit-agent-work.sh
    branch_suffix: str = ""               # appended to issue-{N} for the commit_after checkout (e.g. "-docs" -> issue-{N}-docs); "" means the default code branch (two-phase design->build, issue #247)
    exclude_classifications: list = field(default_factory=list)  # skip if issue classification matches
    exclude_labels: list = field(default_factory=list)           # skip if any of these labels is on the work item
    review_loop: Optional[dict] = None  # {"re_invoke": str, "max_cycles": int, "also_clear": [...]} — auto-retry on :review
    max_concurrent: int = 1             # max concurrent instances across work items; null/absent in pipeline.json defaults to 1
    script_timeout_seconds: int = SCRIPT_TIMEOUT_SECONDS  # override default timeout for script-type steps
    auto_approve_on_complete: bool = False  # if True, orchestrator auto-applies human_gate_label when agent emits :complete
    self_gates: bool = False  # if True, the agent's own AI_AGILE_STATUS (review vs complete) decides whether the gate fires -- :complete is NOT force-overridden to :review. human_gate_after/human_gate_label still apply for promotion when the agent itself emits :review.
    extra_allowedTools: list[str] = field(default_factory=list)  # per-agent tools from pipeline.json; merged with defaults and frontmatter

    @property
    def label_key(self) -> str:
        """Short name used in GitHub labels — strips the phase/ prefix."""
        return self.agent.rsplit("/", 1)[-1]

    @property
    def complete_label(self) -> str:
        return f"{self.label_key}:{STATUS_COMPLETE}"

    @property
    def in_progress_label(self) -> str:
        return f"{self.label_key}:{STATUS_IN_PROGRESS}"

    @property
    def failed_label(self) -> str:
        return f"{self.label_key}:{STATUS_FAILED}"

    @property
    def review_label(self) -> str:
        return f"{self.label_key}:{STATUS_REVIEW}"

    @property
    def blocked_label(self) -> str:
        return f"{self.label_key}:{STATUS_BLOCKED}"

    @property
    def skipped_label(self) -> str:
        return f"{self.label_key}:{STATUS_SKIPPED}"

    def status_label(self, status: str) -> str:
        return f"{self.label_key}:{status}"


@dataclass
class WorkItem:
    """Represents an open GitHub issue or PR."""
    number: int
    kind: str          # "issue" or "pr"
    title: str
    labels: set[str]
    url: str
    is_merged: bool = False
    is_closed: bool = False


@dataclass
class AgentRunResult:
    """Outcome of one invoke_agent call.

    success      — True if the agent subprocess exited 0.
    returncode   — The subprocess return code (None if not run).
    captured_tail — The tail of the agent's text output (extracted from the
                    stream-json event stream), capped so it can fit in a
                    GitHub comment. Empty when the agent didn't run
                    (dry-run, missing prompt file).
    rate_limited — True if the failure was an Anthropic rate-limit
                    error and the orchestrator wrote the pause marker.
                    Caller should NOT apply :failed in this case.
    input_tokens  — Total input tokens for the run, extracted from the
                    stream-json result event. None if unavailable.
    output_tokens — Total output tokens for the run, extracted from the
                    stream-json result event. None if unavailable.
    init_event   — Raw system/init event dict captured from the stream.
                    None when the agent did not emit an init event.
    result_event — Raw result event dict captured from the stream.
                    None when the agent did not emit a result event.
    retry_count  — Number of system/api_retry events observed during the run.
    retry_errors — Error category strings from each api_retry event.
    """
    success: bool
    returncode: Optional[int] = None
    captured_tail: str = ""
    rate_limited: bool = False
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    init_event: Optional[dict] = None
    result_event: Optional[dict] = None
    retry_count: int = 0
    retry_errors: list = field(default_factory=list)


@dataclass
class ConcurrencyState:
    """Mutable concurrency accounting for one orchestrator tick.

    running_counts maps each agent label_key to the number of work items
    currently carrying that agent's :wip label — initialised from work_items
    fetched at the start of the tick, then incremented as agents are launched
    within the tick. tick_launch_count tracks the total agents launched in this
    tick against the pipeline-wide aggregate ceiling (PIPELINE_MAX_CONCURRENT).
    """
    running_counts: dict  # label_key → int
    tick_launch_count: int = 0


# ---------------------------------------------------------------------------
# Pipeline loader
# ---------------------------------------------------------------------------

def _coerce_tools(val: object) -> list[str]:
    """Coerce an extra_allowedTools value to a list of strings.

    Accepts a JSON array (list), a comma-separated string (same format as
    defaults.extra_allowedTools), or None/missing (returns []).
    Raises TypeError for any other type so pipeline.json errors surface early.
    """
    if val is None or val == []:
        return []
    if isinstance(val, str):
        return [t.strip() for t in val.split(",") if t.strip()]
    if isinstance(val, list):
        for t in val:
            if not isinstance(t, str):
                raise TypeError(
                    f"extra_allowedTools list elements must be strings, got {type(t).__name__}: {t!r}"
                )
        return [t.strip() for t in val if t.strip()]
    raise TypeError(f"extra_allowedTools must be a list or comma-separated string, got {type(val).__name__}")


def load_pipeline(path: Path) -> tuple[list[AgentDef], list[str]]:
    """Parse pipeline.json once and return (agents, default_extra_tools).

    default_extra_tools comes from defaults.extra_allowedTools and is
    prepended to every agent's own extra_allowedTools at invocation time.
    """
    entry: dict = {}  # sentinel so the except block can report agent name
    try:
        with open(path) as f:
            raw = json.load(f)

        agents = []
        for entry in raw["pipeline"]:
            agents.append(AgentDef(
                agent=entry["agent"],
                phase=entry["phase"],
                objects=entry["object"],
                trigger=entry["trigger"],
                dependencies=entry.get("dependencies", []),
                human_gate_after=entry.get("human_gate_after", False),
                human_gate_label=entry.get("human_gate_label"),
                description=entry["description"],
                step_type=entry.get("type", "agent"),
                script_path=entry.get("script"),
                max_retries=int(entry.get("max_retries", 0)),
                session_scope=entry.get("session", {}).get("scope", "per_issue"),
                session_id_pattern=entry.get("session", {}).get("id_pattern"),
                post_steps=list(entry.get("post_steps", [])),
                review_gate=bool(entry.get("review_gate", False)),
                commit_after=bool(entry.get("git_ops", {}).get("commit_after", False)),
                branch_suffix=entry.get("branch_suffix", ""),
                exclude_classifications=list(entry.get("exclude_classifications", [])),
                exclude_labels=list(entry.get("exclude_labels", [])),
                review_loop=entry.get("review_loop"),
                max_concurrent=int(entry.get("max_concurrent") or 1),
                script_timeout_seconds=int(entry.get("script_timeout_seconds", SCRIPT_TIMEOUT_SECONDS)),
                auto_approve_on_complete=bool(entry.get("auto_approve_on_complete", False)),
                self_gates=bool(entry.get("self_gates", False)),
                extra_allowedTools=_coerce_tools(entry.get("extra_allowedTools")),
            ))
            if entry.get("git_ops", {}).get("mark_ready_on_complete"):
                log.warning(
                    "pipeline.json: agent %r uses deprecated git_ops.mark_ready_on_complete; "
                    "migrate to post_steps: [\".github/scripts/mark-pr-ready.sh\"]",
                    entry.get("agent", "<unknown>"),
                )

        default_extra_tools: list[str] = _coerce_tools(
            raw.get("defaults", {}).get("extra_allowedTools")
        )

        return agents, default_extra_tools
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        log.error("pipeline.json is malformed (agent: %s) — cannot start: %s", entry.get("agent", "<unknown>"), exc)
        sys.exit(1)


def pipeline_by_name(agents: list[AgentDef]) -> dict[str, AgentDef]:
    return {a.agent: a for a in agents}


def _count_running(work_items: list[WorkItem], agents: list[AgentDef]) -> dict[str, int]:
    """Count work items carrying each agent's :wip label at tick start.

    Returns a dict from agent label_key to count. Used to initialise
    ConcurrencyState so the per-agent ceiling accounts for instances already
    running from a prior orchestrator tick before this one started.
    """
    counts: dict[str, int] = {}
    for agent_def in agents:
        key = agent_def.label_key
        counts[key] = sum(
            1 for wi in work_items
            if agent_def.in_progress_label in wi.labels
        )
    return counts


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

class GitHubClient:
    # HTTP retry configuration. Honoured for transient errors:
    # 429 (rate limit), 502/503/504 (transient server), and connection
    # errors. Retry-After header is honoured when present.
    _REQUEST_TIMEOUT_SECONDS = 30
    _MAX_RETRIES = 4
    _RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.token = token
        self.base = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> requests.Response:
        """Issue an HTTP request with timeout and retry-with-backoff.

        Retries on 429 / 5xx (transient) and connection errors with
        delays of 2s, 4s, 8s, 16s. Honours `Retry-After` on 429. After
        the final attempt, raises the underlying error.
        """
        url = f"{self.base}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                r = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    timeout=self._REQUEST_TIMEOUT_SECONDS,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt == self._MAX_RETRIES:
                    raise
                delay = 2 ** (attempt + 1)
                log.warning(
                    "  HTTP %s %s — connection error (%s); retrying in %ds (attempt %d/%d)",
                    method, path, exc, delay, attempt + 1, self._MAX_RETRIES,
                )
                time.sleep(delay)
                continue

            # Non-retryable success or non-retryable error → return.
            if r.status_code not in self._RETRYABLE_STATUSES:
                return r

            # Retryable status. Honour Retry-After if provided.
            if attempt == self._MAX_RETRIES:
                return r  # caller will raise_for_status

            retry_after = r.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = min(int(retry_after), 60)  # cap at 60s per attempt
            else:
                delay = 2 ** (attempt + 1)
            log.warning(
                "  HTTP %s %s — %d; retrying in %ds (attempt %d/%d)",
                method, path, r.status_code, delay, attempt + 1, self._MAX_RETRIES,
            )
            time.sleep(delay)

        # Defensive: should not reach here.
        if last_exc:
            raise last_exc
        raise RuntimeError("retry loop exited without a response")

    def _get(self, path: str, params: dict = None) -> dict | list:
        r = self._request("GET", path, params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = self._request("POST", path, json_body=body)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> None:
        r = self._request("DELETE", path)
        if r.status_code not in (200, 204):
            r.raise_for_status()

    def get_issue_labels(self, number: int) -> set[str]:
        data = self._get(f"/repos/{self.repo}/issues/{number}/labels")
        return {lbl["name"] for lbl in data}

    def get_pr_reviews(self, pr_number: int) -> list:
        return self._get(f"/repos/{self.repo}/pulls/{pr_number}/reviews")

    def add_label(self, number: int, label: str) -> None:
        self._ensure_label_exists(label)
        self._post(f"/repos/{self.repo}/issues/{number}/labels", {"labels": [label]})

    def remove_label(self, number: int, label: str) -> None:
        try:
            self._delete(f"/repos/{self.repo}/issues/{number}/labels/{requests.utils.quote(label, safe='')}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                pass  # label wasn't on the issue
            else:
                raise

    def transition_label(self, number: int, agent: str, from_status: str, to_status: str) -> None:
        """Remove agent:from_status and add agent:to_status atomically."""
        old = f"{agent}:{from_status}"
        new = f"{agent}:{to_status}"
        self.remove_label(number, old)
        self.add_label(number, new)

    def list_open_issues(self, kind: str = "all") -> list[WorkItem]:
        """Return open issues and/or PRs. kind: 'issues', 'prs', or 'all'."""
        items = []

        if kind in ("issues", "all"):
            page = 1
            while True:
                data = self._get(
                    f"/repos/{self.repo}/issues",
                    params={"state": "open", "per_page": 100, "page": page}
                )
                if not data:
                    break
                for item in data:
                    if "pull_request" not in item:
                        items.append(WorkItem(
                            number=item["number"],
                            kind="issue",
                            title=item["title"],
                            labels={lbl["name"] for lbl in item["labels"]},
                            url=item["html_url"],
                            is_closed=item["state"] == "closed",
                        ))
                page += 1

        if kind in ("prs", "all"):
            page = 1
            while True:
                data = self._get(
                    f"/repos/{self.repo}/pulls",
                    params={"state": "open", "per_page": 100, "page": page}
                )
                if not data:
                    break
                for item in data:
                    items.append(WorkItem(
                        number=item["number"],
                        kind="pr",
                        title=item["title"],
                        labels={lbl["name"] for lbl in item["labels"]},
                        url=item["html_url"],
                        is_merged=item.get("merged", False),
                    ))
                page += 1

        return items

    def _ensure_label_exists(self, label: str) -> None:
        """Create the label if it doesn't exist, with an appropriate colour."""
        try:
            self._get(f"/repos/{self.repo}/labels/{requests.utils.quote(label, safe='')}")
        except requests.HTTPError as e:
            # e.response can be None if the failure was connection-level
            # rather than HTTP; in that case re-raise rather than silently
            # treating it as 404.
            if e.response is None or e.response.status_code != 404:
                raise
            # Standalone labels (no colon) use their declared colour; suffix-based
            # labels derive colour from the status name after the last colon.
            if label in STANDALONE_LABEL_COLOURS:
                colour = STANDALONE_LABEL_COLOURS[label]
            else:
                suffix = label.split(":")[-1] if ":" in label else "complete"
                colour = LABEL_COLOURS.get(suffix, "EDEDED")
            try:
                self._post(f"/repos/{self.repo}/labels", {
                    "name": label,
                    "color": colour,
                    "description": f"Orchestrator: {label}",
                })
                log.debug("Created label: %s", label)
            except requests.HTTPError as create_err:
                # Race condition — another process created it first
                if create_err.response is not None and create_err.response.status_code == 422:
                    pass
                else:
                    raise

    def post_comment(self, number: int, body: str) -> None:
        self._post(f"/repos/{self.repo}/issues/{number}/comments", {"body": body})

    def close_issue(self, number: int) -> None:
        r = self._request(
            "PATCH",
            f"/repos/{self.repo}/issues/{number}",
            json_body={"state": "closed", "state_reason": "completed"},
        )
        r.raise_for_status()

    def mark_pr_ready(self, pr_number: int) -> None:
        """Convert a draft PR to ready-for-review. Safe to call if already ready (GitHub returns 200)."""
        r = self._request("PATCH", f"/repos/{self.repo}/pulls/{pr_number}",
                          json_body={"draft": False})
        r.raise_for_status()

    def find_pr_by_branch(self, branch: str) -> Optional[int]:
        """Return the number of the first open PR whose head is *branch*, or None."""
        owner = self.repo.split("/")[0]
        data = self._get(
            f"/repos/{self.repo}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open", "per_page": 1},
        )
        return data[0]["number"] if data else None

    def find_pr_by_label(self, label: str) -> Optional[int]:
        """Return the number of the first open PR that has *label*, or None.

        Uses the issues API (which includes PRs) since the pulls API does not
        support label filtering directly.
        """
        data = self._get(
            f"/repos/{self.repo}/issues",
            params={"labels": label, "state": "open", "per_page": 100},
        )
        for item in data:
            if "pull_request" in item:
                return item["number"]
        return None

    def _put(self, path: str, body: dict) -> requests.Response:
        """Issue a PUT request; returns the raw response so callers can inspect 409."""
        return self._request("PUT", path, json_body=body)


# ---------------------------------------------------------------------------
# Audit event emission (stdout JSON lines)
# ---------------------------------------------------------------------------

def _make_audit_event(
    session_id: str,
    event: str,
    repo: str,
    work_item: Optional[WorkItem] = None,
    agent: Optional[str] = None,
    outcome_status: str = "ok",
    outcome_detail: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> dict:
    """Build one audit event per the schema in docs/product/orchestrator/08-audit-log.md."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    obj: Optional[dict] = None
    if work_item is not None:
        obj = {"kind": work_item.kind, "id": work_item.number, "repo": repo}
    return {
        "ts": ts,
        "event": event,
        "session_id": session_id,
        "issue": obj["id"] if obj and obj.get("kind") == "issue" else None,
        "status": outcome_status,
        "detail": outcome_detail,
        "object": obj,
        "agent": agent,
        "actor": {
            "kind": "orchestrator",
            "id": "github-actions" if _HEADLESS else "interactive",
            "human": None if _HEADLESS else True,
        },
        "ref": None,
        "duration_ms": duration_ms,
    }


def _emit_audit_event(event: dict) -> None:
    """Print one audit event as a compact JSON line to stdout."""
    try:
        print(json.dumps(event, separators=(",", ":")), flush=True)
    except Exception as exc:
        log.warning("could not emit audit event: %s", exc)


# ---------------------------------------------------------------------------
# Per-cycle metrics capture
# ---------------------------------------------------------------------------

METRICS_BRANCH = "ai-agile/metrics"
METRICS_RECORDS_FILE = "records.jsonl"
METRICS_SCHEMA_FILE = "schema.json"

# Required-minimum JSON Schema for metrics records.
# additionalProperties: true ensures future CLI fields are not rejected.
# Null is accepted for every AI-specific field so scripted-step records
# (which set those fields to null) pass validation without a separate schema.
METRICS_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AI Agile Metrics Record",
    "description": (
        "Per-cycle orchestrator metrics. Required fields are the floor; "
        "additionalProperties: true allows future CLI additions."
    ),
    "type": "object",
    "required": [
        "timestamp_start", "timestamp_end", "github_issue_number",
        "agent_id", "cycle_id", "duration_ms",
        "input_tokens", "output_tokens", "retry_count", "retry_errors",
    ],
    "additionalProperties": True,
    "properties": {
        "timestamp_start": {"type": "string", "description": "ISO 8601 UTC timestamp when the orchestrator launched the step"},
        "timestamp_end":   {"type": "string", "description": "ISO 8601 UTC timestamp when the orchestrator observed step completion"},
        "github_issue_number": {"type": ["integer", "null"]},
        "agent_id":   {"type": "string"},
        "branch_id":  {"type": ["string", "null"]},
        "pr_id":      {"type": ["integer", "null"]},
        "cycle_id":   {"type": "string"},
        "session_id": {"type": ["string", "null"]},
        "model":      {"type": ["string", "null"]},
        "cwd":        {"type": ["string", "null"]},
        "permission_mode":  {"type": ["string", "null"]},
        "tools_available":  {"type": ["string", "null"]},
        "mcp_servers":      {"type": ["string", "null"]},
        "subtype":          {"type": ["string", "null"]},
        "is_error":         {"type": ["boolean", "null"]},
        "duration_ms":         {"type": "integer", "minimum": 0},
        "duration_api_ms":     {"type": "integer", "minimum": 0},
        "num_turns":           {"type": "integer", "minimum": 0},
        "input_tokens":        {"type": "integer", "minimum": 0},
        "output_tokens":       {"type": "integer", "minimum": 0},
        "cache_creation_input_tokens": {"type": "integer", "minimum": 0},
        "cache_read_input_tokens":     {"type": "integer", "minimum": 0},
        "web_search_requests":         {"type": "integer", "minimum": 0},
        "service_tier":   {"type": ["string", "null"]},
        "total_cost_usd": {"type": "number",  "minimum": 0},
        "retry_count":    {"type": "integer", "minimum": 0},
        "retry_errors":   {"type": "array",   "items": {"type": "string"}},
    },
}

# Fields from system/init and result events that are explicitly mapped to
# canonical names — excluded from the "extra" pass-through so they don't
# appear twice in the record.
_INIT_ENVELOPE: frozenset = frozenset({
    "type", "subtype", "session_id", "model", "cwd",
    "permissionMode", "tools", "mcp_servers",
})
_RESULT_ENVELOPE: frozenset = frozenset({
    "type", "subtype", "is_error", "duration_ms", "duration_api_ms",
    "num_turns", "usage", "total_cost_usd", "result", "session_id", "cost_usd",
})


def _build_agent_metrics(
    agent_def: "AgentDef",
    work_item: "WorkItem",
    result: "AgentRunResult",
    timestamp_start: str,
    timestamp_end: str,
    cycle_id: str,
    *,
    is_error_override: Optional[bool] = None,
) -> dict:
    """Build a complete per-cycle metrics record from a completed agent run.

    Extra fields from system/init and result events (beyond the PRD-enumerated
    minimum) are included at their original CLI names so no field is silently
    dropped. Known canonical fields override any same-named extra field.
    """
    init = result.init_event or {}
    result_ev = result.result_event or {}
    usage = result_ev.get("usage") or {}
    server_tool_use = usage.get("server_tool_use") or {}

    # Pass through any extra fields from both events that are not already
    # captured by the canonical mapping, preserving their original names.
    extra: dict = {}
    for k, v in init.items():
        if k not in _INIT_ENVELOPE:
            extra[k] = v
    for k, v in result_ev.items():
        if k not in _RESULT_ENVELOPE:
            extra[k] = v

    tools = init.get("tools", [])
    tools_str: Optional[str] = None
    if isinstance(tools, list) and tools:
        tools_str = ",".join(
            t.get("name", str(t)) if isinstance(t, dict) else str(t)
            for t in tools
        )

    mcps = init.get("mcp_servers", [])
    mcp_str: Optional[str] = None
    if isinstance(mcps, list) and mcps:
        mcp_str = ",".join(
            f"{m.get('name', '?')}:{m.get('status', '?')}"
            for m in mcps
            if isinstance(m, dict)
        )

    try:
        _ts = timestamp_start.rstrip("Z") + "+00:00"
        _te = timestamp_end.rstrip("Z") + "+00:00"
        _dur = (datetime.fromisoformat(_te) - datetime.fromisoformat(_ts)).total_seconds()
        duration_ms = max(0, int(_dur * 1000))
    except (ValueError, AttributeError):
        duration_ms = int(result_ev.get("duration_ms") or 0)

    github_issue_number: Optional[int] = work_item.number if work_item.kind == "issue" else None
    pr_id: Optional[int] = work_item.number if work_item.kind == "pr" else None
    branch_id: Optional[str] = (
        f"issue-{work_item.number}" if work_item.kind == "issue" else None
    )

    is_error = (
        is_error_override
        if is_error_override is not None
        else result_ev.get("is_error")
    )

    known: dict = {
        "timestamp_start": timestamp_start,
        "timestamp_end": timestamp_end,
        "github_issue_number": github_issue_number,
        "agent_id": agent_def.agent,
        "branch_id": branch_id,
        "pr_id": pr_id,
        "cycle_id": cycle_id,
        "session_id": init.get("session_id"),
        "model": init.get("model"),
        "cwd": init.get("cwd"),
        "permission_mode": init.get("permissionMode"),
        "tools_available": tools_str,
        "mcp_servers": mcp_str,
        "subtype": result_ev.get("subtype"),
        "is_error": is_error,
        "duration_ms": duration_ms,
        "duration_api_ms": int(result_ev.get("duration_api_ms") or 0),
        "num_turns": int(result_ev.get("num_turns") or 0),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "web_search_requests": int(server_tool_use.get("web_search_requests") or 0),
        "service_tier": usage.get("service_tier"),
        "total_cost_usd": float(result_ev.get("total_cost_usd") or 0),
        "retry_count": result.retry_count,
        "retry_errors": list(result.retry_errors),
    }

    # Known canonical fields override any same-named extra fields.
    return {**extra, **known}


def _build_scripted_metrics(
    agent_def: "AgentDef",
    work_item: "WorkItem",
    is_error: bool,
    timestamp_start: str,
    timestamp_end: str,
    cycle_id: str,
) -> dict:
    """Build a metrics record for a scripted (non-AI) pipeline step.

    AI-specific fields are set to their zero values (null/0/[]) as required
    by the PRD so every pipeline step leaves exactly one record regardless
    of step type. The zero-value block signals 'deterministic step' without
    a missing or broken record.
    """
    try:
        _ts = timestamp_start.rstrip("Z") + "+00:00"
        _te = timestamp_end.rstrip("Z") + "+00:00"
        _dur = (datetime.fromisoformat(_te) - datetime.fromisoformat(_ts)).total_seconds()
        duration_ms = max(0, int(_dur * 1000))
    except (ValueError, AttributeError):
        duration_ms = 0

    github_issue_number: Optional[int] = work_item.number if work_item.kind == "issue" else None
    pr_id: Optional[int] = work_item.number if work_item.kind == "pr" else None
    branch_id: Optional[str] = (
        f"issue-{work_item.number}" if work_item.kind == "issue" else None
    )

    return {
        "timestamp_start": timestamp_start,
        "timestamp_end": timestamp_end,
        "github_issue_number": github_issue_number,
        "agent_id": agent_def.agent,
        "branch_id": branch_id,
        "pr_id": pr_id,
        "cycle_id": cycle_id,
        "session_id": None,
        "model": None,
        "cwd": None,
        "permission_mode": None,
        "tools_available": None,
        "mcp_servers": None,
        "subtype": "script",
        "is_error": is_error,
        "duration_ms": duration_ms,
        "duration_api_ms": 0,
        "num_turns": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "web_search_requests": 0,
        "service_tier": None,
        "total_cost_usd": 0,
        "retry_count": 0,
        "retry_errors": [],
    }


def _build_step_metrics(
    agent_def: "AgentDef",
    work_item: "WorkItem",
    result: "AgentRunResult",
    timestamp_start: str,
    timestamp_end: str,
    cycle_id: str,
    *,
    is_error_override: Optional[bool] = None,
) -> dict:
    """Dispatch to the correct metrics builder based on step type."""
    if agent_def.step_type == "script":
        is_error = is_error_override if is_error_override is not None else (not result.success)
        return _build_scripted_metrics(
            agent_def, work_item, is_error, timestamp_start, timestamp_end, cycle_id
        )
    return _build_agent_metrics(
        agent_def, work_item, result, timestamp_start, timestamp_end, cycle_id,
        is_error_override=is_error_override,
    )


def _post_metrics_comment(
    gh: "GitHubClient",
    work_item: "WorkItem",
    record: dict,
) -> None:
    """Post a structured metrics comment on the work item."""
    comment = (
        "<!-- ai-agile/metrics/v1 -->\n"
        "<details><summary>Pipeline step metrics</summary>\n\n"
        "```json\n"
        f"{json.dumps(record, indent=2)}\n"
        "```\n\n"
        "</details>"
    )
    try:
        gh.post_comment(work_item.number, comment)
    except Exception as exc:
        log.warning("could not post metrics comment on #%d: %s", work_item.number, exc)


def _ensure_metrics_branch(gh: "GitHubClient", repo: str) -> None:
    """Create the ai-agile/metrics branch in *repo* if it does not exist.

    Initialises the branch from the repo's default branch and pushes the
    JSON schema file. A concurrent creation race is handled by swallowing
    the 422 response from GitHub.
    """
    try:
        gh._get(f"/repos/{repo}/git/refs/heads/{METRICS_BRANCH}")
        return  # already exists
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 404:
            raise

    # Determine default branch SHA to branch from.
    try:
        repo_data = gh._get(f"/repos/{repo}")
        default_branch = repo_data.get("default_branch", "main")
        ref_data = gh._get(f"/repos/{repo}/git/refs/heads/{default_branch}")
        sha = ref_data["object"]["sha"]
    except Exception as exc:
        log.warning("metrics branch: could not get default branch SHA for %s — %s", repo, exc)
        return

    try:
        gh._post(f"/repos/{repo}/git/refs", {
            "ref": f"refs/heads/{METRICS_BRANCH}",
            "sha": sha,
        })
        log.info("metrics branch: created %s in %s", METRICS_BRANCH, repo)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 422:
            return  # concurrent creation — branch now exists
        raise

    schema_b64 = base64.b64encode(
        (json.dumps(METRICS_SCHEMA, indent=2) + "\n").encode()
    ).decode()
    try:
        gh._put(f"/repos/{repo}/contents/{METRICS_SCHEMA_FILE}", {
            "message": "metrics: initialize schema for ai-agile/metrics branch",
            "content": schema_b64,
            "branch": METRICS_BRANCH,
        })
        log.info("metrics branch: schema pushed to %s", METRICS_BRANCH)
    except Exception as exc:
        log.warning("metrics branch: could not push schema — %s", exc)


def _append_metrics_record(
    gh: "GitHubClient",
    repo: str,
    record: dict,
    *,
    _retries: int = 2,
) -> None:
    """Append one metrics record to records.jsonl on the ai-agile/metrics branch.

    Uses plain git plumbing (fetch/hash-object/commit-tree/push) rather than
    the GitHub Contents API: some restricted sessions (e.g. an interactive
    Claude Code session) 403 on a direct Contents API PUT even though `git
    push` over the same HTTPS credential helper succeeds. Object/ref
    operations don't touch the working tree or the real index (a scratch
    GIT_INDEX_FILE is used), so this is safe to run while another branch is
    checked out. Retries on a rejected push (concurrent writer) up to
    _retries times. gh is accepted for interface symmetry with
    _ensure_metrics_branch but unused here.
    """
    record_line = json.dumps(record, separators=(",", ":")) + "\n"
    commit_message = (
        f"metrics: {record.get('agent_id', 'step')} "
        f"on #{record.get('github_issue_number')}"
    )

    for attempt in range(_retries + 1):
        subprocess.run(
            ["git", "fetch", "origin", METRICS_BRANCH],
            check=True, capture_output=True,
        )
        parent_sha = subprocess.run(
            ["git", "rev-parse", f"origin/{METRICS_BRANCH}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        show = subprocess.run(
            ["git", "show", f"{parent_sha}:{METRICS_RECORDS_FILE}"],
            capture_output=True, text=True,
        )
        existing = show.stdout if show.returncode == 0 else ""

        blob_sha = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            input=existing + record_line, check=True, capture_output=True, text=True,
        ).stdout.strip()

        with tempfile.NamedTemporaryFile(delete=False) as idx_file:
            index_path = idx_file.name
        try:
            git_env = {**os.environ, "GIT_INDEX_FILE": index_path}
            subprocess.run(
                ["git", "read-tree", parent_sha],
                check=True, env=git_env, capture_output=True,
            )
            subprocess.run(
                ["git", "update-index", "--add", "--cacheinfo",
                 f"100644,{blob_sha},{METRICS_RECORDS_FILE}"],
                check=True, env=git_env, capture_output=True,
            )
            tree_sha = subprocess.run(
                ["git", "write-tree"],
                check=True, env=git_env, capture_output=True, text=True,
            ).stdout.strip()
        finally:
            os.unlink(index_path)

        commit_sha = subprocess.run(
            ["git", "commit-tree", tree_sha, "-p", parent_sha, "-m", commit_message],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        push = subprocess.run(
            ["git", "push", "origin", f"{commit_sha}:refs/heads/{METRICS_BRANCH}"],
            capture_output=True, text=True,
        )
        if push.returncode == 0:
            return
        if attempt < _retries:
            log.debug(
                "metrics: push rejected appending records.jsonl (concurrent writer?),"
                " retrying (attempt %d): %s",
                attempt + 1, push.stderr.strip(),
            )
            time.sleep(1)
            continue
        raise RuntimeError(f"git push to {METRICS_BRANCH} failed: {push.stderr.strip()}")


def _post_cycle_metrics(
    gh: "GitHubClient",
    repo: str,
    work_item: "WorkItem",
    record: dict,
    dry_run: bool,
) -> None:
    """Post metrics comment on the work item and append to the metrics branch.

    Both outputs carry identical field sets from the shared *record* dict.
    Skipped in dry_run mode. All failures are logged as warnings and never
    propagated — metrics must never halt the pipeline.
    """
    if dry_run:
        return
    _post_metrics_comment(gh, work_item, record)
    try:
        _ensure_metrics_branch(gh, repo)
        _append_metrics_record(gh, repo, record)
    except Exception as exc:
        log.warning(
            "could not push metrics record for #%d: %s",
            work_item.number, exc,
        )


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Rate-limit pause handling
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_pipeline_paused() -> tuple[bool, Optional[str], Optional[datetime]]:
    """Return (paused, reason, until). Auto-clears expired markers.

    The pause marker is a JSON file at PAUSE_MARKER_PATH containing:
        { "until": "<ISO-8601>", "reason": "...", "paused_at": "<ISO-8601>" }

    Safe against TOCTOU: a concurrent process may delete or rewrite
    the marker between our existence check and read; either is
    treated as "not paused" for this run.
    """
    try:
        raw = PAUSE_MARKER_PATH.read_text()
    except FileNotFoundError:
        return False, None, None
    except OSError as exc:
        log.warning(
            "Pause marker at %s could not be read (%s); ignoring.",
            PAUSE_MARKER_PATH, exc,
        )
        return False, None, None

    try:
        marker = json.loads(raw)
        until = datetime.fromisoformat(marker["until"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        log.warning(
            "Pause marker at %s is malformed (%s); ignoring.",
            PAUSE_MARKER_PATH, exc,
        )
        return False, None, None

    if _now_utc() < until:
        return True, marker.get("reason", "pipeline paused"), until

    # Expired — clear it so the next agent failure can write a fresh marker.
    try:
        PAUSE_MARKER_PATH.unlink(missing_ok=True)
    except OSError as exc:
        log.debug("Could not unlink expired pause marker: %s", exc)
    log.info("Pause marker expired (was until %s); cleared.", until.isoformat())
    return False, None, None


def pause_pipeline(seconds: int, reason: str) -> datetime:
    """Write the pause marker. Returns the until-time."""
    seconds = max(1, min(seconds, MAX_PAUSE_SECONDS))
    until = _now_utc() + timedelta(seconds=seconds)
    payload = {
        "until": until.isoformat(),
        "reason": reason,
        "paused_at": _now_utc().isoformat(),
        "seconds": seconds,
    }
    tmp = PAUSE_MARKER_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(PAUSE_MARKER_PATH)
    log.warning(
        "Pipeline paused for %d seconds (until %s): %s",
        seconds, until.isoformat(), reason,
    )
    return until


def clear_pause() -> bool:
    """Manually clear the pause marker. Returns True if a marker was cleared."""
    if PAUSE_MARKER_PATH.exists():
        PAUSE_MARKER_PATH.unlink()
        log.info("Pause marker cleared.")
        return True
    return False


def is_pipeline_stopped() -> tuple[bool, str]:
    """Return (stopped, reason). No auto-expiry — must be cleared explicitly.

    The stop marker is a JSON file at STOP_MARKER_PATH containing:
        { "stopped_at": "<ISO-8601>", "reason": "...", "stopped_by": "github-actions" }

    Unlike the pause marker, the stop marker has no time field and is never
    auto-cleared. It persists until an owner clears it -- by deleting the
    committed marker (git rm .pipeline-stop) or running --clear-stop.
    """
    try:
        raw = STOP_MARKER_PATH.read_text()
    except FileNotFoundError:
        return False, ""
    except OSError as exc:
        log.warning(
            "Stop marker at %s could not be read (%s); ignoring.",
            STOP_MARKER_PATH, exc,
        )
        return False, ""

    try:
        marker = json.loads(raw)
        reason = marker.get("reason", "pipeline stopped")
    except (json.JSONDecodeError, ValueError):
        reason = "pipeline stopped (malformed marker)"

    return True, reason


def clear_stop() -> bool:
    """Clear the emergency stop marker. Returns True if a marker was cleared.

    # Mirrors clear_pause() — one call site is expected for this operator-only flag.
    """
    try:
        STOP_MARKER_PATH.unlink()
        log.info("Stop marker cleared.")
        return True
    except FileNotFoundError:
        return False


def _check_controls(repo: str) -> Literal["run", "pause", "stop"]:
    """Check repository-level pause and stop signals.

    Called once per work item at the entry of process_work_item(). Returns
    "stop" if an emergency stop marker is active (headless runs only),
    "pause" if a rate-limit pause marker is active, or "run" if the pipeline
    should proceed.

    Stop is gated on _HEADLESS: interactive runs log the marker but return
    "run" so a human driving a specific issue is not blocked by a scheduled
    automation stop. Pause always applies regardless of invocation mode.

    repo is accepted for future multi-repo extensibility but unused in the
    current file-based implementation.
    """
    stopped, _stop_reason = is_pipeline_stopped()
    if stopped:
        if _HEADLESS:
            return "stop"
        log.warning("Operating in interactive mode, ignoring pipeline stop.")
    paused, _pause_reason, _until = is_pipeline_paused()
    if paused:
        return "pause"
    return "run"


def detect_rate_limit(output: str) -> tuple[bool, int]:
    """Inspect agent subprocess output for rate-limit indicators.

    Returns (is_rate_limited, retry_after_seconds). retry_after_seconds is
    DEFAULT_PAUSE_SECONDS when no specific value can be parsed from the
    output, capped at MAX_PAUSE_SECONDS.
    """
    if not output:
        return False, 0

    haystack = output.lower()
    if not any(re.search(pat, haystack) for pat in RATE_LIMIT_PATTERNS):
        return False, 0

    # Try to parse a specific retry-after value.
    for pat in RETRY_AFTER_PATTERNS:
        m = re.search(pat, haystack)
        if m:
            try:
                seconds = int(m.group(1))
                return True, min(seconds, MAX_PAUSE_SECONDS)
            except (ValueError, IndexError):
                continue

    return True, DEFAULT_PAUSE_SECONDS


def _terminate_subprocess(proc: subprocess.Popen) -> None:
    """Kill a subprocess and reap it so it does not become a zombie.

    Tries SIGTERM first, then SIGKILL after a short grace period.
    Always calls wait() so the OS can free the process slot.
    """
    if proc.poll() is not None:
        return  # already exited
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log.warning("Subprocess pid=%d did not exit after SIGKILL", proc.pid)
    except (ProcessLookupError, OSError) as exc:
        log.debug("Could not terminate subprocess pid=%d: %s", proc.pid, exc)


def _probe_kind(gh: "GitHubClient", number: int) -> str:
    """Determine whether a numeric ID refers to an issue or a PR.

    GitHub's REST API treats every PR as an issue (they share number-space
    in the issues endpoint), but PRs have an additional `pull_request` key
    on the issues payload. We probe by fetching the issue and inspecting
    that key.
    """
    try:
        data = gh._get(f"/repos/{gh.repo}/issues/{number}")
        return "pr" if "pull_request" in data else "issue"
    except Exception as exc:
        log.warning("Could not probe kind for #%d: %s — defaulting to 'issue'", number, exc)
        return "issue"


def agent_status(labels: set[str], agent: str) -> Optional[str]:
    """Return the current status of an agent from the label set, or None."""
    for status in ALL_STATUSES:
        if f"{agent}:{status}" in labels:
            return status
    return None


def _get_review_cycle(labels: set[str]) -> int:
    """Return the current review-loop cycle count from review-cycle:N labels."""
    for label in labels:
        if label.startswith("review-cycle:"):
            try:
                return int(label.split(":")[-1])
            except ValueError:
                pass
    return 0


def _handle_review_loop(
    gh: "GitHubClient",
    agent_def: "AgentDef",
    work_item: "WorkItem",
    labels: set[str],
    pipeline_map: dict[str, "AgentDef"],
    *,
    skip_cycle_increment: bool = False,
    human_reviews: Optional[list] = None,
) -> set[str]:
    """Called when a review-loop agent completes with :review status.

    Normal path (skip_cycle_increment=False):
      If cycles < max_cycles: clears the reviewer's :review and the target
      agent's :complete, increments the review-cycle counter, and posts a
      comment so the next orchestrator tick re-invokes the target.
      If cycles >= max_cycles: leaves :review in place and posts a human-
      escalation comment explaining that the loop has reached its limit.
      Cleans up HUMAN_REVIEW_PENDING_LABEL if present from a prior free cycle.

    Human-review free re-invoke (skip_cycle_increment=True):
      Clears :review and target :complete (same as normal), but does NOT
      advance the review-cycle counter. Instead, applies HUMAN_REVIEW_PENDING_LABEL
      so the coder enters Mode B and the once-only guard is set for subsequent ticks.
      The max_cycles limit is NOT checked — the free re-invoke is always allowed.
      human_reviews (list of review dicts) is included in the loop comment when set.

    Returns the updated in-memory label set.
    """
    loop = agent_def.review_loop or {}
    re_invoke_name = loop.get("re_invoke", "")
    max_cycles = int(loop.get("max_cycles", 3))

    target_def = pipeline_map.get(re_invoke_name)
    if target_def is None:
        log.error(
            "review_loop re_invoke '%s' not found in pipeline — leaving :review",
            re_invoke_name,
        )
        return labels

    current_cycle = _get_review_cycle(labels)
    next_cycle = current_cycle + 1

    if not skip_cycle_increment and next_cycle > max_cycles:
        log.info(
            "  LOOP    %-38s  %d/%d cycles — escalating to human",
            agent_def.agent, next_cycle, max_cycles,
        )
        try:
            gh.post_comment(
                work_item.number,
                (
                    f"**Review loop reached {next_cycle} cycle(s) — human review required.**\n\n"
                    f"`{agent_def.agent}` has requested changes {next_cycle} time(s) and "
                    f"`{re_invoke_name}` has not reached an APPROVE.\n\n"
                    f"Please review the open findings, apply any fixes manually, then remove "
                    f"the `{agent_def.review_label}` label to re-trigger the review."
                ),
            )
        except Exception as exc:
            log.warning("could not post loop-escalation comment on #%d: %s", work_item.number, exc)
        return labels  # leave :review intact — human must act

    if skip_cycle_increment:
        log.info(
            "  LOOP    %-38s  human-review free re-invoke — re-invoking %s",
            agent_def.agent, re_invoke_name,
        )
    else:
        log.info(
            "  LOOP    %-38s  re-invoking %s (counter advances at dispatch)",
            agent_def.agent, re_invoke_name,
        )

    if skip_cycle_increment:
        # Apply HUMAN_REVIEW_PENDING_LABEL to signal Mode B to the coder and
        # prevent a second free re-invoke.
        try:
            gh.add_label(work_item.number, HUMAN_REVIEW_PENDING_LABEL)
            labels.add(HUMAN_REVIEW_PENDING_LABEL)
        except Exception as exc:
            log.warning(
                "could not apply %s on #%d: %s", HUMAN_REVIEW_PENDING_LABEL, work_item.number, exc
            )
            return labels  # guard not set; abort free re-invoke to preserve once-only semantics
    else:
        # Clean up HUMAN_REVIEW_PENDING_LABEL if present from a prior free cycle —
        # the normal automated review cycle supersedes it.
        if HUMAN_REVIEW_PENDING_LABEL in labels:
            try:
                gh.remove_label(work_item.number, HUMAN_REVIEW_PENDING_LABEL)
                labels.discard(HUMAN_REVIEW_PENDING_LABEL)
            except Exception as exc:
                log.debug(
                    "could not remove %s on #%d: %s",
                    HUMAN_REVIEW_PENDING_LABEL, work_item.number, exc,
                )

    # Clear reviewer's :review so the pipeline is no longer halted
    try:
        gh.remove_label(work_item.number, agent_def.review_label)
        labels.discard(agent_def.review_label)
    except Exception as exc:
        log.warning(
            "could not remove %s on #%d: %s", agent_def.review_label, work_item.number, exc
        )

    # Clear target's :complete (or :skipped if it was bypassed) so it can be re-triggered.
    for lbl in (target_def.complete_label, target_def.skipped_label):
        if lbl not in labels:
            continue
        try:
            gh.remove_label(work_item.number, lbl)
            labels.discard(lbl)
        except Exception as exc:
            log.warning(
                "could not remove %s on #%d: %s", lbl, work_item.number, exc
            )

    # Clear any intermediate steps that must re-run (e.g. ci-gate between coder and pr-reviewer)
    also_cleared: list[str] = []
    for also_name in loop.get("also_clear", []):
        also_def = pipeline_map.get(also_name)
        if also_def is None:
            log.warning("review_loop also_clear '%s' not found in pipeline — skipping", also_name)
            continue
        cleared_any = False
        for lbl in (also_def.complete_label, also_def.skipped_label):
            if lbl not in labels:
                continue
            try:
                gh.remove_label(work_item.number, lbl)
                labels.discard(lbl)
                cleared_any = True
            except Exception as exc:
                log.warning(
                    "could not remove %s on #%d: %s", lbl, work_item.number, exc
                )
        if cleared_any:
            also_cleared.append(also_name)

    also_suffix = (
        f" (also cleared: {', '.join(f'`{n}`' for n in also_cleared)})" if also_cleared else ""
    )

    if skip_cycle_increment:
        reviewers = [r.get("user", {}).get("login", "") for r in (human_reviews or [])]
        reviewer_info = (
            f" Reviewer(s) with open REQUEST_CHANGES: "
            f"{', '.join(f'@{r}' for r in reviewers if r)}."
            if reviewers
            else ""
        )
        comment_text = (
            f"**Human review: free re-invoke of `{re_invoke_name}`** "
            f"(does not count toward the {max_cycles - 1}-cycle limit).{reviewer_info} "
            f"`{agent_def.agent}` approved the code quality, but unresolved human "
            f"`REQUEST_CHANGES` reviews remain. `{re_invoke_name}` will address them."
            f"{also_suffix}"
        )
    else:
        comment_text = (
            f"**Review cycle {next_cycle}/{max_cycles - 1}:** "
            f"`{agent_def.agent}` requested changes — re-invoking `{re_invoke_name}`."
            f"{also_suffix}"
        )

    try:
        gh.post_comment(work_item.number, comment_text)
    except Exception as exc:
        log.warning("could not post loop comment on #%d: %s", work_item.number, exc)

    return labels


def _fetch_unresolved_human_review_requests(gh: "GitHubClient", pr_number: int) -> list[dict]:
    """Return reviews where the latest review from each human (non-bot) is CHANGES_REQUESTED.

    Uses the PR reviews REST endpoint. A reviewer's state is their latest review
    ordered by submitted_at. DISMISSED reviews count as resolved. Bot accounts
    (user.type == 'Bot') are excluded per the acceptance criteria in issue #100.
    Returns an empty list on any API or parse error so callers can safely skip
    the edge-case path without failing the run.
    """
    try:
        reviews = gh.get_pr_reviews(pr_number)
    except Exception as exc:
        log.warning("could not fetch PR reviews for #%d: %s", pr_number, exc)
        return []
    if not isinstance(reviews, list):
        return []

    latest_by_reviewer: dict[str, dict] = {}
    for review in reviews:
        user = review.get("user") or {}
        if user.get("type", "").lower() == "bot":
            continue
        login = user.get("login", "")
        if not login:
            continue
        existing = latest_by_reviewer.get(login)
        submitted = review.get("submitted_at")
        if not submitted:
            continue
        if existing is None or submitted > existing.get("submitted_at", ""):
            latest_by_reviewer[login] = review

    return [r for r in latest_by_reviewer.values() if r.get("state") == "CHANGES_REQUESTED"]


def normalize_skipped_labels(
    labels: set[str],
    pipeline_map: dict[str, AgentDef],
) -> set[str]:
    """Return a copy of labels with :complete synthesized for every :skipped agent.

    Downstream eligibility checks (dependencies_complete, trigger_label_present)
    only need to test for :complete — the "is done?" concept lives here, once.
    """
    normalized = set(labels)
    for adef in pipeline_map.values():
        if adef.skipped_label in labels:
            normalized.add(adef.complete_label)
    return normalized


def _gate_label_human_applied(gh, repo, work_item_number, gate_label) -> bool:
    """Return True unless the gate label was verifiably applied by a bot.

    A prompt-injected agent can self-approve its own gate by applying its
    ``{agent}:approved`` label. Since PR #262 agents run with the repo-scoped
    GITHUB_TOKEN, so an agent-applied label is authored by a bot account
    (``actor.type == "Bot"`` and/or a login ending in ``[bot]``). A genuine
    human approval is authored by a real user login.

    This inspects the issue's ``labeled`` events, finds the most recent one for
    ``gate_label``, and returns False only when that actor is determinably a
    bot. It is FAIL-OPEN: if the events call raises, no matching labeled event
    is found, or the actor cannot be determined, it logs a warning and returns
    True (allow) so a transient API error never halts the pipeline. The only
    case it blocks is the determinable bot-self-approval.
    """
    try:
        events = gh._get(f"/repos/{repo}/issues/{work_item_number}/events")
    except Exception as exc:
        log.warning(
            "  could not fetch events for #%s to verify gate '%s' applier: %s"
            " - allowing (fail-open)",
            work_item_number, gate_label, exc,
        )
        return True

    if not isinstance(events, list):
        log.warning(
            "  unexpected events payload for #%s verifying gate '%s' - allowing (fail-open)",
            work_item_number, gate_label,
        )
        return True

    labeled = [
        e for e in events
        if isinstance(e, dict)
        and e.get("event") == "labeled"
        and isinstance(e.get("label"), dict)
        and e["label"].get("name") == gate_label
    ]
    if not labeled:
        log.warning(
            "  no 'labeled' event found for gate '%s' on #%s - allowing (fail-open)",
            gate_label, work_item_number,
        )
        return True

    actor = labeled[-1].get("actor")
    if not isinstance(actor, dict):
        log.warning(
            "  could not determine actor for gate '%s' on #%s - allowing (fail-open)",
            gate_label, work_item_number,
        )
        return True

    actor_type = actor.get("type")
    actor_login = actor.get("login") or ""
    if actor_type == "Bot" or actor_login.endswith("[bot]"):
        log.warning(
            "  gate '%s' on #%s was applied by bot '%s' - NOT treating gate as"
            " satisfied (self-approval guard)",
            gate_label, work_item_number, actor_login or actor_type,
        )
        return False

    return True


def dependencies_complete(
    labels: set[str],
    agent_def: AgentDef,
    pipeline_map: dict[str, AgentDef],
    gh=None,
    repo: str = "",
    work_item_number: Optional[int] = None,
) -> bool:
    """Return True if every dependency's :complete label is present and its human gate is satisfied.

    ``labels`` must already be normalized via :func:`normalize_skipped_labels` before
    this call — a skipped dependency's synthesized ``:complete`` label must be present
    for it to be treated as done.

    When ``gh`` and ``work_item_number`` are provided, a present gate label is
    additionally verified to have been applied by a human (see
    :func:`_gate_label_human_applied`); a bot-self-applied gate does not satisfy
    the gate. When ``gh`` is None the verification is skipped (allow), so
    pure-unit callers are unaffected.
    """
    for dep_name in agent_def.dependencies:
        dep = pipeline_map.get(dep_name)
        if dep is None:
            log.warning("Unknown dependency: %s (required by %s)", dep_name, agent_def.agent)
            return False

        if dep.complete_label not in labels:
            return False

        # Human gate only applies when the dep actually ran — a skipped dep
        # never ran, so its gate label was never applied. self_gates deps
        # decide their own gate (see _resolve_applied_status): if one reached
        # :complete directly (no :review), the gate label was never meant to
        # be required. A self_gates dep that legitimately needs review is
        # still blocked above — it never reaches :complete until a human
        # applies the gate label and promote_gated_agents promotes it.
        dep_skipped = dep.skipped_label in labels
        if not dep_skipped and dep.human_gate_after and dep.human_gate_label and not dep.self_gates:
            if dep.human_gate_label not in labels:
                log.debug(
                    "  %s complete but human gate '%s' not yet applied",
                    dep_name, dep.human_gate_label
                )
                return False
            # The gate label is present, but a prompt-injected agent could have
            # self-applied it. When we have a gh client, require a human applier.
            if (
                gh is not None
                and work_item_number is not None
                and not _gate_label_human_applied(gh, repo, work_item_number, dep.human_gate_label)
            ):
                log.warning(
                    "  %s complete but human gate '%s' was not human-applied - treating as unmet",
                    dep_name, dep.human_gate_label,
                )
                return False

    return True


def trigger_label_present(labels: set[str], agent_def: AgentDef) -> bool:
    """Return True if the label trigger for this agent is satisfied."""
    if "label" not in agent_def.trigger:
        # Event and schedule triggers are handled externally (GitHub Actions).
        # When running interactively, treat them as always-eligible.
        return True
    label = agent_def.trigger["label"]
    if not isinstance(label, str):
        log.warning(
            "agent %s has non-string trigger label %r — treating as ineligible",
            agent_def.agent, label,
        )
        return False
    return label in labels


_CLASSIFICATION_TYPES = {"bug", "toil", "enhancement", "feature", "spike", "security"}

def get_work_item_classification(work_item: WorkItem) -> Optional[str]:
    """
    Return the issue classification (bug/toil/enhancement/feature/spike), or
    None if not determinable.

    Detection order:
      1. A 'classification: {type}' label applied by issue-classifier.
      2. A '[TYPE]' title prefix (e.g. '[SPIKE] - ...') as a fallback when
         the label could not be created (e.g. label not pre-created in repo).
    """
    for label in work_item.labels:
        if label.startswith("classification: "):
            cls = label.split(": ", 1)[1].strip().lower()
            if cls in _CLASSIFICATION_TYPES:
                return cls

    m = re.match(r"^\[([A-Z]+)\]", work_item.title)
    if m:
        cls = m.group(1).lower()
        if cls in _CLASSIFICATION_TYPES:
            return cls

    return None


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------

STATUS_SH = SUBMODULE_ROOT / ".github/scripts/status.sh"

# Shared agent context — every agent reads this before starting. It
# distils the principles, lifecycle, status contract, and "must not"
# rules from the design docs into a single page agents can ingest at
# runtime. The orchestrator exports its path so agents reference it
# without hardcoding the location.
AI_AGILE_CONTEXT = SUBMODULE_ROOT / ".claude" / "AGENTS.md"

# Rate-limit pause marker. When the Claude API returns a 429 / usage-limit
# error, the orchestrator writes this file with a JSON payload describing
# how long to back off. Subsequent runs check this file before doing
# anything; if the until-time has not yet passed, the orchestrator logs
# the wait and exits cleanly. The next scheduled tick (or a manual
# workflow_dispatch with --clear-pause) resumes work.
PAUSE_MARKER_PATH = Path(os.environ.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT))) / ".pipeline-pause"

# Emergency stop marker. Written by the pipeline-emergency-stop workflow when an
# operator halts the pipeline manually. Unlike the rate-limit pause, this marker
# is never auto-cleared -- it persists until an owner clears it (git rm the
# committed marker, or run --clear-stop locally).
STOP_MARKER_PATH = Path(os.environ.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT))) / ".pipeline-stop"

# Fixed UUID v5 namespace for deterministic session ID generation.
# The claude CLI requires a valid UUID for --session-id; we derive one
# deterministically from our human-readable session key so the same
# (agent, scope, work-item) triple always maps to the same UUID across runs.
#
# WARNING: do not change this value once deployed. Changing it would silently
# assign a different UUID to every existing live session, breaking session
# continuity for in-flight agents. Treat it as append-only infrastructure.
_SESSION_NAMESPACE = uuid.UUID("a15a91e5-a191-5001-b001-000000000001")

# Default pause duration if the API response does not name one. Five
# minutes is short enough that a transient burst recovers quickly; long
# enough that we don't hammer the API after a real per-minute exhaust.
DEFAULT_PAUSE_SECONDS = 300

# Maximum pause duration. Caps any retry-after we honour from the API
# so a misbehaving server cannot pause us indefinitely. One hour is
# longer than any documented Anthropic per-minute limit reset and
# shorter than any reasonable manual response time.
MAX_PAUSE_SECONDS = 3600

# Default max turns for agents that do not declare one in frontmatter.
# 30 is enough for complex agents; simple ones (classifier) declare lower
# values via max_turns: in their frontmatter.
DEFAULT_MAX_TURNS = 30

# Patterns in agent subprocess output that indicate a rate-limit /
# usage-limit error rather than a logic failure. Case-insensitive match.
RATE_LIMIT_PATTERNS = [
    r"rate[_\s-]?limit",
    r"\b429\b",
    r"usage limit",
    r"quota (exceeded|exhausted)",
    r"tokens? per minute",
    r"daily token limit",
    r"too many requests",
    r"overloaded_error",
]

# Patterns to extract a retry-after value (in seconds) from the output.
# Matches: "retry-after: 120", "retry after 60s", "wait 30 seconds".
RETRY_AFTER_PATTERNS = [
    r"retry[-_\s]?after[:\s=]+(\d+)",
    r"retry after (\d+)\s*s",
    r"wait\s+(\d+)\s*seconds?",
]


def _strip_frontmatter(text: str) -> str:
    """Return the body of a markdown file with the YAML frontmatter block removed."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(lines[i + 1:]).lstrip("\n")
    return text


def parse_frontmatter(text: str) -> dict:
    """Parse YAML-like frontmatter between --- delimiters.

    Handles simple scalars (key: value) and inline lists (key: [a, b, c]).
    Block scalars (key: >) and indented continuation lines are ignored.
    Returns {} when no frontmatter is found or the format is unrecognised.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}
    result: dict = {}
    for line in lines[1:end]:
        if ":" not in line or line.startswith(" "):
            continue  # skip indented continuation lines of block scalars
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not key or not raw or raw == ">":
            continue
        if raw.startswith("[") and raw.endswith("]"):
            result[key] = [x.strip() for x in raw[1:-1].split(",") if x.strip()]
        else:
            result[key] = raw
    return result


def _captured_tail(lines: list[str], max_lines: int = 50, max_chars: int = 4000) -> str:
    """Return the tail of agent output, capped for inclusion in a comment.

    Picks at most max_lines from the end; trims further if the result
    exceeds max_chars (GitHub comments tolerate more, but we want
    failure comments to stay readable in the timeline).
    """
    if not lines:
        return ""
    tail = lines[-max_lines:]
    text = "".join(tail).rstrip()
    if len(text) > max_chars:
        text = "…(truncated)…\n" + text[-max_chars:]
    return text


# ---------------------------------------------------------------------------
# Sentinel parsing and status application (shared by agent and script paths)
# ---------------------------------------------------------------------------

# Matches the AI_AGILE_STATUS: sentinel that agents and scripts emit.
# Only the last 5 lines of output are searched to prevent crafted content
# in an issue body (echoed earlier in the run) from spoofing the sentinel.
_SENTINEL_RE = re.compile(
    r"^AI_AGILE_STATUS:\s+(complete|review|blocked)(?:\s+\"([^\"]*)\")?",
    re.MULTILINE,
)


def _parse_agent_sentinel(captured_tail: str) -> tuple[Optional[str], str]:
    """Scan the last 5 lines of captured output for the agent status sentinel.

    Only the tail is searched — the sentinel must be the final meaningful
    output. Restricting the search window prevents crafted issue body
    content (reflected in stdout when the agent reads the issue) from
    being mistaken for a legitimate sentinel.

    Returns (status, message) where status is one of complete/review/blocked,
    or (None, "") if no sentinel is found.
    """
    last_lines = "\n".join(captured_tail.splitlines()[-5:]) if captured_tail else ""
    matches = list(_SENTINEL_RE.finditer(last_lines))
    if not matches:
        return None, ""
    m = matches[-1]
    return m.group(1), (m.group(2) or "")


def _should_emit_stream_line(line: str, verbose: bool) -> bool:
    """Return True when line should be forwarded to stderr from the agent read loop.

    verbose=False (default): only result-type events and non-JSON lines.
    verbose=True  (--verbose): all non-system events and non-JSON lines.
    """
    try:
        ev = json.loads(line)
        event_type = ev.get("type")
        if event_type == "system":
            return False
        return verbose or event_type == "result"
    except (json.JSONDecodeError, AttributeError):
        return True


def _extract_text_from_stream_event(event: dict) -> str:
    """Extract human-readable text from a stream-json CLI event.

    Handles two event types that carry agent text output:
    - "assistant": collects text from all text-type content blocks.
    - "result": returns the result field (the agent's final text output).

    Returns "" for all other event types (system, user, etc.).
    """
    if not isinstance(event, dict):
        return ""
    event_type = event.get("type", "")

    if event_type == "assistant":
        message = event.get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)

    if event_type == "result":
        result_text = event.get("result", "")
        return result_text if isinstance(result_text, str) else ""

    return ""


def _extract_usage_from_result_event(event: dict) -> tuple[Optional[int], Optional[int]]:
    """Extract (input_tokens, output_tokens) from a stream-json result event.

    Returns (None, None) if the event is not a result event, if usage data
    is absent, or if any token count is not a valid non-negative integer.
    """
    if not isinstance(event, dict) or event.get("type") != "result":
        return None, None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None, None
    try:
        raw_input = usage.get("input_tokens")
        raw_output = usage.get("output_tokens")
        input_tok = int(raw_input) if raw_input is not None else None
        output_tok = int(raw_output) if raw_output is not None else None
        if input_tok is not None and input_tok < 0:
            raise ValueError("negative input_tokens")
        if output_tok is not None and output_tok < 0:
            raise ValueError("negative output_tokens")
    except (ValueError, TypeError):
        return None, None
    return input_tok, output_tok


class _StreamAccumulator:
    """Accumulates agent text, token usage, and metrics events from stream-json CLI lines.

    A single line at a time is fed via ``feed()``. Both the live
    ``invoke_agent`` read loop and the batch ``_accumulate_stream_text``
    helper drive the same ``feed()`` logic, so tests that exercise the
    batch form cover the exact parsing the production loop uses.
    """

    __slots__ = (
        "text_parts", "input_tokens", "output_tokens",
        "init_event", "retry_count", "retry_errors", "result_event",
    )

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.input_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None
        self.init_event: Optional[dict] = None
        self.retry_count: int = 0
        self.retry_errors: list[str] = []
        self.result_event: Optional[dict] = None

    def feed(self, line: str) -> None:
        """Parse one stream-json line, collecting text, tokens, and metrics events.

        Blank lines are ignored. A non-JSON line is kept as plain text so
        CLI startup messages remain visible in diagnostics.
        """
        stripped = line.strip()
        if not stripped:
            return
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            self.text_parts.append(line.rstrip("\n"))
            return

        # Capture events needed for per-cycle metrics.
        event_type = event.get("type", "")
        event_subtype = event.get("subtype", "")
        if event_type == "system":
            if event_subtype == "init":
                self.init_event = event
            elif event_subtype == "api_retry":
                self.retry_count += 1
                error = event.get("error")
                if error is not None:
                    self.retry_errors.append(str(error))
        elif event_type == "result":
            self.result_event = event

        text = _extract_text_from_stream_event(event)
        if text:
            self.text_parts.append(text)
        inp, out = _extract_usage_from_result_event(event)
        if inp is not None:
            self.input_tokens = inp
        if out is not None:
            self.output_tokens = out

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts)


def _accumulate_stream_text(
    lines: list[str],
) -> tuple[str, Optional[int], Optional[int]]:
    """Batch form of the ``invoke_agent`` stream-json accumulation loop.

    Parses each line as a stream-json event and returns
    ``(agent_text, input_tokens, output_tokens)``. Shares ``feed()`` with
    the live loop so it is a faithful stand-in for testing.
    """
    acc = _StreamAccumulator()
    for line in lines:
        acc.feed(line)
    return acc.text, acc.input_tokens, acc.output_tokens


def _build_opening_announcement(
    agent_def: AgentDef,
    work_item: WorkItem,
    session_id: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "session_id": session_id,
        "agent": agent_def.agent,
        "phase": "start",
        "started_at": now,
        "intent": agent_def.description[:120],
    }
    if work_item.kind == "issue":
        payload["branch"] = f"issue-{work_item.number}"
    return (
        f"<!-- ai-agile/announcement/v1 by {agent_def.agent} -->\n"
        f"```json\n"
        f"{json.dumps(payload, indent=2)}\n"
        f"```"
    )


def _build_closing_announcement(
    agent_def: AgentDef,
    work_item: WorkItem,
    session_id: str,
    outcome: str,
    summary: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "session_id": session_id,
        "agent": agent_def.agent,
        "phase": "end",
        "ended_at": now,
        "outcome": outcome,
        "summary": summary,
    }
    if work_item.kind == "issue":
        payload["branch"] = f"issue-{work_item.number}"
    return (
        f"<!-- ai-agile/announcement/v1 by {agent_def.agent} -->\n"
        f"```json\n"
        f"{json.dumps(payload, indent=2)}\n"
        f"```"
    )


def _apply_terminal_status(
    gh: GitHubClient,
    agent_def: AgentDef,
    work_item: WorkItem,
    status: str,
) -> None:
    """Clear all non-terminal status labels and apply the given terminal status.

    Mirrors _apply_failed's cleanup so the work item always ends with exactly
    one status label regardless of which non-terminal state the step left behind.
    Includes STATUS_REQUESTED so a failed :requested-removal earlier in the
    invocation path cannot leave a stale :requested alongside the terminal label.
    """
    for stale in (STATUS_WIP, STATUS_REVIEW, STATUS_BLOCKED, STATUS_REQUESTED):
        try:
            gh.remove_label(work_item.number, agent_def.status_label(stale))
        except Exception as exc:
            log.debug(
                "could not remove :%s for %s on #%d: %s",
                stale, agent_def.agent, work_item.number, exc,
            )
    try:
        gh.add_label(work_item.number, agent_def.status_label(status))
    except Exception as exc:
        log.error(
            "could not apply :%s for %s on #%d: %s — re-applying :wip to restore a recoverable state",
            status, agent_def.agent, work_item.number, exc,
        )
        try:
            gh.add_label(work_item.number, agent_def.status_label(STATUS_WIP))
        except Exception as inner:
            log.error(
                "could not re-apply :wip for %s on #%d: %s — item has no status label",
                agent_def.agent, work_item.number, inner,
            )


# ---------------------------------------------------------------------------
# Script invocation (type: script pipeline steps)
# ---------------------------------------------------------------------------

def invoke_script(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
) -> AgentRunResult:
    """Invoke a script-type pipeline step directly via bash.

    The script receives the same environment variables as an agent
    ($REPO, $ISSUE_NUMBER / $PR_NUMBER, $WORK_ITEM_KIND, etc.) and must
    emit AI_AGILE_STATUS: complete|review|blocked as the last output line.
    The orchestrator reads the sentinel and applies the matching label.

    No Claude CLI is invoked. Rate-limit detection is not applicable.
    """
    if not agent_def.script_path:
        log.warning("    Script step %s has no script path — skipping", agent_def.agent)
        return AgentRunResult(
            success=False,
            captured_tail=f"pipeline.json entry '{agent_def.agent}' has type:script but no script field.",
        )

    script_file = SUBMODULE_ROOT / agent_def.script_path
    if not script_file.exists():
        log.warning("    Script not found: %s — skipping", script_file)
        return AgentRunResult(
            success=False,
            captured_tail=f"Script not found at {script_file}.",
        )

    if dry_run:
        log.info(
            "    [DRY RUN] script: %s | script_file: %s",
            agent_def.agent, script_file,
        )
        return AgentRunResult(success=True)

    log.info("    Invoking script: %s on %s #%d", agent_def.agent, work_item.kind, work_item.number)
    log.debug("    script_file: %s", script_file)

    agent_env = {
        **os.environ,
        "STATUS_SH":        str(STATUS_SH),
        "AI_AGILE_ROOT":    os.environ.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT)),
        "AI_AGILE_CONTEXT": str(AI_AGILE_CONTEXT),
        "REPO":             repo,
        "WORK_ITEM_KIND":   work_item.kind,
        "WORK_ITEM_NUMBER": str(work_item.number),
        # SESSION_ID / SESSION_SCOPE are not meaningful for script steps (no
        # Claude CLI session), but are exported so scripts can reference them
        # in announcement output without having to special-case the env.
        "SESSION_ID":       f"script-{agent_def.agent}-{work_item.number}",
        "SESSION_SCOPE":    "per_issue",
    }
    if work_item.kind == "issue":
        agent_env["ISSUE_NUMBER"] = str(work_item.number)
    else:
        agent_env["PR_NUMBER"] = str(work_item.number)

    MAX_SCRIPT_CAPTURED_LINES = 500
    captured_lines: list[str] = []

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            ["bash", str(script_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=agent_env,
        )
        deadline = time.monotonic() + agent_def.script_timeout_seconds
        try:
            if proc.stdout is None:
                raise RuntimeError("subprocess stdout pipe unexpectedly None")
            for line in proc.stdout:
                sys.stderr.write(line)
                if len(captured_lines) < MAX_SCRIPT_CAPTURED_LINES:
                    captured_lines.append(line)
                # Deadline is checked at line boundaries; a script that holds
                # stdout open without emitting a newline can run slightly over
                # the configured timeout before the raise fires.
                if time.monotonic() > deadline:
                    raise subprocess.TimeoutExpired(["bash", str(script_file)], agent_def.script_timeout_seconds)
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log.error("    Script %s timed out on #%d", agent_def.agent, work_item.number)
            _terminate_subprocess(proc)
            return AgentRunResult(
                success=False,
                returncode=proc.returncode,
                captured_tail=(
                    f"Script timed out after {agent_def.script_timeout_seconds}s.\n\n"
                    f"Last output:\n{_captured_tail(captured_lines)}"
                ),
            )

        success = proc.returncode == 0
        return AgentRunResult(
            success=success,
            returncode=proc.returncode,
            captured_tail=_captured_tail(captured_lines),
        )

    except FileNotFoundError:
        log.error("    'bash' not found — cannot run script step")
        return AgentRunResult(success=False, captured_tail="bash not found in PATH.")
    finally:
        # Guard against unexpected exceptions leaving a zombie subprocess.
        if proc is not None:
            _terminate_subprocess(proc)



def _compute_agent_session_id(agent_def: AgentDef, work_item: WorkItem, repo: str) -> str:
    """Return the human-readable session ID the orchestrator will pass to the agent.

    Deterministic for a given (agent, work_item, repo) triple so the same
    session ID is reused across separate orchestrator invocations for the same
    work item (providing Claude-level conversation continuity). Retries within
    a single invocation append a '-r{N}' suffix via the caller.
    """
    owner, _, repo_name = repo.partition("/")
    safe_agent = re.sub(r"[^a-z0-9-]", "-", agent_def.agent.lower()).strip("-")
    safe_phase  = re.sub(r"[^a-z0-9-]", "-", agent_def.phase.lower()).strip("-")
    safe_repo   = re.sub(r"[^a-z0-9-]", "-", repo.lower()).strip("-")

    session_tokens: dict[str, str] = {
        "agent":      agent_def.agent,
        "safe_agent": safe_agent,
        "phase":      agent_def.phase,
        "safe_phase": safe_phase,
        "number":     str(work_item.number),
        "kind":       work_item.kind,
        "owner":      owner,
        "repo_name":  repo_name,
        "safe_repo":  safe_repo,
    }

    def _scope_default() -> str:
        if agent_def.session_scope == "global":
            return f"ais-v1-{safe_agent}"
        return f"ais-v1-{safe_agent}-issue-{work_item.number}"

    if agent_def.session_id_pattern:
        _tok_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
        try:
            if re.search(r"\{[^}]*[.\[][^}]*\}", agent_def.session_id_pattern):
                raise ValueError("unsafe attribute/index access in id_pattern")
            sid = _tok_re.sub(
                lambda m: session_tokens[m.group(1)],
                agent_def.session_id_pattern,
            )
        except (KeyError, ValueError) as exc:
            log.warning("Bad id_pattern for %s (%s); using scope default", agent_def.agent, exc)
            sid = _scope_default()
    else:
        sid = _scope_default()

    _sid_re = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    if not _sid_re.match(sid):
        sanitised = re.sub(r"[^a-z0-9-]", "-", sid.lower()).strip("-")
        log.warning("Session ID %r for %s contains invalid chars; sanitised to %r",
                    sid, agent_def.agent, sanitised)
        sid = sanitised
    return sid


# Explicit allowlist of environment variables passed through from the
# orchestrator's own environment into each Claude agent subprocess.
#
# We deliberately do NOT hand the agent `{**os.environ}`: agents read UNTRUSTED
# issue/PR content and a prompt-injected agent can read its own
# /proc/self/environ. If the full environment were inherited, the agent could
# exfiltrate any secret the orchestrator holds. In particular this list MUST
# NOT contain AI_AGILE_BOT_TOKEN (workflow-scope push token) nor the
# GIT_CONFIG_COUNT / GIT_CONFIG_KEY_0 / GIT_CONFIG_VALUE_0 git-auth header set
# by _wake (that base64 header embeds GITHUB_TOKEN). Only process essentials,
# the agent's own API key, and a gh token for the agent's read/comment calls
# are passed through here. ANTHROPIC_API_KEY is then dropped again for
# interactive runs, which inherit the session's own auth instead (issue #346);
# see _build_agent_env. Work-item context vars (AI_AGILE_ROOT, REPO,
# ISSUE_NUMBER, etc.) are set explicitly in _build_agent_env, not passed through.
AGENT_ENV_PASSTHROUGH = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "ANTHROPIC_API_KEY",   # the agent's Claude CLI auth
    "GH_TOKEN",            # the agent's gh read/comment calls
    "GITHUB_TOKEN",
    # Network reachability (non-secret): let the agent's Claude CLI and gh reach
    # the API through a proxy / custom CA when the runner requires one. Harmless
    # on GitHub-hosted runners where these are unset.
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
)

# The env keys resolve-only mode (--print-prompt) may print. That output goes to
# stdout and /run-agent captures it inside an interactive session, so it is built
# by naming exactly what may be exported -- never by subtracting known-bad keys
# from the full env. A denylist would start leaking the moment a new credential
# joined AGENT_ENV_PASSTHROUGH; this list stays silent about anything it does not
# name. These are the agent-facing context vars documented in AGENTS.md. Host
# plumbing inherited from the ambient environment (PATH, HOME, proxy and CA
# settings, and every credential) is deliberately absent: it is not part of the
# agent contract, and a consumer that needs it already has it. invoke_agent's
# real subprocess env is unaffected.
PRINT_PROMPT_ENV_KEYS = (
    "AI_AGILE_ROOT",
    "AI_AGILE_CONTEXT",
    "AI_AGILE_EXECUTION_MODE",
    "REPO",
    "WORK_ITEM_KIND",
    "WORK_ITEM_NUMBER",
    "SESSION_ID",
    "SESSION_SCOPE",
    "ISSUE_NUMBER",
    "PR_NUMBER",
)


# How long the auth probe below waits for the CLI to answer a trivial prompt.
CLAUDE_PROBE_TIMEOUT_SECONDS = 90

# Probe results, keyed by whether the probed env carried an ANTHROPIC_API_KEY.
# The probe spawns a CLI process, so each distinct case runs at most once per
# orchestrator run.
_CLAUDE_CLI_PROBE: dict[bool, bool] = {}


def _claude_cli_usable(env: Mapping[str, str]) -> bool:
    """True when the Claude CLI can actually authenticate using ``env``.

    Determined by running the CLI, not by guessing from where credentials
    happen to be stored. The previous check tested for
    ``$HOME/.claude/.credentials.json``, which is only one of the ways the CLI
    can be authenticated: inside a Claude Code session the CLI is authenticated
    by the harness with no API key and no credentials file, so the file test
    false-negatived and refused spawns that would have succeeded (issue #346).

    ``env`` is the environment the agent subprocess will actually receive, so a
    successful probe means that spawn can authenticate -- not merely that this
    process could. Cached per run; failures are cached too, since a static
    environment will not start working on a retry.
    """
    key = env.get("ANTHROPIC_API_KEY") is not None
    if key not in _CLAUDE_CLI_PROBE:
        try:
            probe = subprocess.run(
                ["claude", "-p", "Reply with exactly: ok"],
                env=dict(env),
                capture_output=True,
                text=True,
                timeout=CLAUDE_PROBE_TIMEOUT_SECONDS,
            )
            _CLAUDE_CLI_PROBE[key] = probe.returncode == 0
            if probe.returncode != 0:
                log.debug(
                    "  claude CLI auth probe failed (rc=%d): %s",
                    probe.returncode, (probe.stderr or "").strip()[:300],
                )
        except Exception as exc:
            log.debug("  claude CLI auth probe could not run: %s", exc)
            _CLAUDE_CLI_PROBE[key] = False
    return _CLAUDE_CLI_PROBE[key]


def _build_agent_env(
    base_env: Mapping[str, str],
    repo: str,
    work_item: WorkItem,
    agent_session_id: str,
    session_scope: str,
) -> dict[str, str]:
    """Build the environment for a Claude agent subprocess.

    Starts from an explicit allowlist of `base_env` keys (AGENT_ENV_PASSTHROUGH)
    rather than the full environment, so orchestrator-only secrets
    (AI_AGILE_BOT_TOKEN, GIT_CONFIG_* git-auth header) are never inherited by a
    potentially prompt-injected agent. The work-item context vars are then set
    explicitly, matching what agents document in AGENTS.md.
    """
    agent_env = {k: base_env[k] for k in AGENT_ENV_PASSTHROUGH if k in base_env}
    # Export resolved paths so the agent prompt's bash snippets work regardless
    # of CWD or where this repo is mounted in the consuming repo. Only one of
    # ISSUE_NUMBER / PR_NUMBER is set, matching the work item's kind, so the
    # agent's prompt cannot get them confused.
    agent_env["AI_AGILE_ROOT"] = base_env.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT))
    agent_env["AI_AGILE_CONTEXT"] = str(AI_AGILE_CONTEXT)
    agent_env["REPO"] = repo
    agent_env["WORK_ITEM_KIND"] = work_item.kind
    agent_env["WORK_ITEM_NUMBER"] = str(work_item.number)
    agent_env["SESSION_ID"] = agent_session_id
    agent_env["SESSION_SCOPE"] = session_scope
    if work_item.kind == "issue":
        agent_env["ISSUE_NUMBER"] = str(work_item.number)
    else:
        agent_env["PR_NUMBER"] = str(work_item.number)
    # Axis B: every orchestrator-spawned subprocess is always headless/opaque,
    # regardless of whether the tick itself was triggered by cron or interactively.
    agent_env["AI_AGILE_EXECUTION_MODE"] = "headless"
    # An interactive run authenticates its agents the same way the surrounding
    # session is authenticated, never with a separate API key (issue #346). Only
    # the headless/CI path, which has no session to inherit, uses
    # ANTHROPIC_API_KEY. The key is kept as a fallback when the session's own
    # auth turns out not to work, so a developer running interactively with only
    # an API key is not locked out.
    if not _HEADLESS and "ANTHROPIC_API_KEY" in agent_env:
        _session_auth_env = {
            k: v for k, v in agent_env.items() if k != "ANTHROPIC_API_KEY"
        }
        if _claude_cli_usable(_session_auth_env):
            del agent_env["ANTHROPIC_API_KEY"]
    return agent_env


# Scoped base tool allowlist granted to every Claude agent. Each entry is a
# glob the bash command must match; keeping these narrow blocks a prompt-injected
# agent from reaching secrets/settings/branches. NOTE: the orchestrator owns the
# label lifecycle (AGENTS.md P-10/P-14). `gh pr edit` is NOT granted -- no agent
# has a legitimate use for it, and it would let an injected agent add a PR gate
# label. `gh issue edit` IS granted broadly because issue-classifier applies the
# routing `classification: {type}` label and sizer applies `epic,blocked` at
# runtime; narrowing it to specific --add-label globs is unsafe (a positive glob
# cannot permit those legitimate labels while denying gate labels like
# `prd-writer:approved` without risking the routing labels). The residual
# self-approval vector (via `gh issue edit` OR the REST issue-write grant below,
# which reaches PRs too since PRs are issues) is closed ORCHESTRATOR-SIDE: the
# gate check rejects any `{agent}:approved` label not applied by a human (#263).
BASE_AGENT_TOOLS = [
    "Bash(gh issue view *)",       # read issue body / labels
    "Bash(gh issue comment *)",    # post artefact comments
    "Bash(gh issue edit *)",       # prd-writer/sizer body rewrites + classifier/sizer routing labels
    "Bash(gh issue list *)",       # cross-issue reads (impact-assessor etc.)
    "Bash(gh pr view *)",          # PR-side agents read PR
    "Bash(gh pr comment *)",       # PR-side agents post comments
    "Bash(gh pr list *)",
    "Bash(gh pr diff *)",          # pr-reviewer reads the diff
    "Bash(gh api repos/*/issues/*)",  # narrow direct API; only issue/PR endpoints
    "Bash(gh api repos/*/pulls/*)",
    "Bash(gh api repos/*/issues*)",   # REST reads incl. list/query forms (issues?labels=...)
    "Bash(gh api repos/*/pulls*)",     # REST reads incl. list/query forms (pulls?head=...)
    # Quoted-URL counterparts of the four patterns above. Permission-rule matching
    # is literal-text prefix matching (a `*` spans characters, not shell tokens), so
    # an agent that quotes its URL argument (idiomatic, defensively-reasonable shell
    # style -- e.g. `gh api "repos/o/r/issues/1"`) needs its own pattern; the
    # unquoted pattern's literal ` repos/` never appears in that command's text
    # (issue #326).
    "Bash(gh api \"repos/*/issues/*)",
    "Bash(gh api \"repos/*/pulls/*)",
    "Bash(gh api \"repos/*/issues*)",
    "Bash(gh api \"repos/*/pulls*)",
    # REST WRITES on issues only (labels/comments/body) -- the in-session
    # equivalent of `gh issue edit`, needed because that command is GraphQL and
    # 403s in a restricted session. It carries the SAME gate-label self-approval
    # vector as `gh issue edit` (a positive glob cannot permit routing labels
    # while denying gate labels), which is closed ORCHESTRATOR-SIDE by the
    # human-actor gate check (#263). No `--method` grant on /pulls: agents never
    # write PRs (merge/ready/close are the orchestrator's/driver's job), so
    # granting it would hand an injected agent merge/close/retarget power.
    "Bash(gh api --method * repos/*/issues*)",
    "Bash(gh api --method * \"repos/*/issues*)",  # quoted-URL counterpart (#326)
    "Bash(cat *)",                 # read prompt-side files
    "Bash(grep *)",
    "Bash(find *)",
    "Read",
    "Glob",
    "Grep",
]


@dataclass
class ResolvedInvocation:
    """The fully-resolved parameters for one agent invocation, before spawning.

    env is not included: callers build it via _build_agent_env and set
    AI_AGILE_EXECUTION_MODE according to their context (headless for real
    subprocess spawns, interactive for the resolve-only /run-agent path).
    """
    prompt: str
    allowed_tools: list[str]
    model: Optional[str]
    max_turns: int
    session_id: str


def _resolve_agent_invocation(
    agent_def: AgentDef,
    work_item: WorkItem,
    repo: str,
    agent_text_override: Optional[str] = None,
    default_extra_tools: Optional[list[str]] = None,
) -> Optional["ResolvedInvocation"]:
    """Resolve an agent invocation's prompt and tool allowlist without spawning.

    Returns a ResolvedInvocation, or None when the agent file cannot be found.
    This is the single source of truth for prompt assembly and tool allowlist
    construction -- both invoke_agent (real spawn) and the resolve-only
    --print-prompt path call this so the two can never drift apart.
    """
    agent_file = SUBMODULE_ROOT / ".claude/agents" / f"{agent_def.agent}.md"

    if agent_text_override is not None:
        agent_text = agent_text_override
    elif not agent_file.exists():
        log.warning("    Agent file not found: %s", agent_file)
        return None
    else:
        agent_text = agent_file.read_text()

    frontmatter = parse_frontmatter(agent_text)
    agent_model: Optional[str] = frontmatter.get("model")  # type: ignore[assignment]
    _frontmatter_extra: list[str] = _coerce_tools(frontmatter.get("extra_allowedTools"))
    extra_tools = list(dict.fromkeys(
        list(default_extra_tools or []) +
        list(agent_def.extra_allowedTools) +
        _frontmatter_extra
    ))
    try:
        max_turns = int(frontmatter.get("max_turns", DEFAULT_MAX_TURNS))
    except (ValueError, TypeError):
        max_turns = DEFAULT_MAX_TURNS

    agents_md = AI_AGILE_CONTEXT.read_text() if AI_AGILE_CONTEXT.exists() else ""
    agent_body = _strip_frontmatter(agent_text)
    num_var = "ISSUE_NUMBER" if work_item.kind == "issue" else "PR_NUMBER"
    kind_label = "Issue" if work_item.kind == "issue" else "PR"
    agent_session_id = _compute_agent_session_id(agent_def, work_item, repo)

    prompt = (
        f"{agents_md}\n\n"
        f"---\n\n"
        f"## Your instructions\n\n"
        f"{agent_body}\n\n"
        f"---\n\n"
        f"## This run\n\n"
        f"Agent: {agent_def.agent}\n"
        f"{kind_label}: #{work_item.number} in {repo}\n"
        f"URL: {work_item.url}\n\n"
        f"## Runtime context\n\n"
        f"REPO={repo.strip()}\n"
        f"{num_var}={work_item.number}\n"
        f"WORK_ITEM_KIND={work_item.kind}\n"
        f"SESSION_ID={agent_session_id.strip()}\n"
        f"SESSION_SCOPE={agent_def.session_scope.strip()}\n"
        f"AI_AGILE_ROOT={os.environ.get('AI_AGILE_ROOT', str(SUBMODULE_ROOT)).strip()}\n"
        f"AI_AGILE_CONTEXT={str(AI_AGILE_CONTEXT).strip()}\n\n"
        f"Print exactly one of these as the last line before exiting:\n"
        f"AI_AGILE_STATUS: complete\n"
        f"AI_AGILE_STATUS: review \"short message\"\n"
        f"AI_AGILE_STATUS: blocked \"reason\"\n"
        f"(No leading spaces — the orchestrator's regex matches only at line start.)\n"
        f"The orchestrator reads this sentinel, applies the label, and posts the closing announcement."
    )

    return ResolvedInvocation(
        prompt=prompt,
        allowed_tools=BASE_AGENT_TOOLS + extra_tools,
        model=agent_model,
        max_turns=max_turns,
        session_id=agent_session_id,
    )


def invoke_agent(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
    attempt: int = 0,
    agent_text_override: Optional[str] = None,
    default_extra_tools: Optional[list[str]] = None,
) -> AgentRunResult:
    """
    Invoke the agent via claude CLI.

    Agents signal their outcome by emitting a sentinel line to stdout:

      AI_AGILE_STATUS: complete
      AI_AGILE_STATUS: review "short message for stakeholder"
      AI_AGILE_STATUS: blocked "reason the agent could not proceed"

    The orchestrator parses the sentinel, applies the matching label, and
    posts the closing announcement. Agents must NOT call status.sh for
    ceremony -- set-wip, opening/closing announcements, and final label
    transitions are all handled here. set-failed is applied by the
    orchestrator when the agent exits non-zero without a sentinel after
    all retries are exhausted.

    Returns an AgentRunResult with success/returncode/captured_tail and
    a rate_limited flag (set when a pause was written). Caller MUST NOT
    apply :failed when rate_limited is True -- the agent never got a fair
    run.
    """
    resolved = _resolve_agent_invocation(
        agent_def, work_item, repo, agent_text_override, default_extra_tools
    )
    if resolved is None:
        agent_file = SUBMODULE_ROOT / ".claude/agents" / f"{agent_def.agent}.md"
        return AgentRunResult(
            success=False,
            captured_tail=f"Agent prompt file not found at {agent_file}.",
        )

    prompt = resolved.prompt
    agent_model = resolved.model
    max_turns = resolved.max_turns
    agent_session_id = resolved.session_id
    # Build env with headless execution mode -- every orchestrator-spawned
    # subprocess is axis-B headless regardless of the tick's trigger source.
    # _build_agent_env already sets AI_AGILE_EXECUTION_MODE="headless".
    agent_env = _build_agent_env(
        os.environ, repo, work_item, agent_session_id, agent_def.session_scope
    )

    if dry_run:
        log.info(
            "    [DRY RUN] %s | model: %s | max_turns: %d | session: %s (uuid: %s) | prompt: %d chars",
            agent_def.agent, agent_model or "default", max_turns,
            agent_session_id, str(uuid.uuid5(_SESSION_NAMESPACE, agent_session_id)), len(prompt),
        )
        return AgentRunResult(success=True)

    # The claude CLI requires a valid UUID for --session-id.
    # Derive one deterministically from our human-readable key via UUID v5.
    # On retries (attempt > 0) we append "-r{attempt}" to the seed so each
    # retry gets a fresh UUID — avoids "Session ID already in use" when a
    # previous run's session was not cleaned up (e.g. CI job killed mid-run).
    session_uuid_seed = agent_session_id if attempt == 0 else f"{agent_session_id}-r{attempt}"
    agent_session_uuid = str(uuid.uuid5(_SESSION_NAMESPACE, session_uuid_seed))

    # The session id is deterministic on purpose: an agent REUSES the same Claude
    # conversation across orchestrator runs (continuity managed through the CLI).
    # But passing --session-id for an id that already exists errors ("Session ID
    # already in use") -- which strands re-runs in a persistent environment.
    # Resume the session when it already exists; create it (--session-id) only
    # when it does not (first run, or a fresh -r{attempt} retry id).
    _proj_dir = os.getcwd().replace("/", "-")
    _home = os.environ.get("HOME") or os.path.expanduser("~")
    _session_file = os.path.join(_home, ".claude", "projects", _proj_dir, f"{agent_session_uuid}.jsonl")
    _session_flag = "--resume" if os.path.isfile(_session_file) else "--session-id"

    log.info("    Invoking agent: %s on %s #%d", agent_def.agent, work_item.kind, work_item.number)
    log.info("    session: %s (uuid: %s, scope=%s)", agent_session_id, agent_session_uuid, agent_def.session_scope)
    if agent_model:
        log.debug("    model: %s", agent_model)
    log.debug("    max_turns: %d | prompt: %d chars", max_turns, len(prompt))

    cmd = [
        "claude",
        "--allowedTools", ",".join(resolved.allowed_tools),
        # Pipeline agents do their work with the allowlisted tools only; they must
        # NOT spawn sub-agents or invoke skills/slash-commands. In a trusted
        # workspace the CLI exposes Task/Agent/Skill even though they are absent
        # from --allowedTools, which let prd-writer recursively re-invoke itself
        # via the run-agent skill (a ~440s nested sub-agent). Deny them explicitly.
        "--disallowedTools", "Task,Agent,Skill",
        "--output-format", "stream-json",
        "--verbose",                    # required alongside stream-json in --print mode
        "--max-turns", str(max_turns),
        _session_flag, agent_session_uuid,
    ]
    if agent_model:
        cmd += ["--model", agent_model]
    cmd += ["-p", prompt]

    # Preflight: the agent's Claude CLI needs some usable auth. Normally that is
    # ANTHROPIC_API_KEY (CI secret); when it is absent the CLI can still be
    # authenticated via a logged-in session (subscription / OAuth) whose
    # credentials live under $HOME (passed through in AGENT_ENV_PASSTHROUGH).
    # Only fail when NEITHER is available -- an unauthenticated launch otherwise
    # produces an auth-error the stream-json parser may misread as a rate-limit
    # pause, leaving the work item stuck in :wip.
    if not _claude_cli_usable(agent_env):
        log.error(
            "  invoke_agent: the Claude CLI cannot authenticate with the agent's "
            "environment for %s on %s #%d. An interactive run inherits the "
            "session's own auth; a headless run needs ANTHROPIC_API_KEY or a "
            "logged-in CLI (`claude login`). Fix the auth, then retry.",
            agent_def.agent, work_item.kind, work_item.number,
        )
        return AgentRunResult(
            success=False,
            captured_tail=(
                "Configuration error: the Claude CLI cannot authenticate with "
                "the agent's environment. Interactive runs use this session's "
                "auth; headless runs need ANTHROPIC_API_KEY or `claude login`."
            ),
        )

    # Capture the stream-json output line-by-line. Each line is a JSON event;
    # we parse it immediately to extract agent text (for sentinel/rate-limit
    # detection) and token usage (from the result event). We also retain the
    # raw lines (capped) so the tail can appear in diagnostic comments.
    MAX_CAPTURED_LINES = 5000
    captured_lines: list[str] = []       # raw NDJSON lines (for diagnostics)
    acc = _StreamAccumulator()           # agent text + token usage from events

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=agent_env,
        )
        deadline = time.monotonic() + AGENT_TIMEOUT_SECONDS
        # Wall-clock timer fires unconditionally — unlike the per-line check
        # below, it also fires when the agent hangs without emitting output.
        # _timed_out lets the loop raise TimeoutExpired with a clear message
        # even when stdout goes silent (no lines arrive to trigger the check).
        _timed_out = threading.Event()
        def _timer_callback() -> None:
            _timed_out.set()
            _terminate_subprocess(proc)
        _kill_timer = threading.Timer(AGENT_TIMEOUT_SECONDS, _timer_callback)
        _kill_timer.daemon = True
        _kill_timer.start()
        try:
            if proc.stdout is None:
                raise RuntimeError("subprocess stdout pipe unexpectedly None")
            for line in proc.stdout:
                # Mirror to our stderr so the subprocess log is visible in the
                # orchestrator's CI output. Verbosity controlled by _VERBOSE:
                # default emits only result-type events; --verbose emits all
                # non-system events. Non-JSON lines are always forwarded.
                if _should_emit_stream_line(line, _VERBOSE):
                    sys.stderr.write(line)
                if len(captured_lines) < MAX_CAPTURED_LINES:
                    captured_lines.append(line)
                # Shared with _accumulate_stream_text so tests cover this path.
                acc.feed(line)
                if time.monotonic() > deadline or _timed_out.is_set():
                    raise subprocess.TimeoutExpired(cmd, AGENT_TIMEOUT_SECONDS)
            # Timer may have fired and drained stdout without triggering the
            # per-line check above (process died between lines). Raise here so
            # the timeout path is always taken when the timer fired.
            if _timed_out.is_set():
                raise subprocess.TimeoutExpired(cmd, AGENT_TIMEOUT_SECONDS)
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            log.error("    Agent %s timed out on #%d", agent_def.agent, work_item.number)
            _terminate_subprocess(proc)
            agent_text = acc.text
            agent_tail = _captured_tail([l + "\n" for l in agent_text.splitlines()])
            return AgentRunResult(
                success=False,
                returncode=proc.returncode,
                captured_tail=(
                    f"Agent timed out after {AGENT_TIMEOUT_SECONDS}s.\n\n"
                    f"Last output:\n{agent_tail}"
                ),
                input_tokens=acc.input_tokens,
                output_tokens=acc.output_tokens,
                init_event=acc.init_event,
                result_event=acc.result_event,
                retry_count=acc.retry_count,
                retry_errors=list(acc.retry_errors),
            )
        finally:
            _kill_timer.cancel()

        # Build the agent's text output for sentinel and rate-limit detection.
        # Text is accumulated from assistant message events (incremental) and
        # the result event (final); the sentinel appears at the end of this text.
        agent_text = acc.text
        agent_tail = _captured_tail([l + "\n" for l in agent_text.splitlines()])

        # On non-zero exit, check whether the cause was a rate-limit
        # error from the Anthropic API. If so, pause the pipeline so
        # subsequent runs back off rather than burning more requests.
        if proc.returncode != 0:
            is_limited, retry_after = detect_rate_limit(agent_text)
            if is_limited:
                until = pause_pipeline(
                    retry_after,
                    reason=(
                        f"Anthropic API rate limit while invoking "
                        f"{agent_def.agent} on {work_item.kind} #{work_item.number}"
                    ),
                )
                log.error(
                    "    Rate limit detected. Pipeline paused until %s.",
                    until.isoformat(),
                )
                return AgentRunResult(
                    success=False,
                    returncode=proc.returncode,
                    rate_limited=True,
                    captured_tail=agent_tail,
                    input_tokens=acc.input_tokens,
                    output_tokens=acc.output_tokens,
                    init_event=acc.init_event,
                    result_event=acc.result_event,
                    retry_count=acc.retry_count,
                    retry_errors=list(acc.retry_errors),
                )
            return AgentRunResult(
                success=False,
                returncode=proc.returncode,
                captured_tail=agent_tail,
                input_tokens=acc.input_tokens,
                output_tokens=acc.output_tokens,
                init_event=acc.init_event,
                result_event=acc.result_event,
                retry_count=acc.retry_count,
                retry_errors=list(acc.retry_errors),
            )

        return AgentRunResult(
            success=True,
            returncode=0,
            captured_tail=agent_tail,
            input_tokens=acc.input_tokens,
            output_tokens=acc.output_tokens,
            init_event=acc.init_event,
            result_event=acc.result_event,
            retry_count=acc.retry_count,
            retry_errors=list(acc.retry_errors),
        )

    except FileNotFoundError:
        log.error("    'claude' CLI not found. Install: npm install -g @anthropic-ai/claude-code")
        return AgentRunResult(
            success=False,
            captured_tail="claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code",
        )


# ---------------------------------------------------------------------------
# Gate promotion
# ---------------------------------------------------------------------------

def promote_gated_agents(
    labels: set[str],
    agents: list[AgentDef],
    work_item: WorkItem,
    gh: GitHubClient,
    *,
    session_id: str = "",
    repo: str = "",
) -> set[str]:
    """Find every gated agent currently in :review whose gate label is
    now present, and transition it from :review to :complete.

    Why this exists. Both mid-run blocks (agent emits AI_AGILE_STATUS: review)
    and post-completion human gates (human_gate_after: true — orchestrator
    applies :review on the agent's behalf after it emits :complete) land the
    work item in :review. When the human applies the gate label
    (e.g. prd-writer:approved or prd-docs-updater:approved), no event reaches
    the agent — the orchestrator is the actor that closes the loop.

    Promotion only fires when the agent is **actually in :review**. If
    the human applies the gate label before the agent has run, the
    agent has no `:review` (or any other) status; we leave it alone so
    the agent runs first, applies `:review`, and is promoted on the
    next tick. If the agent is in any non-`:review` non-terminal state
    (`:wip`, `:blocked`, `:failed`), promotion is also skipped — those
    states each need their own resolution.

    Order of operations is **add :complete BEFORE remove :review** so
    that a crash mid-promotion leaves the work item with both labels
    rather than no agent status. The next tick observes `:complete`
    (terminal) and treats the agent as done; the stale `:review` is
    cleaned up by this same function on the next call.

    Returns the updated label set so the caller can use it for the
    per-agent eligibility loop without re-fetching from GitHub.
    """
    updated = set(labels)
    for agent_def in agents:
        if not agent_def.human_gate_after or not agent_def.human_gate_label:
            continue
        if work_item.kind not in agent_def.objects:
            continue

        review_label = agent_def.review_label
        complete_label = agent_def.complete_label
        gate_label = agent_def.human_gate_label
        requested_label = agent_def.status_label(STATUS_REQUESTED)

        # A gate label only counts when a human applied it. A prompt-injected
        # agent that self-applied its own {agent}:approved label (a bot actor
        # since PR #262) must NOT promote itself past the gate. Fail-open on any
        # API error (see _gate_label_human_applied). Short-circuit avoids the
        # events lookup entirely when the label is absent.
        gate_present = gate_label in updated and _gate_label_human_applied(
            gh, repo or gh.repo, work_item.number, gate_label,
        )
        review_present = review_label in updated
        complete_present = complete_label in updated
        requested_present = requested_label in updated

        # Rejection: human commented and applied :requested while the agent
        # is in :review. Remove :review so :requested is the highest-priority
        # status on the next pass, triggering a re-run in the per-agent loop.
        if review_present and requested_present and not gate_present and not complete_present:
            try:
                gh.remove_label(work_item.number, review_label)
                updated.discard(review_label)
                log.info(
                    "  REJECT  %-38s  :requested while in :review → clearing :review for re-run",
                    agent_def.agent,
                )
                if session_id:
                    _emit_audit_event(_make_audit_event(
                        session_id, "gate.rejected", repo or gh.repo,
                        work_item=work_item, agent=agent_def.agent,
                        outcome_status="requested",
                        outcome_detail="human applied :requested — agent will re-run and read feedback",
                    ))
            except Exception as exc:
                log.error(
                    "  could not clear :review for rejection of %s on #%d: %s — pipeline state may be inconsistent",
                    agent_def.agent, work_item.number, exc,
                )
            continue

        # Standard promotion: gate applied while agent is in :review.
        if gate_present and review_present:
            try:
                # Add :complete first so a crash between add and remove
                # leaves the issue with both labels; the next tick sees
                # :complete and treats the agent as done regardless of
                # :review still being present.
                if not complete_present:
                    gh.add_label(work_item.number, complete_label)
                    updated.add(complete_label)
                gh.remove_label(work_item.number, review_label)
                updated.discard(review_label)
                # Clean up a stale :requested that arrived simultaneously with
                # :approved — promotion wins but :requested must not linger.
                if requested_label in updated:
                    try:
                        gh.remove_label(work_item.number, requested_label)
                        updated.discard(requested_label)
                    except Exception:
                        pass  # best-effort; stale label is cosmetic only
                log.info(
                    "  PROMOTE %-38s  %s applied → :review → :complete",
                    agent_def.agent, gate_label,
                )
                if session_id:
                    _emit_audit_event(_make_audit_event(
                        session_id, "gate.approved", repo or gh.repo,
                        work_item=work_item, agent=agent_def.agent,
                        outcome_status="complete",
                        outcome_detail=f"{gate_label} applied by human",
                    ))
            except Exception as exc:
                log.error(
                    "  could not promote %s on #%d: %s — pipeline state may be inconsistent",
                    agent_def.agent, work_item.number, exc,
                )
            continue

        # All other states (gate present without :review; gate present
        # with :wip / :blocked / :failed; gate not present at all) are
        # left alone. The agent runs / re-runs / is unblocked through
        # its normal flow; promotion only applies to the explicit
        # :review → :complete handoff.
    return updated


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

def _apply_failed(
    gh: GitHubClient,
    agent_def: AgentDef,
    work_item: WorkItem,
    result: AgentRunResult,
    *,
    reason: str = "",
    heading: str = "",
) -> None:
    """Apply :failed for an agent, clear any other non-terminal status it
    left behind, and post a diagnostic comment that includes the tail
    of the agent's captured output.

    Each step is wrapped in its own try/except so a partial failure
    (e.g. comment post fails after label was applied) is logged but
    never silently masks the :failed signal.

    Args:
        reason: Optional human-readable cause override for the comment footer.
            When set (and heading is not), it also changes the default heading
            from "exited with an error" to "completed — post-run step failed",
            implying the agent itself succeeded but a subsequent orchestrator
            step failed. Pass an explicit heading= to override this behaviour.
        heading: Optional heading override. When set it replaces the default
            heading so callers can distinguish retry-exhaustion failures from
            generic non-zero exits.
    """
    # Clear any non-terminal status the agent may have left behind so
    # the work item has exactly one status label after this. We only
    # touch this agent's labels — humans manage their own (skipped).
    for stale in (STATUS_WIP, STATUS_REVIEW, STATUS_BLOCKED, STATUS_REQUESTED):
        try:
            gh.remove_label(work_item.number, agent_def.status_label(stale))
        except Exception as exc:  # pragma: no cover — best-effort cleanup
            log.debug(
                "  could not remove %s during failed transition: %s",
                agent_def.status_label(stale), exc,
            )

    # Apply the :failed label. This is the load-bearing signal — if
    # everything else fails, the label is still on the issue and the
    # pipeline will halt.
    try:
        gh.add_label(work_item.number, agent_def.failed_label)
    except Exception as exc:
        log.error(
            "  could not apply %s on #%d: %s — pipeline state may be inconsistent",
            agent_def.failed_label, work_item.number, exc,
        )

    # Post the diagnostic comment. Wrapped because a comment-post
    # failure (rate limit, transient API blip, missing scope) must not
    # crash the orchestrator — the :failed label above is what gates
    # the pipeline.
    detail = result.captured_tail or "(no captured output)"
    footer = (
        reason
        if reason
        else "_Posted by the orchestrator after the agent subprocess exited non-zero "
             "without one of the three terminal status calls (set-complete / set-review / set-blocked)._"
    )
    heading = (
        heading
        if heading
        else (
            f"### `{agent_def.agent}` completed — post-run step failed"
            if reason
            else f"### `{agent_def.agent}` exited with an error"
        )
    )
    body_parts = [
        heading,
        "",
        f"Return code: `{result.returncode if result.returncode is not None else 'unknown'}`",
        "",
        "**Last output (tail):**",
        "",
        "```",
        detail,
        "```",
        "",
        "**To recover:**",
        f"- Fix the underlying error, then **remove** the `{agent_def.failed_label}` label to retry, or",
        f"- Apply the `{agent_def.skipped_label}` label to bypass this agent on this item.",
        "",
        footer,
    ]
    body = "\n".join(body_parts)
    try:
        gh.post_comment(work_item.number, body)
    except Exception as exc:
        log.error(
            "  could not post failure comment on #%d (%s); :failed label is still applied. "
            "Detail follows in this log:\n%s",
            work_item.number, exc, body,
        )


# ---------------------------------------------------------------------------
# Core orchestration logic
# ---------------------------------------------------------------------------

def _restore_pre_agent_branch(branch: str) -> None:
    """Restore the git branch saved before a pre-agent checkout, if any."""
    if not branch:
        return
    try:
        subprocess.run(["git", "checkout", branch], check=False, capture_output=True)
    except Exception:
        pass


def _should_run(
    agent_def: AgentDef,
    work_item: WorkItem,
    labels: set,
    pipeline_map: dict,
    concurrency: Optional[ConcurrencyState],
    gh=None,
    repo: str = "",
) -> Optional[bool]:
    """Evaluate whether an agent should be dispatched for a work item.

    Returns True to dispatch, False to skip (continue to next agent),
    or None to stop processing agents for this work item (aggregate ceiling hit).
    """
    if work_item.kind not in agent_def.objects:
        return False

    if agent_def.exclude_classifications and work_item.kind == "issue":
        _classification = get_work_item_classification(work_item)
        if _classification and _classification in agent_def.exclude_classifications:
            log.debug(
                "  skip %-40s  [classification '%s' excluded]",
                agent_def.agent, _classification,
            )
            return False

    if agent_def.exclude_labels:
        _blocking_label = next(
            (lbl for lbl in agent_def.exclude_labels if lbl in labels), None
        )
        if _blocking_label:
            log.debug(
                "  skip %-40s  [label '%s' excludes this agent]",
                agent_def.agent, _blocking_label,
            )
            return False

    current_status = agent_status(labels, agent_def.label_key)

    if current_status in (STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED):
        log.debug("  skip %-40s  [%s]", agent_def.agent, current_status)
        return False

    if current_status == STATUS_IN_PROGRESS:
        log.info("  wait %-40s  [wip]", agent_def.agent)
        return False

    # :review means awaiting a gate label or human reject; :blocked means
    # human intervention required. Re-invoking without human action would
    # loop indefinitely or duplicate the artefact.
    if current_status in HALT_STATUSES:
        log.info("  halt %-40s  [%s]", agent_def.agent, current_status)
        return False

    # :requested is a manual override — bypass trigger check.
    _manual_trigger = (current_status == STATUS_REQUESTED)

    if not _manual_trigger and not trigger_label_present(labels, agent_def):
        log.debug(
            "  skip %-40s  [trigger not met: %s]",
            agent_def.agent,
            agent_def.trigger.get("label", "event/schedule"),
        )
        return False

    if not dependencies_complete(
        labels, agent_def, pipeline_map,
        gh=gh, repo=repo, work_item_number=work_item.number,
    ):
        log.debug("  skip %-40s  [dependencies unmet]", agent_def.agent)
        return False

    if concurrency is not None:
        _running = concurrency.running_counts.get(agent_def.label_key, 0)
        if _running >= agent_def.max_concurrent:
            log.info(
                "  skip %-40s  [per-agent concurrency: %d/%d running]",
                agent_def.agent, _running, agent_def.max_concurrent,
            )
            return False
        # Aggregate pipeline ceiling: stop the loop when hit.
        if concurrency.tick_launch_count >= PIPELINE_MAX_CONCURRENT:
            log.info(
                "  ceiling %-38s  [pipeline max-concurrent: %d/%d launched this tick]",
                agent_def.agent, concurrency.tick_launch_count, PIPELINE_MAX_CONCURRENT,
            )
            return None

    return True


def _acquire_wip_and_announce(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    manual_trigger: bool,
    repo: str,
    labels: set,
    concurrency: Optional[ConcurrencyState],
    gh: "GitHubClient",
    pipeline_map: dict,
) -> None:
    """Pre-invocation ceremony: remove :requested, apply :wip, announce, cycle++.

    Applies the :wip status label and bumps concurrency counters (live or dry-run),
    posts the opening announcement, and increments review-cycle:N for re_invoke
    targets. Mutates labels and work_item.labels in-place.
    """
    if not dry_run:
        # Remove :requested before applying :wip so the work item never
        # carries two status labels simultaneously.
        if manual_trigger:
            try:
                gh.remove_label(work_item.number, agent_def.status_label(STATUS_REQUESTED))
                labels.discard(agent_def.status_label(STATUS_REQUESTED))
            except Exception as exc:
                log.debug(
                    "  could not remove :requested for %s on #%d: %s",
                    agent_def.agent, work_item.number, exc,
                )
        try:
            gh.add_label(work_item.number, agent_def.status_label(STATUS_WIP))
            labels.add(agent_def.status_label(STATUS_WIP))
            work_item.labels = labels
            # Track the in-flight :wip so a termination signal can clear it
            # rather than stranding the mutex (see _clear_inflight_wip_on_signal).
            global _CURRENT_WIP
            _CURRENT_WIP = (gh, work_item.number, agent_def.status_label(STATUS_WIP))
            # Increment only on successful label application — a failed
            # add_label means no :wip was set so no slot is consumed.
            if concurrency is not None:
                concurrency.running_counts[agent_def.label_key] = (
                    concurrency.running_counts.get(agent_def.label_key, 0) + 1
                )
                concurrency.tick_launch_count += 1
        except Exception as exc:
            log.error(
                "  could not apply :wip for %s on #%d: %s",
                agent_def.agent, work_item.number, exc,
            )
        try:
            # Use the agent's own deterministic session ID so the announcement
            # matches what the agent prints in its own start comment.
            _agent_sid = _compute_agent_session_id(agent_def, work_item, repo)
            gh.post_comment(
                work_item.number,
                _build_opening_announcement(agent_def, work_item, _agent_sid),
            )
        except Exception as exc:
            log.warning(
                "  could not post opening announcement for %s on #%d: %s",
                agent_def.agent, work_item.number, exc,
            )

        # Increment review-cycle:N at dispatch for review_loop re_invoke targets.
        # The counter reflects the number of times this agent has started.
        _is_reinvoke_target = any(
            ad.review_loop and ad.review_loop.get("re_invoke") == agent_def.agent
            for ad in pipeline_map.values()
        )
        if _is_reinvoke_target:
            _rc_cur = _get_review_cycle(labels)
            _rc_next = _rc_cur + 1
            if _rc_cur > 0:
                try:
                    gh.remove_label(work_item.number, f"review-cycle:{_rc_cur}")
                    labels.discard(f"review-cycle:{_rc_cur}")
                except Exception as exc:
                    log.debug(
                        "could not remove review-cycle:%d on #%d: %s",
                        _rc_cur, work_item.number, exc,
                    )
            try:
                gh.add_label(work_item.number, f"review-cycle:{_rc_next}")
                labels.add(f"review-cycle:{_rc_next}")
                log.info(
                    "  CYCLE   %-38s  review-cycle:%d", agent_def.agent, _rc_next,
                )
            except Exception as exc:
                log.warning(
                    "could not apply review-cycle:%d on #%d: %s",
                    _rc_next, work_item.number, exc,
                )

    else:
        # dry_run: skip :wip ceremony but advance counters so simulated output
        # respects per-agent and aggregate ceilings.
        if concurrency is not None:
            concurrency.running_counts[agent_def.label_key] = (
                concurrency.running_counts.get(agent_def.label_key, 0) + 1
            )
            concurrency.tick_launch_count += 1


def _invoke_with_retries(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
    gh: "GitHubClient",
    default_extra_tools: Optional[list],
    agent_text_snapshot: Optional[str],
) -> tuple:
    """Invoke an agent, retrying on crash (no sentinel) up to max_retries.

    Rate-limit events break immediately without applying :failed. Parses the
    sentinel from the final run. Returns (result, sentinel_status,
    sentinel_message, attempt).
    """
    sentinel_status: Optional[str] = None
    sentinel_message: str = ""
    _attempt = 0
    # Retry loop: re-invoke on crash (no sentinel) up to max_retries times.
    # Rate-limit events break immediately without applying :failed.
    result = invoke_agent(
        agent_def, work_item, dry_run, repo, attempt=0,
        agent_text_override=agent_text_snapshot,
        default_extra_tools=default_extra_tools,
    )
    while not dry_run:
        if result.rate_limited:
            break
        sentinel_status, sentinel_message = _parse_agent_sentinel(result.captured_tail)
        if sentinel_status or result.success or _attempt >= agent_def.max_retries:
            break
        _attempt += 1
        _backoff = 5 * (2 ** (_attempt - 1))
        log.info(
            "  RETRY   %d/%d %-38s  (exit %d; sleeping %ds)",
            _attempt, agent_def.max_retries,
            agent_def.agent, result.returncode or -1, _backoff,
        )
        try:
            gh.post_comment(
                work_item.number,
                f"**`{agent_def.agent}` retry {_attempt}/{agent_def.max_retries}** — "
                f"attempt {_attempt} failed "
                f"(exit {result.returncode if result.returncode is not None else 'unknown'}); "
                f"retrying automatically.",
            )
        except Exception as exc:
            log.warning("  could not post retry comment on #%d: %s", work_item.number, exc)
        time.sleep(_backoff)
        result = invoke_agent(
            agent_def, work_item, dry_run, repo, attempt=_attempt,
            agent_text_override=agent_text_snapshot,
            default_extra_tools=default_extra_tools,
        )
        if result.rate_limited:
            break

    if not dry_run and not result.rate_limited:
        sentinel_status, sentinel_message = _parse_agent_sentinel(result.captured_tail)

    return result, sentinel_status, sentinel_message, _attempt


def _run_agent(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
    labels: set,
    session_id: str,
    default_extra_tools: Optional[list],
    concurrency: Optional[ConcurrencyState],
    gh: "GitHubClient",
    pipeline_map: dict,
) -> tuple:
    """Pre-invocation ceremony, agent/script dispatch, and retry loop.

    Applies :wip, posts the opening announcement, manages the review-cycle
    counter, invokes the agent or script, and parses the sentinel.

    Modifies labels and work_item.labels in-place (review-cycle tracking).

    Returns: (result, sentinel_status, sentinel_message,
              pre_agent_branch, invoked_at, attempt)
    """
    log.info("  TRIGGER %-38s  [%s]", agent_def.agent, agent_def.step_type)

    # :requested is a manual override — detect before removing the label below.
    _manual_trigger = agent_status(labels, agent_def.label_key) == STATUS_REQUESTED

    _acquire_wip_and_announce(
        agent_def, work_item, dry_run, _manual_trigger,
        repo, labels, concurrency, gh, pipeline_map,
    )

    if session_id and not dry_run:
        _emit_audit_event(_make_audit_event(
            session_id, "agent.invoked", repo,
            work_item=work_item, agent=agent_def.agent,
            outcome_status="started",
            outcome_detail=f"mode={agent_def.step_type}",
        ))
    _invoked_at = time.monotonic()

    # Snapshot the agent file before any branch checkout below so agent
    # definitions always reflect the orchestrator's branch, not the issue branch.
    _agent_file_path = SUBMODULE_ROOT / ".claude/agents" / f"{agent_def.agent}.md"
    _agent_text_snapshot: Optional[str] = (
        _agent_file_path.read_text() if _agent_file_path.exists() else None
    )

    # For commit_after agents, check out the issue branch before invoking so
    # the agent reads accumulated state. commit-agent-work.sh handles staging,
    # commit, and push. Guard: only for issue work items (ISSUE_NUMBER required).
    _pre_agent_branch: str = ""
    if not dry_run and agent_def.commit_after and work_item.kind == "issue":
        try:
            _pre_agent_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            _issue_branch = f"issue-{work_item.number}{agent_def.branch_suffix}"
            subprocess.run(["git", "fetch", "origin", _issue_branch], check=True)
            subprocess.run(
                ["git", "checkout", "-B", _issue_branch, f"origin/{_issue_branch}"],
                check=True,
            )
            log.info("  pre-agent: checked out %s for %s", _issue_branch, agent_def.agent)
        except Exception as _pre_exc:
            log.warning(
                "  pre-agent branch checkout failed for %s: %s — running on current branch",
                agent_def.agent, _pre_exc,
            )
            _pre_agent_branch = ""  # don't attempt restoration if checkout failed

    sentinel_status: Optional[str] = None
    sentinel_message: str = ""
    _attempt = 0

    if agent_def.step_type == "script":
        result = invoke_script(agent_def, work_item, dry_run, repo)
        if not dry_run:
            sentinel_status, sentinel_message = _parse_agent_sentinel(result.captured_tail)
    else:
        result, sentinel_status, sentinel_message, _attempt = _invoke_with_retries(
            agent_def, work_item, dry_run, repo, gh,
            default_extra_tools, _agent_text_snapshot,
        )

    return result, sentinel_status, sentinel_message, _pre_agent_branch, _invoked_at, _attempt


# ---------------------------------------------------------------------------
# Orchestration-script resolution (issue #196)
#
# The orchestrator's own helper scripts (commit-agent-work.sh, mark-pr-ready.sh,
# ...) are infrastructure that ships with the orchestrator, not work-item
# content. A commit_after agent checks out the issue branch before committing;
# when that branch is stale (cut from an old main that predates a script), the
# script is ABSENT from the checked-out tree and the step hard-fails even
# though the agent's work is complete (orchestrator run #1207, issue #143).
#
# Resolution is working-tree-first, main-fallback:
#   - If the script is present in the working tree, use it. This is the common
#     case -- a healthy issue branch, or any agent (e.g. pr-reviewer) that never
#     checked out an issue branch and is still on main. No network, no shadowing.
#   - If the script is ABSENT (the stale-branch failure), read its blob from
#     origin/main and materialize it into a temp dir. The returned path lives
#     outside any work-item tree, so a stale branch cannot remove it. If
#     origin/main is also unavailable, return the (missing) working-tree path
#     and let the caller's existence check report the real problem.
#
# Mode-agnostic: cwd is SUBMODULE_ROOT (this repo in source mode, the pinned
# submodule dir in submodule mode), so origin/main is always this framework's
# main, never the consuming repo's issue branch.
# ---------------------------------------------------------------------------
_ORCH_SCRIPT_CACHE: dict[str, Path] = {}
_ORCH_SCRIPT_DIR: Optional[Path] = None
_ORCH_MAIN_FETCHED = False


def _orchestration_script_path(rel_path: str) -> Path:
    """Resolve an orchestration helper script to an executable path, recovering
    from origin/main when a stale issue branch lacks it. See the block comment
    above for the working-tree-first, main-fallback contract."""
    global _ORCH_SCRIPT_DIR, _ORCH_MAIN_FETCHED
    working_tree_path = SUBMODULE_ROOT / rel_path

    # Fast path: script present on the checked-out tree (healthy branch, or on
    # main). No network, no interference with a stale-branch recovery.
    if working_tree_path.exists():
        return working_tree_path

    if rel_path in _ORCH_SCRIPT_CACHE:
        return _ORCH_SCRIPT_CACHE[rel_path]

    # Recovery path: the checked-out (stale) branch is missing this script.
    # Fetch origin/main once per process, then read the script's blob from it.
    if not _ORCH_MAIN_FETCHED:
        _ORCH_MAIN_FETCHED = True
        try:
            subprocess.run(
                ["git", "fetch", "--quiet", "origin", "main"],
                cwd=SUBMODULE_ROOT, capture_output=True, text=True, timeout=120,
            )
        except Exception as exc:
            log.debug("  orchestration-script: could not fetch origin/main: %s", exc)

    try:
        blob = subprocess.run(
            ["git", "show", f"origin/main:{rel_path}"],
            cwd=SUBMODULE_ROOT, capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except Exception as exc:
        log.debug(
            "  orchestration-script: origin/main:%s unavailable (%s) -- using working tree %s",
            rel_path, exc, working_tree_path,
        )
        return working_tree_path

    if _ORCH_SCRIPT_DIR is None:
        _ORCH_SCRIPT_DIR = Path(tempfile.mkdtemp(prefix="ai-agile-orch-scripts-"))
    dest = _ORCH_SCRIPT_DIR / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(blob)
    _ORCH_SCRIPT_CACHE[rel_path] = dest
    log.info(
        "  orchestration-script: %s missing on checked-out branch -- recovered from origin/main",
        rel_path,
    )
    return dest


def _invoke_commit_after(agent_def: AgentDef, work_item: WorkItem) -> Optional[str]:
    """Run commit-agent-work.sh for a `commit_after` agent.

    Returns a human-readable failure reason, or None on success. The caller
    owns the label/branch side-effects on failure.
    """
    _commit_script = _orchestration_script_path(".github/scripts/commit-agent-work.sh")
    _commit_env = {
        **os.environ,
        "AGENT_NAME": agent_def.agent,
        "ISSUE_NUMBER": str(work_item.number),
        "BRANCH_SUFFIX": agent_def.branch_suffix,
    }
    log.info(
        "  commit-after: invoking commit-agent-work.sh for %s on #%d",
        agent_def.agent, work_item.number,
    )
    if not _commit_script.exists():
        log.error("  commit-after: commit-agent-work.sh not found at %s", _commit_script)
        return (
            "_commit-agent-work.sh not found. Check that .github/scripts/commit-agent-work.sh "
            "exists on the orchestrator branch. Remove the failed label to retry._"
        )
    try:
        _commit_result = subprocess.run(
            ["bash", str(_commit_script)],
            env=_commit_env, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        log.error(
            "  commit-after: commit-agent-work.sh timed out for %s on #%d",
            agent_def.agent, work_item.number,
        )
        return "_commit-agent-work.sh timed out after 300s. Remove the failed label to retry._"
    except FileNotFoundError:
        log.error("  commit-after: bash not found in PATH")
        return (
            "_bash not found in PATH; commit-agent-work.sh could not run. "
            "Remove the failed label to retry._"
        )
    if _commit_result.returncode != 0:
        _failure_output = (_commit_result.stderr or _commit_result.stdout)[:2000]
        log.error(
            "  commit-after: commit-agent-work.sh exited %d for %s on #%d\n%s",
            _commit_result.returncode, agent_def.agent, work_item.number, _failure_output,
        )
        return (
            "_The agent completed successfully but commit-agent-work.sh failed. "
            "Check the orchestrator CI log for the specific error. "
            "Remove the failed label to retry._"
        )
    log.info(
        "  commit-after: commit-agent-work.sh completed for %s on #%d",
        agent_def.agent, work_item.number,
    )
    return None


def _invoke_post_steps(
    agent_def: AgentDef, work_item: WorkItem, repo: str, gh: "GitHubClient"
) -> Optional[str]:
    """Run an agent's post_steps completion hooks in order.

    Returns the first failure reason, or None if all hooks succeed. Each hook is
    a repo-relative bash script; a path escaping the repo root is rejected.
    """
    _ps_env = {
        **os.environ,
        "REPO": repo or gh.repo,
        "WORK_ITEM_KIND": work_item.kind,
        "WORK_ITEM_NUMBER": str(work_item.number),
        "AGENT_NAME": agent_def.agent,
    }
    if work_item.kind == "issue":
        _ps_env["ISSUE_NUMBER"] = str(work_item.number)
    else:
        _ps_env["PR_NUMBER"] = str(work_item.number)
    _ps_env["AI_AGILE_ROOT"] = os.environ.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT))
    for _ps_path_str in agent_def.post_steps:
        # Escape check on the DECLARED (working-tree) path: rejects a
        # pipeline.json entry that tries to point outside the repo root. This
        # must run before resolution-from-main, whose temp path legitimately
        # lives outside SUBMODULE_ROOT.
        _ps_declared = SUBMODULE_ROOT / _ps_path_str
        if not _ps_declared.resolve().is_relative_to(SUBMODULE_ROOT.resolve()):
            log.error(
                "  post_steps: path %s escapes repo root — blocked (agent %s on #%d)",
                _ps_path_str, agent_def.agent, work_item.number,
            )
            return (
                f"_post_steps path `{_ps_path_str}` escapes the repository root. "
                f"This is a configuration error in pipeline.json. "
                f"The agent is :complete; this post_step failure is surfaced as a "
                f"warning comment on the work item._"
            )
        # Resolve the execution path from origin/main (issue #196) so a stale
        # issue branch cannot shadow or remove the orchestrator's own scripts.
        _ps_file = _orchestration_script_path(_ps_path_str)
        if not _ps_file.exists():
            log.error(
                "  post_steps: %s not found at %s (agent %s on #%d)",
                _ps_path_str, _ps_file, agent_def.agent, work_item.number,
            )
            return (
                f"_post_steps script `{_ps_path_str}` not found. "
                f"Check that the script exists on the orchestrator branch. "
                f"The agent is :complete; this post_step failure is surfaced as a "
                f"warning comment on the work item._"
            )
        log.info(
            "  post_steps: running %s for %s on #%d",
            _ps_path_str, agent_def.agent, work_item.number,
        )
        try:
            _ps_result = subprocess.run(
                ["bash", str(_ps_file)],
                env=_ps_env, capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            log.error(
                "  post_steps: %s timed out for %s on #%d",
                _ps_path_str, agent_def.agent, work_item.number,
            )
            return (
                f"_post_steps script `{_ps_path_str}` timed out after 300s. "
                f"The agent is :complete; this post_step failure is surfaced as a "
                f"warning comment on the work item._"
            )
        except FileNotFoundError:
            log.error("  post_steps: bash not found in PATH")
            return (
                "_bash not found in PATH; post_steps script could not run. "
                "The agent is :complete; this post_step failure is surfaced as a "
                "warning comment on the work item._"
            )
        if _ps_result.returncode != 0:
            _ps_output = (_ps_result.stderr or _ps_result.stdout)[:2000]
            log.error(
                "  post_steps: %s exited %d for %s on #%d\n%s",
                _ps_path_str, _ps_result.returncode,
                agent_def.agent, work_item.number, _ps_output,
            )
            return (
                f"_post_steps script `{_ps_path_str}` exited {_ps_result.returncode}. "
                f"Check the orchestrator CI log for details. "
                f"The agent is :complete; this post_step failure is surfaced as a "
                f"warning comment on the work item._"
            )
        log.info(
            "  post_steps: %s completed for %s on #%d",
            _ps_path_str, agent_def.agent, work_item.number,
        )
    return None


def _finalize_run_failure(
    agent_def: AgentDef,
    work_item: WorkItem,
    result: AgentRunResult,
    attempt: int,
    invoked_at: float,
    gh: "GitHubClient",
    session_id: str,
    repo: str,
) -> None:
    """Apply :failed for a non-zero exit with no sentinel, and emit agent.failed.

    Covers the retry-exhausted and never-retried cases. The caller owns branch
    restoration and the early return.
    """
    # Non-zero exit, no sentinel — retries exhausted (or not configured).
    if attempt > 0:
        _exhaustion_reason = (
            f"Retry limit exhausted — `{agent_def.agent}` failed "
            f"{attempt + 1} time(s) (max_retries: {agent_def.max_retries}). "
            f"Human intervention is required: fix the underlying issue, "
            f"then remove `{agent_def.failed_label}` to retry."
        )
        _apply_failed(
            gh, agent_def, work_item, result,
            heading=f"### `{agent_def.agent}` failed — retry limit exhausted",
            reason=_exhaustion_reason,
        )
    else:
        _apply_failed(gh, agent_def, work_item, result)
    log.error(
        "  FAILED  %-38s  after %d attempt(s) on #%d",
        agent_def.agent, attempt + 1, work_item.number,
    )
    if session_id:
        _emit_audit_event(_make_audit_event(
            session_id, "agent.failed", repo,
            work_item=work_item, agent=agent_def.agent,
            outcome_status="failed",
            outcome_detail=(
                f"exit code {result.returncode} after {attempt + 1} attempt(s) "
                f"mode={agent_def.step_type}"
            ),
            duration_ms=int((time.monotonic() - invoked_at) * 1000),
        ))


def _compute_human_review_override(
    agent_def: AgentDef,
    work_item: WorkItem,
    final_status: str,
    labels: set,
    gh: "GitHubClient",
) -> tuple:
    """Resolve the issue-#100 human-review override.

    When pr-reviewer APPROVEs but unresolved human REQUEST_CHANGES reviews exist,
    override final_status to :review for a free coder re-invoke (once-only, guarded
    by HUMAN_REVIEW_PENDING_LABEL). On the second approve, clears the label.

    Returns (final_status, human_review_override, human_review_list).
    """
    _human_review_override = False
    _human_review_list: list = []
    if (
        final_status == STATUS_COMPLETE
        and agent_def.review_gate
        and agent_def.review_loop
        and HUMAN_REVIEW_PENDING_LABEL not in labels
    ):
        _hr_pr_number: Optional[int] = None
        if work_item.kind == "pr":
            _hr_pr_number = work_item.number
        elif work_item.kind == "issue":
            try:
                _hr_pr_number = gh.find_pr_by_branch(f"issue-{work_item.number}")
                if _hr_pr_number is None:
                    _hr_pr_number = gh.find_pr_by_label(
                        f"source-issue:{work_item.number}"
                    )
            except Exception as exc:
                log.warning(
                    "  could not look up PR for human review check on #%d: %s",
                    work_item.number, exc,
                )
        if _hr_pr_number is not None:
            _human_review_list = _fetch_unresolved_human_review_requests(gh, _hr_pr_number)
            if _human_review_list:
                log.info(
                    "  HUMAN   %-38s  %d unresolved REQUEST_CHANGES — "
                    "overriding to :review for free re-invoke",
                    agent_def.agent, len(_human_review_list),
                )
                final_status = STATUS_REVIEW
                _human_review_override = True
    elif (
        HUMAN_REVIEW_PENDING_LABEL in labels
        and final_status == STATUS_COMPLETE
        and agent_def.review_gate
        and agent_def.review_loop
    ):
        # Free re-invoke already ran (label present) and pr-reviewer APPROVEs
        # again — remove the label before the PR is marked ready.
        try:
            gh.remove_label(work_item.number, HUMAN_REVIEW_PENDING_LABEL)
            labels.discard(HUMAN_REVIEW_PENDING_LABEL)
            work_item.labels = labels
        except Exception as exc:
            log.debug(
                "  could not remove %s on #%d: %s",
                HUMAN_REVIEW_PENDING_LABEL, work_item.number, exc,
            )
    return final_status, _human_review_override, _human_review_list


def _resolve_applied_status(
    agent_def: AgentDef,
    work_item: WorkItem,
    final_status: str,
    gh: "GitHubClient",
) -> str:
    """Map final_status to the status label actually applied.

    An agent with a human gate completing applies :review (the "needs human
    action" state) instead of :complete, unless auto_approve_on_complete is set,
    in which case the gate label is auto-applied and :complete stands. If
    self_gates is set, the agent's own emitted status is trusted verbatim
    instead -- :complete never gets force-overridden to :review. The agent
    decides per-run whether its work needs review by emitting
    AI_AGILE_STATUS: review itself; human_gate_after/human_gate_label still
    apply for promotion once the agent has emitted :review.
    """
    applied_status = final_status
    if (
        final_status == STATUS_COMPLETE
        and agent_def.human_gate_after
        and agent_def.human_gate_label
        and not agent_def.self_gates
    ):
        if agent_def.auto_approve_on_complete:
            try:
                gh.add_label(work_item.number, agent_def.human_gate_label)
                log.info(
                    "  auto-approved  %-38s  applied %s on #%d",
                    agent_def.agent, agent_def.human_gate_label, work_item.number,
                )
            except Exception as exc:
                log.warning(
                    "  could not auto-apply gate label %s on #%d: %s",
                    agent_def.human_gate_label, work_item.number, exc,
                )
        else:
            applied_status = STATUS_REVIEW
    return applied_status


def _announce_and_prompt(
    agent_def: AgentDef,
    work_item: WorkItem,
    session_id: str,
    applied_status: str,
    sentinel_message: str,
    gh: "GitHubClient",
) -> None:
    """Post the closing announcement and, if awaiting a gate, the gate prompt."""
    try:
        gh.post_comment(
            work_item.number,
            _build_closing_announcement(
                agent_def, work_item, session_id, applied_status, sentinel_message,
            ),
        )
    except Exception as exc:
        log.warning(
            "  could not post closing announcement for %s on #%d: %s",
            agent_def.agent, work_item.number, exc,
        )

    # If awaiting human sign-off, post the gate prompt immediately after the
    # closing announcement so the required action is clear.
    if applied_status == STATUS_REVIEW and agent_def.human_gate_after and agent_def.human_gate_label:
        try:
            gh.post_comment(
                work_item.number,
                (
                    f"<!-- ai-agile/gate-prompt/v1 by {agent_def.agent} -->\n"
                    f"**{agent_def.agent}** is complete.\n\n"
                    f"- Apply `{agent_def.human_gate_label}` to approve and advance the pipeline.\n"
                    f"- Add your feedback as a comment, then apply "
                    f"`{agent_def.status_label(STATUS_REQUESTED)}` to request changes "
                    f"(the agent will re-read your comments and revise).\n\n"
                    f"> **Note:** Applying `:requested` clears the current `:review` state. "
                    f"If you had already applied `{agent_def.human_gate_label}`, "
                    f"re-apply it after reviewing the revision."
                ),
            )
        except Exception as exc:
            log.warning(
                "  could not post gate comment for %s on #%d: %s",
                agent_def.agent, work_item.number, exc,
            )
        log.info(
            "  GATE    %-38s  waiting for: %s",
            agent_def.agent, agent_def.human_gate_label,
        )


def _emit_terminal_audit(
    agent_def: AgentDef,
    work_item: WorkItem,
    applied_status: str,
    invoked_at: float,
    session_id: str,
    repo: str,
) -> None:
    """Emit the terminal agent.* audit event for the applied status."""
    if not (session_id and applied_status):
        return
    _et_map = {
        STATUS_COMPLETE: "agent.complete",
        STATUS_REVIEW:   "agent.review",
        STATUS_BLOCKED:  "agent.blocked",
        STATUS_SKIPPED:  "agent.skipped",
    }
    _emit_audit_event(_make_audit_event(
        session_id, _et_map.get(applied_status, "agent.complete"), repo,
        work_item=work_item, agent=agent_def.agent,
        outcome_status=applied_status,
        outcome_detail=f"mode={agent_def.step_type}",
        duration_ms=int((time.monotonic() - invoked_at) * 1000),
    ))


def _mark_pr_ready_if_requested(
    agent_def: AgentDef,
    work_item: WorkItem,
    gh: "GitHubClient",
) -> None:
    """Locate the PR for a review_gate agent and mark it ready for review."""
    if work_item.kind == "pr":
        _ready_pr_number = work_item.number
    elif work_item.kind == "issue":
        try:
            _ready_pr_number = gh.find_pr_by_branch(f"issue-{work_item.number}")
            if _ready_pr_number is None:
                _ready_pr_number = gh.find_pr_by_label(
                    f"source-issue:{work_item.number}"
                )
        except Exception as exc:
            log.warning(
                "  could not look up PR for issue #%d: %s",
                work_item.number, exc,
            )
            _ready_pr_number = None
    else:
        _ready_pr_number = None

    if _ready_pr_number:
        try:
            gh.mark_pr_ready(_ready_pr_number)
            log.info(
                "  READY   %-38s  marked PR #%d ready for review",
                agent_def.agent, _ready_pr_number,
            )
        except Exception as exc:
            log.warning(
                "  could not mark PR #%d ready after %s: %s",
                _ready_pr_number, agent_def.agent, exc,
            )
    elif agent_def.review_gate:
        log.warning(
            "  review_gate set on %s but no PR found for #%d — skipped",
            agent_def.agent, work_item.number,
        )


def _apply_result(
    agent_def: AgentDef,
    work_item: WorkItem,
    result: AgentRunResult,
    sentinel_status: Optional[str],
    sentinel_message: str,
    pre_agent_branch: str,
    invoked_at: float,
    attempt: int,
    labels: set,
    concurrency: Optional[ConcurrencyState],
    gh: "GitHubClient",
    session_id: str,
    repo: str,
    pipeline_map: dict,
    *,
    dry_run: bool = False,
    cycle_id: str = "",
    timestamp_start: str = "",
    timestamp_end: str = "",
) -> bool:
    """Apply GitHub side-effects for a completed agent run.

    Handles rate-limit short-circuit, final status determination, commit-after
    invocation, human review override, terminal label application, closing
    announcement, gate prompt, label refresh, audit event, PR ready promotion,
    and per-cycle metrics (issue #121).

    Calls _restore_pre_agent_branch on every break path before returning True.
    The caller (process_work_item) calls _restore_pre_agent_branch on the
    non-break path after this function returns False.

    Returns True if the agent loop should stop (break), False to continue.
    Updates work_item.labels after GitHub label refresh on the non-break path.
    """
    # Rate-limit short-circuit is handled by the caller (process_work_item) before
    # _apply_result is invoked, so result.rate_limited is always False here.
    if sentinel_status:
        final_status = sentinel_status
    elif result.success:
        final_status = STATUS_COMPLETE
        sentinel_message = "completed (no sentinel; inferred from exit 0)"
    else:
        _finalize_run_failure(
            agent_def, work_item, result, attempt, invoked_at, gh, session_id, repo,
        )
        _metrics_record = _build_step_metrics(
            agent_def, work_item, result,
            timestamp_start, timestamp_end, cycle_id,
            is_error_override=True,
        )
        _post_cycle_metrics(gh, repo, work_item, _metrics_record, dry_run)
        _restore_pre_agent_branch(pre_agent_branch)
        return True

    # commit-after: invoke commit-agent-work.sh when git_ops.commit_after: true.
    # Guard: commit-agent-work.sh requires ISSUE_NUMBER; only invoke for issue work items.
    if final_status == STATUS_COMPLETE and agent_def.commit_after and work_item.kind == "issue":
        _commit_fail_reason = _invoke_commit_after(agent_def, work_item)
        if _commit_fail_reason:
            _apply_failed(gh, agent_def, work_item, result, reason=_commit_fail_reason)
            final_status = STATUS_FAILED
            log.error(
                "  FAILED  %-38s  commit-after failed on #%d",
                agent_def.agent, work_item.number,
            )
            _metrics_record = _build_step_metrics(
                agent_def, work_item, result,
                timestamp_start, timestamp_end, cycle_id,
                is_error_override=True,
            )
            _post_cycle_metrics(gh, repo, work_item, _metrics_record, dry_run)
            _restore_pre_agent_branch(pre_agent_branch)
            return True

    # Edge case (issue #100): pr-reviewer APPROVEs (STATUS_COMPLETE) but
    # unresolved human REQUEST_CHANGES reviews exist on the PR. Override
    # final_status to STATUS_REVIEW so _handle_review_loop triggers a free
    # coder re-invoke. HUMAN_REVIEW_PENDING_LABEL guards against a second
    # free cycle (once-only).
    final_status, _human_review_override, _human_review_list = _compute_human_review_override(
        agent_def, work_item, final_status, labels, gh,
    )

    # When an agent with a human gate completes, apply :review rather than
    # :complete so the "needs human action" state is visible consistently.
    # promote_gated_agents advances to :complete once the gate label is applied.
    #
    # Exception: auto_approve_on_complete=True — orchestrator auto-applies the
    # gate label so downstream agents are not blocked.
    applied_status = _resolve_applied_status(agent_def, work_item, final_status, gh)

    _apply_terminal_status(gh, agent_def, work_item, applied_status)

    # The step has transitioned off :wip -- clear the in-flight marker so the
    # SIGTERM handler only ever acts on a genuinely running step.
    global _CURRENT_WIP
    _CURRENT_WIP = None

    _announce_and_prompt(
        agent_def, work_item, session_id, applied_status, sentinel_message, gh,
    )

    # Refresh label set from GitHub after our writes.
    labels_refreshed = gh.get_issue_labels(work_item.number)
    work_item.labels = labels_refreshed

    log.info("  %-6s  %-38s", (applied_status or "?").upper(), agent_def.agent)

    _emit_terminal_audit(agent_def, work_item, applied_status, invoked_at, session_id, repo)

    _metrics_record = _build_step_metrics(
        agent_def, work_item, result,
        timestamp_start, timestamp_end, cycle_id,
    )
    _post_cycle_metrics(gh, repo, work_item, _metrics_record, dry_run)

    # Mark the PR ready-for-review if the agent declares it (P-16).
    # Only fires on true completion — not when awaiting a human gate.
    if applied_status == STATUS_COMPLETE and agent_def.review_gate:
        _mark_pr_ready_if_requested(agent_def, work_item, gh)

    # post_steps: run per-agent completion hooks after the agent signals :complete.
    # Each hook is a repo-relative path to a bash script. A non-zero exit is
    # surfaced as a warning comment on the work item; :complete is preserved so
    # that a genuine agent success is not misrepresented by an auxiliary failure.
    if applied_status == STATUS_COMPLETE and agent_def.post_steps:
        _ps_fail_reason = _invoke_post_steps(agent_def, work_item, repo, gh)
        if _ps_fail_reason:
            log.warning(
                "  post_steps: failure after :complete on #%d — keeping :complete, posting warning",
                work_item.number,
            )
            _ps_warning = (
                f"<!-- ai-agile/announcement/v1 by orchestrator -->\n"
                f"**post_steps warning on #{work_item.number}** "
                f"(agent `{agent_def.agent}`):\n\n{_ps_fail_reason}\n\n"
                f"The agent's own work completed successfully; `:complete` is preserved. "
                f"The post_step failure is logged here for visibility."
            )
            try:
                gh.post_comment(work_item.number, _ps_warning)
            except Exception as exc:
                log.warning(
                    "  could not post post_steps warning comment on #%d: %s",
                    work_item.number, exc,
                )

    # Halt if blocked, awaiting review, or failed — stop dispatching further agents.
    if applied_status in (STATUS_BLOCKED, STATUS_REVIEW, STATUS_FAILED):
        if applied_status == STATUS_REVIEW and agent_def.review_loop:
            labels_refreshed = _handle_review_loop(
                gh, agent_def, work_item, labels_refreshed, pipeline_map,
                skip_cycle_increment=_human_review_override,
                human_reviews=_human_review_list if _human_review_override else None,
            )
            work_item.labels = labels_refreshed
        _restore_pre_agent_branch(pre_agent_branch)
        return True

    return False


def process_work_item(
    work_item: WorkItem,
    agents: list[AgentDef],
    pipeline_map: dict[str, AgentDef],
    gh: GitHubClient,
    dry_run: bool,
    repo: str,
    *,
    session_id: str = "",
    default_extra_tools: Optional[list[str]] = None,
    concurrency: Optional[ConcurrencyState] = None,
) -> int:
    """Evaluate all agents against a single issue or PR.

    Thin orchestration wrapper: promotes gated agents, then for each agent
    calls _should_run(), _run_agent(), and _apply_result() in sequence.
    Returns the number of agents triggered.
    """
    ctrl = _check_controls(repo)
    if ctrl != "run":
        log.warning(
            "  CTRL    pipeline %s — skipping work item #%d",
            ctrl, work_item.number,
        )
        return 0

    triggered = 0
    labels = work_item.labels

    log.info(
        "%s #%d: %s",
        work_item.kind.upper(), work_item.number,
        work_item.title[:70] + ("…" if len(work_item.title) > 70 else ""),
    )

    # Gate promotion runs FIRST every tick so the eligibility loop sees a
    # consistent state for all gated agents.
    if not dry_run:
        labels = promote_gated_agents(
            labels, agents, work_item, gh,
            session_id=session_id, repo=repo,
        )
        work_item.labels = labels

    # Synthesize :complete for every :skipped agent so downstream eligibility
    # checks express "is done?" as a single :complete test throughout.
    labels = normalize_skipped_labels(labels, pipeline_map)

    for agent_def in agents:
        should_run = _should_run(
            agent_def, work_item, labels, pipeline_map, concurrency,
            gh=gh, repo=repo,
        )
        if should_run is None:
            break
        if not should_run:
            continue

        _cycle_id = str(uuid.uuid4())
        _timestamp_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        result, sentinel_status, sentinel_message, pre_branch, invoked_at, attempt = _run_agent(
            agent_def, work_item, dry_run, repo, labels,
            session_id, default_extra_tools, concurrency, gh, pipeline_map,
        )

        _timestamp_end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if not dry_run:
            # Rate-limit short-circuit: the pause marker was written.
            # Do NOT mark :failed — the agent never got a fair run.
            # The next tick's _check_controls() call will detect the pause marker.
            if result.rate_limited:
                log.warning(
                    "  PAUSED  %-38s  rate-limited; next tick will check pause status",
                    agent_def.agent,
                )
                # Remove :wip so the next tick sees a clean state
                try:
                    gh.remove_label(work_item.number, agent_def.status_label(STATUS_WIP))
                except Exception:
                    pass
                # Roll back in-memory concurrency counts: the :wip was removed,
                # so the slot is free again. Without this the per-agent and
                # aggregate ceilings would over-count for the rest of the tick.
                if concurrency is not None:
                    concurrency.running_counts[agent_def.label_key] = max(
                        0, concurrency.running_counts.get(agent_def.label_key, 0) - 1
                    )
                    concurrency.tick_launch_count = max(0, concurrency.tick_launch_count - 1)
                _restore_pre_agent_branch(pre_branch)
                break

            stop = _apply_result(
                agent_def, work_item, result, sentinel_status, sentinel_message,
                pre_branch, invoked_at, attempt, labels, concurrency,
                gh, session_id, repo, pipeline_map,
                dry_run=dry_run, cycle_id=_cycle_id,
                timestamp_start=_timestamp_start, timestamp_end=_timestamp_end,
            )
            labels = normalize_skipped_labels(work_item.labels, pipeline_map)  # re-normalize after _apply_result refresh
            if stop:
                break
                break

        _restore_pre_agent_branch(pre_branch)
        triggered += 1

    return triggered


# ---------------------------------------------------------------------------
# Helpers used by entry point
# ---------------------------------------------------------------------------

def _discover_github_token() -> str | None:
    """Return the GitHub token from env or gh CLI; None if unavailable."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _ensure_gh_cli() -> None:
    """Ensure `gh` is on PATH and can make authenticated REST calls, installing
    it via apt if missing.

    Script-type pipeline steps (.github/scripts/*.sh) shell out to `gh api`
    REST calls, not gh's GraphQL-backed subcommands (some of which 403 in
    restricted sessions -- see #276/#284), so this only needs the binary plus
    GITHUB_TOKEN/GH_TOKEN in the environment. Verification below uses
    `gh api user` rather than `gh auth status`: the latter performs a
    GraphQL-backed validation call that can 403 in a restricted session even
    when `gh api` works fine, producing a false "not authenticated" reading.
    """
    if not shutil.which("gh"):
        log.warning("gh CLI not found on PATH -- installing via apt (script-type steps call `gh api`)")
        try:
            subprocess.run(["apt-get", "update", "-qq"], check=True,
                            capture_output=True, text=True, timeout=120)
            subprocess.run(["apt-get", "install", "-y", "-qq", "gh"], check=True,
                            capture_output=True, text=True, timeout=120)
        except Exception as exc:
            stderr = getattr(exc, "stderr", None) or ""
            log.error("Could not install gh CLI automatically (%s; stderr: %s); script-type "
                       "steps calling `gh api` will fail until it is installed manually",
                       exc, stderr.strip())
            return
        if not shutil.which("gh"):
            log.error("apt install of gh exited cleanly but `gh` is still not on PATH")
            return
        log.info("gh CLI installed")

    try:
        probe = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                                capture_output=True, text=True, timeout=30)
    except Exception as exc:
        log.warning("Could not probe gh CLI REST auth: %s", exc)
        return
    if probe.returncode == 0:
        log.info("gh CLI REST-authenticated as %s", probe.stdout.strip())
    else:
        log.warning("gh CLI present but `gh api user` failed -- script-type steps "
                     "calling `gh api` may fail: %s", probe.stderr.strip())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PDLC/SDLC pipeline orchestrator")
    p.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="GitHub repo in OWNER/REPO format (default: $GITHUB_REPOSITORY)",
    )
    p.add_argument(
        "--issue",
        type=int,
        default=None,
        help="Process only this issue/PR number (default: all open items)",
    )
    p.add_argument(
        "--kind",
        choices=["issue", "pr"],
        default=None,
        help="When --issue is given, declares whether the number is an issue or a PR. "
             "If omitted, the orchestrator probes the GitHub API to determine the kind.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be triggered without invoking agents or modifying labels",
    )
    p.add_argument(
        "--pipeline",
        type=Path,
        default=PIPELINE_PATH,
        help=f"Path to pipeline.json (default: {PIPELINE_PATH})",
    )
    p.add_argument(
        "--clear-pause",
        action="store_true",
        help="Clear the rate-limit pause marker if set, then exit. "
             "Use this when you want to manually resume after a pause "
             "without waiting for it to expire naturally.",
    )
    p.add_argument(
        "--phases",
        default=None,
        metavar="PHASE[,PHASE...]",
        help=(
            "Comma-separated list of phases to process "
            "(e.g. '01_product_docs,02_design'). "
            "Default: all phases. "
            "Useful for manual or debug runs to scope the orchestrator to a "
            "subset of phases. Agents outside the allowed set are silently "
            "skipped for this run only; pipeline state is unchanged. The "
            "orchestrator workflow does not set this — it runs all phases."
        ),
    )
    p.add_argument(
        "--clear-stop",
        action="store_true",
        help="Clear the emergency stop marker if set, then exit. "
             "Use this when you want to resume after an emergency stop "
             "(the owner-run restart mechanism; there is no restart workflow).",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help=(
            "Emit all non-system agent stream-json events to stderr. "
            "Default (without this flag): emit only the result-type summary "
            "event per agent invocation. Non-JSON lines are always forwarded "
            "regardless of this flag. Also enables debug-level logging."
        ),
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Declare this as an unattended/scheduled invocation. "
            "Added unconditionally by ai_orchestrator.yml; omit for interactive "
            "runs (/maos-run, developer). Effects: (1) the audit actor field "
            "records the real trigger identity; (2) the .pipeline-stop check "
            "only halts headless runs -- an interactive run logs the marker "
            "but proceeds."
        ),
    )
    p.add_argument(
        "--agent",
        default=None,
        metavar="AGENT",
        help=(
            "Agent name override (e.g. '01_product_docs/prd-writer'). "
            "Required when using --print-prompt."
        ),
    )
    p.add_argument(
        "--print-prompt",
        action="store_true",
        help=(
            "Resolve-only mode: print the named agent's prompt text, tool "
            "allowlist, and env as JSON without spawning a subprocess or "
            "mutating any GitHub state (no label writes, no :wip). "
            "Used by /run-agent to obtain authoritative invocation parameters. "
            "The printed env carries only the agent-facing context vars; every "
            "other key, credentials included, is omitted by name only under "
            "env_omitted_keys. "
            "Requires --agent and --issue (or --repo + --issue)."
        ),
    )
    return p.parse_args()


@dataclass
class RunContext:
    """Everything one orchestrator tick needs to do its work.

    Built once during _wake() from GitHub + pipeline config; consumed by
    _do_work() and _close_down(). Run-scoped and transient — it is NOT
    persisted between runs (P-1: GitHub labels remain the source of truth).
    """
    gh: "GitHubClient"
    agents: list
    pipeline_map: dict
    work_items: list
    concurrency: ConcurrencyState
    repo: str
    session_id: str
    dry_run: bool
    default_extra_tools: Optional[list]


def _read_pr_event_action() -> str:
    """Return the GitHub pull_request event action from GITHUB_EVENT_PATH.

    Reads the JSON event payload written by GitHub Actions. Returns the action
    string (e.g. "closed", "opened") or "" when unavailable (no env var,
    missing file, or malformed JSON). Never raises.
    """
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        return ""
    try:
        with open(event_path) as f:
            data = json.load(f)
        return data.get("action", "")
    except (OSError, json.JSONDecodeError, ValueError):
        return ""


def _read_pr_event_merged() -> bool:
    """Return whether the GitHub pull_request event's PR was merged.

    Reads the JSON event payload written by GitHub Actions. Returns
    `pull_request.merged` (a bool), or False when unavailable (no env var,
    missing file, malformed JSON, or the field is absent). Never raises.
    """
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        return False
    try:
        with open(event_path) as f:
            data = json.load(f)
        pull_request = data.get("pull_request")
        if not isinstance(pull_request, dict):
            return False
        return bool(pull_request.get("merged", False))
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def _call_delete_branch(repo: str, branch: str) -> None:
    """Invoke delete-branch.sh to remove a branch when a PR closes.

    Logs the outcome but never raises -- branch cleanup is best-effort and
    must not abort the orchestrator process on partial failure.
    """
    if not branch:
        log.warning("_call_delete_branch: BRANCH is empty -- skipping")
        return
    if not repo:
        log.warning("_call_delete_branch: REPO is empty -- skipping")
        return

    script = SUBMODULE_ROOT / ".github/scripts/delete-branch.sh"
    if not script.exists():
        log.warning(
            "delete-branch.sh not found at %s -- branch '%s' not cleaned up",
            script, branch,
        )
        return

    env = {**os.environ, "REPO": repo, "BRANCH": branch}
    log.info("Deleting branch '%s' from %s (pull_request.closed)", branch, repo)
    try:
        result = subprocess.run(
            ["bash", str(script)],
            env=env,
            timeout=60,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            log.info("delete-branch.sh stdout: %s", result.stdout.strip())
        if result.returncode != 0:
            log.warning(
                "delete-branch.sh exited %d for branch '%s': %s",
                result.returncode, branch, (result.stderr or "").strip(),
            )
    except subprocess.TimeoutExpired:
        log.warning("delete-branch.sh timed out for branch '%s'", branch)
    except OSError as exc:
        log.warning("delete-branch.sh could not run for branch '%s': %s", branch, exc)


def _run_print_prompt(args) -> None:
    """Resolve-only mode: resolve the named agent's prompt/tools/env and print as JSON.

    No labels are changed, no :wip is applied, and no GitHub API write calls
    are made. Called when --print-prompt is passed; used by /run-agent to obtain
    authoritative invocation parameters from the orchestrator's own resolution
    logic instead of hand-parsing the agent file.

    The printed env is built by naming exactly the keys that may be exported
    (PRINT_PROMPT_ENV_KEYS), not by removing known-bad ones: this output is
    captured into an interactive session, unlike invoke_agent's env which is
    only ever handed to subprocess. Everything else, credentials included, is
    omitted by default; the omitted key names are reported under
    env_omitted_keys.
    """
    if not args.agent:
        log.error("--print-prompt requires --agent <agent-name>")
        sys.exit(1)
    if not args.issue:
        log.error("--print-prompt requires --issue <number>")
        sys.exit(1)
    if not args.repo:
        log.error("--print-prompt requires --repo <owner/repo>")
        sys.exit(1)

    token = _discover_github_token()
    if not token:
        log.error("No GitHub token found. Set $GITHUB_TOKEN or authenticate with `gh auth login`.")
        sys.exit(1)

    gh = GitHubClient(token, args.repo)
    kind = args.kind or "issue"
    try:
        if kind == "pr":
            data = gh._get(f"/repos/{args.repo}/pulls/{args.issue}")
        else:
            data = gh._get(f"/repos/{args.repo}/issues/{args.issue}")
        work_item = WorkItem(
            number=data["number"],
            kind=kind,
            title=data["title"],
            labels={lbl["name"] for lbl in data.get("labels", [])},
            url=data["html_url"],
        )
    except Exception as exc:
        log.error("Could not load work item %s #%d: %s", kind, args.issue, exc)
        sys.exit(1)

    # Build a minimal AgentDef from the agent file's frontmatter. The agent
    # is specified by name; extra_allowedTools come from the file's frontmatter
    # only (no pipeline.json context in resolve-only mode).
    agent_name = args.agent
    agent_file = SUBMODULE_ROOT / ".claude/agents" / f"{agent_name}.md"
    if not agent_file.exists():
        log.error("Agent file not found: %s", agent_file)
        sys.exit(1)

    agent_text = agent_file.read_text()
    frontmatter = parse_frontmatter(agent_text)
    extra = _coerce_tools(frontmatter.get("extra_allowedTools"))

    agent_def = AgentDef(
        agent=agent_name,
        phase="",
        objects=[],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="",
        extra_allowedTools=extra,
    )

    resolved = _resolve_agent_invocation(agent_def, work_item, args.repo)
    if resolved is None:
        log.error("Could not resolve invocation for agent %s", agent_name)
        sys.exit(1)

    # Build env with interactive mode -- this path is used by /run-agent, not
    # by a real orchestrator subprocess spawn.
    env = _build_agent_env(os.environ, args.repo, work_item, resolved.session_id, agent_def.session_scope)
    env["AI_AGILE_EXECUTION_MODE"] = "interactive"

    # Export only the named keys -- see PRINT_PROMPT_ENV_KEYS. The names of the
    # keys left out are still reported so a consumer can tell the difference
    # between "not needed" and "not shown"; only their values are withheld.
    printable_env = {k: env[k] for k in PRINT_PROMPT_ENV_KEYS if k in env}
    omitted = sorted(k for k in env if k not in printable_env)

    output = {
        "agent": agent_name,
        "session_id": resolved.session_id,
        "allowed_tools": resolved.allowed_tools,
        "model": resolved.model,
        "max_turns": resolved.max_turns,
        "env": printable_env,
        "env_omitted_keys": omitted,
        "prompt": resolved.prompt,
    }
    print(json.dumps(output, indent=2))


def _wake(args) -> "Optional[RunContext]":
    """Wake up: honour control flags, evaluate pause/stop, authenticate, load
    the pipeline, then fetch and priority-order the work.

    Returns a RunContext to act on, or None if this run should not proceed
    (a --clear-* invocation, or an active pause/stop). Exits the process on a
    fatal misconfiguration (missing --repo or token).
    """
    # Manual pause clear — short-circuit before doing anything else.
    if args.clear_pause:
        if clear_pause():
            log.info("Pause marker cleared. Re-run without --clear-pause to resume work.")
        else:
            log.info("No pause marker was set.")
        return None

    # Manual stop clear — short-circuit before doing anything else.
    if args.clear_stop:
        if clear_stop():
            log.info("Stop marker cleared. Re-run without --clear-stop to resume work.")
        else:
            log.info("No stop marker was set.")
        return None

    # Handle pull_request.closed (merged only): delete the branch and exit
    # without processing any pipeline work. Runs before pause/stop checks so
    # merged-PR branches are cleaned up even when the pipeline is paused or
    # stopped. PRs closed without merging are left alone -- the branch may
    # still hold work the human wants to resume or recover.
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        _action = _read_pr_event_action()
        if _action == "closed" and _read_pr_event_merged():
            _branch = os.environ.get("GITHUB_HEAD_REF", "")
            _repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
            log.info(
                "pull_request.closed (merged): cleaning up branch '%s' from %s", _branch, _repo
            )
            _call_delete_branch(_repo, _branch)
            return None

    # If a previous run hit an Anthropic rate limit and wrote the pause
    # marker, exit early. The scheduled tick will retry once the marker
    # has expired (or the operator clears it manually with --clear-pause).
    paused, reason, until = is_pipeline_paused()
    if paused:
        log.warning(
            "Pipeline is paused until %s — %s. Skipping this run. "
            "(Use `--clear-pause` to override.)",
            until.isoformat() if until else "<unknown>",
            reason or "no reason recorded",
        )
        return None

    # Emergency stop: an operator has halted the pipeline indefinitely.
    # Unlike the rate-limit pause, the stop marker is never auto-cleared.
    # Headless/scheduled runs respect the marker; interactive runs log it
    # and proceed (an operator stopping automation does not also halt themselves).
    stopped, stop_reason = is_pipeline_stopped()
    if stopped:
        if args.headless:
            log.warning(
                "Pipeline is STOPPED: %s. No agents will be invoked. "
                "(Clear the .pipeline-stop marker or use `--clear-stop` to resume.)",
                stop_reason or "no reason recorded",
            )
            _stop_session = f"ais-v1-orch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            _emit_audit_event(_make_audit_event(
                _stop_session, "system.emergency_stop", args.repo or "",
                outcome_status="stopped",
                outcome_detail=stop_reason or "no reason recorded",
            ))
            return None
        log.warning("Operating in interactive mode, ignoring pipeline stop.")

    if not args.repo:
        log.error("--repo is required or set $GITHUB_REPOSITORY")
        sys.exit(1)

    _ensure_gh_cli()

    token = _discover_github_token()
    if not token:
        log.error(
            "No GitHub token found. Set $GITHUB_TOKEN or authenticate with `gh auth login`"
        )
        sys.exit(1)

    # Set GIT_CONFIG env vars so that git fetch / git checkout operations in
    # this process authenticate with GITHUB_TOKEN (contents:write scope).
    # The token is passed via env vars, never embedded in a URL, keeping it
    # out of `git remote -v`, `ps`, and CI logs.
    # NOTE: GITHUB_TOKEN cannot push .github/workflows/ files; commit-agent-work.sh
    # reads AI_AGILE_BOT_TOKEN when workflow-scope pushes are needed.
    _git_auth_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if _git_auth_token:
        try:
            _git_auth_encoded = base64.b64encode(
                f"x-access-token:{_git_auth_token}".encode()
            ).decode()
            subprocess.run(
                ["git", "config", "--local", "--unset-all",
                 "http.https://github.com/.extraHeader"],
                check=False,
                capture_output=True,
            )
            # These GIT_CONFIG_* vars go into the process-global os.environ so
            # the orchestrator's OWN git subprocesses inherit them: the git
            # checkout/fetch calls (via subprocess.run) and commit-agent-work.sh
            # / post_steps scripts all build their env from {**os.environ}, so
            # they must stay here for authenticated git to work.
            # SECURITY: this base64 header embeds GITHUB_TOKEN. It must NEVER be
            # added to AGENT_ENV_PASSTHROUGH -- agent subprocesses build env via
            # _build_agent_env, which does not pass GIT_CONFIG_* through, so a
            # prompt-injected agent cannot read the token from /proc/self/environ.
            os.environ["GIT_CONFIG_COUNT"] = "1"
            os.environ["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraHeader"
            os.environ["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {_git_auth_encoded}"
            log.info("git auth: GIT_CONFIG env vars set (contents:write scope)")
        except Exception as exc:
            log.warning("git auth: could not set GIT_CONFIG env vars — %s", exc)
    else:
        log.warning("git auth: no GITHUB_TOKEN found — git fetch/checkout may fail")

    agents, default_extra_tools = load_pipeline(args.pipeline)

    # Phase filter — restrict which agents this run is allowed to process.
    # Optional; used for manual or debug runs. The orchestrator workflow does
    # not set --phases, so it processes all phases in one pass. Agents outside
    # the allowed set are skipped silently; pipeline state is unchanged.
    if args.phases:
        allowed_phases = {p.strip() for p in args.phases.split(",") if p.strip()}
        before_count = len(agents)
        agents = [a for a in agents if a.phase in allowed_phases]
        log.info(
            "Phase filter: %s — %d/%d agents active",
            ", ".join(sorted(allowed_phases)), len(agents), before_count,
        )

    pipeline_map = pipeline_by_name(agents)
    gh = GitHubClient(repo=args.repo, token=token)

    session_id = f"ais-v1-orch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    log.info("Pipeline: %d agents across %d phases",
             len(agents),
             len({a.phase for a in agents}))
    if default_extra_tools:
        log.debug("Pipeline defaults: extra_allowedTools=%s", default_extra_tools)
    log.info("Repository: %s", args.repo)
    log.info("Session: %s", session_id)
    if args.dry_run:
        log.info("DRY RUN — no labels will be changed, no agents will be invoked")

    # Fetch work items
    if args.issue:
        kind = args.kind or _probe_kind(gh, args.issue)
        labels = gh.get_issue_labels(args.issue)
        path = "pull" if kind == "pr" else "issues"
        work_items = [WorkItem(
            number=args.issue,
            kind=kind,
            title=f"{kind.upper()} #{args.issue}",
            labels=labels,
            url=f"https://github.com/{args.repo}/{path}/{args.issue}",
        )]
    else:
        work_items = gh.list_open_issues(kind="all")

    # Multi-tier priority ordering driven by statuses.json priority_ordering.
    # Each label in PRIORITY_LABEL_ORDERING forms one tier; items carrying an
    # earlier-listed label are evaluated before items carrying a later-listed
    # label, which are evaluated before items carrying none. Within each tier,
    # relative order from the GitHub API response is preserved.
    # Example: ["classification: security", "priority"] produces:
    #   security items -> priority items -> all other items.
    _tiers: list[list] = [[] for _ in PRIORITY_LABEL_ORDERING]
    _other_items: list = []
    for wi in work_items:
        placed = False
        for idx, lbl in enumerate(PRIORITY_LABEL_ORDERING):
            if lbl in wi.labels:
                _tiers[idx].append(wi)
                placed = True
                break
        if not placed:
            _other_items.append(wi)
    for idx, lbl in enumerate(PRIORITY_LABEL_ORDERING):
        if _tiers[idx]:
            log.info(
                "Priority tier %r: %d item(s) (will be evaluated first): %s",
                lbl,
                len(_tiers[idx]),
                [wi.number for wi in _tiers[idx]],
            )
    work_items = [wi for tier in _tiers for wi in tier] + _other_items

    log.info("Work items to evaluate: %d", len(work_items))

    if not args.dry_run:
        _emit_audit_event(_make_audit_event(
            session_id, "system.tick", args.repo,
            outcome_status="started",
            outcome_detail=f"evaluating {len(work_items)} work item(s)",
        ))

    # Build concurrency state from labels fetched above. running_counts reflects
    # agents started in prior ticks that are still :wip; tick_launch_count will
    # accumulate launches within this tick against PIPELINE_MAX_CONCURRENT.
    conc = ConcurrencyState(running_counts=_count_running(work_items, agents))
    _active = {k: v for k, v in conc.running_counts.items() if v > 0}
    if _active:
        log.info("Running at tick start (prior-tick :wip): %s", _active)

    return RunContext(
        gh=gh, agents=agents, pipeline_map=pipeline_map, work_items=work_items,
        concurrency=conc, repo=args.repo, session_id=session_id,
        dry_run=args.dry_run, default_extra_tools=default_extra_tools,
    )


def _find_epic_siblings(gh: "GitHubClient", issue_number: int) -> list:
    """Return state info for all issues carrying parent-issue:{issue_number} label.

    Returns a list of {"number": N, "state": "open"|"closed"} dicts.
    Returns an empty list on any API error so the check is safely skipped.
    PRs are excluded (they carry pull_request in the API response).
    """
    label = f"parent-issue:{issue_number}"
    results = []
    page = 1
    try:
        while True:
            data = gh._get(
                f"/repos/{gh.repo}/issues",
                params={"labels": label, "state": "all", "per_page": 100, "page": page},
            )
            if not data:
                break
            for item in data:
                if "pull_request" not in item:
                    results.append({"number": item["number"], "state": item["state"]})
            if len(data) < 100:
                break
            page += 1
    except Exception as exc:
        log.warning("could not fetch siblings for epic #%d: %s", issue_number, exc)
        return []
    return results


def _check_epic_completions(ctx: "RunContext") -> None:
    """For each open epic-labeled issue, check whether all child issues are closed.

    If all siblings are closed, re-processes the epic as a work item so it
    advances through its own next eligible pipeline step.  When no agent fires
    (today's default: no pipeline steps target epics), falls back to posting a
    completion comment and closing the epic directly.

    Runs after the normal work-item loop in _do_work().
    """
    for item in ctx.work_items:
        if "epic" not in item.labels:
            continue
        if item.is_closed:
            continue

        siblings = _find_epic_siblings(ctx.gh, item.number)
        if not siblings:
            log.debug("epic #%d: no parent-issue siblings found — skipping", item.number)
            continue

        open_siblings = [s for s in siblings if s["state"].lower() == "open"]
        if open_siblings:
            log.info(
                "epic #%d: %d/%d sub-issue(s) still open — keeping open",
                item.number, len(open_siblings), len(siblings),
            )
            continue

        log.info(
            "epic #%d: all %d sub-issue(s) closed — re-processing as work item",
            item.number, len(siblings),
        )

        triggered = process_work_item(
            item, ctx.agents, ctx.pipeline_map, ctx.gh, ctx.dry_run, ctx.repo,
            session_id=ctx.session_id,
            default_extra_tools=ctx.default_extra_tools,
            concurrency=ctx.concurrency,
        )

        if triggered == 0 and ctx.dry_run:
            log.info(
                "  [DRY RUN] would close epic #%d (%d sub-issue(s) all closed)",
                item.number, len(siblings),
            )
        elif triggered == 0:
            # No pipeline agent matched — fall back to direct close with comment.
            # Future pipeline steps (e.g. a whole-feature review) plug in by adding
            # an agent that matches epics; once triggered > 0 this block is skipped.
            try:
                ctx.gh.post_comment(
                    item.number,
                    (
                        "<!-- ai-agile/announcement/v1 by orchestrator -->\n"
                        "## Epic complete\n\n"
                        f"All {len(siblings)} sub-issue(s) have been closed. "
                        "Closing this epic."
                    ),
                )
            except Exception as exc:
                log.warning("could not post completion comment on epic #%d: %s", item.number, exc)
            try:
                ctx.gh.close_issue(item.number)
                log.info("epic #%d: closed", item.number)
            except Exception as exc:
                log.warning("could not close epic #%d: %s", item.number, exc)


def _do_work(ctx: "RunContext") -> int:
    """Do the work: evaluate each work item, honouring the pipeline-wide
    aggregate concurrency ceiling. Returns the number of agents triggered."""
    total_triggered = 0
    for item in ctx.work_items:
        if not ctx.dry_run and ctx.concurrency.tick_launch_count >= PIPELINE_MAX_CONCURRENT:
            log.info(
                "Pipeline aggregate ceiling (%d) reached — deferring remaining work items to next tick.",
                PIPELINE_MAX_CONCURRENT,
            )
            break
        n = process_work_item(
            item, ctx.agents, ctx.pipeline_map, ctx.gh, ctx.dry_run, ctx.repo,
            session_id=ctx.session_id,
            default_extra_tools=ctx.default_extra_tools,
            concurrency=ctx.concurrency,
        )
        total_triggered += n
        if n > 0:
            # Brief pause between agent invocations to avoid rate limits
            time.sleep(2)
    _check_epic_completions(ctx)
    return total_triggered


def _close_down(ctx: "RunContext", total_triggered: int) -> None:
    """Close down: emit the run summary."""
    log.info("─" * 60)
    log.info("Complete. Agents triggered this run: %d", total_triggered)
    if not ctx.dry_run:
        _emit_audit_event(_make_audit_event(
            ctx.session_id, "system.tick", ctx.repo,
            outcome_status="complete",
            outcome_detail=f"{total_triggered} agent(s) triggered",
        ))


# Set to (gh, work_item_number, wip_label) while an agent is mid-flight so a
# termination signal (e.g. a CI or interactive timeout sending SIGTERM) can
# clear the :wip mutex it would otherwise strand. Updated by the :wip ceremony.
_CURRENT_WIP = None


def _clear_inflight_wip_on_signal(signum, _frame) -> None:
    """Best-effort: drop the in-flight :wip label, then exit.

    A killed tick (SIGTERM/SIGINT) otherwise leaves the work item stuck at :wip
    -- the mutex blocks the next tick from re-triggering the agent. Clearing that
    one label makes the item immediately retryable.
    """
    wip = _CURRENT_WIP
    if wip is not None:
        gh, number, label = wip
        try:
            gh.remove_label(number, label)
            log.warning("signal %d: cleared in-flight %s on #%d before exit", signum, label, number)
        except Exception as exc:
            log.warning("signal %d: could not clear in-flight %s on #%d: %s", signum, label, number, exc)
    sys.exit(128 + signum)


def main() -> None:
    # Wake up -> do the work -> close down.
    args = parse_args()

    # Clear an in-flight :wip if this process is terminated (timeout/cancel) so a
    # killed tick does not strand the mutex and block the next run.
    signal.signal(signal.SIGTERM, _clear_inflight_wip_on_signal)
    signal.signal(signal.SIGINT, _clear_inflight_wip_on_signal)

    global _VERBOSE, _HEADLESS
    _VERBOSE = args.verbose
    _HEADLESS = args.headless

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.print_prompt:
        _run_print_prompt(args)
        return

    ctx = _wake(args)
    if ctx is None:
        return

    total_triggered = _do_work(ctx)
    _close_down(ctx, total_triggered)


if __name__ == "__main__":
    main()
