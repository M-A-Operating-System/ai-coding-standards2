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
| PR ready-for-review | Call `gh pr ready` when an agent with `git_ops.mark_ready_on_complete: true` completes — agents never do this themselves |
| Git commit + push | Stage, commit, and push agent file changes to `issue-{N}` after any `commit_after: true` agent signals `complete` |
| Audit log emission | Emit one JSONL event per transition to stdout |

It owns none of these:

- Agent behaviour (prompts, tools, model — those live in `.claude/agents/{agent}.md`)
- Standards checking (the `standards-compliance-reviewer` agent does this)
- Pipeline graph definition (`pipeline.json` is the source of truth; the orchestrator reads it)

---

## Source location

```
pipeline/
  pipeline_orchestrator.py     ← the orchestrator
  pipeline.json                ← the dependency graph it reads
  schemas/
    pipeline.schema.json
  generators/
    generate_docs.py
    generate_pipeline_mermaid.py
```

The GitHub Actions workflow that invokes it lives at:

```
.github/workflows/
  orchestrator.yml    ← single workflow handling all triggers
```

---

## Inputs

| Input | Source | How used |
|---|---|---|
| `pipeline.json` | Repo file | Loaded once per run; defines agent graph, dependencies, triggers, and gates |
| GitHub labels on the work item | GitHub REST API | Determines current agent statuses and which gate labels are present |
| `priority` label on issues | GitHub REST API | When present on an open issue, that issue is selected ahead of non-priority issues in the work item iteration order |
| GitHub event payload | Actions `GITHUB_EVENT_PATH` | Narrows which work item to process; identifies the triggering event type |
| `GITHUB_TOKEN` | Actions secret | Authenticates all GitHub API calls; must have `issues:write` and `pull-requests:write` |
| `ANTHROPIC_API_KEY` | Actions secret | Passed through to the Claude CLI when invoking agents |
| `GITHUB_REPOSITORY` | Actions env | `owner/repo` string; used in all API paths |
| Agent prompt files | `.claude/agents/{agent}.md` | Passed by path reference to the Claude CLI; the orchestrator does not read their content |

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
| Audit log JSONL event | Print to stdout | Once per status transition, agent run, or gate approval |
| Git commit + push | `git` subprocess | After an agent signals `complete` (`git_ops.commit_after: true`) |
| PR push (existing branch, Mode B) | `git` subprocess | After a code-writing agent addresses review feedback |

---

## Decision loop

On every invocation, the orchestrator runs the same loop:

Work items are evaluated in two passes: open issues carrying the `priority`
label are iterated first, then all remaining open work items. Within each
pass the per-agent logic is identical. This means a `priority`-labeled issue
will receive the next available `:wip` slot before any non-priority issue,
while the existing concurrency limits apply unchanged to both passes.

```
# Pass 1: priority-labeled issues; Pass 2: all other work items
for each work item (issue or PR), priority-labeled issues first:
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

        if running_count(agent_def.agent) >= agent_def.max_concurrent:
            skip                          ← per-agent concurrency ceiling reached

        if tick_launch_count >= PIPELINE_MAX_CONCURRENT:
            skip                          ← aggregate pipeline ceiling reached for this tick

        ← step is eligible
        acquire_mutex(work_item, agent_def)
        # Pre-invocation ceremony
        apply {agent}:wip
        post opening announcement comment
        # invoke — script steps handle their own git/PR operations
        if agent_def.type == "script":
            success = invoke_script(work_item, agent_def)
        else:
            success = invoke_agent(work_item, agent_def)
        parse AI_AGILE_STATUS: sentinel from stream-json event stream
        # Post-completion git operations for agent steps
        if sentinel == complete AND agent_def.git_ops.commit_after:
            commit_and_push(work_item, agent_def)   ← see "Code commit and PR lifecycle"
        apply matching terminal label; remove :wip
        post closing announcement comment
        handle_outcome(work_item, agent_def, success, labels)

        if agent_outcome in {review, blocked, failed}:
            break                         ← halt this item; no further agents this run
```

The loop is **deterministic**: given identical inputs (labels + `pipeline.json`)
it always produces the same decision. There is no randomness, no LLM call.
The only external writes are the mutex label and the audit log event.

Agent steps are re-invoked up to `max_retries` times (configured per agent in
`pipeline.json`) with exponential backoff (5 s, 10 s, 20 s…) when the agent
exits non-zero without a sentinel. On each retry, the orchestrator posts a
comment on the work item recording the attempt number so operators can audit
the retry history. When the retry limit is exhausted, the orchestrator applies
`:failed` and posts a comment stating the limit has been reached and human
intervention is required. An agent that succeeds after one or more retries
receives the normal success label — no retry count is retained or displayed in
the final state. Script steps are not retried.

