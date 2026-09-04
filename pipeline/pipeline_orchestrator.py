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
    {agent-name}:exhausted    — agent ran out of its turn or wall-clock budget
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
import fnmatch
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
STATUS_EXHAUSTED   = "exhausted"
STATUS_SKIPPED     = "skipped"
STATUS_REQUESTED   = "requested"

# Alias kept for internal use
STATUS_IN_PROGRESS = STATUS_WIP

# Prefix identifying a component-claim label on an issue (e.g. "component:auth").
# Deliberately unvalidated -- no register of valid components anywhere; the
# orchestrator only compares these labels for equality (PRODUCT.md, "A
# component label lets unrelated work run at once").
COMPONENT_LABEL_PREFIX = "component:"

# Blocking eligibility (issue #405). blocks:{N} and blockedby:{N} declare an
# ordering dependency between two issues symmetrically -- PRODUCT.md,
# "Blocking declares an ordering dependency between issues". blockedby:{N}
# on an issue while N is still open makes that issue ineligible to start at
# all; blocks:{N} is the informational reciprocal on N's own label list.
BLOCKEDBY_LABEL_PREFIX = "blockedby:"
BLOCKS_LABEL_PREFIX = "blocks:"

ALL_STATUSES: list[str] = [
    STATUS_COMPLETE, STATUS_FAILED, STATUS_EXHAUSTED, STATUS_SKIPPED,  # terminal — highest priority
    STATUS_REVIEW, STATUS_BLOCKED,                     # halt
    STATUS_WIP,                                        # running
    STATUS_REQUESTED,                                  # manual trigger
]

# Statuses where the orchestrator takes no further action on this agent.
# review and blocked halt the pipeline but are NOT terminal — a human
# removes the label to resume. failed, exhausted and skipped are terminal:
# the orchestrator never auto-retries any of the three (PRODUCT.md, "A step
# returns exactly one of five outcomes" — exhausted is never retried because
# the budget itself has not changed between runs).
HALT_STATUSES    = {STATUS_REVIEW, STATUS_BLOCKED}
TERMINAL_STATUSES = {STATUS_COMPLETE, STATUS_FAILED, STATUS_EXHAUSTED, STATUS_SKIPPED}

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

# How much work a single tick will start before it stops, so a burst of
# eligible work (a hundred issues becoming eligible at once) does not consume
# everything available in one pass. A budget, not a concurrency-safety
# mechanism -- concurrent execution is governed by component-label claiming
# (ComponentClaims, below), independently of how many of those starts can run
# together (PRODUCT.md, "A component label lets unrelated work run at once").
# Default only -- load_pipeline() overwrites this from pipeline.json's
# budgets.max_launches_per_tick once the pipeline definition is loaded (AS-1).
MAX_LAUNCHES_PER_TICK = 20

# Maximum wall-clock time for a single agent invocation, unless the step
# declares its own override (AgentDef.max_wall_seconds).
# Default only -- load_pipeline() overwrites this from pipeline.json's
# budgets.max_wall_seconds once the pipeline definition is loaded (AS-1).
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
    lifecycle_before: list = field(default_factory=list)  # defaults.agent_lifecycle.before — run immediately before each invocation, including each retry
    lifecycle_after: list = field(default_factory=list)   # defaults.agent_lifecycle.after — run once after the last retry, whatever the outcome
    review_gate: bool = False             # True only for the agent that gates human review (pr-reviewer); controls free-reinvoke on unresolved human REQUEST_CHANGES
    commit_after: bool = False            # True when git_ops.commit_after is true; drives branch checkout + commit-agent-work.sh
    branch_suffix: str = ""               # appended to issue-{N} for the commit_after checkout (e.g. "-docs" -> issue-{N}-docs); "" means the default code branch (two-phase design->build, issue #247)
    exclude_classifications: list = field(default_factory=list)  # skip if issue classification matches
    exclude_labels: list = field(default_factory=list)           # skip if any of these labels is on the work item
    review_loop: Optional[dict] = None  # {"re_invoke": str, "max_cycles": int, "also_clear": [...]} — auto-retry on :review
    script_timeout_seconds: int = SCRIPT_TIMEOUT_SECONDS  # override default timeout for script-type steps
    auto_approve_on_complete: bool = False  # if True, orchestrator auto-applies human_gate_label when agent emits :complete
    self_gates: bool = False  # if True, the agent's own AI_AGILE_STATUS (review vs complete) decides whether the gate fires -- :complete is NOT force-overridden to :review. human_gate_after/human_gate_label still apply for promotion when the agent itself emits :review.
    extra_allowedTools: list[str] = field(default_factory=list)  # per-agent tools from pipeline.json; merged with defaults.extra_allowedTools (AS-1: nowhere else)
    model: Optional[str] = None         # agent-type steps only; which model this step runs on (AS-1: not a frontmatter field)
    max_turns: Optional[int] = None     # per-step override of budgets.max_turns; None means use the pipeline-wide default
    max_wall_seconds: Optional[int] = None  # per-step override of budgets.max_wall_seconds; None means use the pipeline-wide default
    expected_effect: dict = field(default_factory=dict)  # {"commits": bool, "creates_issues": bool} — what this step is supposed to change (MI-6)
    allowed_labels: dict = field(default_factory=dict)    # {"add": [...], "remove": [...]} — label patterns this step may request

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
    def exhausted_label(self) -> str:
        return f"{self.label_key}:{STATUS_EXHAUSTED}"

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
    timed_out    — True if the subprocess was killed for exceeding its
                    wall-clock budget (agent_def.max_wall_seconds /
                    AGENT_TIMEOUT_SECONDS). Distinguishes a budget exhaustion
                    from a generic crash so the caller can apply :exhausted
                    (never retried) instead of :failed (retried).
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
    timed_out: bool = False


@dataclass
class ComponentClaims:
    """Tracks which `component:` labels are currently claimed.

    PRODUCT.md, "A component label lets unrelated work run at once": before
    starting an item, an orchestrator instance claims every `component:`
    label the item names, all at once, and starts only if it can claim them
    all -- an item never holds part of what it needs while waiting for the
    rest, which is what keeps this from deadlocking. An untagged item claims
    everything, so it runs exactly as sequentially as the pipeline did before
    component claims existed.

    `claimed` holds the individual component labels currently held by some
    in-flight (or already-launched-this-tick) item; claims are disjoint by
    construction, since an item only ever claims components nothing else
    currently holds. `claims_everything` is True while an untagged item is
    in flight -- nothing else may claim anything until it finishes, and it
    itself may only start when nothing else is claimed.

    tick_launch_count tracks agents launched in this tick against the
    pipeline-wide per-tick budget (MAX_LAUNCHES_PER_TICK) -- unrelated to
    claiming; it exists purely to bound how much one tick starts.
    """
    claimed: set = field(default_factory=set)
    claims_everything: bool = False
    tick_launch_count: int = 0

    def can_claim(self, components: "frozenset[str] | set[str]") -> bool:
        if self.claims_everything:
            return False
        if not components:
            return not self.claimed
        return not (set(components) & self.claimed)

    def claim(self, components: "frozenset[str] | set[str]") -> None:
        if not components:
            self.claims_everything = True
        else:
            self.claimed |= set(components)

    def unclaim(self, components: "frozenset[str] | set[str]") -> None:
        if not components:
            self.claims_everything = False
        else:
            self.claimed -= set(components)


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
                script_timeout_seconds=int(entry.get("script_timeout_seconds", SCRIPT_TIMEOUT_SECONDS)),
                auto_approve_on_complete=bool(entry.get("auto_approve_on_complete", False)),
                self_gates=bool(entry.get("self_gates", False)),
                extra_allowedTools=_coerce_tools(entry.get("extra_allowedTools")),
                model=entry.get("model"),
                max_turns=(entry.get("budgets") or {}).get("max_turns"),
                max_wall_seconds=(entry.get("budgets") or {}).get("max_wall_seconds"),
                expected_effect=dict(entry.get("expected_effect") or {}),
                allowed_labels=dict(entry.get("allowed_labels") or {}),
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

        # Scripts the orchestrator runs around every agent invocation. Declared
        # here rather than named in this module because the pipeline describes
        # itself (STD-ARCH-035): a new lifecycle step is added by writing a
        # script and listing it, with no change to the orchestrator.
        #
        # Agent steps only. A script step is a process step in its own right --
        # it is not wrapped, and it is never handed a scratch directory, so an
        # "after" hook for one would tear down something it never received.
        _lifecycle = raw.get("defaults", {}).get("agent_lifecycle", {}) or {}
        _before = list(_lifecycle.get("before", []))
        _after = list(_lifecycle.get("after", []))
        for _agent in agents:
            if _agent.step_type == "agent":
                _agent.lifecycle_before = list(_before)
                _agent.lifecycle_after = list(_after)

        # AS-1: pipeline.json's budgets is the sole source for these three
        # values -- they used to be hardcoded module constants. Mutating the
        # globals here (rather than threading a return value through every
        # caller) keeps every existing reference to DEFAULT_MAX_TURNS /
        # AGENT_TIMEOUT_SECONDS / MAX_LAUNCHES_PER_TICK unchanged; only their
        # source of truth moves.
        global DEFAULT_MAX_TURNS, AGENT_TIMEOUT_SECONDS, MAX_LAUNCHES_PER_TICK
        _budgets = raw["budgets"]
        DEFAULT_MAX_TURNS = int(_budgets["max_turns"])
        AGENT_TIMEOUT_SECONDS = int(_budgets["max_wall_seconds"])
        MAX_LAUNCHES_PER_TICK = int(_budgets.get("max_launches_per_tick", MAX_LAUNCHES_PER_TICK))

        return agents, default_extra_tools
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        log.error("pipeline.json is malformed (agent: %s) — cannot start: %s", entry.get("agent", "<unknown>"), exc)
        sys.exit(1)


def pipeline_by_name(agents: list[AgentDef]) -> dict[str, AgentDef]:
    return {a.agent: a for a in agents}


def _work_item_components(work_item: WorkItem) -> frozenset[str]:
    """The `component:` labels a work item carries.

    Empty means untagged -- PRODUCT.md: an untagged item claims everything.
    """
    return frozenset(lbl for lbl in work_item.labels if lbl.startswith(COMPONENT_LABEL_PREFIX))


def _is_in_flight(work_item: WorkItem) -> bool:
    """True if the item carries any agent's :wip status label."""
    return any(lbl.endswith(f":{STATUS_WIP}") for lbl in work_item.labels)


def _seed_component_claims(work_items: list[WorkItem]) -> ComponentClaims:
    """Settled component-claim state at headless tick start.

    Every item already carrying some agent's :wip label (left running by a
    prior tick) has its components claimed, so this tick's eligibility checks
    account for them from the first item evaluated.
    """
    claims = ComponentClaims()
    for wi in work_items:
        if _is_in_flight(wi):
            claims.claim(_work_item_components(wi))
    return claims


def _fresh_component_claims(gh: "GitHubClient", exclude_number: int) -> ComponentClaims:
    """Interactive mode: read every OTHER in-flight item's component labels
    fresh from GitHub.

    Interactive is genuinely several unserialised processes (PRODUCT.md, "A
    component label lets unrelated work run at once") -- a settled in-memory
    snapshot from this process's own tick start could miss a sibling
    `/maos-{agent}` invocation that started after that snapshot was taken, so
    this reads the current label state directly instead of trusting it.

    Fail-closed (STD-ARCH-014, MI-7 pattern): an API error refuses every
    claim (claims_everything=True) rather than silently proceeding as if
    nothing were in flight, since the latter could commit two runs onto the
    same component. The caller sees "no claim available" and the item is
    simply re-checked next time.
    """
    claims = ComponentClaims()
    try:
        items = gh.list_open_issues(kind="all")
    except Exception as exc:
        log.warning(
            "could not fetch fresh component claims (%s) — refusing to claim "
            "(fail-closed)", exc,
        )
        claims.claims_everything = True
        return claims
    for item in items:
        if item.number == exclude_number:
            continue
        if _is_in_flight(item):
            claims.claim(_work_item_components(item))
    return claims


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

    def list_comment_bodies(self, number: int) -> list[str]:
        """Return every comment body on an issue or PR, oldest first, paginated."""
        bodies: list[str] = []
        page = 1
        while True:
            data = self._get(
                f"/repos/{self.repo}/issues/{number}/comments",
                params={"per_page": 100, "page": page},
            )
            if not data:
                break
            bodies.extend(c.get("body") or "" for c in data)
            page += 1
        return bodies

    def get_body(self, number: int) -> str:
        """Return the current body text of an issue or PR.

        A PR is an issue as far as this endpoint is concerned (same as
        post_comment above), so one method covers both. Never None -- an
        issue/PR with no body returns "".
        """
        data = self._get(f"/repos/{self.repo}/issues/{number}")
        return data.get("body") or ""

    def update_body(self, number: int, body: str, title: Optional[str] = None) -> None:
        """Replace an issue's or PR's body, and optionally its title.

        Full replace only -- callers that need a partial update (issue #401's
        section-scoped todos patch) read the current body via get_body,
        compute the new full body themselves, and pass that here.
        """
        payload: dict = {"body": body}
        if title is not None:
            payload["title"] = title
        r = self._request("PATCH", f"/repos/{self.repo}/issues/{number}", json_body=payload)
        r.raise_for_status()

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
    """Build one audit event per the schema in docs/product/orchestrator/PRODUCT.md, MI-6 'The shape of one record'."""
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


