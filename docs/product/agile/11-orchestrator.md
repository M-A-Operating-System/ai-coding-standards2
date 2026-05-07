# Orchestrator — Technical Design

The orchestrator is the single component with routing authority over the
pipeline. It reacts to GitHub events, evaluates the dependency graph, and
decides which agent runs next. No LLM is in this path — every decision is
deterministic Python (P-14).

This document covers: inputs, outputs, decision logic, the mutex protocol,
gate label handling, failure recovery, and the GitHub Actions workflows that
host it.

---

## Role and scope

The orchestrator owns exactly these responsibilities:

| Responsibility | Detail |
|---|---|
| Event intake | Translate raw GitHub webhooks into the semantic event vocabulary |
| State read | Read pipeline state — labels, session comments, PR metadata — from GitHub |
| Eligibility evaluation | Walk the dependency graph in `pipeline.json` and decide which agent is next |
| Mutex management | Acquire and release the `:wip` label lock per (object, agent) |
| Agent invocation | Spawn the agent subprocess; set `:failed` if it crashes without a terminal status |
| Gate promotion | When a human applies a gate label, remove `:review` and apply `:complete` |
| Audit log emission | Append one JSONL event per transition to the `ai-agile/log` branch |

It owns none of these:

- Agent behaviour (prompts, tools, model — those live in `.github/agents/{agent}.md`)
- Standards checking (the `standards-compliance-reviewer` agent does this)
- Pipeline graph definition (`pipeline.json` is the source of truth; the orchestrator reads it)

---

## Source location

```
ai-agile/pipeline/
  pipeline_orchestrator.py     ← the orchestrator
  pipeline.json                ← the dependency graph it reads
  schemas/
    pipeline.schema.json
  generators/
    generate_docs.py
    generate_pipeline_mermaid.py
```

The GitHub Actions workflows that invoke it live at:

```
.github/workflows/
  orchestrator-label.yml       ← fires on label add/remove
  orchestrator-pr.yml          ← fires on PR lifecycle events
  orchestrator-schedule.yml    ← fires every 15 minutes
  orchestrator-dispatch.yml    ← manual trigger (debug / single-item)
```

---

## Inputs

| Input | Source | How used |
|---|---|---|
| `pipeline.json` | Repo file | Loaded once per run; defines agent graph, dependencies, triggers, and gates |
| GitHub labels on the work item | GitHub REST API | Determines current agent statuses and which gate labels are present |
| GitHub event payload | Actions `GITHUB_EVENT_PATH` | Narrows which work item to process; identifies the triggering event type |
| `GITHUB_TOKEN` | Actions secret | Authenticates all GitHub API calls; must have `issues:write` and `pull-requests:write` |
| `ANTHROPIC_API_KEY` | Actions secret | Passed through to the Claude CLI when invoking agents |
| `GITHUB_REPOSITORY` | Actions env | `owner/repo` string; used in all API paths |
| Agent prompt files | `.github/agents/{agent}.md` | Passed by path reference to the Claude CLI; the orchestrator does not read their content |

The orchestrator holds no persistent state between runs. Everything it needs
is reconstructed from GitHub labels at the start of each run. This is the
direct consequence of P-1 (Git is authoritative) and P-11 (resumable by
default).

---

## Outputs

| Output | Mechanism | When |
|---|---|---|
| `{agent}:wip` label applied | GitHub REST API | At start of mutex acquisition |
| `{agent}:failed` label applied | GitHub REST API | When agent exits non-zero without a terminal status |
| `{agent}:review` → `{agent}:complete` transition | GitHub REST API | When human applies the gate label (gate promotion) |
| Gate prompt comment | GitHub Issues API | After a non-gated agent completes and the next step requires a gate label |
| `:failed` recovery comment | GitHub Issues API | When an agent crashes; names the label to remove and the label to skip |
| Audit log JSONL event | Append to `ai-agile/log` branch | Once per status transition, agent run, or gate approval |

---

## Decision loop

On every invocation, the orchestrator runs the same loop:

