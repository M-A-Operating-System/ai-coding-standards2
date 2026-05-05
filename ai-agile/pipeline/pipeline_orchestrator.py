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
    pip install PyGithub requests
    gh CLI authenticated
    ANTHROPIC_API_KEY set in environment (for agent execution)
    GITHUB_TOKEN set in environment (or gh CLI authenticated)
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
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

# Alias kept for internal use
STATUS_IN_PROGRESS = STATUS_WIP

ALL_STATUSES = {
    STATUS_COMPLETE, STATUS_WIP, STATUS_REVIEW,
    STATUS_BLOCKED, STATUS_FAILED, STATUS_SKIPPED,
}

# Statuses where the orchestrator takes no further action on this agent.
# review and blocked halt the pipeline but are NOT terminal — a human
# removes the label to resume. failed and skipped are terminal.
HALT_STATUSES    = {STATUS_REVIEW, STATUS_BLOCKED}
TERMINAL_STATUSES = {STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED}

STATUSES_JSON = Path(__file__).parent / "statuses.json"

# Submodule root — the directory containing this repo's .github/ and
# ai-agile/. When installed as a submodule, it is the submodule's root,
# not the consuming repo's root. Used to locate status.sh and agent
# prompt files. Override with $AI_AGILE_ROOT for non-standard layouts.
SUBMODULE_ROOT = (
    Path(os.environ["AI_AGILE_ROOT"]).resolve()
    if os.environ.get("AI_AGILE_ROOT")
    else Path(__file__).resolve().parent.parent.parent
)

def load_statuses() -> list[dict]:
    """Load status definitions from statuses.json. Exits if file is missing or malformed."""
    if not STATUSES_JSON.exists():
        log.error("statuses.json not found at %s — cannot start", STATUSES_JSON)
        sys.exit(1)
    try:
        with open(STATUSES_JSON) as f:
            return json.load(f)["statuses"]
    except (KeyError, json.JSONDecodeError) as e:
        log.error("statuses.json is malformed: %s", e)
        sys.exit(1)

STATUSES     = load_statuses()
LABEL_COLOURS = {s["status"]: s["colour"] for s in STATUSES}


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

    @property
    def complete_label(self) -> str:
        return f"{self.agent}:{STATUS_COMPLETE}"

    @property
    def in_progress_label(self) -> str:
        return f"{self.agent}:{STATUS_IN_PROGRESS}"

    @property
    def failed_label(self) -> str:
        return f"{self.agent}:{STATUS_FAILED}"

    @property
    def review_label(self) -> str:
        return f"{self.agent}:{STATUS_REVIEW}"

    @property
    def blocked_label(self) -> str:
        return f"{self.agent}:{STATUS_BLOCKED}"

    def status_label(self, status: str) -> str:
        return f"{self.agent}:{status}"


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


# ---------------------------------------------------------------------------
# Pipeline loader
# ---------------------------------------------------------------------------

def load_pipeline(path: Path) -> list[AgentDef]:
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
        ))
    return agents


def pipeline_by_name(agents: list[AgentDef]) -> dict[str, AgentDef]:
    return {a.agent: a for a in agents}


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