# STD-SEC-022 — git plumbing (read-tree, update-index, write-tree): purely local
# object-store ops; no network, no auth token needed. GIT_INDEX_FILE is set explicitly.
_GIT_PLUMBING_ENV_VARS = ("PATH", "HOME")


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
            git_env = {  # STD-SEC-022
                **{k: os.environ[k] for k in _GIT_PLUMBING_ENV_VARS if k in os.environ},
                "GIT_INDEX_FILE": index_path,
            }
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
    """Return True only if the gate label was verifiably applied by a human.

    A prompt-injected agent can self-approve its own gate by applying its
    ``{agent}:approved`` label. Since PR #262 agents run with the repo-scoped
    GITHUB_TOKEN, so an agent-applied label is authored by a bot account
    (``actor.type == "Bot"`` and/or a login ending in ``[bot]``). A genuine
    human approval is authored by a real user login.

    This inspects the issue's ``labeled`` events (paginated -- see below),
    finds the most recent one for ``gate_label``, and returns True only when
    that actor is positively a human (``actor.type == "User"``, login not
    ``[bot]``-suffixed).

    FAIL-CLOSED (STD-ARCH-014; PRODUCT.md MI-7 -- "An approval the
    orchestrator cannot establish a person stood behind is refused"): every
    inconclusive case -- an API error, an unexpected payload shape, no
    matching labeled event found, or an actor that isn't determinably human
    -- refuses (returns False). A transient API error now halts the gate
    rather than silently admitting an unverified approval; that tradeoff is
    the point (MI-7's "no amount of actor-checking" note is about interactive
    mode's transcription path, not about weakening this check).

    Paginated: an issue with many label transitions can have its gate's
    ``labeled`` event beyond the API's default single page, which would
    silently read as "no matching event" -- harmless under the old fail-open
    behaviour, but a false refusal of a genuine approval under fail-closed.
    """
    events: list = []
    page = 1
    try:
        while True:
            batch = gh._get(
                f"/repos/{repo}/issues/{work_item_number}/events",
                params={"per_page": 100, "page": page},
            )
            if not isinstance(batch, list):
                log.warning(
                    "  unexpected events payload for #%s verifying gate '%s' -"
                    " refusing (fail-closed)",
                    work_item_number, gate_label,
                )
                return False
            if not batch:
                break
            events.extend(batch)
            if len(batch) < 100:
                break
            page += 1
    except Exception as exc:
        log.warning(
            "  could not fetch events for #%s to verify gate '%s' applier: %s"
            " - refusing (fail-closed)",
            work_item_number, gate_label, exc,
        )
        return False

    labeled = [
        e for e in events
        if isinstance(e, dict)
        and e.get("event") == "labeled"
        and isinstance(e.get("label"), dict)
        and e["label"].get("name") == gate_label
    ]
    if not labeled:
        log.warning(
            "  no 'labeled' event found for gate '%s' on #%s - refusing (fail-closed)",
            gate_label, work_item_number,
        )
        return False

    actor = labeled[-1].get("actor")
    if not isinstance(actor, dict):
        log.warning(
            "  could not determine actor for gate '%s' on #%s - refusing (fail-closed)",
            gate_label, work_item_number,
        )
        return False

    actor_type = actor.get("type")
    actor_login = actor.get("login") or ""
    if actor_type == "User" and not actor_login.endswith("[bot]"):
        return True

    log.warning(
        "  gate '%s' on #%s was applied by non-human actor '%s' (type=%s) -"
        " NOT treating gate as satisfied (self-approval guard, fail-closed)",
        gate_label, work_item_number, actor_login or "?", actor_type,
    )
    return False


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

# Default max turns for steps that do not declare their own budgets.max_turns
# in pipeline.json. 30 is enough for complex agents; simple ones (classifier)
# declare a lower per-step override.
# Default only -- load_pipeline() overwrites this from pipeline.json's
# budgets.max_turns once the pipeline definition is loaded (AS-1).
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


# ---------------------------------------------------------------------------
# Step result file (issue #400) — agent-type steps only. Script-type steps
# (invoke_script) still use the AI_AGILE_STATUS stdout sentinel above; that
# migration is out of scope here (a script "meets the contract by
# construction", per PRODUCT.md — it cannot improvise past a refusal or
# replay a stale answer the way a non-deterministic agent can).
# ---------------------------------------------------------------------------

_RESULT_FILENAME = "result.json"
_VALID_OUTCOMES = (STATUS_COMPLETE, STATUS_REVIEW, STATUS_BLOCKED)


@dataclass
class StepResult:
    """One step's structured return, read from $AI_AGILE_SCRATCH/result.json.

    Mirrors PRODUCT.md's "What a step must return" table. outcome/summary/
    undone are required; message/output/expected_effect/label_requests
    default to empty when the step omits them (e.g. a `complete` outcome
    with nothing to report beyond the summary).

    body_write (issue #401) is one of two shapes, or {} for no body write:
      {"target": "issue"|"pr", "mode": "replace", "body": str, "title": str?}
      {"target": "issue"|"pr", "mode": "patch", "subsection": str, "content": str}
    A step never writes the body itself (PRODUCT.md, "What a step must
    return"): "replace" is a full-body rewrite (prd-writer); "patch" is a
    section-scoped update inside the todos block (see _apply_todos_patch),
    retried on conflict by the orchestrator.
    """
    outcome: str                    # complete | review | blocked
    summary: str                    # the step's own account, including "did nothing"
    undone: str = ""                # what's left; empty when nothing was left
    message: str = ""               # short message for review/blocked (what a person must act on)
    output: str = ""                # artefact content; the orchestrator posts this, the step doesn't
    expected_effect: dict = field(default_factory=dict)   # the step's own belief about what it changed this run
    label_requests: list = field(default_factory=list)    # [{"issue": int|None, "add": [...], "remove": [...]}]
    body_write: dict = field(default_factory=dict)        # {} = none; see _read_step_result for the two shapes


def _result_file_path(scratch_dir: str) -> Path:
    """Sole definition of the result-file path formula, matching _scratch_path."""
    return Path(scratch_dir) / _RESULT_FILENAME


def _read_step_result(scratch_dir: str) -> tuple[Optional[StepResult], str]:
    """Read and validate the step's result file.

    Returns (StepResult, "") on success, or (None, reason) when the file is
    missing, unreadable, not a JSON object, or missing/malformed a required
    field. Any of these is treated as "returned something malformed" — the
    same bucket PRODUCT.md puts a crash and an empty return in ("A step
    returns exactly one of five outcomes": failed is set by the orchestrator
    when a step "crashed, returned nothing, or returned something
    malformed"). No outcome is inferred from a clean process exit alone.
    """
    if not scratch_dir:
        return None, "no scratch directory for this run"
    path = _result_file_path(scratch_dir)
    if not path.is_file():
        return None, f"no result file at {path}"
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"result file could not be read/parsed: {exc}"
    if not isinstance(raw, dict):
        return None, "result file is not a JSON object"

    outcome = raw.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        return None, f"result.outcome must be one of {_VALID_OUTCOMES}, got {outcome!r}"

    summary = raw.get("summary")
    if not isinstance(summary, str):
        return None, "result.summary must be a string"

    for _field in ("undone", "message", "output"):
        _val = raw.get(_field, "")
        if not isinstance(_val, str):
            return None, f"result.{_field} must be a string"

    expected_effect = raw.get("expected_effect", {})
    if not isinstance(expected_effect, dict):
        return None, "result.expected_effect must be an object"

    label_requests = raw.get("label_requests", [])
    if not isinstance(label_requests, list):
        return None, "result.label_requests must be an array"
    for lr in label_requests:
        if not isinstance(lr, dict):
            return None, "each result.label_requests entry must be an object"
        _issue = lr.get("issue")
        if _issue is not None and not isinstance(_issue, int):
            return None, "result.label_requests[].issue must be an integer or null"
        for _key in ("add", "remove"):
            _labels = lr.get(_key, [])
            if not isinstance(_labels, list) or not all(isinstance(x, str) for x in _labels):
                return None, f"result.label_requests[].{_key} must be an array of strings"

    body_write = raw.get("body_write", {})
    if not isinstance(body_write, dict):
        return None, "result.body_write must be an object"
    if body_write:
        if body_write.get("target") not in ("issue", "pr"):
            return None, 'result.body_write.target must be "issue" or "pr"'
        _mode = body_write.get("mode")
        if _mode == "replace":
            if not isinstance(body_write.get("body"), str):
                return None, "result.body_write.body must be a string when mode is \"replace\""
            _title = body_write.get("title")
            if _title is not None and not isinstance(_title, str):
                return None, "result.body_write.title must be a string or absent"
        elif _mode == "patch":
            if not isinstance(body_write.get("subsection"), str) or not body_write.get("subsection"):
                return None, "result.body_write.subsection must be a non-empty string when mode is \"patch\""
            if not isinstance(body_write.get("content"), str):
                return None, "result.body_write.content must be a string when mode is \"patch\""
        else:
            return None, 'result.body_write.mode must be "replace" or "patch"'

    return StepResult(
        outcome=outcome,
        summary=summary,
        undone=raw.get("undone", ""),
        message=raw.get("message", ""),
        output=raw.get("output", ""),
        expected_effect=expected_effect,
        label_requests=label_requests,
        body_write=body_write,
    ), ""


def _is_exhausted(result: "AgentRunResult") -> bool:
    """True when the run hit a budget wall rather than crashing or finishing.

    Two independent signals: the orchestrator's own wall-clock timer fired
    (result.timed_out), or the CLI itself reports exhausting --max-turns via
    the result event's subtype (already captured into metrics as
    result_event["subtype"] — see _build_agent_metrics).
    """
    if result.timed_out:
        return True
    return (result.result_event or {}).get("subtype") == "error_max_turns"


def _label_pattern_matches(pattern: str, label: str) -> bool:
    """Same glob convention as extra_allowedTools: '*' spans any characters."""
    return fnmatch.fnmatchcase(label, pattern)


def _filter_allowed_label_requests(agent_def: "AgentDef", label_requests: list) -> list:
    """Filter requested label add/remove ops down to what allowed_labels permits.

    Returns a flat list of (issue_number_or_None, "add"|"remove", label)
    tuples that clear the check. Everything else is silently dropped
    (PRODUCT.md: "the orchestrator checks each request against the step's
    declared allowed_labels and applies only what clears, silently dropping
    the rest") — a step with no declared allowed_labels may request nothing.
    """
    allowed_add = agent_def.allowed_labels.get("add", []) or []
    allowed_remove = agent_def.allowed_labels.get("remove", []) or []
    cleared: list = []
    for lr in label_requests:
        issue_num = lr.get("issue")
        for lbl in lr.get("add", []) or []:
            if any(_label_pattern_matches(p, lbl) for p in allowed_add):
                cleared.append((issue_num, "add", lbl))
        for lbl in lr.get("remove", []) or []:
            if any(_label_pattern_matches(p, lbl) for p in allowed_remove):
                cleared.append((issue_num, "remove", lbl))
    return cleared


def _apply_label_requests(
    gh: "GitHubClient", agent_def: "AgentDef", work_item: "WorkItem", label_requests: list,
) -> None:
    """Apply every label request that clears allowed_labels. Never raises."""
    for issue_num, op, lbl in _filter_allowed_label_requests(agent_def, label_requests):
        target = issue_num if issue_num is not None else work_item.number
        try:
            if op == "add":
                gh.add_label(target, lbl)
            else:
                gh.remove_label(target, lbl)
            log.info("  LABEL   %-38s  %s %r on #%d", agent_def.agent, op, lbl, target)
        except Exception as exc:
            log.warning(
                "  could not %s label %r on #%d (requested by %s): %s",
                op, lbl, target, agent_def.agent, exc,
            )


def _post_artefact_if_present(
    gh: "GitHubClient", agent_def: "AgentDef", work_item: "WorkItem", step_result: Optional[StepResult],
) -> None:
    """Post the step's output as a structured artefact comment, if it produced one.

    The step never posts its own comments (P-10/P-14, PRODUCT.md "What a
    step must never do"); this is the orchestrator doing that on its behalf,
    the same way it already owns the opening/closing announcements.
    """
    if not step_result or not step_result.output:
        return
    body = f"<!-- ai-agile/artefact/v1 by {agent_def.agent} -->\n\n{step_result.output}"
    try:
        gh.post_comment(work_item.number, body)
    except Exception as exc:
        log.warning(
            "  could not post artefact comment for %s on #%d: %s",
            agent_def.agent, work_item.number, exc,
        )