```
for each work item (issue or PR):
    labels = read_labels(work_item)

    for each agent_def in pipeline.json (in declaration order):
        if work_item.kind not in agent_def.object:
            skip                          ← wrong object type

        status = current_status(labels, agent_def.agent)

        if status in {complete, failed, skipped}:
            skip                          ← terminal; nothing to do

        if status == wip:
            skip                          ← already running; do not double-trigger

        if status == review:
            check_gate_promotion(labels, agent_def)  ← see Gate promotion below
            skip                          ← halted pending human approval

        if status == blocked:
            skip                          ← halted pending human resolution

        if not trigger_satisfied(labels, agent_def):
            skip                          ← label trigger not present

        if not dependencies_complete(labels, agent_def):
            skip                          ← upstream agents / gates not yet done

        ← agent is eligible
        acquire_mutex(work_item, agent_def)
        success = invoke_agent(work_item, agent_def)
        labels = refresh_labels(work_item)    ← re-read after agent run
        handle_outcome(work_item, agent_def, success, labels)

        if agent_outcome in {review, blocked, failed}:
            break                         ← halt this item; no further agents this run
```

The loop is **deterministic**: given identical inputs (labels + `pipeline.json`)
it always produces the same decision. There is no randomness, no LLM call,
no retry logic inside the loop. The only external writes are the mutex label
and the audit log event.

---

## Eligibility check

An agent is eligible to run when all four conditions hold simultaneously:

**1. Object match.**
The agent's `object` array in `pipeline.json` contains the type of the
current work item (`"issue"` or `"pr"`).

**2. No existing status.**
No `{agent}:{any-status}` label is present on the work item. An agent that
already has a status — even `:failed` — is skipped until a human removes the
label.

**3. Trigger satisfied.**
- `{event: "pr.draft_opened"}` — satisfied when the current invocation was
  triggered by that specific PR event (detected from the event payload).
- `{label: "some-label"}` — satisfied when that label is present on the work
  item.
- `{schedule: "..."}` — always satisfied when the orchestrator runs (the
  schedule is enforced by the Actions cron, not the orchestrator).
- Combined triggers (multiple shapes on one agent) — satisfied when **any**
  shape is met.
- Path-filter modifier — for triggers with `path_filter`, satisfied only
  when the changed file set matches the filter.

**4. Dependencies complete.**
For every agent listed in `agent_def.dependencies`:

```
dep_agent:complete ∈ labels
AND (if dep_agent has human_gate_after=true):
    dep_agent.human_gate_label ∈ labels
```

Both conditions must hold. A `dep:complete` without its gate label means the
human gate has not yet been applied; the dependent agent stays ineligible.
A `dep:skipped` label is treated as equivalent to `dep:complete` — the agent
was bypassed and downstream work may proceed.

---

## Mutex acquisition (P-4)

The `:wip` label is the lock for an `(object, agent)` pair. Acquisition
follows a claim+verify protocol to prevent double-triggering in
multi-runner deployments:

```
1. Read current labels.
2. If any {agent}:{status} label is present → abort (another runner got there).
3. Apply {agent}:wip.
4. Post a claim comment:
   <!-- ai-agile/claim/v1 -->
   {"runner": "{runner_id}", "agent": "{agent}", "item": {number}, "at": "{iso8601}"}
5. Wait 2 seconds (GitHub comment list consistency window).
6. Re-read claim comments on the work item.
7. Find the claim with the lowest GitHub comment ID — that is the winner.
8. If our comment ID is not the lowest:
   → remove {agent}:wip, delete our claim comment, abort.
9. If our comment ID is the lowest → we hold the lock; proceed.
```

The 2-second wait in step 5 is the documented lower bound for GitHub's
comment list eventual consistency. The claim comment is deleted at the end
of the agent run (winning claim) or immediately on loss (step 8). This
keeps the issue comment history clean.

**Stale lock reclaim.** A `:wip` label older than the configured agent
timeout (default 30 minutes, set per agent in `pipeline.json` via
`max_wall_seconds`) is forcibly reclaimed by the orchestrator on its next
scheduled tick. Reclaim: remove `:wip`, apply `:failed`, post a recovery
comment, emit `agent.failed` to the audit log.

---

## Agent invocation

Once the mutex is held, the orchestrator invokes the agent as a subprocess:

```bash
claude \
  --allowedTools "Bash(git *),Bash(gh *),Bash(bash .github/scripts/status.sh *),Read,Glob,Grep" \
  --max-turns 60 \
  -p "<system prompt>"
```

The system prompt injected by the orchestrator provides:

- The agent's name and the path to its prompt file
  (`.github/agents/{agent}.md`)
