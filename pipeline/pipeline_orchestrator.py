#!/usr/bin/env python3
"""
pipeline_orchestrator.py

Reads pipeline.json and orchestrates agent execution by inspecting GitHub
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

AUDIT_LOG_BRANCH = "ai-agile/log"
# Well-known empty-tree SHA in Git — used to create the orphan audit commit
# without making an API round-trip to POST /git/trees.
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

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

# Maximum agent instances launched across ALL agent types in a single orchestrator tick.
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
    mark_ready_on_complete: bool = False  # orchestrator calls gh pr ready on :complete
    commit_after: bool = False            # orchestrator stages + commits + pushes on :complete
    exclude_classifications: list = field(default_factory=list)  # skip if issue classification matches
    review_loop: Optional[dict] = None  # {"re_invoke": str, "max_cycles": int, "also_clear": [...]} — auto-retry on :review
    max_concurrent: int = 1             # max concurrent instances across work items; null/absent in pipeline.json defaults to 1
    script_timeout_seconds: int = SCRIPT_TIMEOUT_SECONDS  # override default timeout for script-type steps
    auto_approve_on_complete: bool = False  # if True, orchestrator auto-applies human_gate_label when agent emits :complete

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

def load_pipeline(path: Path) -> tuple[list[AgentDef], list[str]]:
    """Parse pipeline.json once and return (agents, default_extra_tools).

    default_extra_tools comes from defaults.extra_allowedTools and is
    prepended to every agent's own extra_allowedTools at invocation time.
    """
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
                mark_ready_on_complete=bool(entry.get("git_ops", {}).get("mark_ready_on_complete", False)),
                commit_after=bool(entry.get("git_ops", {}).get("commit_after", False)),
                exclude_classifications=list(entry.get("exclude_classifications", [])),
                review_loop=entry.get("review_loop"),
                max_concurrent=int(entry.get("max_concurrent") or 1),
                script_timeout_seconds=int(entry.get("script_timeout_seconds", SCRIPT_TIMEOUT_SECONDS)),
                auto_approve_on_complete=bool(entry.get("auto_approve_on_complete", False)),
            ))

        _raw_defaults = raw.get("defaults", {}).get("extra_allowedTools", [])
        default_extra_tools: list[str] = (
            [t.strip() for t in _raw_defaults.split(",") if t.strip()]
            if isinstance(_raw_defaults, str)
            else list(_raw_defaults)
        )

        return agents, default_extra_tools
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        log.error("pipeline.json is malformed — cannot start: %s", exc)
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
# Audit log (ai-agile/log orphan branch)
# ---------------------------------------------------------------------------

def _make_audit_event(
    session_id: str,
    event_type: str,
    repo: str,
    work_item: Optional[WorkItem] = None,
    agent: Optional[str] = None,
    outcome_status: str = "ok",
    outcome_detail: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> dict:
    """Build one audit event per the schema in docs/product/agile/08-audit-log.md."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    obj: Optional[dict] = None
    if work_item is not None:
        obj = {"kind": work_item.kind, "id": work_item.number, "repo": repo}
    return {
        "ts": ts,
        "event_type": event_type,
        "session_id": session_id,
        "object": obj,
        "agent": agent,
        "actor": {"kind": "orchestrator", "id": "github-actions", "human": None},
        "outcome": {"status": outcome_status, "detail": outcome_detail},
        "ref": None,
        "duration_ms": duration_ms,
    }


def _ensure_audit_log_branch(gh: GitHubClient) -> None:
    """Create the orphan ai-agile/log branch if it does not already exist."""
    encoded = requests.utils.quote(AUDIT_LOG_BRANCH, safe="")
    r = gh._request("GET", f"/repos/{gh.repo}/git/refs/heads/{encoded}")
    if r.status_code == 200:
        return
    if r.status_code != 404:
        r.raise_for_status()

    # Create an orphan commit on the well-known empty tree (no parents).
    commit = gh._post(f"/repos/{gh.repo}/git/commits", {
        "message": (
            "chore: initialise audit log\n\n"
            "Orphan branch — no shared history with main.\n"
            "Append-only JSONL event store per docs/product/agile/08-audit-log.md."
        ),
        "tree": EMPTY_TREE_SHA,
        "parents": [],
    })
    try:
        gh._post(f"/repos/{gh.repo}/git/refs", {
            "ref": f"refs/heads/{AUDIT_LOG_BRANCH}",
            "sha": commit["sha"],
        })
        log.info("Created orphan audit log branch: %s", AUDIT_LOG_BRANCH)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 422:
            log.debug("Audit log branch already exists (concurrent bootstrap); proceeding.")
        else:
            raise