# ---------------------------------------------------------------------------
# Body writes (issue #401) — a step never writes an issue/PR body itself
# (PRODUCT.md, "What a step must return" / "What a step must never do");
# it returns what the new body or section should say, in StepResult's
# body_write field, and the orchestrator applies it here.
# ---------------------------------------------------------------------------

_TODOS_HEADING = "## AI Agile -- Tasks"
_TODOS_OUTER_START = "<!-- ai-agile/todos/v1 START -->"
_TODOS_OUTER_END = "<!-- ai-agile/todos/v1 END -->"

_BODY_WRITE_MAX_ATTEMPTS = 3


def _todos_subsection_markers(subsection: str) -> tuple[str, str]:
    return (
        f"<!-- ai-agile/todos/{subsection}/v1 START -->",
        f"<!-- ai-agile/todos/{subsection}/v1 END -->",
    )


_CHECKED_ITEM_RE = re.compile(r"^[ \t]*-\s*\[x\]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _checked_items_would_be_lost(old_content: str, new_content: str) -> str:
    """Return a non-empty refusal reason if any `- [x]` line in old_content
    is missing, or no longer checked, in new_content -- comparing by the
    checkbox's own text, so a step that only appends new entries or ticks
    more boxes never trips this. A checked item's text is terminal (AGENTS.md:
    a `done`/`blocked`/`skipped` event is appended once and it never changes
    again), so an exact-text comparison is the whole check.
    """
    old_checked = set(_CHECKED_ITEM_RE.findall(old_content))
    if not old_checked:
        return ""
    lost = old_checked - set(_CHECKED_ITEM_RE.findall(new_content))
    if not lost:
        return ""
    shown = sorted(lost)[:3]
    return (
        f"patch would un-check or drop {len(lost)} previously checked item(s): "
        + "; ".join(shown) + ("; ..." if len(lost) > len(shown) else "")
    )


def _apply_todos_patch(body: str, subsection: str, content: str) -> tuple[Optional[str], str]:
    """Compute a new body with `subsection`'s todos-block content replaced by
    `content`, creating the outer/subsection marker blocks if either is
    absent yet (PRODUCT.md, "What lands on the issue"). Returns (new_body,
    "") on success, or (None, reason) when the patch would silently drop a
    previously checked item -- the caller keeps the old body unchanged.

    Touches only the named subsection; every other subsection's content,
    and everything outside the outer block, passes through byte-for-byte.
    """
    sub_start, sub_end = _todos_subsection_markers(subsection)

    outer_start_idx = body.find(_TODOS_OUTER_START)
    if outer_start_idx == -1:
        # No todos block at all yet -- create it, with just this subsection.
        block = (
            f"\n\n{_TODOS_HEADING}\n\n{_TODOS_OUTER_START}\n"
            f"{sub_start}\n{content}\n{sub_end}\n"
            f"{_TODOS_OUTER_END}\n"
        )
        return body.rstrip("\n") + block, ""

    outer_end_idx = body.find(_TODOS_OUTER_END, outer_start_idx)
    if outer_end_idx == -1:
        return None, "found an unterminated todos block (START with no matching END)"

    outer_inner_start = outer_start_idx + len(_TODOS_OUTER_START)
    outer_content = body[outer_inner_start:outer_end_idx]

    sub_start_idx = outer_content.find(sub_start)
    if sub_start_idx == -1:
        # Subsection doesn't exist yet within the outer block -- append it,
        # leaving every existing subsection untouched.
        new_outer_content = outer_content.rstrip("\n") + f"\n{sub_start}\n{content}\n{sub_end}\n"
        return body[:outer_inner_start] + new_outer_content + body[outer_end_idx:], ""

    sub_end_idx = outer_content.find(sub_end, sub_start_idx)
    if sub_end_idx == -1:
        return None, f"found an unterminated {subsection} subsection (START with no matching END)"

    sub_inner_start = sub_start_idx + len(sub_start)
    old_content = outer_content[sub_inner_start:sub_end_idx]

    refusal = _checked_items_would_be_lost(old_content, content)
    if refusal:
        return None, refusal

    # Same "\n{content}\n" wrapping as the create-from-scratch and
    # new-subsection paths above, so a subsection's on-disk shape doesn't
    # depend on whether this is its first patch or a later one.
    new_outer_content = outer_content[:sub_inner_start] + f"\n{content}\n" + outer_content[sub_end_idx:]
    return body[:outer_inner_start] + new_outer_content + body[outer_end_idx:], ""


def _resolve_body_write_target(
    gh: "GitHubClient", work_item: "WorkItem", target: str,
) -> Optional[int]:
    """Resolve body_write's declared target ("issue" or "pr") to a real
    number. Mirrors _mark_pr_ready_if_requested's PR lookup: a step running
    against an issue work item but targeting "pr" (e.g. coder ticking a PR's
    build-plan) needs the PR found by branch/label the same way review-gate
    promotion does.
    """
    if target == "issue":
        return work_item.number if work_item.kind == "issue" else None
    if work_item.kind == "pr":
        return work_item.number
    try:
        pr_number = gh.find_pr_by_branch(f"issue-{work_item.number}")
        if pr_number is None:
            pr_number = gh.find_pr_by_label(f"source-issue:{work_item.number}")
        return pr_number
    except Exception:
        return None


def _snapshot_body_if_first_replace(gh: "GitHubClient", agent_def: "AgentDef", number: int) -> None:
    """Post the pre-write body as a snapshot comment, once, before the first
    full-body replace this agent makes on this target (PRODUCT.md: "snapshot
    ... Human-authored content preserved verbatim before a step rewrote it").
    Idempotent -- checks for a prior `ai-agile/snapshot/v1 by {agent}`
    comment first, so a re-run never re-snapshots (P-11).
    """
    marker = f"<!-- ai-agile/snapshot/v1 by {agent_def.agent} -->"
    if any(marker in existing for existing in gh.list_comment_bodies(number)):
        return
    current_body = gh.get_body(number)
    gh.post_comment(number, f"{marker}\n\n{current_body}")


def _apply_body_write(
    gh: "GitHubClient", agent_def: "AgentDef", work_item: "WorkItem", step_result: Optional[StepResult],
) -> None:
    """Apply the step's requested body write (issue #401), if any. Never raises.

    "replace": a full-body rewrite, snapshotted first (see
    _snapshot_body_if_first_replace).

    "patch": a section-scoped todos-block update, retried up to
    _BODY_WRITE_MAX_ATTEMPTS times on a verified conflict -- read the
    current body, compute the patch, write it, then re-read to confirm the
    write landed as intended. The Issues API has no ETag/If-Match for body
    PATCHes, so this is an application-level optimistic-retry loop, not a
    server-enforced one (PRODUCT.md: "retrying if another write landed
    first is post-action plumbing").
    """
    if not step_result or not step_result.body_write:
        return
    bw = step_result.body_write
    target_number = _resolve_body_write_target(gh, work_item, bw["target"])
    if target_number is None:
        log.warning(
            "  could not resolve body_write target (%s) for %s on #%d",
            bw["target"], agent_def.agent, work_item.number,
        )
        return

    if bw["mode"] == "replace":
        try:
            _snapshot_body_if_first_replace(gh, agent_def, target_number)
            gh.update_body(target_number, bw["body"], title=bw.get("title"))
            log.info("  BODY    %-38s  replaced #%d", agent_def.agent, target_number)
        except Exception as exc:
            log.warning(
                "  could not replace body for %s on #%d: %s",
                agent_def.agent, target_number, exc,
            )
        return

    # mode == "patch"
    subsection, content = bw["subsection"], bw["content"]
    sub_start, sub_end = _todos_subsection_markers(subsection)
    expected_fragment = f"{sub_start}\n{content}\n{sub_end}"
    for attempt in range(1, _BODY_WRITE_MAX_ATTEMPTS + 1):
        try:
            current_body = gh.get_body(target_number)
            new_body, refusal = _apply_todos_patch(current_body, subsection, content)
            if refusal:
                log.warning(
                    "  refused body_write patch for %s on #%d: %s",
                    agent_def.agent, target_number, refusal,
                )
                return
            gh.update_body(target_number, new_body)
            # Verify the write landed as intended -- a concurrent write
            # between our read and our write would otherwise go undetected.
            if expected_fragment in gh.get_body(target_number):
                log.info(
                    "  BODY    %-38s  patched %s on #%d (attempt %d)",
                    agent_def.agent, subsection, target_number, attempt,
                )
                return
        except Exception as exc:
            log.warning(
                "  body_write patch attempt %d for %s on #%d failed: %s",
                attempt, agent_def.agent, target_number, exc,
            )
    log.warning(
        "  could not apply body_write patch for %s on #%d after %d attempt(s) -- conflicting writes",
        agent_def.agent, target_number, _BODY_WRITE_MAX_ATTEMPTS,
    )


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
    expected_effect: Optional[dict] = None,
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
    # The step's declared expected effect (pipeline.json, MI-6) — recorded
    # here so it's visible in the audit trail alongside the outcome it
    # produced. Comparing it against what actually changed is a follow-up;
    # this records the declared half of that comparison.
    if expected_effect:
        payload["expected_effect"] = expected_effect
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

# STD-SEC-022 -- env vars passed to bash script-type pipeline steps (create-pr.sh,
# create-docs-pr.sh, merge-docs-pr.sh, ci-gate.sh). These scripts invoke gh/git
# but not Claude CLI, so no ANTHROPIC_API_KEY. Work-item context vars (REPO,
# ISSUE_NUMBER, etc.) are set explicitly below, not passed through.
#
# CI_GATE_EXCLUDE_JOB_NAMES and GITHUB_RUN_ID are read by ci-gate.sh to exclude
# the orchestrator's own in-flight job from the checks it waits on. Without them
# the exclusion list is empty and the gate counts its own run, stalling on
# :blocked. Neither is a credential.
_SCRIPT_AGENT_ENV_VARS = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
    "GH_TOKEN", "GITHUB_TOKEN",
    "CI_GATE_EXCLUDE_JOB_NAMES", "GITHUB_RUN_ID",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
)

# Scripts that open or merge a PR, and so may need the bot PAT when org policy
# blocks GITHUB_TOKEN from those operations:
#   create-pr.sh      -- _PR_TOKEN, for `gh pr create`
#   merge-docs-pr.sh  -- _MERGE_TOKEN, for the design-PR merge
#   create-docs-pr.sh -- execs into create-pr.sh, so it needs it too
# ci-gate.sh only reads check runs and never references the variable, so it is
# not on this list. AI_AGILE_BOT_TOKEN is a classic PAT with repo+workflow
# scopes -- the broadest credential the orchestrator holds -- so it goes only to
# the steps that demonstrably use it.
_PR_WRITING_SCRIPTS = (
    "create-pr.sh",
    "create-docs-pr.sh",
    "merge-docs-pr.sh",
)


def _script_step_env_vars(script_path: Optional[str]) -> tuple[str, ...]:
    """Env allowlist for a script-type step, per STD-SEC-022.

    Returns the base list, plus AI_AGILE_BOT_TOKEN only for the scripts that
    actually consume it. Matching is on the file name so a repo that relocates
    the scripts directory still resolves correctly.
    """
    name = Path(script_path).name if script_path else ""
    if name in _PR_WRITING_SCRIPTS:
        return _SCRIPT_AGENT_ENV_VARS + ("AI_AGILE_BOT_TOKEN",)
    return _SCRIPT_AGENT_ENV_VARS