- The work item type, number, title, and URL
- The set of `status.sh` commands the agent uses for label
  transitions: `set-wip`, `set-complete`, `set-review`, `set-blocked`.
  `set-failed` is **not** in the agent's allowlist — only the
  orchestrator applies `:failed`, when the agent exits non-zero
  without one of the three terminal calls above.
- The constraint: "call exactly one terminal status command
  (set-complete, set-review, or set-blocked) before exiting"

Agents use `status.sh` for every label write. They never call the GitHub
API directly for status transitions. This keeps the transition logic in one
auditable place.

The Claude CLI subprocess inherits `GITHUB_TOKEN` and `ANTHROPIC_API_KEY`
from the orchestrator's environment. Per-agent tool restrictions are
enforced via `--allowedTools`.

**Timeout.** Each agent has a `max_wall_seconds` field in `pipeline.json`
(default 1800 / 30 minutes). `subprocess.run` enforces this via its
`timeout` parameter. On timeout, the orchestrator applies `:failed` and
posts a recovery comment.

---

## Post-run handling

After the agent subprocess exits, the orchestrator:

```
refresh labels from GitHub API

if agent exited non-zero AND no terminal status set:
    apply {agent}:failed
    post recovery comment (what to remove, what to skip)
    emit agent.failed to audit log
    break item loop (halt further agents on this item)

if final_status == complete AND agent has human_gate_after:
    post gate prompt comment: "Apply {gate_label} to advance"
    emit agent.complete to audit log

if final_status == review:
    # pipeline halted; gate promotion watches for the gate label
    emit agent.review to audit log
    break item loop

if final_status in {blocked, failed}:
    emit agent.blocked / agent.failed to audit log
    break item loop
```

---

## Gate promotion

When a human applies a gate label (e.g., `prd:approved`), the orchestrator
must transition the gated agent from `:review` to `:complete`. This is a
separate concern from agent invocation and runs on every tick regardless of
whether an agent was invoked.

```
for each agent_def with human_gate_after=true:
    if {agent}:review ∈ labels AND agent_def.human_gate_label ∈ labels:
        # Gate has been applied while agent was in :review state
        remove {agent}:review
        apply {agent}:complete
        emit gate.approved + agent.complete to audit log
        # Do not break — downstream agents may now be eligible
```

This is the single point where `:review` → `:complete` happens. Humans
never apply `:complete` directly. The promotion is idempotent: if the
orchestrator crashes between removing `:review` and applying `:complete`,
the next tick detects `gate_label ∈ labels` and no `:review` label, finds
`:complete` absent, and completes the transition.

**Partial-state recovery rule.** The orchestrator checks for this partial
state on every tick:

```
if agent_def.human_gate_label ∈ labels
AND {agent}:review ∉ labels
AND {agent}:complete ∉ labels:
    → apply {agent}:complete (finish interrupted transition)
    → emit agent.complete to audit log
```

---

## Audit log emission

Every status transition emits one event to the `ai-agile/log` orphan
branch (P-3). Events are written as JSONL appended to
`events/{YYYY}/{MM}/{DD}.jsonl` and batched into one commit per day.

The orchestrator is the **only writer** to the audit log branch. Agents do
not write to it. Events emitted by the orchestrator:

| Event type | Emitted when |
|---|---|
| `agent.invoked` | Orchestrator acquired mutex and launched the subprocess |
| `agent.complete` | Agent called `set-complete` or gate promotion completed |
| `agent.review` | Agent called `set-review` |
| `agent.blocked` | Agent called `set-blocked` |
| `agent.failed` | Agent crashed or timed out; `:failed` applied |
| `gate.approved` | Human applied the gate label; gate promotion about to run |
| `lock.reclaimed` | Stale `:wip` was force-reclaimed |

Each event carries: `session_id`, `event`, `actor.kind` (human or agent),
`actor.login`, `object.kind`, `object.number`, `agent`, `timestamp`,
and `outcome.detail` (bounded length, redacted of secrets).

---

## GitHub Actions workflows

The orchestrator is hosted entirely in GitHub Actions. There are four
workflows with distinct triggers; they all call the same Python script.

### Overview

