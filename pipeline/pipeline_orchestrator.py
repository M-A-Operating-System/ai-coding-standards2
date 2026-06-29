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
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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

def load_statuses() -> tuple[list[dict], list[dict]]:
    """Load status and standalone-label definitions from statuses.json."""
    if not STATUSES_JSON.exists():
        log.error("statuses.json not found at %s — cannot start", STATUSES_JSON)
        sys.exit(1)
    try:
        with open(STATUSES_JSON) as f:
            data = json.load(f)
        return data["statuses"], data.get("standalone_labels", [])
    except (KeyError, json.JSONDecodeError) as e:
        log.error("statuses.json is malformed: %s", e)
        sys.exit(1)

STATUSES, STANDALONE_LABELS = load_statuses()
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
    exclude_classifications: list = field(default_factory=list)  # skip if issue classification matches
    exclude_labels: list = field(default_factory=list)           # skip if any of these labels is on the work item
    review_loop: Optional[dict] = None  # {"re_invoke": str, "max_cycles": int, "also_clear": [...]} — auto-retry on :review
    max_concurrent: int = 1             # max concurrent instances across work items; null/absent in pipeline.json defaults to 1
    script_timeout_seconds: int = SCRIPT_TIMEOUT_SECONDS  # override default timeout for script-type steps
    auto_approve_on_complete: bool = False  # if True, orchestrator auto-applies human_gate_label when agent emits :complete
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
    """
    success: bool
    returncode: Optional[int] = None
    captured_tail: str = ""
    rate_limited: bool = False
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


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
                exclude_classifications=list(entry.get("exclude_classifications", [])),
                exclude_labels=list(entry.get("exclude_labels", [])),
                review_loop=entry.get("review_loop"),
                max_concurrent=int(entry.get("max_concurrent") or 1),
                script_timeout_seconds=int(entry.get("script_timeout_seconds", SCRIPT_TIMEOUT_SECONDS)),
                auto_approve_on_complete=bool(entry.get("auto_approve_on_complete", False)),
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
        "actor": {"kind": "orchestrator", "id": "github-actions", "human": None},
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
    auto-cleared. It persists until the pipeline-restart workflow deletes it
    or the operator runs --clear-stop.
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

    # Clear target's :complete so it can be re-triggered
    try:
        gh.remove_label(work_item.number, target_def.complete_label)
        labels.discard(target_def.complete_label)
    except Exception as exc:
        log.warning(
            "could not remove %s on #%d: %s", target_def.complete_label, work_item.number, exc
        )

    # Clear any intermediate steps that must re-run (e.g. ci-gate between coder and pr-reviewer)
    also_cleared: list[str] = []
    for also_name in loop.get("also_clear", []):
        also_def = pipeline_map.get(also_name)
        if also_def is None:
            log.warning("review_loop also_clear '%s' not found in pipeline — skipping", also_name)
            continue
        try:
            gh.remove_label(work_item.number, also_def.complete_label)
            labels.discard(also_def.complete_label)
            also_cleared.append(also_name)
        except Exception as exc:
            log.warning(
                "could not remove %s on #%d: %s", also_def.complete_label, work_item.number, exc
            )

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


def dependencies_complete(
    labels: set[str],
    agent_def: AgentDef,
    pipeline_map: dict[str, AgentDef],
) -> bool:
    """
    Return True if every dependency is complete, where complete means:
      - The label {dep}:complete exists on the issue/PR, AND
      - If the dependency has a human_gate_label, that label also exists.
    """
    for dep_name in agent_def.dependencies:
        dep = pipeline_map.get(dep_name)
        if dep is None:
            log.warning("Unknown dependency: %s (required by %s)", dep_name, agent_def.agent)
            return False

        if dep.complete_label not in labels:
            return False

        if dep.human_gate_after and dep.human_gate_label:
            if dep.human_gate_label not in labels:
                log.debug(
                    "  %s complete but human gate '%s' not yet applied",
                    dep_name, dep.human_gate_label
                )
                return False

    return True


def trigger_label_present(labels: set[str], agent_def: AgentDef) -> bool:
    """Return True if the label trigger for this agent is satisfied."""
    trigger = agent_def.trigger
    if "label" in trigger:
        return trigger["label"] in labels
    # Event and schedule triggers are handled externally (GitHub Actions).
    # When running interactively, treat them as always-eligible.
    return True


_CLASSIFICATION_TYPES = {"bug", "toil", "enhancement", "feature", "spike"}

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
# is never auto-cleared — it persists until the pipeline-restart workflow deletes
# it (or the operator runs --clear-stop locally).
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
    """Accumulates agent text and token usage from stream-json CLI lines.

    A single line at a time is fed via ``feed()``. Both the live
    ``invoke_agent`` read loop and the batch ``_accumulate_stream_text``
    helper drive the same ``feed()`` logic, so tests that exercise the
    batch form cover the exact parsing the production loop uses.
    """

    __slots__ = ("text_parts", "input_tokens", "output_tokens")

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.input_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None

    def feed(self, line: str) -> None:
        """Parse one stream-json line, collecting text and (last-wins) tokens.

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
    ceremony — set-wip, opening/closing announcements, and final label
    transitions are all handled here. set-failed is applied by the
    orchestrator when the agent exits non-zero without a sentinel after
    all retries are exhausted.

    Returns an AgentRunResult with success/returncode/captured_tail and
    a rate_limited flag (set when a pause was written). Caller MUST NOT
    apply :failed when rate_limited is True — the agent never got a fair
    run.
    """
    agent_file = SUBMODULE_ROOT / ".claude/agents" / f"{agent_def.agent}.md"

    if agent_text_override is not None:
        # Caller pre-read the file before a branch checkout; use that snapshot
        # so the agent definition always reflects the orchestrator's branch,
        # not whatever happens to be checked out at invocation time.
        agent_text = agent_text_override
    elif not agent_file.exists():
        log.warning("    Agent file not found: %s — skipping", agent_file)
        return AgentRunResult(
            success=False,
            captured_tail=f"Agent prompt file not found at {agent_file}.",
        )
    else:
        agent_text = agent_file.read_text()

    frontmatter = parse_frontmatter(agent_text)
    agent_model: Optional[str] = frontmatter.get("model")  # type: ignore[assignment]
    # Frontmatter extra_allowedTools is a deprecated fallback; canonical config lives in
    # pipeline.json. All registered agents now have an empty frontmatter entry (comment only).
    _frontmatter_extra: list[str] = _coerce_tools(frontmatter.get("extra_allowedTools"))
    # Merge: defaults → pipeline.json per-agent → frontmatter fallback (deduplicated, order preserved).
    extra_tools = list(dict.fromkeys(
        list(default_extra_tools or []) +
        list(agent_def.extra_allowedTools) +
        _frontmatter_extra
    ))
    try:
        max_turns = int(frontmatter.get("max_turns", DEFAULT_MAX_TURNS))
    except (ValueError, TypeError):
        max_turns = DEFAULT_MAX_TURNS

    # Inline shared context and agent instructions into the prompt so both
    # are part of the first user message and eligible for prompt caching from
    # turn 1. Stable content (AGENTS.md, agent file) comes first; the small
    # work-item-specific wire-up comes last.
    agents_md = AI_AGILE_CONTEXT.read_text() if AI_AGILE_CONTEXT.exists() else ""
    agent_body = _strip_frontmatter(agent_text)
    num_var = "ISSUE_NUMBER" if work_item.kind == "issue" else "PR_NUMBER"
    kind_label = "Issue" if work_item.kind == "issue" else "PR"

    # Build the claude session ID before the prompt so its resolved value can
    # be embedded directly — agents must not shell out to read it.
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

    log.info("    Invoking agent: %s on %s #%d", agent_def.agent, work_item.kind, work_item.number)
    log.info("    session: %s (uuid: %s, scope=%s)", agent_session_id, agent_session_uuid, agent_def.session_scope)
    if agent_model:
        log.debug("    model: %s", agent_model)
    if extra_tools:
        log.debug("    extra_allowedTools: %s", extra_tools)
    log.debug("    max_turns: %d | prompt: %d chars", max_turns, len(prompt))

    # Scoped base allowlist. Each entry is a glob the bash command must
    # match. Keeping these narrow blocks the agent from reaching
    # secrets/settings/branches even if it is prompt-injected.
    base_tools = [
        "Bash(gh issue view *)",       # read issue body / labels
        "Bash(gh issue comment *)",    # post artefact comments
        "Bash(gh issue edit *)",       # apply classification/* and other labels
        "Bash(gh issue list *)",       # cross-issue reads (impact-assessor etc.)
        "Bash(gh pr view *)",          # PR-side agents read PR
        "Bash(gh pr comment *)",       # PR-side agents post comments
        "Bash(gh pr edit *)",          # PR-side label edits
        "Bash(gh pr list *)",
        "Bash(gh pr diff *)",          # pr-reviewer reads the diff
        "Bash(gh api repos/*/issues/*)",  # narrow direct API; only issue/PR endpoints
        "Bash(gh api repos/*/pulls/*)",
        "Bash(cat *)",                 # read prompt-side files
        "Bash(grep *)",
        "Bash(find *)",
        "Read",
        "Glob",
        "Grep",
    ]

    cmd = [
        "claude",
        "--allowedTools", ",".join(base_tools + extra_tools),
        "--output-format", "stream-json",
        "--verbose",                    # required alongside stream-json in --print mode
        "--max-turns", str(max_turns),
        "--session-id", agent_session_uuid,
    ]
    if agent_model:
        cmd += ["--model", agent_model]
    cmd += ["-p", prompt]

    # Export resolved paths so the agent prompt's bash snippets work
    # regardless of CWD or where this repo is mounted in the consuming
    # repo. Only one of ISSUE_NUMBER / PR_NUMBER is set, matching the
    # work item's kind, so the agent's prompt cannot get them confused.
    agent_env = {
        **os.environ,
        "AI_AGILE_ROOT": os.environ.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT)),
        "AI_AGILE_CONTEXT": str(AI_AGILE_CONTEXT),
        "REPO": repo,
        "WORK_ITEM_KIND": work_item.kind,
        "WORK_ITEM_NUMBER": str(work_item.number),
        "SESSION_ID": agent_session_id,
        "SESSION_SCOPE": agent_def.session_scope,
    }
    if work_item.kind == "issue":
        agent_env["ISSUE_NUMBER"] = str(work_item.number)
    else:
        agent_env["PR_NUMBER"] = str(work_item.number)

    # Preflight: a missing ANTHROPIC_API_KEY produces an auth-error response
    # that the stream-json parser may misread as a rate-limit pause, masking
    # the real cause and leaving the work item stuck in :wip indefinitely.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error(
            "  invoke_agent: ANTHROPIC_API_KEY is not set — cannot launch %s "
            "on %s #%d; add the key to CI secrets and retry.",
            agent_def.agent, work_item.kind, work_item.number,
        )
        return AgentRunResult(
            success=False,
            captured_tail=(
                "Configuration error: ANTHROPIC_API_KEY is not set. "
                "Add the key to CI secrets and retry."
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
                # orchestrator's CI output. Skip type=system events (thinking
                # token progress ticks) — they are pure noise in the log.
                try:
                    _ev = json.loads(line)
                    if _ev.get("type") != "system":
                        sys.stderr.write(line)
                except (json.JSONDecodeError, AttributeError):
                    sys.stderr.write(line)  # non-JSON lines always shown
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
                )
            return AgentRunResult(
                success=False,
                returncode=proc.returncode,
                captured_tail=agent_tail,
                input_tokens=acc.input_tokens,
                output_tokens=acc.output_tokens,
            )

        return AgentRunResult(
            success=True,
            returncode=0,
            captured_tail=agent_tail,
            input_tokens=acc.input_tokens,
            output_tokens=acc.output_tokens,
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

        gate_present = gate_label in updated
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
        f"- Apply the `{agent_def.status_label(STATUS_SKIPPED)}` label to bypass this agent on this item.",
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

    if not dependencies_complete(labels, agent_def, pipeline_map):
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
            _issue_branch = f"issue-{work_item.number}"
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


def _invoke_commit_after(agent_def: AgentDef, work_item: WorkItem) -> Optional[str]:
    """Run commit-agent-work.sh for a `commit_after` agent.

    Returns a human-readable failure reason, or None on success. The caller
    owns the label/branch side-effects on failure.
    """
    _commit_script = SUBMODULE_ROOT / ".github/scripts/commit-agent-work.sh"
    _commit_env = {
        **os.environ,
        "AGENT_NAME": agent_def.agent,
        "ISSUE_NUMBER": str(work_item.number),
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
        _ps_file = SUBMODULE_ROOT / _ps_path_str
        if not _ps_file.resolve().is_relative_to(SUBMODULE_ROOT.resolve()):
            log.error(
                "  post_steps: path %s escapes repo root — blocked (agent %s on #%d)",
                _ps_path_str, agent_def.agent, work_item.number,
            )
            return (
                f"_post_steps path `{_ps_path_str}` escapes the repository root. "
                f"This is a configuration error in pipeline.json. "
                f"Remove the failed label to retry._"
            )
        if not _ps_file.exists():
            log.error(
                "  post_steps: %s not found at %s (agent %s on #%d)",
                _ps_path_str, _ps_file, agent_def.agent, work_item.number,
            )
            return (
                f"_post_steps script `{_ps_path_str}` not found. "
                f"Check that the script exists on the orchestrator branch. "
                f"Remove the failed label to retry._"
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
                f"Remove the failed label to retry._"
            )
        except FileNotFoundError:
            log.error("  post_steps: bash not found in PATH")
            return (
                "_bash not found in PATH; post_steps script could not run. "
                "Remove the failed label to retry._"
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
                f"Remove the failed label to retry._"
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
    in which case the gate label is auto-applied and :complete stands.
    """
    applied_status = final_status
    if (
        final_status == STATUS_COMPLETE
        and agent_def.human_gate_after
        and agent_def.human_gate_label
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
) -> bool:
    """Apply GitHub side-effects for a completed agent run.

    Handles rate-limit short-circuit, final status determination, commit-after
    invocation, human review override, terminal label application, closing
    announcement, gate prompt, label refresh, audit event, and PR ready promotion.

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

    _announce_and_prompt(
        agent_def, work_item, session_id, applied_status, sentinel_message, gh,
    )

    # Refresh label set from GitHub after our writes.
    labels_refreshed = gh.get_issue_labels(work_item.number)
    work_item.labels = labels_refreshed

    log.info("  %-6s  %-38s", (applied_status or "?").upper(), agent_def.agent)

    _emit_terminal_audit(agent_def, work_item, applied_status, invoked_at, session_id, repo)

    # Mark the PR ready-for-review if the agent declares it (P-16).
    # Only fires on true completion — not when awaiting a human gate.
    if applied_status == STATUS_COMPLETE and agent_def.review_gate:
        _mark_pr_ready_if_requested(agent_def, work_item, gh)

    # post_steps: run per-agent completion hooks after the agent signals :complete.
    # Each hook is a repo-relative path to a bash script. A non-zero exit removes
    # :complete and applies :failed, halting the pipeline for this work item.
    if applied_status == STATUS_COMPLETE and agent_def.post_steps:
        _ps_fail_reason = _invoke_post_steps(agent_def, work_item, repo, gh)
        if _ps_fail_reason:
            try:
                gh.remove_label(work_item.number, agent_def.complete_label)
            except Exception as exc:
                log.debug(
                    "  could not remove %s before post_steps failure on #%d: %s",
                    agent_def.complete_label, work_item.number, exc,
                )
            _apply_failed(gh, agent_def, work_item, result, reason=_ps_fail_reason)
            applied_status = STATUS_FAILED
            log.error(
                "  FAILED  %-38s  post_steps failed on #%d",
                agent_def.agent, work_item.number,
            )
            _restore_pre_agent_branch(pre_agent_branch)
            return True

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

    for agent_def in agents:
        should_run = _should_run(agent_def, work_item, labels, pipeline_map, concurrency)
        if should_run is None:
            break
        if not should_run:
            continue

        result, sentinel_status, sentinel_message, pre_branch, invoked_at, attempt = _run_agent(
            agent_def, work_item, dry_run, repo, labels,
            session_id, default_extra_tools, concurrency, gh, pipeline_map,
        )

        if not dry_run:
            if result.rate_limited:
                paused, _reason, until = is_pipeline_paused()
                log.warning(
                    "  PAUSED  %-38s  rate-limited; resuming after %s",
                    agent_def.agent, until.isoformat() if until else "?"
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
            )
            labels = work_item.labels  # sync after _apply_result may have refreshed labels
            if stop:
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
             "without running the pipeline-restart workflow.",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show debug-level output",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Manual pause clear — short-circuit before doing anything else.
    if args.clear_pause:
        if clear_pause():
            log.info("Pause marker cleared. Re-run without --clear-pause to resume work.")
        else:
            log.info("No pause marker was set.")
        return

    # Manual stop clear — short-circuit before doing anything else.
    if args.clear_stop:
        if clear_stop():
            log.info("Stop marker cleared. Re-run without --clear-stop to resume work.")
        else:
            log.info("No stop marker was set.")
        return

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
        return

    # Emergency stop: an operator has halted the pipeline indefinitely.
    # Unlike the rate-limit pause, the stop marker is never auto-cleared.
    stopped, stop_reason = is_pipeline_stopped()
    if stopped:
        log.warning(
            "Pipeline is STOPPED: %s. No agents will be invoked. "
            "(Run pipeline-restart or use `--clear-stop` to resume.)",
            stop_reason or "no reason recorded",
        )
        _stop_session = f"ais-v1-orch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        _emit_audit_event(_make_audit_event(
            _stop_session, "system.emergency_stop", args.repo or "",
            outcome_status="stopped",
            outcome_detail=stop_reason or "no reason recorded",
        ))
        return

    if not args.repo:
        log.error("--repo is required or set $GITHUB_REPOSITORY")
        sys.exit(1)

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

    # Two-pass priority ordering: issues carrying the `priority` label are
    # moved to the front so they receive the next available :wip slot before
    # any non-priority work item. Concurrency limits apply unchanged to both
    # passes. List comprehensions iterate in source order, so relative order
    # within each group is preserved from the GitHub API response.
    _priority_items = [wi for wi in work_items if "priority" in wi.labels]
    _other_items    = [wi for wi in work_items if "priority" not in wi.labels]
    if _priority_items:
        log.info(
            "Priority items: %d (will be evaluated first): %s",
            len(_priority_items),
            [wi.number for wi in _priority_items],
        )
    work_items = _priority_items + _other_items

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

    total_triggered = 0
    for item in work_items:
        stopped, stop_reason = is_pipeline_stopped()
        if stopped:
            log.warning(
                "Pipeline STOPPED mid-run: %s. Exiting without further agent invocations.",
                stop_reason or "no reason recorded",
            )
            return

        if not args.dry_run and conc.tick_launch_count >= PIPELINE_MAX_CONCURRENT:
            log.info(
                "Pipeline aggregate ceiling (%d) reached — deferring remaining work items to next tick.",
                PIPELINE_MAX_CONCURRENT,
            )
            break
        n = process_work_item(
            item, agents, pipeline_map, gh, args.dry_run, args.repo,
            session_id=session_id,
            default_extra_tools=default_extra_tools,
            concurrency=conc,
        )
        total_triggered += n
        if n > 0:
            # Brief pause between agent invocations to avoid rate limits
            time.sleep(2)

    log.info("─" * 60)
    log.info("Complete. Agents triggered this run: %d", total_triggered)

    if not args.dry_run:
        _emit_audit_event(_make_audit_event(
            session_id, "system.tick", args.repo,
            outcome_status="complete",
            outcome_detail=f"{total_triggered} agent(s) triggered",
        ))


if __name__ == "__main__":
    main()