def invoke_script(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
    *,
    cwd: Optional[str] = None,
) -> AgentRunResult:
    """Invoke a script-type pipeline step directly via bash.

    The script receives the same environment variables as an agent
    ($REPO, $ISSUE_NUMBER / $PR_NUMBER, $WORK_ITEM_KIND, etc.) and must
    emit AI_AGILE_STATUS: complete|review|blocked as the last output line.
    The orchestrator reads the sentinel and applies the matching label.

    cwd (#373): for a commit_after step, the isolated worktree the script
    should run in instead of the orchestrator's own working directory. None
    for every other step.

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

    _step_env_vars = _script_step_env_vars(agent_def.script_path)
    agent_env = {  # STD-SEC-022
        **{k: os.environ[k] for k in _step_env_vars if k in os.environ},
        "STATUS_SH":        str(STATUS_SH),
        # cwd (#373): a commit_after script step's isolated worktree, so a
        # script that reads AI_AGILE_ROOT operates on the same tree it was
        # actually spawned in rather than the orchestrator's own checkout.
        "AI_AGILE_ROOT":    cwd or os.environ.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT)),
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
            cwd=cwd,
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
# stdout and /maos-{agent}-i captures it inside an interactive session, so it is built
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
    # Derived from SESSION_ID, which is already here -- a path, not a secret.
    # Without it /maos-{agent}-i has nothing to export and every hand-run agent
    # falls through ${AI_AGILE_SCRATCH:-/tmp} to a shared directory with fixed
    # filenames, so the isolation the orchestrator path guarantees is absent
    # exactly where a human is watching (issue #321). /maos-{agent}-i runs
    # scratch-setup.sh on this path before the agent starts; the two changes
    # only work together -- exporting a directory nothing creates is worse than
    # not exporting one, because the agent is told not to create it itself.
    "AI_AGILE_SCRATCH",
)


# Warned-once flag for the untrusted-workspace check below.
_WORKSPACE_TRUST_WARNED = False


def _warn_if_grants_dropped() -> int:
    """Log the `permissions.allow` entries the CLI will discard, and count them.

    The Claude CLI ignores every `permissions.allow` entry in
    `.claude/settings.json` unless the workspace carries
    `projects[<root>].hasTrustDialogAccepted: true` in the CLI's own config.
    It says so on stderr and then runs with narrower permissions than the repo
    configured, which is invisible to the orchestrator and to the agent -- the
    agent just sees an Edit denial on a path the repo explicitly granted
    (issue #362).

    Headless runs are largely insulated because the orchestrator grants
    `Edit`/`Write` outright through `--allowedTools`, which is not subject to
    the trust gate. The `/maos-{agent}-i` path is not: it has no `--allowedTools`
    of its own and leans on the session's resolved permissions. Either way the
    drop is a fact about the run, so name it once instead of letting it scroll
    past in a subprocess's stderr.

    Returns the number of entries that will be dropped (0 when none are, or
    when neither file can be read).
    """
    global _WORKSPACE_TRUST_WARNED

    settings_file = SUBMODULE_ROOT / ".claude/settings.json"
    try:
        allow = json.loads(settings_file.read_text()).get("permissions", {}).get("allow", [])
    except (OSError, ValueError):
        return 0
    if not allow:
        return 0

    # HOME is passed straight through to the agent subprocess
    # (AGENT_ENV_PASSTHROUGH), so this process's config is the agent's config.
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("HOME")
    if not config_dir:
        return 0
    try:
        projects = json.loads((Path(config_dir) / ".claude.json").read_text()).get("projects", {})
    except (OSError, ValueError):
        return 0

    root = os.environ.get("AI_AGILE_ROOT") or str(SUBMODULE_ROOT)
    if projects.get(str(Path(root).resolve()), projects.get(root, {})).get("hasTrustDialogAccepted"):
        return 0

    if not _WORKSPACE_TRUST_WARNED:
        _WORKSPACE_TRUST_WARNED = True
        log.warning(
            "  %d permissions.allow entr%s in .claude/settings.json will be "
            "DROPPED: %s. The workspace %s is not trusted in %s/.claude.json, "
            "so the CLI ignores them. Agents will be denied these grants with "
            "no error of their own. Remedy: accept the trust dialog once "
            "interactively in that directory, or set "
            "projects[%r].hasTrustDialogAccepted to true.",
            len(allow), "y" if len(allow) == 1 else "ies",
            ", ".join(allow), root, config_dir, root,
        )
    return len(allow)


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


# STD-SEC-022 -- env for the agent-lifecycle scripts declared in
# defaults.agent_lifecycle. The rule, not an observation about today's two
# scripts: a lifecycle script prepares the environment an agent runs in, so it
# touches the filesystem and never GitHub, and no credential is passed. A script
# that needs one is doing process work and belongs in post_steps, which has its
# own allowlist. AI_AGILE_SCRATCH is added per call by _run_lifecycle_scripts.
_LIFECYCLE_SCRIPT_ENV_VARS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE")


def _scratch_path(agent_session_id: str) -> str:
    """The per-run scratch directory for a session id.

    Sole definition of the formula -- every caller derives the path from here
    rather than rebuilding it. Two callers exist: _build_agent_env, which
    exports it for the agent, and _run_agent, which needs it for teardown after
    invoke_agent's env has gone out of scope. Both pass the same session id, so
    both get the same path.
    """
    return f"/tmp/{agent_session_id}"


def _run_lifecycle_scripts(scripts: list, scratch_dir: str) -> None:
    """Run the agent-lifecycle scripts declared in pipeline.json. Never raises.

    The third kind of script in the pipeline, alongside script steps and
    post_steps, and the only one that is not a process step in its own right:
    these wrap an agent invocation, emit no `AI_AGILE_STATUS:` sentinel, take no
    label, and cannot fail a run. See
    docs/product/orchestrator/PRODUCT.md, "Every step has the same four parts".

    The work lives in .github/scripts/ and the list lives in pipeline.json, so
    the orchestrator neither performs the work nor names the scripts (P-14,
    STD-ARCH-035). Failure is logged and swallowed: the "before" scripts are
    idempotent, so a missed "after" self-heals on the next run and must never
    fail an agent.
    """
    for script_rel in scripts:
        script = SUBMODULE_ROOT / script_rel
        if not script.is_file():
            log.warning("lifecycle: %s not found; skipping", script_rel)
            continue
        env = {k: os.environ[k] for k in _LIFECYCLE_SCRIPT_ENV_VARS if k in os.environ}
        env["AI_AGILE_SCRATCH"] = scratch_dir
        try:
            res = subprocess.run(
                ["bash", str(script)], env=env, capture_output=True, text=True, timeout=30,
            )
            if res.returncode != 0:
                log.warning(
                    "lifecycle: %s exited %d: %s",
                    script_rel, res.returncode, (res.stderr or "").strip()[:200],
                )
        except Exception as exc:  # pragma: no cover -- best-effort
            log.warning("lifecycle: %s could not run: %s", script_rel, exc)


def _build_agent_env(
    base_env: Mapping[str, str],
    repo: str,
    work_item: WorkItem,
    agent_session_id: str,
    session_scope: str,
    *,
    ai_agile_root: Optional[str] = None,
) -> dict[str, str]:
    """Build the environment for a Claude agent subprocess.

    Starts from an explicit allowlist of `base_env` keys (AGENT_ENV_PASSTHROUGH)
    rather than the full environment, so orchestrator-only secrets
    (AI_AGILE_BOT_TOKEN, GIT_CONFIG_* git-auth header) are never inherited by a
    potentially prompt-injected agent. The work-item context vars are then set
    explicitly, matching what agents document in AGENTS.md.

    ai_agile_root (#373): for a commit_after step, the isolated worktree the
    agent should treat as its repo root -- agent prompts document `cd
    $AI_AGILE_ROOT && <command>` as the idiom for a granted Bash command that
    needs to run repo-relative, so this must point at the same directory the
    subprocess itself is spawned in (its `cwd`); otherwise that idiom would
    `cd` an agent straight out of its isolated worktree and back onto the
    orchestrator's own shared checkout, defeating the isolation. None for
    every other step (falls back to base_env's AI_AGILE_ROOT / SUBMODULE_ROOT).
    """
    agent_env = {k: base_env[k] for k in AGENT_ENV_PASSTHROUGH if k in base_env}
    # Export resolved paths so the agent prompt's bash snippets work regardless
    # of CWD or where this repo is mounted in the consuming repo. Only one of
    # ISSUE_NUMBER / PR_NUMBER is set, matching the work item's kind, so the
    # agent's prompt cannot get them confused.
    agent_env["AI_AGILE_ROOT"] = ai_agile_root or base_env.get("AI_AGILE_ROOT", str(SUBMODULE_ROOT))
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
    # Per-run scratch directory under /tmp — outside the working tree, so it
    # can never appear in git status or be swept into a commit. Creation and
    # removal are done by .github/scripts/scratch-{setup,teardown}.sh, which
    # the orchestrator runs around each agent invocation.
    agent_env["AI_AGILE_SCRATCH"] = _scratch_path(agent_session_id)
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


# Scoped base tool allowlist granted to every Claude agent -- now declared in
# pipeline.json's defaults.extra_allowedTools (AS-1: pipeline.json is the sole
# source of entitlements; JSON cannot carry inline comments, so the rationale
# for each pattern is kept here instead). Each entry is a glob the bash
# command must match; keeping these narrow blocks a prompt-injected agent from
# reaching secrets/settings/branches. NOTE: the orchestrator owns the label
# lifecycle (AGENTS.md P-10/P-14). `gh pr edit` is NOT granted -- no agent has
# a legitimate use for it, and it would let an injected agent add a PR gate
# label. `gh issue edit` IS granted broadly because issue-classifier applies the
# routing `classification: {type}` label and sizer applies `epic,blocked` at
# runtime; narrowing it to specific --add-label globs is unsafe (a positive glob
# cannot permit those legitimate labels while denying gate labels like
# `prd-writer:approved` without risking the routing labels). The residual
# self-approval vector (via `gh issue edit` OR the REST issue-write grant below,
# which reaches PRs too since PRs are issues) is closed ORCHESTRATOR-SIDE: the
# gate check rejects any `{agent}:approved` label not applied by a human (#263).
#
#   "Bash(gh issue view *)"       -- read issue body / labels
#   "Bash(gh issue comment *)"    -- post artefact comments
#   "Bash(gh issue edit *)"       -- prd-writer/sizer body rewrites + classifier/sizer routing labels
#   "Bash(gh issue list *)"       -- cross-issue reads (impact-assessor etc.)
#   "Bash(gh pr view *)"          -- PR-side agents read PR
#   "Bash(gh pr comment *)"       -- PR-side agents post comments
#   "Bash(gh pr list *)"
#   "Bash(gh pr diff *)"          -- pr-reviewer reads the diff
#   "Bash(gh api repos/*/issues/*)"  -- narrow direct API; only issue/PR endpoints
#   "Bash(gh api repos/*/pulls/*)"
#   "Bash(gh api repos/*/issues*)"   -- REST reads incl. list/query forms (issues?labels=...)
#   "Bash(gh api repos/*/pulls*)"    -- REST reads incl. list/query forms (pulls?head=...)
#
# Quoted-URL counterparts of the four patterns above. Permission-rule matching
# is literal-text prefix matching (a `*` spans characters, not shell tokens), so
# an agent that quotes its URL argument (idiomatic, defensively-reasonable shell
# style -- e.g. `gh api "repos/o/r/issues/1"`) needs its own pattern; the
# unquoted pattern's literal ` repos/` never appears in that command's text
# (issue #326):
#
#   "Bash(gh api \"repos/*/issues/*)"
#   "Bash(gh api \"repos/*/pulls/*)"
#   "Bash(gh api \"repos/*/issues*)"
#   "Bash(gh api \"repos/*/pulls*)"
#
# REST WRITES on issues only (labels/comments/body) -- the in-session
# equivalent of `gh issue edit`, needed because that command is GraphQL and
# 403s in a restricted session. It carries the SAME gate-label self-approval
# vector as `gh issue edit` (a positive glob cannot permit routing labels
# while denying gate labels), which is closed ORCHESTRATOR-SIDE by the
# human-actor gate check (#263). No `--method` grant on /pulls: agents never
# write PRs (merge/ready/close are the orchestrator's/driver's job), so
# granting it would hand an injected agent merge/close/retarget power.
#
#   "Bash(gh api --method * repos/*/issues*)"
#   "Bash(gh api --method * \"repos/*/issues*)"  -- quoted-URL counterpart (#326)
#   "Bash(cat *)"                 -- read prompt-side files
#   "Bash(grep *)"
#   "Bash(find *)"
#
# Scope checking splits a command into its sub-commands and requires every one
# of them to be granted (#362), so the idiomatic `cd $AI_AGILE_ROOT &&
# <granted command>` needs `cd` granted in its own right. Without it the
# leading `cd` sinks the whole call, which is how a granted `sed` was refused
# on #321. `cd` reads and writes nothing.
#
#   "Bash(cd *)"
#   "Read", "Glob", "Grep"


@dataclass
class ResolvedInvocation:
    """The fully-resolved parameters for one agent invocation, before spawning.

    env is not included: callers build it via _build_agent_env and set
    AI_AGILE_EXECUTION_MODE according to their context (headless for real
    subprocess spawns, interactive for the resolve-only /maos-{agent}-i path).
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
    *,
    cwd: Optional[str] = None,
) -> Optional["ResolvedInvocation"]:
    """Resolve an agent invocation's prompt and tool allowlist without spawning.

    Returns a ResolvedInvocation, or None when the agent file cannot be found.
    This is the single source of truth for prompt assembly and tool allowlist
    construction -- both invoke_agent (real spawn) and the resolve-only
    --print-prompt path call this so the two can never drift apart.

    cwd (#373): for a commit_after step, the isolated worktree this
    invocation will run in -- the prompt's own `AI_AGILE_ROOT=` line must
    match it (see _build_agent_env's ai_agile_root docstring for why). None
    for every other step.
    """
    agent_file = SUBMODULE_ROOT / ".claude/agents" / f"{agent_def.agent}.md"

    if agent_text_override is not None:
        agent_text = agent_text_override
    elif not agent_file.exists():
        log.warning("    Agent file not found: %s", agent_file)
        return None
    else:
        agent_text = agent_file.read_text()

    # Model and max_turns come from agent_def (pipeline.json) only -- not the
    # agent's frontmatter, which declares just name and description (AS-1).
    agent_model: Optional[str] = agent_def.model
    extra_tools = list(dict.fromkeys(
        list(default_extra_tools or []) +
        list(agent_def.extra_allowedTools)
    ))
    max_turns = agent_def.max_turns or DEFAULT_MAX_TURNS

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
        f"AI_AGILE_ROOT={(cwd or os.environ.get('AI_AGILE_ROOT', str(SUBMODULE_ROOT))).strip()}\n"
        f"AI_AGILE_CONTEXT={str(AI_AGILE_CONTEXT).strip()}\n\n"
        f"Before exiting, write your result to $AI_AGILE_SCRATCH/{_RESULT_FILENAME} "
        f"(use the Write tool — see AGENTS.md's \"How you communicate\" for why). "
        f"A JSON object with these fields:\n"
        f"  outcome           (required) one of \"complete\", \"review\", \"blocked\"\n"
        f"  summary           (required) your own account of what you did, in plain words,\n"
        f"                    including when you did nothing\n"
        f"  undone            what you left, if anything — empty string when you finished it all\n"
        f"  message           short message for \"review\"/\"blocked\": what a person must act on\n"
        f"  output            the artefact you produced (a review, a PRD, a plan) — the\n"
        f"                    orchestrator posts this as a comment; you do not post it yourself\n"
        f"  expected_effect   what you believe you changed this run, e.g. {{\"commits\": true}}\n"
        f"  label_requests    [{{\"issue\": null, \"add\": [...], \"remove\": [...]}}] — \"issue\" null\n"
        f"                    means this work item; only requests matching your declared\n"
        f"                    allowed_labels are applied, the rest are silently dropped\n"
        f"Do not print an AI_AGILE_STATUS sentinel — that mechanism is retired for agent-type "
        f"steps. The orchestrator reads the result file, applies the matching label, posts the "
        f"closing announcement and any artefact/label changes on your behalf."
    )

    return ResolvedInvocation(
        prompt=prompt,
        allowed_tools=extra_tools,
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
    *,
    cwd: Optional[str] = None,
) -> AgentRunResult:
    """
    Invoke the agent via claude CLI.

    cwd (#373): for a commit_after step, the isolated worktree the agent
    should run in instead of the orchestrator's own working directory. None
    for every other step.

    Agents signal their outcome by writing one structured result to
    $AI_AGILE_SCRATCH/result.json (issue #400) -- see _read_step_result and
    the "Before exiting, write your result" text _resolve_agent_invocation
    injects into the prompt. The orchestrator reads that file, applies the
    matching label, and posts the closing announcement and any artefact
    comment / label changes on the agent's behalf. Agents must NOT call
    status.sh for ceremony -- set-wip, opening/closing announcements, and
    final label transitions are all handled here. :failed is applied by the
    orchestrator when the agent exits without a valid result after all
    retries are exhausted; :exhausted is applied when it ran out of its
    turn or wall-clock budget first (never retried).

    Returns an AgentRunResult with success/returncode/captured_tail and
    a rate_limited flag (set when a pause was written). Caller MUST NOT
    apply :failed when rate_limited is True -- the agent never got a fair
    run.
    """
    resolved = _resolve_agent_invocation(
        agent_def, work_item, repo, agent_text_override, default_extra_tools,
        cwd=cwd,
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
    # ai_agile_root=cwd keeps AI_AGILE_ROOT consistent with the subprocess's
    # actual working directory (#373) -- see _build_agent_env's docstring.
    agent_env = _build_agent_env(
        os.environ, repo, work_item, agent_session_id, agent_def.session_scope,
        ai_agile_root=cwd,
    )

    # Run the declared "before" scripts. Inside invoke_agent, so each retry gets
    # its own setup -- an attempt must never read the previous attempt's files.
    scratch_dir = agent_env.get("AI_AGILE_SCRATCH", "")
    if scratch_dir and not dry_run:
        _run_lifecycle_scripts(agent_def.lifecycle_before, scratch_dir)

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
        # via the maos-{agent}-i command (a ~440s nested sub-agent). Deny them explicitly.
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
    _warn_if_grants_dropped()

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

    # Per-step override of the pipeline-wide wall-clock budget (budgets.max_wall_seconds
    # in pipeline.json), same shape as max_turns above.
    wall_seconds = agent_def.max_wall_seconds or AGENT_TIMEOUT_SECONDS

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=agent_env,
            cwd=cwd,
        )
        deadline = time.monotonic() + wall_seconds
        # Wall-clock timer fires unconditionally — unlike the per-line check
        # below, it also fires when the agent hangs without emitting output.
        # _timed_out lets the loop raise TimeoutExpired with a clear message
        # even when stdout goes silent (no lines arrive to trigger the check).
        _timed_out = threading.Event()

        def _timer_callback() -> None:
            _timed_out.set()
            _terminate_subprocess(proc)
        _kill_timer = threading.Timer(wall_seconds, _timer_callback)
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
                    raise subprocess.TimeoutExpired(cmd, wall_seconds)
            # Timer may have fired and drained stdout without triggering the
            # per-line check above (process died between lines). Raise here so
            # the timeout path is always taken when the timer fired.
            if _timed_out.is_set():
                raise subprocess.TimeoutExpired(cmd, wall_seconds)
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
                    f"Agent timed out after {wall_seconds}s.\n\n"
                    f"Last output:\n{agent_tail}"
                ),
                input_tokens=acc.input_tokens,
                output_tokens=acc.output_tokens,
                init_event=acc.init_event,
                result_event=acc.result_event,
                retry_count=acc.retry_count,
                retry_errors=list(acc.retry_errors),
                timed_out=True,
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
        # since PR #262) must NOT promote itself past the gate. Fail-closed on
        # any API error or inconclusive check (see _gate_label_human_applied,
        # MI-7). Short-circuit avoids the events lookup entirely when the
        # label is absent.
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