| Workflow file | Trigger | `--issue` arg | Purpose |
|---|---|---|---|
| `orchestrator-label.yml` | `issues: [labeled, unlabeled]`  `pull_request: [labeled, unlabeled]` | Event item number | Primary advance trigger — fires immediately when a label changes |
| `orchestrator-pr.yml` | `pull_request: [opened, synchronize, ready_for_review, closed]` | PR number | Advance PR-side agents on PR lifecycle events |
| `orchestrator-schedule.yml` | `schedule: */15 6-20 * * 1-5` | _(none — scans all)_ | Backstop reconciler — catches anything the event triggers missed |
| `orchestrator-dispatch.yml` | `workflow_dispatch` | Optional (default: all) | Manual trigger for debugging, dry-run, or single-item reprocessing |

All four share the same job definition; the only differences are the
trigger block and the `--issue` argument construction.

---

### `orchestrator-label.yml`

Fires immediately when any label is added or removed on an issue or PR.
This is the primary pipeline-advance trigger for the per-ticket flow.

```yaml
name: Orchestrator — Label event

on:
  issues:
    types: [labeled, unlabeled]
  pull_request:
    types: [labeled, unlabeled]

permissions:
  contents: write          # audit log branch appends
  issues: write
  pull-requests: write

concurrency:
  group: orchestrator-${{ github.event.issue.number || github.event.pull_request.number }}
  cancel-in-progress: false  # never cancel a running orchestrator for the same item

jobs:
  orchestrate:
    name: Evaluate pipeline state
    runs-on: ubuntu-latest
    timeout-minutes: 120

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # needed for audit log branch operations

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install requests

      - name: Install Claude Code CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Run orchestrator
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python ai-agile/pipeline/pipeline_orchestrator.py \
            --repo "$GITHUB_REPOSITORY" \
            --issue ${{ github.event.issue.number || github.event.pull_request.number }}
```

**Why `cancel-in-progress: false`.** Two label events can fire within
seconds (e.g., human applies gate label; orchestrator immediately promotes
the agent and applies `:complete`, firing a second event). Cancelling the
second run would skip the promotion step. The concurrency key serialises
runs for the same work item; it never cancels a run already in progress.

---

### `orchestrator-pr.yml`

Fires on PR lifecycle events that are not label changes: opened (draft PR
opened by `coder`), synchronize (new commits), ready_for_review, and
closed (for audit log purposes).

```yaml
name: Orchestrator — PR lifecycle event

on:
  pull_request:
    types: [opened, synchronize, ready_for_review, closed]

permissions:
  contents: write
  issues: write
  pull-requests: write

concurrency:
  group: orchestrator-pr-${{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  orchestrate:
    name: Evaluate pipeline state on PR event
    runs-on: ubuntu-latest
    timeout-minutes: 120

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install requests

      - name: Install Claude Code CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Map PR event to trigger name
        id: event
        run: |
          case "${{ github.event.action }}" in
            opened)          echo "trigger=pr.draft_opened" >> $GITHUB_OUTPUT ;;
            synchronize)     echo "trigger=pr.draft_synchronized" >> $GITHUB_OUTPUT ;;
            ready_for_review) echo "trigger=pr.draft_ready" >> $GITHUB_OUTPUT ;;
            closed)          echo "trigger=pr.closed" >> $GITHUB_OUTPUT ;;
          esac

      - name: Run orchestrator
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          PIPELINE_TRIGGER: ${{ steps.event.outputs.trigger }}
        run: |
          python ai-agile/pipeline/pipeline_orchestrator.py \
            --repo "$GITHUB_REPOSITORY" \
            --issue ${{ github.event.pull_request.number }} \
            --trigger "$PIPELINE_TRIGGER"
```

The `--trigger` argument passes the semantic event name into the
orchestrator so it can evaluate trigger conditions of the form
`{event: "pr.draft_opened"}` against the actual event rather than always
treating event triggers as satisfied.

---

### `orchestrator-schedule.yml`

The scheduled reconciler. Runs every 15 minutes on weekdays during working
hours (06:00–20:00 UTC). It is the backstop for:

- Webhook drops (GitHub guarantees at-least-once delivery, not exactly-once)
- Stale lock reclaim (`:wip` labels that have exceeded `max_wall_seconds`)
- Gate promotions that missed their label event (rare but possible on
  flaky webhook delivery)
- Partial-state recovery (interrupted `:review` → `:complete` transitions)