---

## Eligibility check

An agent is eligible to run when all six conditions hold simultaneously:

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

**5. Per-agent concurrency ceiling not reached.**
The count of all open issues that currently carry `{agent}:wip` (instances
running from a prior tick) is less than `agent_def.max_concurrent` (default 1
when the field is absent). When the ceiling is already reached, all remaining
eligible issues for that agent are deferred to the next tick.

**6. Aggregate pipeline ceiling not reached.**
The total number of agent instances launched in the current tick is less than
the pipeline-wide maximum (see `PIPELINE_MAX_CONCURRENT` in `pipeline/pipeline_orchestrator.py` for the authoritative value). If this ceiling is reached, all
remaining eligible work across all agent types is deferred to the next tick.

---

## Mutex acquisition (P-4)

The `:wip` label is the lock for an `(object, agent)` pair. Acquisition
uses the in-memory label snapshot combined with the GitHub Actions
concurrency group to ensure at-most-one invocation:

```
1. At run start, read ALL labels for the work item from GitHub into an
   in-memory set (one API call per item, not per agent).
2. For each agent in declaration order:
   a. Check the in-memory set: if any {agent}:{status} label is present
      → skip (already running or terminal).
   b. Apply {agent}:wip via GitHub API.
   c. Immediately add {agent}:wip to the in-memory set.
      (So the next agent in the same run sees the updated state without
       a round-trip to GitHub.)
   d. Invoke the agent subprocess.
   e. On completion, apply the terminal label and remove {agent}:wip from
      GitHub API and from the in-memory set.
```