def _apply_exhausted(gh: "GitHubClient", agent_def: AgentDef, work_item: WorkItem, result: AgentRunResult) -> None:
    """Apply :exhausted -- the step ran out of turn or wall-clock budget
    before it could write a result. Distinct from :failed (a crash): the
    step didn't break, it just didn't finish inside the budget it was
    given, so the recovery instruction is "raise the budget or shrink the
    step", not "read the logs" (PRODUCT.md, "A step returns exactly one of
    five outcomes"). Mirrors _apply_failed's structure and best-effort
    error handling.
    """
    for stale in (STATUS_WIP, STATUS_REVIEW, STATUS_BLOCKED, STATUS_REQUESTED):
        try:
            gh.remove_label(work_item.number, agent_def.status_label(stale))
        except Exception as exc:  # pragma: no cover — best-effort cleanup
            log.debug(
                "  could not remove %s during exhausted transition: %s",
                agent_def.status_label(stale), exc,
            )

    try:
        gh.add_label(work_item.number, agent_def.exhausted_label)
    except Exception as exc:
        log.error(
            "  could not apply %s on #%d: %s — pipeline state may be inconsistent",
            agent_def.exhausted_label, work_item.number, exc,
        )

    _which_budget = "wall-clock" if result.timed_out else "turn"
    detail = result.captured_tail or "(no captured output)"
    body_parts = [
        f"### `{agent_def.agent}` exhausted its {_which_budget} budget",
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
        f"- Raise this step's `{'max_wall_seconds' if result.timed_out else 'max_turns'}` budget "
        f"in pipeline.json, or make the step smaller, then **remove** the "
        f"`{agent_def.exhausted_label}` label to retry, or",
        f"- Apply the `{agent_def.skipped_label}` label to bypass this agent on this item.",
        "",
        "_Posted by the orchestrator — this run is never retried automatically, "
        "since the budget itself does not change between runs._",
    ]
    body = "\n".join(body_parts)
    try:
        gh.post_comment(work_item.number, body)
    except Exception as exc:
        log.error(
            "  could not post exhaustion comment on #%d (%s); :exhausted label is still applied. "
            "Detail follows in this log:\n%s",
            work_item.number, exc, body,
        )


# ---------------------------------------------------------------------------
# Core orchestration logic
# ---------------------------------------------------------------------------

# Per-run git worktree isolation (issue #373, #404). Each commit_after run
# checks out its issue branch into its own worktree here rather than the
# orchestrator's own shared checkout, so a concurrent run on a different
# issue cannot move this run's HEAD out from under it. Nested under
# .claude/worktrees/ (already gitignored for Claude Code's own background-
# agent worktrees) with an "orchestrator" subdirectory so the two unrelated
# mechanisms never collide on the same path.
_WORKTREE_ROOT = SUBMODULE_ROOT / ".claude" / "worktrees" / "orchestrator"


def _run_worktree_path(issue_branch: str) -> Path:
    """Deterministic worktree directory for one issue branch."""
    _safe = re.sub(r"[^A-Za-z0-9._-]", "-", issue_branch)
    return _WORKTREE_ROOT / _safe


def _create_run_worktree(issue_branch: str) -> str:
    """Create an isolated git worktree checked out to `issue_branch`.

    Fetches the branch, then `git worktree add`s it into its own directory
    (rather than checking it out in the orchestrator's own shared working
    tree) so a concurrent run on a different issue cannot move this run's
    HEAD (#373). Raises on any failure -- the caller must fail the run
    loudly rather than fall back to the shared working tree.
    """
    _WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _run_worktree_path(issue_branch)
    if path.exists():
        # Debris from a run killed mid-flight -- SIGTERM cleanup
        # (_clear_inflight_wip_on_signal) is best-effort, so a prior worktree
        # may still be registered here. Clear it before adding a fresh one
        # rather than colliding with it.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            check=False, capture_output=True,
        )
        shutil.rmtree(path, ignore_errors=True)
    subprocess.run(["git", "worktree", "prune"], check=False, capture_output=True)
    try:
        subprocess.run(
            ["git", "fetch", "origin", issue_branch],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "worktree", "add", "--force", "-B", issue_branch, str(path), f"origin/{issue_branch}"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        # str(CalledProcessError) omits stderr even though capture_output=True
        # captured it -- without this, the :failed diagnostic comment a human
        # reads never shows the actual git error.
        raise RuntimeError(f"{exc}: {(exc.stderr or '').strip()}") from exc
    global _CURRENT_WORKTREE
    _CURRENT_WORKTREE = str(path)
    return str(path)


def _remove_run_worktree(path: str) -> None:
    """Tear down a worktree created by _create_run_worktree. Best-effort --
    cleanup must never raise, since it runs on every break path after the
    run's own outcome has already been decided."""
    if not path:
        return
    global _CURRENT_WORKTREE
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", path],
            check=False, capture_output=True,
        )
        shutil.rmtree(path, ignore_errors=True)
    except Exception as exc:
        log.warning("could not remove worktree %s: %s", path, exc)
    if _CURRENT_WORKTREE == path:
        _CURRENT_WORKTREE = None


def _should_run(
    agent_def: AgentDef,
    work_item: WorkItem,
    labels: set,
    pipeline_map: dict,
    concurrency: Optional[ComponentClaims],
    gh=None,
    repo: str = "",
) -> Optional[bool]:
    """Evaluate whether an agent should be dispatched for a work item.

    Returns True to dispatch, False to skip (continue to next agent),
    or None to stop processing agents for this work item (per-tick launch
    budget hit).
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

    if current_status in (STATUS_COMPLETE, STATUS_FAILED, STATUS_EXHAUSTED, STATUS_SKIPPED):
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
        _components = _work_item_components(work_item)
        # Headless is one process at a time (only one tick ever runs, per
        # PRODUCT.md's own concurrency guarantee), so its settled in-memory
        # claims are trustworthy. Interactive is genuinely several
        # unserialised processes, so it reads GitHub's labels fresh instead
        # of trusting this process's own possibly-stale snapshot.
        _claims = concurrency if _HEADLESS else _fresh_component_claims(gh, work_item.number)
        if not _claims.can_claim(_components):
            log.info(
                "  wait %-40s  [component claim unavailable: %s]",
                agent_def.agent, ", ".join(sorted(_components)) or "untagged (claims everything)",
            )
            return False
        # Per-tick launch budget: stop the loop when hit.
        if concurrency.tick_launch_count >= MAX_LAUNCHES_PER_TICK:
            log.info(
                "  ceiling %-38s  [max launches per tick: %d/%d launched this tick]",
                agent_def.agent, concurrency.tick_launch_count, MAX_LAUNCHES_PER_TICK,
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
    concurrency: Optional[ComponentClaims],
    gh: "GitHubClient",
    pipeline_map: dict,
) -> None:
    """Pre-invocation ceremony: remove :requested, apply :wip, announce, cycle++.

    Applies the :wip status label and claims the item's components (live or
    dry-run), posts the opening announcement, and increments review-cycle:N
    for re_invoke targets. Mutates labels and work_item.labels in-place.
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
            # Claim only on successful label application — a failed
            # add_label means no :wip was set so nothing is actually running.
            if concurrency is not None:
                concurrency.claim(_work_item_components(work_item))
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
        # dry_run: skip :wip ceremony but advance claims so simulated output
        # respects component-claim exclusion and the per-tick launch budget.
        if concurrency is not None:
            concurrency.claim(_work_item_components(work_item))
            concurrency.tick_launch_count += 1