class GitHubClient:
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

    def _get(self, path: str, params: dict = None) -> dict | list:
        r = self.session.get(f"{self.base}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = self.session.post(f"{self.base}{path}", json=body)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> None:
        r = self.session.delete(f"{self.base}{path}")
        if r.status_code not in (200, 204):
            r.raise_for_status()

    def get_issue_labels(self, number: int) -> set[str]:
        data = self._get(f"/repos/{self.repo}/issues/{number}/labels")
        return {lbl["name"] for lbl in data}

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
            if e.response.status_code != 404:
                raise
            # Determine colour from the status suffix
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
                if create_err.response.status_code == 422:
                    pass
                else:
                    raise

    def post_comment(self, number: int, body: str) -> None:
        self._post(f"/repos/{self.repo}/issues/{number}/comments", {"body": body})


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
    """
    if not PAUSE_MARKER_PATH.exists():
        return False, None, None
    try:
        marker = json.loads(PAUSE_MARKER_PATH.read_text())
        until = datetime.fromisoformat(marker["until"])
        if _now_utc() < until:
            return True, marker.get("reason", "pipeline paused"), until
        # Expired — clear it so the next agent failure can write a fresh marker.
        PAUSE_MARKER_PATH.unlink(missing_ok=True)
        log.info("Pause marker expired (was until %s); cleared.", until.isoformat())
        return False, None, None
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        log.warning("Pause marker at %s is malformed (%s); ignoring.", PAUSE_MARKER_PATH, exc)
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
    PAUSE_MARKER_PATH.write_text(json.dumps(payload, indent=2))
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

        if f"{dep_name}:{STATUS_COMPLETE}" not in labels:
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


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------

STATUS_SH = SUBMODULE_ROOT / ".github/scripts/status.sh"

# Rate-limit pause marker. When the Claude API returns a 429 / usage-limit
# error, the orchestrator writes this file with a JSON payload describing
# how long to back off. Subsequent runs check this file before doing
# anything; if the until-time has not yet passed, the orchestrator logs
# the wait and exits cleanly. The next scheduled tick (or a manual
# workflow_dispatch with --clear-pause) resumes work.
PAUSE_MARKER_PATH = SUBMODULE_ROOT / ".pipeline-pause"

# Default pause duration if the API response does not name one. Five
# minutes is short enough that a transient burst recovers quickly; long
# enough that we don't hammer the API after a real per-minute exhaust.
DEFAULT_PAUSE_SECONDS = 300

# Maximum pause duration. Caps any retry-after we honour from the API
# so a misbehaving server cannot pause us indefinitely. One hour is
# longer than any documented Anthropic per-minute limit reset and
# shorter than any reasonable manual response time.
MAX_PAUSE_SECONDS = 3600

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


def invoke_agent(
    agent_def: AgentDef,
    work_item: WorkItem,
    dry_run: bool,
    repo: str,
) -> bool:
    """
    Invoke the agent via claude CLI.

    Agents use status.sh for all label transitions so they behave
    identically whether called manually or by this orchestrator:

      bash .github/scripts/status.sh set-wip      <agent> <number>
      bash .github/scripts/status.sh set-complete  <agent> <number>
      bash .github/scripts/status.sh set-review    <agent> <number> [message]
      bash .github/scripts/status.sh set-blocked   <agent> <number> <reason>
      bash .github/scripts/status.sh set-failed    <agent> <number> [detail]

    The orchestrator does NOT apply wip/complete itself — it tells the
    agent to do so via status.sh, keeping the transition logic in one place.

    Returns True if the invocation succeeded, False otherwise.
    """
    agent_file = SUBMODULE_ROOT / ".github/agents" / f"{agent_def.agent}.md"

    if not STATUS_SH.exists():
        log.error("status.sh not found at %s", STATUS_SH)
        return False

    # Build the prompt that is passed to every agent.
    # Agents MUST use status.sh for all label transitions and reference
    # it via the $STATUS_SH env var the orchestrator exports below — that
    # way the same prompt works whether this repo is checked out at the
    # consuming repo's root or as a submodule under it.
    prompt = (
        f"You are the {agent_def.agent} agent defined in {agent_file}.\n"
        f"Follow those instructions exactly.\n\n"
        f"## Work item\n"
        f"- Repository: {repo}\n"
        f"- {'Issue' if work_item.kind == 'issue' else 'PR'} number: #{work_item.number}\n"
        f"- Title: {work_item.title}\n"
        f"- URL: {work_item.url}\n\n"
        f"## Status commands\n"
        f"Use these commands for all label transitions. Do not apply labels directly.\n"
        f"$STATUS_SH is exported in your environment and resolves to:\n"
        f"  {STATUS_SH}\n\n"
        f"  # Mark yourself as running (already applied by orchestrator — skip if present)\n"
        f"  bash $STATUS_SH set-wip {agent_def.agent} {work_item.number}\n\n"
        f"  # Mark complete when your work is done (non-gated agents only)\n"
        f"  bash $STATUS_SH set-complete {agent_def.agent} {work_item.number}\n\n"
        f"  # Request human review (post your artefact first, then call this — gated agents)\n"
        f"  bash $STATUS_SH set-review {agent_def.agent} {work_item.number} \"<message>\"\n\n"
        f"  # Mark blocked when you cannot proceed without human help\n"
        f"  bash $STATUS_SH set-blocked {agent_def.agent} {work_item.number} \"<reason>\"\n\n"
        f"You MUST call exactly one of set-complete, set-review, or set-blocked before exiting.\n"
        f"You MUST NOT call set-failed — the orchestrator applies :failed if you exit non-zero "
        f"without one of the three terminal calls above."
    )

    cmd = [
        "claude",
        "--allowedTools",
        f"Bash(git *),Bash(gh *),Bash(bash {STATUS_SH} *),Read,Glob,Grep",
        "--max-turns", "60",
        "-p", prompt,
    ]

    if dry_run:
        log.info("    [DRY RUN] Would invoke: claude --max-turns 60 -p <prompt>")
        log.info("    [DRY RUN] Agent: %s | Item: %s #%d", agent_def.agent, work_item.kind, work_item.number)
        return True

    if not agent_file.exists():
        log.warning("    Agent file not found: %s — skipping", agent_file)
        return False

    log.info("    Invoking agent: %s on %s #%d", agent_def.agent, work_item.kind, work_item.number)

    # Export resolved paths so the agent prompt's bash snippets work
    # regardless of CWD or where this repo is mounted in the consuming repo.
    agent_env = {
        **os.environ,
        "STATUS_SH": str(STATUS_SH),
        "AI_AGILE_ROOT": str(SUBMODULE_ROOT),
        "REPO": repo,
        "ISSUE_NUMBER": str(work_item.number),
        "PR_NUMBER": str(work_item.number),
    }

    # Capture output so we can detect Anthropic rate-limit errors after
    # the run. Stream it to our stderr line-by-line so logs remain
    # readable in real time, but keep a copy in `captured` for inspection.
    captured_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=agent_env,
        )
        deadline = time.monotonic() + 1800   # 30 min max
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                captured_lines.append(line)
                # Mirror to our stderr so the subprocess log is visible
                # in the orchestrator's CI output.
                sys.stderr.write(line)
                if time.monotonic() > deadline:
                    proc.kill()
                    raise subprocess.TimeoutExpired(cmd, 1800)
            proc.wait()
        except subprocess.TimeoutExpired:
            log.error("    Agent %s timed out on #%d", agent_def.agent, work_item.number)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return False

        # On non-zero exit, check whether the cause was a rate-limit
        # error from the Anthropic API. If so, pause the pipeline so
        # subsequent runs back off rather than burning more requests.
        if proc.returncode != 0:
            captured = "".join(captured_lines)
            is_limited, retry_after = detect_rate_limit(captured)
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
                # Treat as a non-failure for the orchestrator's perspective:
                # the agent did not get a fair chance to run, so we should
                # not mark it :failed. Caller treats False as "did not
                # succeed"; we rely on the pause marker to keep subsequent
                # ticks from re-invoking until the limit clears.
            return False

        return True

    except FileNotFoundError:
        log.error("    'claude' CLI not found. Install: npm install -g @anthropic-ai/claude-code")
        return False


# ---------------------------------------------------------------------------
# Core orchestration logic
# ---------------------------------------------------------------------------

def process_work_item(
    work_item: WorkItem,
    agents: list[AgentDef],
    pipeline_map: dict[str, AgentDef],
    gh: GitHubClient,
    dry_run: bool,
    repo: str,
) -> int:
    """
    Evaluate all agents against a single issue or PR.
    Returns the number of agents triggered.
    """
    triggered = 0
    labels = work_item.labels

    log.info(
        "%s #%d: %s",
        work_item.kind.upper(), work_item.number,
        work_item.title[:70] + ("…" if len(work_item.title) > 70 else "")
    )

    for agent_def in agents:

        # Skip if this agent doesn't operate on this kind of work item
        if work_item.kind not in agent_def.objects:
            continue

        current_status = agent_status(labels, agent_def.agent)

        # Skip if already terminal
        if current_status in (STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED):
            log.debug("  skip %-40s  [%s]", agent_def.agent, current_status)
            continue

        # Skip if already running
        if current_status == STATUS_IN_PROGRESS:
            log.info("  wait %-40s  [wip]", agent_def.agent)
            continue

        # Check trigger label is present
        if not trigger_label_present(labels, agent_def):
            log.debug(
                "  skip %-40s  [trigger not met: %s]",
                agent_def.agent,
                agent_def.trigger.get("label", "event/schedule")
            )
            continue

        # Check all dependencies are complete (including human gates)
        if not dependencies_complete(labels, agent_def, pipeline_map):
            log.debug("  skip %-40s  [dependencies unmet]", agent_def.agent)
            continue

        # All conditions met — trigger this agent.
        # The agent itself calls status.sh set-wip at start and
        # set-complete / set-review / set-blocked on exit.
        # The orchestrator only applies set-failed if the agent crashes
        # (non-zero exit) without setting a terminal status itself.
        log.info("  TRIGGER %-38s", agent_def.agent)

        success = invoke_agent(agent_def, work_item, dry_run, repo)

        if not dry_run:
            # If invoke_agent set a pause marker (Anthropic rate limit),
            # stop processing entirely. Do NOT mark :failed — the agent
            # never got a fair run. The next scheduled tick (after the
            # pause expires) will retry.
            paused, reason, until = is_pipeline_paused()
            if paused:
                log.warning(
                    "  PAUSED  %-38s  rate-limited; resuming after %s",
                    agent_def.agent, until.isoformat() if until else "?"
                )
                break

            # Refresh labels — the agent may have applied wip, complete,
            # review, or blocked via status.sh during its run.
            labels = gh.get_issue_labels(work_item.number)
            work_item.labels = labels
            final_status = agent_status(labels, agent_def.agent)

            if not success and final_status not in (
                STATUS_COMPLETE, STATUS_REVIEW, STATUS_BLOCKED, STATUS_SKIPPED
            ):
                # Agent crashed without cleanly setting a status — apply failed.
                gh.add_label(work_item.number, agent_def.failed_label)
                gh.post_comment(
                    work_item.number,
                    (
                        f"**{agent_def.agent}** exited with an error on #{work_item.number}.\n\n"
                        f"The pipeline is paused. Review the agent logs, then either:\n"
                        f"- Remove `{agent_def.failed_label}` to retry, or\n"
                        f"- Apply `{agent_def.status_label(STATUS_SKIPPED)}` to bypass."
                    )
                )
                log.error(
                    "  FAILED  %-38s  pipeline paused on #%d",
                    agent_def.agent, work_item.number
                )
                break

            log.info(
                "  %-6s  %-38s",
                (final_status or "?").upper(), agent_def.agent
            )

            # If the agent wrote complete and a human gate is configured,
            # post the gate comment so the reviewer knows what to do.
            if final_status == STATUS_COMPLETE and agent_def.human_gate_after and agent_def.human_gate_label:
                gh.post_comment(
                    work_item.number,
                    (
                        f"**{agent_def.agent}** is complete.\n\n"
                        f"Apply `{agent_def.human_gate_label}` to advance the pipeline."
                    )
                )
                log.info(
                    "  GATE    %-38s  waiting for: %s",
                    agent_def.agent, agent_def.human_gate_label
                )

            # Halt if the agent blocked or requested review — do not
            # attempt to trigger further agents on this item this run.
            if final_status in (STATUS_BLOCKED, STATUS_REVIEW, STATUS_FAILED):
                break

        triggered += 1

    return triggered


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

    if not args.repo:
        log.error("--repo is required or set $GITHUB_REPOSITORY")
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        # Fall back to gh CLI token
        try:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, check=True
            )
            token = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            log.error(
                "No GitHub token found. Set $GITHUB_TOKEN or authenticate with `gh auth login`"
            )
            sys.exit(1)

    agents = load_pipeline(args.pipeline)
    pipeline_map = pipeline_by_name(agents)
    gh = GitHubClient(repo=args.repo, token=token)

    log.info("Pipeline: %d agents across %d phases",
             len(agents),
             len({a.phase for a in agents}))
    log.info("Repository: %s", args.repo)
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

    log.info("Work items to evaluate: %d", len(work_items))

    total_triggered = 0
    for item in work_items:
        n = process_work_item(item, agents, pipeline_map, gh, args.dry_run, args.repo)
        total_triggered += n
        if n > 0:
            # Brief pause between agent invocations to avoid rate limits
            time.sleep(2)

    log.info("─" * 60)
    log.info("Complete. Agents triggered this run: %d", total_triggered)


if __name__ == "__main__":
    main()