**Why this is safe.** A single GitHub Actions concurrency group
(`pipeline-orchestrator`) serialises all orchestrator runs. GitHub
queues a second triggered run rather than starting it in parallel.
The second run, when it eventually starts, reads the current settled
label state and sees the `:wip` label from the first run — so it
correctly skips the already-running agent. See
[Race condition and concurrency management](#race-condition-and-concurrency-management)
below for the full analysis.

**Stale lock reclaim.** A `:wip` label older than the configured agent
timeout (default 30 minutes, set per agent in `pipeline.json` via
`max_wall_seconds`) is forcibly reclaimed by the orchestrator on its next
scheduled tick. Reclaim: remove `:wip`, apply `:failed`, post a recovery
comment, emit `agent.failed` to the audit log.

---

## Step invocation

The orchestrator supports two invocation modes, selected by the `"type"` field
in `pipeline.json` (default: `"agent"`).

### Agent steps (`type: "agent"`)

The orchestrator invokes the Claude CLI as a subprocess:

```bash
claude \
  --allowedTools "Bash(gh issue view *),Bash(gh issue comment *),Bash(gh issue edit *),Bash(gh issue list *),Bash(gh pr view *),Bash(gh pr comment *),Bash(gh pr edit *),Bash(gh pr list *),Bash(gh pr diff *),Bash(gh api repos/*/issues/*),Bash(gh api repos/*/pulls/*),Bash(cat *),Bash(grep *),Bash(find *),Read,Glob,Grep" \
  --output-format stream-json \
  --max-turns 60 \
  -p "<system prompt>"
```

The tools listed above are the base allowlist applied to every agent. Per-agent tools are added via the `extra_allowedTools` frontmatter field in the agent's `.claude/agents/` prompt file.

The system prompt injected by the orchestrator provides:

- The agent's name and the path to its prompt file
  (`.claude/agents/{agent}.md`)
- The work item type, number, title, and URL
- The sentinel format agents use to signal their terminal state:
  `AI_AGILE_STATUS: complete`, `AI_AGILE_STATUS: review`, or
  `AI_AGILE_STATUS: blocked`, emitted as the last line of stdout.
  `:failed` is **not** a sentinel — the orchestrator applies `:failed`
  when the agent exits non-zero without one of the three sentinel values.

Agents signal status via stdout sentinel only. They never call the GitHub
API directly for label writes. The orchestrator reads the sentinel and
applies the matching label — keeping the transition logic in one
auditable place.

The Claude CLI subprocess inherits `GITHUB_TOKEN` and `ANTHROPIC_API_KEY`
from the orchestrator's environment. Per-agent tool restrictions are
enforced via `--allowedTools`.

**Timeout.** Default 1800 seconds (30 minutes). On timeout, the orchestrator
applies `:failed` and posts a recovery comment.

### Script steps (`type: "script"`)

The orchestrator invokes a bash script directly, without the Claude CLI. Use
script steps for deterministic tasks that need no reasoning.

```bash
bash .github/scripts/{script-name}.sh
```

Key differences from agent steps:

| | Agent step | Script step |
|---|---|---|
| `:wip` ownership | Orchestrator applies `:wip` before invoking | Orchestrator applies `:wip` before invoking |
| Status signalling | Agent emits `AI_AGILE_STATUS:` to stdout | Script emits `AI_AGILE_STATUS:` to stdout |
| Label write | Orchestrator reads sentinel → applies label | Orchestrator reads sentinel → applies label |
| Rate limiting | Anthropic API calls possible | No Anthropic API; rate limiting not applicable |
| Timeout | 1800 s (30 min) | 300 s (5 min) |

The script receives the same environment variables as agents: `$REPO`,
`$ISSUE_NUMBER` (or `$PR_NUMBER`), `$WORK_ITEM_KIND`, `$WORK_ITEM_NUMBER`,
`$AI_AGILE_ROOT`, `$GITHUB_TOKEN`.

**Sentinel parsing.** The orchestrator searches only the last 5 lines of the
script's stdout for the sentinel, preventing crafted content in an issue body
(echoed earlier) from spoofing the signal:

```
AI_AGILE_STATUS: complete
AI_AGILE_STATUS: review "short message"
AI_AGILE_STATUS: blocked "reason"
```

If the script exits non-zero without a sentinel, the orchestrator applies
`:failed` identically to a crashed agent.

---

## Post-run handling

After the subprocess exits, the orchestrator handles the outcome differently
depending on the step type:

**Agent steps** — the orchestrator reads the sentinel and applies the label:
```
parse AI_AGILE_STATUS: from stream-json event stream text events
extract token usage (input_tokens, output_tokens) from stream-json result event

if sentinel found:
    remove :wip, apply matching label ({agent}:complete / :review / :blocked)
elif agent exited zero (no sentinel):
    remove :wip, apply :complete   ← backward-compat default
else (exited non-zero, no sentinel):
    remove :wip, apply :failed
    post recovery comment
    emit agent.failed (mode=agent) to audit log
    break item loop
```

**Script steps** — the orchestrator reads the sentinel and applies the label:
```
parse AI_AGILE_STATUS: from last 5 lines of stdout

if sentinel found:
    remove :wip, apply matching label ({agent}:complete / :review / :blocked)
elif script exited non-zero (no sentinel):
    remove :wip, apply :failed
    post recovery comment
    emit agent.failed (mode=script) to audit log
    break item loop
else (exited 0, no sentinel):
    remove :wip, apply :complete   ← backward-compat default
```

**Common path** (both step types, after labels are resolved):
```
refresh labels from GitHub API

if final_status == complete:
    emit agent.complete to audit log
    # complete + human_gate_after does NOT post a gate prompt — the agent
    # chose complete meaning "automated path, no human needed this cycle"
    if git_ops.mark_ready_on_complete == true AND work_item is a PR:
        call `gh pr ready {number}`

if final_status == review AND step has human_gate_after:
    post gate prompt comment: "Apply {gate_label} to advance"
    emit agent.review to audit log
    break item loop   ← halt until human applies gate

if final_status == review AND NOT step has human_gate_after:
    emit agent.review to audit log
    break item loop   ← halted (unusual; treat like blocked)

if final_status in {blocked, failed}:
    emit agent.blocked / agent.failed to audit log
    break item loop
```

**Gate promotion** (separate pass, runs every tick):
```
for each agent_def with human_gate_after=true:
    if {agent}:review ∈ labels AND agent_def.human_gate_label ∈ labels:
        remove {agent}:review
        apply {agent}:complete
        emit gate.approved + agent.complete to audit log
```

---

## Code commit and PR lifecycle

Some agents write files but cannot run git or create PRs — by design. The
orchestrator commits and pushes their file changes after they signal
`complete`. Branch creation and PR opening are handled by the dedicated
`create-pr` script step, not by individual agents. The `git_ops` object
controls the post-completion commit behaviour:

```json
"git_ops": {
  "commit_after": true      ← stage + commit + push after agent signals complete
}
```

Note: the branch name is fixed as `issue-{N}` — this is hardcoded in the
orchestrator and is not configurable via `git_ops`.

If `git_ops` is absent or `commit_after` is `false`, no git operations run.

### Branch and PR creation — `create-pr` script step

The `create-pr` pipeline step (`.github/scripts/create-pr.sh`) runs as a
dedicated script after the PRD is approved, before any docs or code agent
runs. It:

1. Creates branch `issue-{N}` from the default branch HEAD (if absent)
2. Opens a draft PR: title `issue-{N}: {title[:60]}`, body `Closes #{N}`
3. Calls `link-pr-to-issue.sh` to apply the `source-issue:{N}` label
4. Posts a comment on the issue with the PR number and URL, so stakeholders
   and engineers can navigate to the draft PR directly from the issue without
   consulting build logs. This comment is posted only once — on idempotent
   re-runs where the PR already exists, no duplicate comment is posted.

Both the branch and the PR exist before `prd-docs-updater` is invoked, so
all subsequent agent commits accumulate in the already-open PR.

### Pre-agent branch checkout (commit_after agents only)

For agents with `commit_after: true` working on an issue, the orchestrator
checks out the issue branch **before** invoking the agent so it sees the
accumulated state (docs from `prd-docs-updater`, code from a prior coder run,
etc.). This is a read-only pre-condition — the agent writes into the working
tree and the orchestrator commits those changes afterwards.

**Agent definition snapshot**: the orchestrator reads the agent's `.md` file
(frontmatter for `extra_allowedTools`, `model`, `max_turns`; body for the
prompt) **before** the branch checkout. This snapshot is passed into the agent
invocation unchanged. As a result, agent definitions always reflect the
**orchestrator's branch** (typically `main`), not whatever version of the file
happens to be on the issue branch. This means a fix to an agent file merged to
`main` takes effect on the next invocation even if the issue branch predates
the fix.

### Mode — Agent commit (PR already exists)

After any `commit_after: true` agent signals `AI_AGILE_STATUS: complete`,
the orchestrator commits the agent's file changes to the existing branch:

```
1. Check:    git status --porcelain → if empty, skip (no working-tree changes)
2. Config:   git config user.email / user.name
3. Stash:    git stash push --include-untracked  (saves agent's file changes)
4. Fetch:    git fetch origin issue-{N}
5. Checkout: git checkout -B issue-{N} origin/issue-{N}  (reset to remote tip)
6. Pop:      git stash pop  (applies agent changes onto issue-{N})
7. Stage:    git add -A
8. Guard:    git diff --cached --quiet → if empty, skip commit
9. Commit:   git commit -m "{phase_prefix}: {label_key} changes for issue #{N}"
             (phase_prefix: "docs" for 01/02 phases, "feat" for 03_execute,
              "chore" otherwise)
10. Push:    git push origin issue-{N}
11. Restore: git checkout {original_branch}  (called at all exit points)
```

Step 1 prevents unnecessary stash/checkout work when an agent writes no
files. Step 8 guards against committing an empty staging area after a pop
that produced no diff. The `finally` block in step 11 ensures the runner
workspace is always restored to the original branch regardless of failures.

### Mode B — Address review feedback (coder re-invocation)

After the coder is re-triggered to address reviewer feedback, the same
`commit_after: true` path used for Mode A applies. The coder writes
files; the orchestrator stages, commits, and pushes those changes to
the existing `issue-{N}` branch after the agent signals `complete`. No
new PR or new branch is created for re-invocations. The orchestrator
then re-applies `pr-reviewer:requested` to the PR to trigger another
review cycle.

**What the coder receives on re-invocation.** The coder reads both the
`pr-reviewer`'s structured finding list and any unresolved human
`REQUEST_CHANGES` review comments on the PR. Both sources are surfaced
together so the coder addresses them in one pass.

**Automated vs. human re-invocation triggers.** Two distinct conditions
can trigger a Mode B re-invocation:

| Trigger | Counts toward `max_cycles`? | Notes |
|---|---|---|
| `pr-reviewer` emits `REQUEST_CHANGES` | Yes | Standard automated quality loop |
| Human posts `REQUEST_CHANGES` review; `pr-reviewer` issues APPROVE | **No** | Free re-invoke; ci-gate and `pr-reviewer` run again afterward |

For the human-triggered edge case: when the `pr-reviewer` completes
with APPROVE but one or more human `REQUEST_CHANGES` reviews remain
open (from non-bot GitHub accounts), the orchestrator does **not** mark
the PR ready. Instead it re-invokes the coder once to address the human
feedback. Bot accounts (`user.type == "Bot"`) are excluded — only
human GitHub accounts count as blocking human reviews.

### Environment variables injected before coder invocation

The orchestrator sets these in the agent subprocess environment so the
coder can read its own context without git or gh calls:

| Variable | Set in | Value |
|---|---|---|
| `$ISSUE_NUMBER` | Both modes | The issue number being implemented |
| `$PR_NUMBER` | Mode B only | The existing PR number; absent in Mode A |
| `$SESSION_ID` | Both modes | Stable ID for this issue's pipeline session |
| `$REPO` | Both modes | `owner/repo` string |

The presence of `$PR_NUMBER` is the Mode A / Mode B switch — agents check
`if [ -n "${PR_NUMBER:-}" ]` at the start of their run.

### Failure handling

If any git operation fails (e.g., merge conflict, push rejected):

1. The orchestrator does **not** apply `:complete`.
2. It applies `{agent}:failed` and posts a recovery comment explaining
   which git step failed and the error output.
3. A human resolves the conflict and removes the `:failed` label to
   allow retry.

The coder's file changes remain on disk in the Actions runner workspace
for inspection, but are not committed to any branch.

---

## Gate promotion

When a human applies a gate label (e.g., `01_product_docs/prd-writer:approved`), the orchestrator
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

Every status transition emits one JSON line to stdout. GitHub Actions
captures stdout natively; the run log is the persistent record. See
[`08-audit-log.md`](08-audit-log.md) for the full schema and how to
query the log.

Events emitted by the orchestrator:

| Event type | Emitted when |
|---|---|
| `agent.invoked` | Orchestrator acquired mutex and launched the subprocess |
| `agent.complete` | Agent emitted `AI_AGILE_STATUS: complete` or gate promotion completed |
| `agent.review` | Agent emitted `AI_AGILE_STATUS: review` |
| `agent.blocked` | Agent emitted `AI_AGILE_STATUS: blocked` |
| `agent.failed` | Agent crashed or timed out without a sentinel; `:failed` applied |
| `gate.approved` | Human applied the gate label; gate promotion about to run |
| `lock.reclaimed` | Stale `:wip` was force-reclaimed |
| `system.emergency_stop` | Stop marker detected at run start; orchestrator exited without invoking agents |

Each event carries at minimum: `ts` (ISO-8601), `event`, `agent`,
`issue`, and `status`. For `agent.invoked` and terminal events,
additional fields may include `mode` (`agent` or `script`) so
operators can confirm which invocation mode ran for any given step.

---

## GitHub Actions workflows

The orchestrator is hosted entirely in GitHub Actions. A single workflow
file handles all triggers by combining them under one `on:` block.

### `orchestrator.yml`

`.github/workflows/orchestrator.yml` handles all four trigger categories:

| Trigger | Events | Purpose |
|---|---|---|
| `issues` | `opened`, `reopened`, `labeled`, `unlabeled` | Primary advance trigger for issue-side agents |
| `pull_request` | `opened`, `reopened`, `synchronize`, `ready_for_review`, `labeled`, `unlabeled`, `closed` | Advance PR-side agents on PR lifecycle events |
| `schedule` | `*/15 6-20 * * 1-5` | Backstop reconciler — catches webhook drops, stale locks, partial-state recovery |
| `workflow_dispatch` | _(manual)_ | Debugging, dry-run, or single-item reprocessing |

```yaml
name: Orchestrator

on:
  issues:
    types: [opened, reopened, labeled, unlabeled]
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review, labeled, unlabeled, closed]
  schedule:
    - cron: '*/15 6-20 * * 1-5'   # every 15 min, Mon–Fri, 06:00–20:00 UTC
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
  contents: write          # git commit + push for commit_after agents
  issues: write
  pull-requests: write

# Single global group — all orchestrator runs are serialised.
# A second trigger queues behind the running instance rather than
# starting in parallel, so the second run always reads settled label state.
concurrency:
  group: pipeline-orchestrator
  cancel-in-progress: false

jobs:
  orchestrate:
    name: Evaluate pipeline state
    runs-on: ubuntu-latest
    timeout-minutes: 120

    steps:
      - uses: actions/checkout@v4

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
          if [ -n "${{ github.event.inputs.issue_number }}" ]; then
            ARGS="$ARGS --issue ${{ github.event.inputs.issue_number }}"
          elif [ "${{ github.event_name }}" = "issues" ]; then
            ARGS="$ARGS --issue ${{ github.event.issue.number }} --kind issue"
          elif [ "${{ github.event_name }}" = "pull_request" ]; then
            ARGS="$ARGS --issue ${{ github.event.pull_request.number }} --kind pr"
          fi
          [ "${{ github.event.inputs.dry_run }}" = "true" ] && ARGS="$ARGS --dry-run"
          echo "args=$ARGS" >> "$GITHUB_OUTPUT"

      - name: Run orchestrator
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GIT_TRACE: "1"
        run: |
          python pipeline/pipeline_orchestrator.py \
            --repo "$GITHUB_REPOSITORY" \
            --verbose \
            ${{ steps.args.outputs.args }}
```

### `sync-claude.yml`

`.github/workflows/sync-claude.yml` keeps the consuming repo's pipeline
artefacts in sync with the `ai-coding-standards2` submodule. It runs
nightly (and on `workflow_dispatch`) and calls `get_started.py` in sync
mode.

**What it updates:**

| Install function | Destination | Stale-file cleanup |
|---|---|---|
| `install_agents` | `.claude/agents/` | Yes — removes agents no longer in the submodule |
| `install_standards` | `standards/` | No — project-specific standards files are never deleted |
| `install_slash_commands` | `.claude/commands/` | Yes |
| `install_orchestrator_workflow` | `.github/workflows/orchestrator.yml` | No (single file) |
| `install_bootstrap_labels_workflow` | `.github/workflows/bootstrap-labels.yml` | No (single file) |
| `install_label_cleanup_workflow` | `.github/workflows/label-cleanup.yml` | No (single file) |
| `install_sync_workflow` | `.github/workflows/sync-claude.yml` | No (self) |

The sync commit is made by the Actions bot if any files changed. If nothing
changed, the workflow exits without a commit.

**Path rewriting.** Workflow files reference `ai-coding-standards2/` as a
path prefix. `install_*_workflow` functions rewrite these paths to
`{SUBMODULE_NAME}/` so they work regardless of the submodule directory name
the consuming repo chose. `_add_submodules_to_checkout` injects
`submodules: true` into any bare `actions/checkout` step that doesn't
already have a `with:` block.

**Initial setup.** The first time a consuming repo adopts the pipeline,
run `python ai-coding-standards2/get_started.py --force` to install all
artefacts. This is idempotent — re-running it updates without overwriting
local additions (e.g. project-specific standards files not in the submodule).

**Why `cancel-in-progress: false`.** Two label events can fire within
seconds (e.g., human applies gate label; orchestrator immediately promotes
the agent and applies `:complete`, firing a second event). Cancelling the
second run would skip the promotion step. The global concurrency key
serialises all orchestrator runs; it never cancels a run already in progress.

**Scheduled reconciler.** The schedule trigger is the backstop for:

- Webhook drops (GitHub guarantees at-least-once delivery, not exactly-once)
- Stale lock reclaim (`:wip` labels that have exceeded `max_wall_seconds`)
- Gate promotions that missed their label event (rare but possible on
  flaky webhook delivery)
- Partial-state recovery (interrupted `:review` → `:complete` transitions)

### `pipeline-emergency-stop.yml`

`.github/workflows/pipeline-emergency-stop.yml` is a `workflow_dispatch`-only
workflow that halts the pipeline immediately.

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `reason` | string | yes | — | Recorded in the stop marker and shown in the workflow log |
| `cancel_runs` | boolean | no | `true` | Whether to cancel all currently-running orchestrator runs via `gh run cancel` |

On run: cancels in-progress orchestrator runs (if `cancel_runs` is `true`),
writes `.pipeline-stop` to the repo root, and logs how many runs were
cancelled. See [Emergency stop](#emergency-stop) for the marker format and
orchestrator behaviour.

### `pipeline-restart.yml`

`.github/workflows/pipeline-restart.yml` is a `workflow_dispatch`-only
workflow that clears the emergency stop and resumes normal pipeline operation.

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `trigger_run` | boolean | no | `true` | Whether to immediately dispatch a fresh orchestrator run after clearing the marker |

On run: deletes `.pipeline-stop` and, if `trigger_run` is `true`, dispatches
a new orchestrator run so the pipeline resumes without waiting for the next
scheduled tick.

---

## CLI reference

```
python pipeline_orchestrator.py [options]

Options:
  --repo OWNER/REPO     GitHub repository (default: $GITHUB_REPOSITORY)
  --issue N             Process only issue/PR number N (default: all open items)
  --kind {issue,pr}     With --issue, declares whether the number is an issue or PR
                        (orchestrator probes the API if omitted)
  --dry-run             Log decisions without invoking agents or changing labels
  --pipeline PATH       Path to pipeline.json (default: pipeline/pipeline.json)
  --clear-pause         Clear the rate-limit pause marker if set, then exit
                        (manual override for operators; see "Anthropic API"
                        in Rate limit handling)
  --clear-stop          Clear the emergency stop marker if set, then exit
                        (manual override for operators; see "Emergency stop")
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

**Orchestrator-run serialisation.** The global `pipeline-orchestrator`
concurrency group serialises all orchestrator *runs* globally — only one
orchestrator process executes at a time. If a label event fires while a run
is active, GitHub queues the new run; the queued run starts only after the
first completes, at which point labels reflect settled state and already-`:wip`
agents are correctly skipped.

**Per-agent concurrency ceiling.** Within a single orchestrator run, multiple
agent instances of the same type may be launched for different issues, up to
the `max_concurrent` value configured in `pipeline.json` (default: 1 when the
field is absent or null). Before launching an instance, the orchestrator counts
the number of open issues that currently carry `{agent}:wip` — instances
running from a prior tick. It starts at most `max_concurrent − running_count`
additional instances. If the running count already meets or exceeds
`max_concurrent`, no new instances are launched for that tick; eligible issues
remain pending until the next tick.

**Aggregate pipeline ceiling.** A pipeline-wide maximum (see `PIPELINE_MAX_CONCURRENT` in `pipeline/pipeline_orchestrator.py` for the authoritative value) caps
the total number of agent instances launched across all agent types in a
single tick, regardless of per-agent `max_concurrent` values. This prevents
unbounded resource consumption when many agent types each have large backlogs.

**Scheduled reconciler as backstop.** GitHub Actions keeps at most one pending
run per concurrency group. If two label events fire in rapid succession while
a run is active, GitHub keeps the second event's run queued and discards any
further queued runs. The 15-minute cron ensures that a discarded event does
not cause a work item to stall indefinitely — the next scheduled tick
re-evaluates all open items and advances any that became eligible.

---

## Race condition and concurrency management

### What the race condition was

Before a global concurrency group was added, multiple orchestrator runs could
execute in parallel. The sequence that caused duplicate agent invocations:

```
t=0s   Run A starts. Reads labels: no :wip on coder. Coder is eligible.
t=1s   Run A calls gh label add {coder}:wip on GitHub.
t=2s   Applying :wip triggers issues.labeled → GitHub starts Run B.
t=3s   Run A invokes the coder subprocess. Coder begins a 30-minute run.
t=4s   Run B starts. Reads labels from GitHub. The :wip write from t=1s
        has not yet propagated to the API response (GitHub label writes
        have eventual consistency of a few seconds in practice).
t=5s   Run B sees no :wip. Coder is eligible. Run B also invokes coder.
        ↳ Two coder subprocesses now running for the same issue.
```

The result was duplicate "opening announcement" comments on the issue and
two agents writing to the same working tree concurrently.

### Why it only surfaced with the coder

Short agents (issue-classifier, prd-writer) complete in 2–5 minutes. By the
time any label event they fire produces a new orchestrator run, the original
run has already written the `:complete` label and exited. The second run sees
a terminal label and skips. The race window is too small to hit in practice.

The coder runs for 20–40 minutes. During that window many label events fire
(`:wip` apply, human gate labels, PR events). Without the concurrency group,
each event started a new parallel run. Because the `:wip` write that gated
the previous check had been applied seconds earlier, GitHub's eventual
consistency window meant some of those parallel runs did not see it yet —
and double-triggered the agent.

### The fix

```yaml
# .github/workflows/orchestrator.yml
concurrency:
  group: pipeline-orchestrator
  cancel-in-progress: false
```

This single change serialises all orchestrator runs at the GitHub Actions
scheduler level, before any Python code runs. The `:wip` check in the
decision loop is now a fast-path skip (already settled from the prior run)
rather than a race-condition guard.

`cancel-in-progress: false` is essential: cancelling the queued run would
drop label events that need processing (gate promotions, PR synchronise
events). Queuing is correct; cancellation is not.

### Trade-off: global serialisation vs. per-item groups

| Approach | Throughput | Correctness |
|---|---|---|
| No concurrency group | Issues advance in parallel | Race condition — duplicate agent invocations |
| Per-item group (`orchestrator-{N}`) | Issues advance in parallel | Still racy: `:wip` apply fires `labeled` event → new run for item N starts before `:wip` propagates |
| Global group (`pipeline-orchestrator`) | Issues advance sequentially | Correct — settled label state guaranteed |

Per-item groups do not eliminate the race because the `:wip` write on item N
fires an `issues.labeled` event for item N, which matches the per-item
concurrency key and queues a new run for item N. That queued run starts
within seconds of `:wip` being applied — inside the propagation window.

The global group prevents this because there is at most one queued run
globally; by the time it starts, all prior writes are settled.

### In-memory label snapshot

Within a single orchestrator run, labels are read once per work item and
held in memory. When the orchestrator writes a label (`:wip`, terminal label)
it updates the in-memory set immediately, without a GitHub round-trip. This
prevents reading stale state between agents on the same item within the same
run. The snapshot is reset at the start of each new run — no state crosses
the process boundary.

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
orchestrator scans the captured stream-json event text for indicators:

| Pattern | Source |
|---|---|
| `rate_limit_error` | Anthropic SDK error class |
| `\b429\b` | HTTP status |
| `usage limit` / `quota (exceeded\|exhausted)` | quota messaging |
| `tokens? per minute` / `daily token limit` | Anthropic-specific phrasing |
| `too many requests` | HTTP status text |
| `overloaded_error` | Anthropic SDK error class for capacity overload |

Because the CLI output is consumed as a stream of newline-delimited JSON
events, the orchestrator extracts text content from `assistant` message
events before applying these patterns. Error events in the stream are
also checked directly for `error.type` values matching the above list.

If any indicator matches, the orchestrator parses an optional
`retry-after`, `retry after Ns`, or `wait N seconds` value from the
same content. If found, the value is honoured (capped at 1 hour). If
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
python pipeline/pipeline_orchestrator.py --clear-pause
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

| Secret | Required | Used by | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | Yes | Orchestrator | Auto-provisioned by Actions; scoped to the repo and workflow run |
| `ANTHROPIC_API_KEY` | Yes | Orchestrator → Claude CLI | Required for agent invocations; store as an Actions repository or org secret |

The `GITHUB_TOKEN` auto-provisioned by Actions has the scopes declared in
each workflow's `permissions` block. No PAT is needed for the orchestrator
itself. A dedicated GitHub App token is required before any production
compliance claim (see [`10-roadmap.md`](10-roadmap.md) — agent identity
prerequisite).

**Workflow file limitation.** GitHub prevents `GITHUB_TOKEN` from pushing
changes to `.github/workflows/`. Automated agents (coder, prd-docs-updater)
must not write directly to that directory. Instead, agents that need to
propose a new workflow write the file to `docs/workflow-proposals/{name}.yml`
and note in their closing announcement that a human must move it to
`.github/workflows/` and push with a token that has `workflow` scope. The
proposed file is committed to the issue branch and visible in the draft PR for
review.

---

## Emergency stop

The emergency stop mechanism lets an operator halt all pipeline activity
immediately. Unlike the rate-limit pause (automatic, time-bounded), the
emergency stop is **operator-initiated** and **never expires** — it persists
until explicitly cleared.

### Stop marker

The orchestrator checks for `.pipeline-stop` at the submodule root at
the very start of `main()`, **after** the pause-marker check. If the
marker exists, the orchestrator:

1. Logs the stop reason.
2. Emits a `system.emergency_stop` audit event.
3. Exits 0 — no labels are changed, no agents are invoked.

The marker is not auto-cleared on the next tick. It persists until a human
runs the restart workflow or invokes `--clear-stop`.

**Marker format** (`.pipeline-stop` in repo root):

```json
{
  "stopped_at": "2026-05-06T21:00:00Z",
  "reason": "bad prompt deployed to prd-writer",
  "stopped_by": "github-actions"
}
```

### Relationship to pause

| | `.pipeline-pause` | `.pipeline-stop` |
|---|---|---|
| Trigger | Automatic (Anthropic rate limit) | Manual (`workflow_dispatch`) |
| Expiry | Yes — auto-cleared when `until` passes | No — must be explicitly cleared |
| Cancels in-flight runs | No | Yes (if `cancel_runs` is `true`) |
| Clear mechanism | Auto on expiry; `--clear-pause` | `pipeline-restart.yml`; `--clear-stop` |
| Check order in `main()` | First | Immediately after pause check |

### Manual override

```bash
python pipeline/pipeline_orchestrator.py --clear-stop
```

Deletes the marker and exits. The next scheduled or event-driven tick
proceeds normally.