```yaml
name: Orchestrator — Scheduled reconciler

on:
  schedule:
    - cron: '*/15 6-20 * * 1-5'   # every 15 min, Mon–Fri, 06:00–20:00 UTC

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  reconcile:
    name: Reconcile all open work items
    runs-on: ubuntu-latest
    timeout-minutes: 120

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install requests

      - name: Install Claude Code CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Run orchestrator (full scan)
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python ai-agile/pipeline/pipeline_orchestrator.py \
            --repo "$GITHUB_REPOSITORY" \
            --reconcile    # scan all open items; also run stale-lock reclaim
```

The `--reconcile` flag enables stale-lock reclaim (normally off on
single-item runs to avoid touching items the current event didn't touch).

---

### `orchestrator-dispatch.yml`

Manual trigger for debugging and operational intervention.

```yaml
name: Orchestrator — Manual dispatch

on:
  workflow_dispatch:
    inputs:
      issue_number:
        description: 'Issue or PR number (blank = all open items)'
        required: false
      dry_run:
        description: 'Dry run — log what would trigger without executing'
        type: boolean
        default: false
      verbose:
        description: 'Verbose logging'
        type: boolean
        default: false

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  dispatch:
    name: Manual orchestrator run
    runs-on: ubuntu-latest
    timeout-minutes: 120

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install requests

      - name: Install Claude Code CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Build args
        id: args
        run: |
          ARGS=""
          [ -n "${{ github.event.inputs.issue_number }}" ] && ARGS="$ARGS --issue ${{ github.event.inputs.issue_number }}"
          [ "${{ github.event.inputs.dry_run }}" = "true" ]  && ARGS="$ARGS --dry-run"
          [ "${{ github.event.inputs.verbose }}" = "true" ]  && ARGS="$ARGS --verbose"
          echo "args=$ARGS" >> "$GITHUB_OUTPUT"

      - name: Run orchestrator
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python ai-agile/pipeline/pipeline_orchestrator.py \
            --repo "$GITHUB_REPOSITORY" \
            ${{ steps.args.outputs.args }}
```

---

## CLI reference

```
python pipeline_orchestrator.py [options]

Options:
  --repo OWNER/REPO     GitHub repository (default: $GITHUB_REPOSITORY)
  --issue N             Process only issue/PR number N (default: all open items)
  --kind {issue,pr}     With --issue, declares whether the number is an issue or PR
                        (orchestrator probes the API if omitted)
  --trigger EVENT       Semantic event name, e.g. pr.draft_opened (default: none)
  --reconcile           Run stale-lock reclaim pass in addition to eligibility check
  --dry-run             Log decisions without invoking agents or changing labels
  --clear-pause         Clear the rate-limit pause marker if set, then exit
                        (manual override for operators; see "Anthropic API"
                        in Rate limit handling)
  --pipeline PATH       Path to pipeline.json (default: ai-agile/pipeline/pipeline.json)
  --verbose, -v         Debug-level output
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | Yes | GitHub token with `issues:write` and `pull-requests:write` |
| `GITHUB_REPOSITORY` | Yes | `owner/repo` — set automatically by GitHub Actions |
| `ANTHROPIC_API_KEY` | Yes (to invoke agents) | Passed to the Claude CLI subprocess |
| `GH_TOKEN` | No (fallback) | Fallback if `GITHUB_TOKEN` is not set; used by `gh` CLI inside agents |
| `PIPELINE_TRIGGER` | No | Semantic event name forwarded from the Actions workflow |

---

## Concurrency model

**Cross-issue parallelism.** Different work items have independent concurrency
groups in GitHub Actions. Two issues can advance simultaneously with no
coordination required. The mutex (`:wip`) is per `(object, agent)`, not
global.

**Intra-item serialisation.** Each workflow run uses a concurrency group
keyed to the work item number with `cancel-in-progress: false`. GitHub
Actions queues subsequent runs rather than dropping them. This means if a
label event fires while a previous run is still processing the same item,
the second run waits and then re-evaluates from the current label state
(which will already reflect the first run's outcome). There is no
double-triggering.

**Multi-runner safety.** If two orchestrator processes do somehow start
for the same `(item, agent)` simultaneously (e.g., two scheduled ticks
overlap), the claim+verify mutex protocol (step 4–9 above) ensures only one
proceeds. The loser aborts cleanly.

---

## Rate limit handling

Two upstream rate limits matter to the orchestrator: the GitHub REST
API and the Anthropic API. They are handled differently because they
fail differently.

### GitHub REST API

The GitHub REST API has a 5000-request-per-hour authenticated rate
limit. Exhaustion is rare (the orchestrator's per-tick API budget is
tens of requests, not thousands), but the client mitigates with:

- **ETag caching.** Label reads use `If-None-Match` headers; a 304 Not
  Modified response does not count toward the core rate limit.
- **Per-item pause.** A 2-second sleep between agent invocations on
  different items reduces burst.
- **Exponential backoff.** On 429 or 5xx responses, the client retries
  up to 4 times with delays of 2 s, 4 s, 8 s, 16 s before failing.
- **Dry-run for audits.** `--dry-run` reads labels but does not write
  anything; useful for rate-limit-safe inspection.

### Anthropic API

The Claude CLI subprocess invokes the Anthropic API once per agent
run, consuming token quota. Exhaustion is much more likely than
GitHub-side exhaustion because token-per-minute and daily-token limits
are smaller relative to typical agent payloads. The orchestrator
treats Anthropic rate-limit errors as a **system-wide pause**, not a
per-agent failure.

**Why pause, not retry-and-fail.** A rate-limit hit at 09:00 means the
next 4 scheduled ticks (every 15 minutes) plus every label-event tick
will all fail the same way, burning more quota and producing
`:failed` labels on every active item. Pausing instead lets the
window naturally clear and lets the next tick resume with no
intervention.

**Detection.** After every agent subprocess exits non-zero, the
orchestrator scans the captured stdout/stderr for indicators:

| Pattern | Source |
|---|---|
| `rate_limit_error` | Anthropic SDK error class |
| `\b429\b` | HTTP status |
| `usage limit` / `quota (exceeded\|exhausted)` | quota messaging |
| `tokens? per minute` / `daily token limit` | Anthropic-specific phrasing |
| `too many requests` | HTTP status text |
| `overloaded_error` | Anthropic SDK error class for capacity overload |

If any indicator matches, the orchestrator parses an optional
`retry-after`, `retry after Ns`, or `wait N seconds` value from the
same output. If found, the value is honoured (capped at 1 hour). If
not found, a default of 5 minutes is used.

**Pause mechanism.** The orchestrator writes a JSON pause marker to
`.pipeline-pause` at the submodule root:

```json
{
  "until": "2026-05-05T21:57:00.533Z",
  "reason": "Anthropic API rate limit while invoking issue-classifier on issue #42",
  "paused_at": "2026-05-05T21:55:38.380Z",
  "seconds": 300
}
```

The marker is **runner-local** (gitignored). For multi-runner
deployments the marker would need to live in GitHub state instead;
that is out of MVP scope.

**Pause behaviour on subsequent ticks.** Every run, before doing any
other work, the orchestrator calls `is_pipeline_paused()`:

- If the marker is missing or expired → proceed normally; expired
  markers are auto-removed.
- If the marker is active → log `Pipeline is paused until <time> — <reason>` and
  exit 0.

The orchestrator does **not** apply `:failed` to the agent that
triggered the rate limit — the agent never got a fair run, so
treating it as a logic failure would force a human to remove labels
to retry later. Instead, on the next tick after the pause expires the
orchestrator sees the agent in its prior state (no terminal label
applied) and re-invokes it normally.

**Manual override.** Operators can clear the pause without waiting:

```bash
python ai-agile/pipeline/pipeline_orchestrator.py --clear-pause
```

This deletes the marker file and exits. The next scheduled or
event-driven tick proceeds as if no pause had been set.

**Constants** (in `pipeline_orchestrator.py`, configurable if needed):

| Constant | Default | Meaning |
|---|---|---|
| `DEFAULT_PAUSE_SECONDS` | `300` (5 min) | Used when the API does not name a retry-after |
| `MAX_PAUSE_SECONDS` | `3600` (1 h) | Cap on any retry-after honoured from the API |

---

## Secrets required

| Secret | Used by | Description |
|---|---|---|
| `GITHUB_TOKEN` | Orchestrator | Auto-provisioned by Actions; scoped to the repo and workflow run |
| `ANTHROPIC_API_KEY` | Orchestrator → Claude CLI | Required for agent invocations; store as an Actions repository or org secret |

The `GITHUB_TOKEN` auto-provisioned by Actions has the scopes declared in
each workflow's `permissions` block. No PAT is needed for the orchestrator
itself. A dedicated GitHub App token is required before any production
compliance claim (see [`10-roadmap.md`](10-roadmap.md) — agent identity
prerequisite).