def _invoke_with_retries(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
    gh: "GitHubClient",
    default_extra_tools: Optional[list],
    agent_text_snapshot: Optional[str],
    *,
    cwd: Optional[str] = None,
) -> tuple:
    """Invoke an agent, retrying on a crashed/malformed result up to max_retries.

    A run that hits its turn or wall-clock budget (_is_exhausted) is never
    retried, whatever attempt count it's on — the budget itself hasn't
    changed between runs, so retrying would just hit the same wall
    (PRODUCT.md, "A step returns exactly one of five outcomes"). Rate-limit
    events also break immediately without applying :failed or :exhausted;
    the run never got a fair try. Reads the step's result file after every
    attempt. Returns (result, step_result, exhausted, attempt).

    cwd (#373): for a commit_after step, the isolated worktree the agent
    should run in instead of the orchestrator's own working directory. None
    for every other step.
    """
    scratch_dir = _scratch_path(_compute_agent_session_id(agent_def, work_item, repo))
    step_result: Optional[StepResult] = None
    exhausted = False
    _attempt = 0
    # Retry loop: re-invoke on a crashed/malformed result up to max_retries
    # times. Rate-limit and exhaustion events break immediately.
    result = invoke_agent(
        agent_def, work_item, dry_run, repo, attempt=0,
        agent_text_override=agent_text_snapshot,
        default_extra_tools=default_extra_tools,
        cwd=cwd,
    )
    while not dry_run:
        if result.rate_limited:
            break
        exhausted = _is_exhausted(result)
        step_result, _ = _read_step_result(scratch_dir)
        if step_result is not None or exhausted or _attempt >= agent_def.max_retries:
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
                f"attempt {_attempt} did not return a valid result "
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
            cwd=cwd,
        )
        if result.rate_limited:
            break

    return result, step_result, exhausted, _attempt


def _run_agent(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
    labels: set,
    session_id: str,
    default_extra_tools: Optional[list],
    concurrency: Optional[ComponentClaims],
    gh: "GitHubClient",
    pipeline_map: dict,
    *,
    interactive_result: bool = False,
) -> tuple:
    """Pre-invocation ceremony, agent/script dispatch, and retry loop.

    Applies :wip, posts the opening announcement, manages the review-cycle
    counter, invokes the agent or script, and resolves its outcome.

    Agent-type steps resolve via the step's result file (issue #400):
    sentinel_status/sentinel_message are populated from step_result.outcome/
    message for compatibility with the rest of the pipeline, and the step's
    output (if any) is posted as an artefact comment here, by the
    orchestrator, before returning. Script-type steps are unaffected and
    still resolve via the AI_AGILE_STATUS stdout sentinel (out of scope for
    #400 — see _read_step_result's module comment).

    interactive_result (issue #402) applies to agent-type steps only: instead
    of spawning a subprocess, read the already-written result.json from the
    same scratch path a real run would use — produced by a person and the
    chat-AI working through the step's instructions under --print-prompt.
    A missing or invalid file resolves exactly like a crashed subprocess
    (step_result is None -> :failed at _apply_result, never silently
    skipped). The commit_after pre-dispatch worktree setup below is skipped
    in this mode: it exists to stage a subprocess onto the right branch, in
    its own isolated tree, before it starts editing, and running it here —
    after a person has already made their edits directly in their own
    session — would fetch and hard-reset onto origin's copy of the branch,
    discarding that work.

    A commit_after run operates in its own git worktree, not the
    orchestrator's own shared checkout (#373): two concurrent runs on
    different issues each get their own working directory, so neither can
    move the other's HEAD. Worktree setup failure fails the run loudly
    (returns a failure result with no sentinel, which _apply_result resolves
    as :failed) rather than falling back to running on whatever branch the
    orchestrator's own tree happens to be on.

    Modifies labels and work_item.labels in-place (review-cycle tracking).

    Returns: (result, sentinel_status, sentinel_message,
              pre_agent_worktree, invoked_at, attempt, exhausted, step_result)
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
            outcome_detail=(
                f"mode={agent_def.step_type} "
                f"grants_dropped={_warn_if_grants_dropped()}"
            ),
        ))
    _invoked_at = time.monotonic()

    # Snapshot the agent file before any branch checkout below so agent
    # definitions always reflect the orchestrator's branch, not the issue branch.
    _agent_file_path = SUBMODULE_ROOT / ".claude/agents" / f"{agent_def.agent}.md"
    _agent_text_snapshot: Optional[str] = (
        _agent_file_path.read_text() if _agent_file_path.exists() else None
    )

    # For commit_after agents, check out the issue branch into its own
    # isolated worktree before invoking, so the agent reads accumulated state
    # without disturbing (or being disturbed by) a concurrent run on a
    # different issue (#373). commit-agent-work.sh handles staging, commit,
    # and push, run from that same worktree. Guard: only for issue work items
    # (ISSUE_NUMBER required). Skipped under interactive_result — see this
    # function's docstring.
    _pre_agent_worktree: str = ""
    _agent_cwd: Optional[str] = None
    if not dry_run and agent_def.commit_after and work_item.kind == "issue" and not interactive_result:
        _issue_branch = f"issue-{work_item.number}{agent_def.branch_suffix}"
        try:
            _pre_agent_worktree = _create_run_worktree(_issue_branch)
            _agent_cwd = _pre_agent_worktree
            log.info(
                "  pre-agent: worktree for %s checked out at %s for %s",
                _issue_branch, _pre_agent_worktree, agent_def.agent,
            )
        except Exception as _pre_exc:
            log.error(
                "  pre-agent worktree setup failed for %s on #%d: %s — "
                "failing the run rather than falling back to the shared "
                "working tree (#373)",
                agent_def.agent, work_item.number, _pre_exc,
            )
            return (
                AgentRunResult(
                    success=False,
                    captured_tail=f"pre-agent worktree setup failed: {_pre_exc}",
                ),
                None, "", "", _invoked_at, 0, False, None,
            )

    # Snapshot repo-root untracked files so anything the agent adds there
    # can be swept afterwards (issue #376).
    _root_before = set() if dry_run else _untracked_root_files()

    sentinel_status: Optional[str] = None
    sentinel_message: str = ""
    step_result: Optional[StepResult] = None
    exhausted = False
    _attempt = 0

    if agent_def.step_type == "script":
        result = invoke_script(agent_def, work_item, dry_run, repo, cwd=_agent_cwd)
        if not dry_run:
            sentinel_status, sentinel_message = _parse_agent_sentinel(result.captured_tail)
    elif interactive_result:
        # No subprocess: read the result a person and the chat-AI already
        # wrote to the same scratch path a real run would use. A missing or
        # invalid file is not a silent no-op — step_result stays None and
        # _apply_result's existing "no valid result file" path applies
        # :failed, exactly as a crashed subprocess would.
        _scratch_dir = _scratch_path(_compute_agent_session_id(agent_def, work_item, repo))
        step_result, _read_err = _read_step_result(_scratch_dir)
        if step_result is None:
            log.error(
                "  interactive-result: no valid result.json for %s on #%d (%s): %s",
                agent_def.agent, work_item.number, _scratch_dir, _read_err,
            )
        result = AgentRunResult(
            success=step_result is not None,
            # Surfaces in the :failed diagnostic comment's "Last output" --
            # otherwise the actual reason only ever reaches this log line,
            # and the person who needs to fix result.json never sees it.
            captured_tail=(
                "" if step_result is not None
                else f"result.json at {_scratch_dir}: {_read_err}"
            ),
        )
        # _attempt stays at its initial 0 (set above): there is no retry loop
        # here, so a non-zero value would make _finalize_run_failure post a
        # false "retry limit exhausted -- failed N time(s)" message.
        if step_result is not None:
            sentinel_status, sentinel_message = step_result.outcome, step_result.message
        _post_artefact_if_present(gh, agent_def, work_item, step_result)
    else:
        result, step_result, exhausted, _attempt = _invoke_with_retries(
            agent_def, work_item, dry_run, repo, gh,
            default_extra_tools, _agent_text_snapshot, cwd=_agent_cwd,
        )
        if step_result is not None:
            sentinel_status, sentinel_message = step_result.outcome, step_result.message
        _post_artefact_if_present(gh, agent_def, work_item, step_result)

    if not dry_run:
        _sweep_agent_root_files(agent_def, _root_before)

    # Run the declared "after" scripts once all retries are done, whatever the
    # outcome. load_pipeline leaves these empty for script steps, which are
    # never handed a scratch directory, so the pairing with "before" holds
    # without the orchestrator deciding anything.
    if not dry_run and agent_def.lifecycle_after:
        _run_lifecycle_scripts(
            agent_def.lifecycle_after,
            _scratch_path(_compute_agent_session_id(agent_def, work_item, repo)),
        )

    return (
        result, sentinel_status, sentinel_message, _pre_agent_worktree,
        _invoked_at, _attempt, exhausted, step_result,
    )


def _repo_root() -> Path:
    """The repository root the sweep operates on.

    Asks git rather than trusting a path. AI_AGILE_ROOT is often "." (it is a
    consuming-repo-relative convention), so reading it directly would leave the
    sweep CWD-relative: a tick started from a subdirectory would list and
    delete files there instead of at the repo root. `git rev-parse
    --show-toplevel` is absolute and correct from anywhere inside the tree.
    """
    start = os.environ.get("AI_AGILE_ROOT") or str(SUBMODULE_ROOT)
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, cwd=start,
        ).stdout.strip()
        if top:
            return Path(top)
    except Exception:
        pass
    return Path(start).resolve()


def _untracked_root_files() -> Optional[set]:
    """Untracked files at the repository root (depth 0 only).

    The scratch contract says agents write working files under
    $AI_AGILE_SCRATCH and never into the repo. When an agent writes to a
    relative path instead, the file lands here.

    Returns None -- NOT an empty set -- when git cannot be consulted. The
    caller uses this result as the "before" baseline, and an empty baseline
    would mean "every untracked root file is new", turning a failed probe into
    a delete-everything sweep. None makes that case unambiguous, so the sweep
    can skip instead.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=True, cwd=str(_repo_root()),
        ).stdout
    except Exception:
        return None
    return {line for line in out.splitlines() if line and "/" not in line}


def _sweep_agent_root_files(agent_def: AgentDef, before: set) -> None:
    """Remove root files the agent created, and say so.

    Runs for EVERY agent. commit-agent-work.sh carries the same guard, but it
    only runs for git_ops.commit_after agents -- prd-writer, pr-reviewer and
    issue-classifier all have none, and all three were observed leaving files
    at the repo root (issue #376). Only files absent before the invocation are
    removed, so a pre-existing file is never touched.
    """
    after = _untracked_root_files()
    if before is None or after is None:
        # A probe failed. Skipping loses a cleanup; guessing risks deleting
        # files the agent never wrote. Skip, and say so.
        log.warning(
            "  scratch: could not check the repo root for %s; skipping the sweep",
            agent_def.agent,
        )
        return
    leaked = sorted(after - before)
    if not leaked:
        return
    log.warning(
        "  scratch: %s wrote %d file(s) to the repo root instead of "
        "$AI_AGILE_SCRATCH; removing: %s",
        agent_def.agent, len(leaked), ", ".join(leaked),
    )
    root = _repo_root()
    for name in leaked:
        try:
            (root / name).unlink()
        except OSError as exc:
            log.warning("  scratch: could not remove %s: %s", name, exc)


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


# STD-SEC-022 — env vars for commit-agent-work.sh: git stash/fetch/checkout/commit/push
# plus base64 for the auth header. AGENT_NAME, ISSUE_NUMBER, BRANCH_SUFFIX are set
# explicitly below.
_COMMIT_AFTER_ENV_VARS = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
    "GH_TOKEN", "GITHUB_TOKEN", "AI_AGILE_BOT_TOKEN",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
)


def _invoke_commit_after(agent_def: AgentDef, work_item: WorkItem, *, cwd: Optional[str] = None) -> Optional[str]:
    """Run commit-agent-work.sh for a `commit_after` agent.

    cwd (#373): the isolated worktree this run's agent invocation used, so
    commit-agent-work.sh stages and commits the files that were actually
    edited there rather than whatever the orchestrator's own working
    directory happens to hold.

    Returns a human-readable failure reason, or None on success. The caller
    owns the label/branch side-effects on failure.
    """
    _commit_script = _orchestration_script_path(".github/scripts/commit-agent-work.sh")
    _commit_env = {  # STD-SEC-022
        **{k: os.environ[k] for k in _COMMIT_AFTER_ENV_VARS if k in os.environ},
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
            env=_commit_env, capture_output=True, text=True, timeout=300, cwd=cwd,
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


# STD-SEC-022 — env vars for post_steps hooks (e.g. mark-pr-ready.sh): gh API/CLI
# calls only, no git commits. REPO, WORK_ITEM_*, AGENT_NAME, ISSUE/PR_NUMBER, and
# AI_AGILE_ROOT are set explicitly below.
_POST_STEPS_ENV_VARS = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
    "GH_TOKEN", "GITHUB_TOKEN",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
)