def write_audit_log(gh: GitHubClient, events: list[dict]) -> None:
    """Append buffered audit events to the ai-agile/log branch.

    Events are grouped by UTC date and appended to events/YYYY/MM/DD.jsonl.
    On a 409 conflict (concurrent writer), fetches the updated file and
    re-applies the buffer, retrying up to three times.
    """
    if not events:
        return

    try:
        _ensure_audit_log_branch(gh)
    except Exception as exc:
        log.warning("Could not ensure audit log branch: %s — events dropped", exc)
        return

    by_date: dict[str, list[dict]] = {}
    for event in events:
        date_str = event.get("ts", "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        by_date.setdefault(date_str, []).append(event)

    for date_str, date_events in sorted(by_date.items()):
        parts = date_str.split("-")
        if len(parts) != 3:
            log.warning("Skipping audit event with malformed date %r — expected YYYY-MM-DD", date_str)
            continue
        year, month, day = parts
        path = f"events/{year}/{month}/{day}.jsonl"
        new_lines = "\n".join(json.dumps(e, separators=(",", ":")) for e in date_events) + "\n"

        _AUDIT_MAX_ATTEMPTS = 4
        for attempt in range(_AUDIT_MAX_ATTEMPTS):
            try:
                r = gh._request(
                    "GET",
                    f"/repos/{gh.repo}/contents/{path}",
                    params={"ref": AUDIT_LOG_BRANCH},
                )
                if r.status_code == 200:
                    file_data = r.json()
                    current_sha: Optional[str] = file_data["sha"]
                    existing = base64.b64decode(file_data["content"]).decode("utf-8")
                    full_content = existing + new_lines
                elif r.status_code == 404:
                    current_sha = None
                    full_content = new_lines
                else:
                    r.raise_for_status()
                    break

                put_body: dict = {
                    "message": f"audit: {len(date_events)} event(s) on {date_str}",
                    "content": base64.b64encode(full_content.encode()).decode(),
                    "branch": AUDIT_LOG_BRANCH,
                }
                if current_sha:
                    put_body["sha"] = current_sha

                put_r = gh._put(f"/repos/{gh.repo}/contents/{path}", put_body)
                if put_r.status_code in (200, 201):
                    log.info("Audit log: wrote %d event(s) → %s", len(date_events), path)
                    break
                elif put_r.status_code == 409:
                    if attempt < _AUDIT_MAX_ATTEMPTS - 1:
                        delay = 2 ** (attempt + 1)
                        log.warning(
                            "Audit log write conflict on %s; retrying in %ds"
                            " (attempt %d/%d)",
                            path, delay, attempt + 1, _AUDIT_MAX_ATTEMPTS,
                        )
                        time.sleep(delay)
                    else:
                        log.warning(
                            "Audit log write conflict on %s; giving up after %d attempts"
                            " — events dropped",
                            path, _AUDIT_MAX_ATTEMPTS,
                        )
                        break
                else:
                    put_r.raise_for_status()
                    break
            except Exception as exc:
                log.warning("Could not write audit log for %s: %s — events dropped", date_str, exc)
                break


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

    if not skip_cycle_increment and next_cycle >= max_cycles:
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
            "  LOOP    %-38s  human-review free re-invoke — re-invoking %s (cycle counter unchanged)",
            agent_def.agent, re_invoke_name,
        )
    else:
        log.info(
            "  LOOP    %-38s  cycle %d/%d — re-invoking %s",
            agent_def.agent, next_cycle, max_cycles, re_invoke_name,
        )

    if skip_cycle_increment:
        # Apply HUMAN_REVIEW_PENDING_LABEL instead of advancing the cycle counter.
        # This signals Mode B to the coder and prevents a second free re-invoke.
        try:
            gh.add_label(work_item.number, HUMAN_REVIEW_PENDING_LABEL)
            labels.add(HUMAN_REVIEW_PENDING_LABEL)
        except Exception as exc:
            log.warning(
                "could not apply %s on #%d: %s", HUMAN_REVIEW_PENDING_LABEL, work_item.number, exc
            )
            return labels  # guard not set; abort free re-invoke to preserve once-only semantics
    else:
        # Rotate the cycle counter label
        if current_cycle > 0:
            old = f"review-cycle:{current_cycle}"
            try:
                gh.remove_label(work_item.number, old)
                labels.discard(old)
            except Exception as exc:
                log.debug("could not remove %s on #%d: %s", old, work_item.number, exc)

        new_cycle_label = f"review-cycle:{next_cycle}"
        try:
            gh.add_label(work_item.number, new_cycle_label)
            labels.add(new_cycle_label)
        except Exception as exc:
            log.warning("could not apply %s on #%d: %s", new_cycle_label, work_item.number, exc)

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