def _invoke_post_steps(
    agent_def: AgentDef, work_item: WorkItem, repo: str, gh: "GitHubClient"
) -> Optional[str]:
    """Run an agent's post_steps completion hooks in order.

    Returns the first failure reason, or None if all hooks succeed. Each hook is
    a repo-relative bash script; a path escaping the repo root is rejected.
    """
    _ps_env = {  # STD-SEC-022
        **{k: os.environ[k] for k in _POST_STEPS_ENV_VARS if k in os.environ},
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

    Covers the retry-exhausted and never-retried cases. The caller owns
    worktree cleanup and the early return.
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


def _finalize_run_exhaustion(
    agent_def: AgentDef,
    work_item: WorkItem,
    result: AgentRunResult,
    invoked_at: float,
    gh: "GitHubClient",
    session_id: str,
    repo: str,
) -> None:
    """Apply :exhausted and emit agent.exhausted. Never varies by attempt --
    exhaustion always breaks the retry loop on the first hit (_invoke_with_retries).
    """
    _apply_exhausted(gh, agent_def, work_item, result)
    log.error(
        "  EXHAUSTED  %-35s  on #%d (%s budget)",
        agent_def.agent, work_item.number,
        "wall-clock" if result.timed_out else "turn",
    )
    if session_id:
        _emit_audit_event(_make_audit_event(
            session_id, "agent.exhausted", repo,
            work_item=work_item, agent=agent_def.agent,
            outcome_status="exhausted",
            outcome_detail=(
                f"{'wall-clock' if result.timed_out else 'turn'} budget exhausted "
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
                expected_effect=agent_def.expected_effect,
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
    *,
    performed_by: str = "agent",
) -> None:
    """Emit the terminal agent.* audit event for the applied status.

    performed_by distinguishes a spawned-agent run from a person's own work
    applied via --interactive-result (PRODUCT.md, "Headless and interactive":
    "the orchestrator records that a person performed the activity rather
    than a spawned agent") — the mechanism that applies the result is
    otherwise identical either way (MI-3).
    """
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
        outcome_detail=f"mode={agent_def.step_type} performed_by={performed_by}",
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
    pre_agent_worktree: str,
    invoked_at: float,
    attempt: int,
    labels: set,
    concurrency: Optional[ComponentClaims],
    gh: "GitHubClient",
    session_id: str,
    repo: str,
    pipeline_map: dict,
    *,
    dry_run: bool = False,
    cycle_id: str = "",
    timestamp_start: str = "",
    timestamp_end: str = "",
    exhausted: bool = False,
    step_result: Optional[StepResult] = None,
    performed_by: str = "agent",
) -> bool:
    """Apply GitHub side-effects for a completed agent run.

    Handles rate-limit short-circuit, final status determination, commit-after
    invocation, human review override, terminal label application, closing
    announcement, gate prompt, requested label-change application, label
    refresh, audit event, PR ready promotion, and per-cycle metrics (issue #121).

    Calls _remove_run_worktree on every break path before returning True.
    The caller (process_work_item) calls _remove_run_worktree on the
    non-break path after this function returns False.

    Returns True if the agent loop should stop (break), False to continue.
    Updates work_item.labels after GitHub label refresh on the non-break path.
    """
    # Rate-limit short-circuit is handled by the caller (process_work_item) before
    # _apply_result is invoked, so result.rate_limited is always False here.
    if sentinel_status:
        final_status = sentinel_status
    elif exhausted:
        _finalize_run_exhaustion(
            agent_def, work_item, result, invoked_at, gh, session_id, repo,
        )
        _metrics_record = _build_step_metrics(
            agent_def, work_item, result,
            timestamp_start, timestamp_end, cycle_id,
            is_error_override=True,
        )
        _post_cycle_metrics(gh, repo, work_item, _metrics_record, dry_run)
        _remove_run_worktree(pre_agent_worktree)
        return True
    elif agent_def.step_type == "script" and result.success:
        # Script-type steps are unaffected by issue #400 — they meet the
        # return contract "by construction" (PRODUCT.md) and still resolve
        # via the AI_AGILE_STATUS stdout sentinel; a clean exit with none is
        # inferred complete, unchanged from before #400.
        final_status = STATUS_COMPLETE
        sentinel_message = "completed (no sentinel; inferred from exit 0)"
    else:
        # Agent-type step with no valid result file (crashed, or exited 0
        # without writing one) — both are "malformed" per PRODUCT.md's
        # `failed` definition. No outcome is inferred from a clean exit alone.
        _finalize_run_failure(
            agent_def, work_item, result, attempt, invoked_at, gh, session_id, repo,
        )
        _metrics_record = _build_step_metrics(
            agent_def, work_item, result,
            timestamp_start, timestamp_end, cycle_id,
            is_error_override=True,
        )
        _post_cycle_metrics(gh, repo, work_item, _metrics_record, dry_run)
        _remove_run_worktree(pre_agent_worktree)
        return True

    # commit-after: invoke commit-agent-work.sh when git_ops.commit_after: true.
    # Guard: commit-agent-work.sh requires ISSUE_NUMBER; only invoke for issue work items.
    if final_status == STATUS_COMPLETE and agent_def.commit_after and work_item.kind == "issue":
        _commit_fail_reason = _invoke_commit_after(agent_def, work_item, cwd=pre_agent_worktree or None)
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
            _remove_run_worktree(pre_agent_worktree)
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

    # Apply the step's requested label changes, filtered against its
    # declared allowed_labels (issue #400) — a step never writes labels
    # itself; this is the orchestrator applying only what clears.
    if step_result and step_result.label_requests:
        _apply_label_requests(gh, agent_def, work_item, step_result.label_requests)

    # Apply the step's requested body write, if any (issue #401) — a step
    # never writes the issue/PR body itself.
    _apply_body_write(gh, agent_def, work_item, step_result)

    # Refresh label set from GitHub after our writes.
    labels_refreshed = gh.get_issue_labels(work_item.number)
    work_item.labels = labels_refreshed

    log.info("  %-6s  %-38s", (applied_status or "?").upper(), agent_def.agent)

    _emit_terminal_audit(
        agent_def, work_item, applied_status, invoked_at, session_id, repo,
        performed_by=performed_by,
    )

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
        _remove_run_worktree(pre_agent_worktree)
        return True

    return False


def _parse_blocking_issue_numbers(labels: set[str]) -> list[int]:
    """Extract the target issue numbers from every blockedby:{N} label.

    A malformed suffix (non-numeric) is logged and ignored rather than
    treated as blocking -- PRODUCT.md's blocking mechanism has no validated
    vocabulary (like component:), so a mistyped label must not silently
    wedge an item forever.
    """
    numbers = []
    for lbl in labels:
        if not lbl.startswith(BLOCKEDBY_LABEL_PREFIX):
            continue
        suffix = lbl[len(BLOCKEDBY_LABEL_PREFIX):]
        if not suffix.isdigit():
            log.warning("malformed %r label -- ignoring (not blocking)", lbl)
            continue
        numbers.append(int(suffix))
    return numbers


def _work_item_has_started(labels: set[str], agents: list[AgentDef]) -> bool:
    """True once any configured agent has any status on this item.

    blockedby: only gates the entry step, never a step mid-flow (PRODUCT.md)
    -- once anything has run, further blockedby:/blocks: changes have no
    effect on this item.
    """
    return any(agent_status(labels, a.label_key) is not None for a in agents)


def _issue_is_open(gh: "GitHubClient", number: int) -> Optional[bool]:
    """True if issue `number` is open, False if closed, None if indeterminate.

    None on any API error or unexpected payload -- callers treat this the
    same as "still blocking": an unverifiable block is never silently lifted
    (STD-ARCH-014 fail-closed).
    """
    try:
        data = gh._get(f"/repos/{gh.repo}/issues/{number}")
        state = data.get("state") if isinstance(data, dict) else None
        if state not in ("open", "closed"):
            return None
        return state == "open"
    except Exception as exc:
        log.warning("could not check state of blocking issue #%d: %s", number, exc)
        return None


def _clear_satisfied_blocks(
    gh: "GitHubClient", work_item: WorkItem, labels: set[str],
) -> set[str]:
    """Remove blockedby:{N} (here) and blocks:{this} (on N) once N has closed.

    PRODUCT.md: "once N closes on its own, both labels come off
    automatically." Runs every tick regardless of whether this item has
    started -- clearing a satisfied block is not itself entry-gated.
    """
    for number in _parse_blocking_issue_numbers(labels):
        if _issue_is_open(gh, number) is not False:  # open, or indeterminate
            continue
        _this_label = f"{BLOCKEDBY_LABEL_PREFIX}{number}"
        try:
            gh.remove_label(work_item.number, _this_label)
            labels.discard(_this_label)
            log.info(
                "  UNBLOCK  #%d: %s cleared (issue #%d closed)",
                work_item.number, _this_label, number,
            )
        except Exception as exc:
            log.warning("  could not remove %s on #%d: %s", _this_label, work_item.number, exc)
        try:
            gh.remove_label(number, f"{BLOCKS_LABEL_PREFIX}{work_item.number}")
        except Exception as exc:
            log.warning(
                "  could not remove %s%d on #%d: %s",
                BLOCKS_LABEL_PREFIX, work_item.number, number, exc,
            )
    return labels


def _is_blocked_from_starting(gh: "GitHubClient", labels: set[str]) -> bool:
    """True if any remaining blockedby:{N} names a still-open (or
    indeterminate) issue."""
    return any(
        _issue_is_open(gh, number) is not False
        for number in _parse_blocking_issue_numbers(labels)
    )


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
    concurrency: Optional[ComponentClaims] = None,
    interactive_result: bool = False,
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

    # Blocking eligibility (issue #405): clear blockedby:/blocks: pairs whose
    # blocking issue has closed, then gate entry -- never a step mid-flow --
    # if anything remains open. No dedicated "unblocker" agent or extra
    # GitHub Actions workflow: this reuses the same orchestrator tick that
    # already evaluates every other agent, by design (the pipeline
    # deliberately runs no scheduled jobs beyond the emergency-stop check and
    # the main orchestrator). Issues only -- blocking is issue-to-issue
    # ordering (PRODUCT.md), not a PR gate.
    if work_item.kind == "issue":
        if not dry_run:
            labels = _clear_satisfied_blocks(gh, work_item, labels)
            work_item.labels = labels
        if not _work_item_has_started(labels, agents) and _is_blocked_from_starting(gh, labels):
            log.info(
                "  BLOCKED #%d: blockedby %s still open -- no entry step dispatched",
                work_item.number, _parse_blocking_issue_numbers(labels),
            )
            return 0

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

        (
            result, sentinel_status, sentinel_message, pre_worktree, invoked_at,
            attempt, exhausted, step_result,
        ) = _run_agent(
            agent_def, work_item, dry_run, repo, labels,
            session_id, default_extra_tools, concurrency, gh, pipeline_map,
            interactive_result=interactive_result,
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
                # Roll back the in-memory claim: the :wip was removed, so the
                # component is free again. Without this the claim and the
                # per-tick launch budget would over-count for the rest of the tick.
                if concurrency is not None:
                    concurrency.unclaim(_work_item_components(work_item))
                    concurrency.tick_launch_count = max(0, concurrency.tick_launch_count - 1)
                _remove_run_worktree(pre_worktree)
                break

            stop = _apply_result(
                agent_def, work_item, result, sentinel_status, sentinel_message,
                pre_worktree, invoked_at, attempt, labels, concurrency,
                gh, session_id, repo, pipeline_map,
                dry_run=dry_run, cycle_id=_cycle_id,
                timestamp_start=_timestamp_start, timestamp_end=_timestamp_end,
                exhausted=exhausted, step_result=step_result,
                performed_by="human" if interactive_result else "agent",
            )
            labels = normalize_skipped_labels(work_item.labels, pipeline_map)  # re-normalize after _apply_result refresh
            if stop:
                break
                break

        _remove_run_worktree(pre_worktree)
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
            "Used by /maos-{agent}-i to obtain the step's own instructions "
            "for a person and the chat-AI to work through directly. "
            "The printed env carries only the agent-facing context vars; every "
            "other key, credentials included, is omitted by name only under "
            "env_omitted_keys. "
            "Requires --agent and --issue (or --repo + --issue)."
        ),
    )
    p.add_argument(
        "--interactive-result",
        action="store_true",
        help=(
            "Apply mode: instead of spawning --agent as a subprocess, read its "
            "already-written $AI_AGILE_SCRATCH/result.json (produced by a "
            "person and the chat-AI working through the step's instructions "
            "under --print-prompt) and apply it exactly as a real run's "
            "result would be applied -- same eligibility check (including the "
            "dependencies_complete gate), same :wip/announcement/artefact/"
            "label/body-write/post_steps handling, so the audit trail and "
            "GitHub state cannot drift between the two paths (MI-3). The only "
            "difference recorded is attribution: the audit event's "
            "performed_by is 'human', not 'agent'. Requires --agent and "
            "--issue (or --repo + --issue). Second phase of /maos-{agent}-i, "
            "run after --print-prompt's first phase and the interactive work "
            "it enables."
        ),
    )
    p.add_argument(
        "--confirm-gate",
        action="store_true",
        help=(
            "Interactive gate-crossing (issue #403; PRODUCT.md MI-7): the "
            "orchestrator itself applies --agent's human_gate_label to "
            "--issue, having been told by the driver that a person "
            "confirmed the approval -- the driver never writes the gate "
            "label directly. Refuses if --agent has no human_gate_label, or "
            "if the label is already present (re-applying is a no-op that "
            "would not generate a fresh, attributable labeled event). "
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
    concurrency: ComponentClaims
    repo: str
    session_id: str
    dry_run: bool
    default_extra_tools: Optional[list]
    interactive_result: bool = False


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


# STD-SEC-022 — env vars for delete-branch.sh: gh API only, no git commands,
# no bot token needed. REPO and BRANCH are set explicitly below.
_DELETE_BRANCH_ENV_VARS = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
    "GH_TOKEN", "GITHUB_TOKEN",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
)


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

    env = {  # STD-SEC-022
        **{k: os.environ[k] for k in _DELETE_BRANCH_ENV_VARS if k in os.environ},
        "REPO": repo,
        "BRANCH": branch,
    }
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
    are made. Called when --print-prompt is passed; used by /maos-{agent}-i to
    obtain authoritative invocation parameters from the orchestrator's own
    resolution logic instead of hand-parsing the agent file.

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
    # Probe rather than assume. Defaulting to "issue" made `--print-prompt
    # --agent 03_execute/coder --issue 360` resolve a PR number as an issue and
    # export WORK_ITEM_KIND=issue, so the agent read the wrong object with no
    # error anywhere (issue #356). The --issue path in main() already probes;
    # resolve-only must agree with it or /maos-{agent}-i silently diverges.
    kind = args.kind or _probe_kind(gh, args.issue)
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

    # Resolve the AgentDef the same way a real spawn does: from pipeline.json,
    # which is where essentially all tool grants live. Building a minimal
    # AgentDef from the agent file's frontmatter instead dropped
    # defaults.extra_allowedTools and the per-agent extra_allowedTools, so
    # resolve-only returned 24 tools where the real spawn gets 93 -- and the
    # predecessor of /maos-{agent}-i wrote that wrong list to the scope file
    # its (since-deleted, issue #402) enforcement hook read (issue #356).
    # --print-prompt already requires --repo and --issue, so loading the
    # pipeline spec adds no new inputs.
    agent_name = args.agent
    agent_file = SUBMODULE_ROOT / ".claude/agents" / f"{agent_name}.md"
    if not agent_file.exists():
        log.error("Agent file not found: %s", agent_file)
        sys.exit(1)

    agents, default_extra_tools = load_pipeline(args.pipeline)
    agent_def = pipeline_by_name(agents).get(agent_name)
    if agent_def is None:
        # An agent file exists but pipeline.json does not register it: on-demand
        # agents (00_ondemand/*) are invoked by label, not by a pipeline step.
        # Fall back to a bare AgentDef -- default_extra_tools (pipeline.json's
        # defaults.extra_allowedTools) still applies; there is nothing left to
        # read from frontmatter, which declares only name and description (AS-1).
        log.info(
            "  %s is not registered in %s; resolving with pipeline-wide defaults only",
            agent_name, args.pipeline,
        )
        agent_def = AgentDef(
            agent=agent_name,
            phase="",
            objects=[],
            trigger={},
            dependencies=[],
            human_gate_after=False,
            human_gate_label=None,
            description="",
        )

    if agent_def.objects and work_item.kind not in agent_def.objects:
        log.warning(
            "  %s runs on %s, not %s. Resolving #%d as a %s anyway, but the "
            "agent's prompt expects the other object kind -- pass --kind "
            "explicitly if this is deliberate.",
            agent_name, "/".join(agent_def.objects), work_item.kind,
            work_item.number, work_item.kind,
        )

    resolved = _resolve_agent_invocation(
        agent_def, work_item, args.repo, default_extra_tools=default_extra_tools,
    )
    if resolved is None:
        log.error("Could not resolve invocation for agent %s", agent_name)
        sys.exit(1)

    # Build env with interactive mode -- this path is used by /maos-{agent}-i,
    # not by a real orchestrator subprocess spawn.
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


def _run_confirm_gate(args) -> None:
    """Interactive gate-crossing (issue #403; PRODUCT.md MI-7).

    The orchestrator -- never the driver -- writes the human-gate label,
    having been told by the driver that a person confirmed the approval.
    Because this runs inside the person's own interactive session, the
    label's GitHub-recorded actor is their own account, so it satisfies
    _gate_label_human_applied exactly the way a headless human-applied label
    does -- one mechanism, not two (MI-3/MI-7).

    Refuses (never silently no-ops) when:
    - --agent has no human_gate_label: nothing for this mode to confirm.
    - the label is already present: gh.add_label on an already-present label
      is a GitHub no-op that generates no new labeled event, so re-adding it
      would silently leave a prior bot-authored event as the most recent one
      -- exactly the trap issue #377 named ("re-applying an existing label is
      a no-op"). If that prior application was already human-verified there
      is nothing to do; if not, the fix is removing it first, not papering
      over it here.
    """
    if not args.agent:
        log.error("--confirm-gate requires --agent <agent-name>")
        sys.exit(1)
    if not args.issue:
        log.error("--confirm-gate requires --issue <number>")
        sys.exit(1)
    if not args.repo:
        log.error("--confirm-gate requires --repo <owner/repo>")
        sys.exit(1)

    token = _discover_github_token()
    if not token:
        log.error("No GitHub token found. Set $GITHUB_TOKEN or authenticate with `gh auth login`.")
        sys.exit(1)

    agents, _default_extra_tools = load_pipeline(args.pipeline)
    agent_def = pipeline_by_name(agents).get(args.agent)
    if agent_def is None:
        log.error("--confirm-gate: unknown --agent %r in %s", args.agent, args.pipeline)
        sys.exit(1)
    if not agent_def.human_gate_label:
        log.error(
            "--confirm-gate: %s declares no human_gate_label -- there is no gate to confirm",
            args.agent,
        )
        sys.exit(1)

    gh = GitHubClient(args.repo, token)
    gate_label = agent_def.human_gate_label
    try:
        current_labels = gh.get_issue_labels(args.issue)
    except Exception as exc:
        log.error("Could not read labels for #%s: %s", args.issue, exc)
        sys.exit(1)

    if gate_label in current_labels:
        if _gate_label_human_applied(gh, args.repo, args.issue, gate_label):
            log.info(
                "  %s is already present on #%s and was human-applied -- nothing to confirm",
                gate_label, args.issue,
            )
            return
        log.error(
            "  %s is already present on #%s but was not verifiably human-applied. "
            "Re-adding it would not change that -- remove it first "
            "(gh issue edit %s --repo %s --remove-label %r), then re-run --confirm-gate "
            "so a fresh, attributable labeled event is recorded.",
            gate_label, args.issue, args.issue, args.repo, gate_label,
        )
        sys.exit(1)

    try:
        gh.add_label(args.issue, gate_label)
    except Exception as exc:
        log.error("Could not apply %s to #%s: %s", gate_label, args.issue, exc)
        sys.exit(1)
    log.info("  CONFIRM %-38s  %s applied to #%s (relayed human confirmation)",
              args.agent, gate_label, args.issue)

    session_id = f"ais-v1-orch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    kind = args.kind or _probe_kind(gh, args.issue)
    _emit_audit_event(_make_audit_event(
        session_id, "gate.confirmed", args.repo,
        work_item=WorkItem(number=args.issue, kind=kind, title="", labels=set(), url=""),
        agent=args.agent,
        outcome_status="confirmed",
        outcome_detail=f"{gate_label} applied by orchestrator on a relayed human confirmation",
    ))


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
            # checkout/fetch calls run via subprocess.run with no env= argument,
            # so they read the header from here and authenticate.
            #
            # commit-agent-work.sh and post_steps do NOT inherit these any more.
            # Since STD-SEC-022 they build their env from named allowlists
            # (_COMMIT_AFTER_ENV_VARS / _POST_STEPS_ENV_VARS) that deliberately
            # omit GIT_CONFIG_*; commit-agent-work.sh derives its own auth
            # header from GH_TOKEN/GITHUB_TOKEN instead. Do not re-add
            # GIT_CONFIG_* to those lists -- the scripts do not need it, and it
            # would hand the embedded token to every post_steps hook.
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

    # pipeline_map is built from the full (phase-filtered) agent set so
    # dependency lookups always resolve, even when --interactive-result below
    # narrows the *iteration* list to one agent.
    pipeline_map = pipeline_by_name(agents)

    # --interactive-result: apply mode for /maos-{agent}-i's second phase.
    # Scope this tick's iteration to exactly the named agent so applying one
    # person-produced result never also spawns a real subprocess for some
    # other, unrelated eligible step (MI-3 — one mechanism, not a second one
    # that happens to run alongside the first). pipeline_map above stays full.
    if args.interactive_result:
        if not args.agent:
            log.error("--interactive-result requires --agent")
            sys.exit(1)
        if not args.issue:
            log.error("--interactive-result requires --issue")
            sys.exit(1)
        agents = [a for a in agents if a.agent == args.agent]
        if not agents:
            log.error("--interactive-result: unknown --agent %r", args.agent)
            sys.exit(1)

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

    # Seed component claims from labels fetched above: items already carrying
    # some agent's :wip label (left running by a prior tick) have their
    # components claimed before this tick evaluates anything. tick_launch_count
    # starts at 0 and accumulates launches within this tick against
    # MAX_LAUNCHES_PER_TICK.
    conc = _seed_component_claims(work_items)
    if conc.claimed or conc.claims_everything:
        log.info(
            "Running at tick start (prior-tick :wip): claimed=%s claims_everything=%s",
            sorted(conc.claimed), conc.claims_everything,
        )

    return RunContext(
        gh=gh, agents=agents, pipeline_map=pipeline_map, work_items=work_items,
        concurrency=conc, repo=args.repo, session_id=session_id,
        dry_run=args.dry_run, default_extra_tools=default_extra_tools,
        interactive_result=args.interactive_result,
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
    per-tick launch budget. Returns the number of agents triggered."""
    total_triggered = 0
    for item in ctx.work_items:
        if not ctx.dry_run and ctx.concurrency.tick_launch_count >= MAX_LAUNCHES_PER_TICK:
            log.info(
                "Per-tick launch budget (%d) reached — deferring remaining work items to next tick.",
                MAX_LAUNCHES_PER_TICK,
            )
            break
        n = process_work_item(
            item, ctx.agents, ctx.pipeline_map, ctx.gh, ctx.dry_run, ctx.repo,
            session_id=ctx.session_id,
            default_extra_tools=ctx.default_extra_tools,
            concurrency=ctx.concurrency,
            interactive_result=ctx.interactive_result,
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

# Set to the absolute path of the isolated worktree (see _create_run_worktree)
# while a commit_after run is mid-flight, so a termination signal can remove
# it rather than leaving debris and a stale registration behind. Cleared by
# _remove_run_worktree once the run's own cleanup runs normally.
_CURRENT_WORKTREE = None


def _clear_inflight_wip_on_signal(signum, _frame) -> None:
    """Best-effort: drop the in-flight :wip label and worktree, then exit.

    A killed tick (SIGTERM/SIGINT) otherwise leaves the work item stuck at :wip
    -- the mutex blocks the next tick from re-triggering the agent. Clearing that
    one label makes the item immediately retryable. Similarly, an isolated
    worktree left behind by a kill would otherwise strand disk and a stale
    `git worktree` registration; _create_run_worktree already clears debris
    from a prior kill on its next use, but removing it here means a killed
    run leaves nothing behind at all when the kill is clean.
    """
    wip = _CURRENT_WIP
    if wip is not None:
        gh, number, label = wip
        try:
            gh.remove_label(number, label)
            log.warning("signal %d: cleared in-flight %s on #%d before exit", signum, label, number)
        except Exception as exc:
            log.warning("signal %d: could not clear in-flight %s on #%d: %s", signum, label, number, exc)
    worktree = _CURRENT_WORKTREE
    if worktree:
        try:
            subprocess.run(["git", "worktree", "remove", "--force", worktree],
                            check=False, capture_output=True)
            log.warning("signal %d: removed in-flight worktree %s before exit", signum, worktree)
        except Exception as exc:
            log.warning("signal %d: could not remove in-flight worktree %s: %s", signum, worktree, exc)
    # No scratch cleanup here: scratch-setup.sh clears the directory at the
    # start of every run, so a killed tick self-heals on the next one.
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

    if args.confirm_gate:
        _run_confirm_gate(args)
        return

    ctx = _wake(args)
    if ctx is None:
        return

    total_triggered = _do_work(ctx)
    _close_down(ctx, total_triggered)


if __name__ == "__main__":
    main()
