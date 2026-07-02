# Pipeline Configuration

The pipeline graph — every agent, every dependency, every gate, every
trigger — lives in one file: `pipeline/pipeline.json`. This is
the single source of truth referenced by [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated).

Anything human-readable about the pipeline (agent catalogues, phase
tables, mermaid diagrams, gate lists) is generated from this file and
committed to `docs/product/agile/generated/`. Hand-editing those generated
files is not allowed.

---

## File location

```
pipeline/
  pipeline.json                     ← the source of truth
  schemas/
    pipeline.schema.json            ← JSON schema (validation)
  generators/
    generate_docs.py                ← produces docs/product/agile/generated/
    generate_pipeline_mermaid.py    ← produces .mmd flowcharts
    generate_phase_mermaid.py       ← produces per-phase .mmd charts under generated/phases/
```

The current `.claude/pipeline.json` is migrated to this location. The
older YAML stub at `.claude/agents/agent-dependencies.yml` is deleted —
JSON is the only format.

---

## What the file declares

Each entry in `pipeline.json` represents one pipeline step. A step is either
an AI agent (invokes Claude CLI) or a script (runs a bash script directly).
For each step, exactly these facts are declared:

| Field | Required | Meaning |
|---|---|---|
| `agent` | yes | Stable step name in the form `{phase}/{short-name}` (e.g. `01_product_docs/prd-writer`); matches `.claude/agents/{phase}/{short-name}.md` for agent steps, or the logical name for script steps. See [`12-agent-spec.md`](12-agent-spec.md#naming-convention). |
| `type` | no | Invocation mode: `"agent"` (default) — invokes Claude CLI with the matching `.claude/agents/` prompt; `"script"` — runs the file at `script` directly via bash. Existing entries with no `type` field are treated as `"agent"`. |
| `script` | conditional | Repo-relative path to the bash script to execute. Required when `type: "script"`; ignored otherwise. The script receives the same environment variables as agents and must emit an `AI_AGILE_STATUS:` sentinel to stdout (see [§ Script steps](#script-steps)). |
| `phase` | yes | One of the ten phase identifiers. Must equal the prefix in `agent`. |
| `object` | yes | Array containing `issue`, `pr`, or both |
| `trigger` | yes | One of: `{event: "..."}`, `{label: "..."}`, `{schedule: "..."}`, optionally with `path_filter` |
| `dependencies` | yes | Array of step names that must reach `:complete` before this step can run |
| `human_gate_after` | yes | Boolean — is there a human gate after this step? |
| `human_gate_label` | conditional | Required if `human_gate_after` is true; the label a human applies to advance. Gate labels are stable identifiers — they may be agent-scoped (e.g. `01_product_docs/prd-writer:approved`) or short-form (e.g. `pr:approved`). |
| `max_retries` | no | How many times the orchestrator re-invokes this step after a `:failed` outcome before giving up (default: 0 — no retries). |
| `max_concurrent` | no | Maximum number of instances of this agent the orchestrator may launch simultaneously across all issues in a single tick. The orchestrator counts active `{agent}:wip` labels across all open issues before launching additional instances; it starts no more than this many at once. Default 1 when the field is absent or null. A pipeline-wide aggregate maximum (see `PIPELINE_MAX_CONCURRENT` in `pipeline/pipeline_orchestrator.py` for the authoritative value) caps total agent launches across all agent types per tick regardless of per-agent settings. |
| `description` | yes | One-sentence statement of what the step owns |
| `session` | no | Session management config (agent steps only — see [§ Session management](#session-management) below). Ignored for script steps. |
| `post_steps` | no | Ordered list of repo-relative shell script paths to execute after the agent signals `:complete`. Agent steps only — see [§ post_steps](#post_steps--per-agent-completion-hooks). |

Anything else about an agent step — its prompt, its tools, its model — lives
in `.claude/agents/{phase}/{short-name}.md`, not in `pipeline.json`.
The pipeline file describes the *graph*, not the *behaviour*.

---

## Script steps

A pipeline step with `"type": "script"` runs a bash script directly, without
invoking Claude CLI. Use script steps for deterministic tasks that need no
reasoning — linking PRs to issues, applying labels, posting templated
comments.

### How script steps work

1. The orchestrator applies `{step}:wip` before invoking both agent and script steps. Agents never call `status.sh` for `:wip`.
2. The script is invoked with `bash {script_path}` and receives the same
   environment variables as agents: `$REPO`, `$ISSUE_NUMBER` (or
   `$PR_NUMBER`), `$WORK_ITEM_KIND`, `$WORK_ITEM_NUMBER`, `$AI_AGILE_ROOT`,
   `$GITHUB_TOKEN`.
3. The script must print an `AI_AGILE_STATUS:` sentinel as its last output
   line. The orchestrator reads the sentinel and applies the matching label,
   then removes `:wip`.
4. Script steps are subject to a 5-minute wall-clock timeout (configurable).
5. Rate-limit detection and pausing does not apply to script steps (they do
   not call the Anthropic API).

### Sentinel convention for scripts

```bash
echo "AI_AGILE_STATUS: complete"           # normal completion
echo 'AI_AGILE_STATUS: blocked "reason"'   # human input needed
```

**Important:** The orchestrator only searches the **last 5 lines** of stdout
for the sentinel. This prevents issue-body content echoed earlier in the run
from spoofing the sentinel. Always emit `AI_AGILE_STATUS:` as one of the
final lines of your script.

If the script exits non-zero without emitting a sentinel, the orchestrator
applies `:failed` exactly as it does for a crashed agent.

### Example entry

```json
{
  "agent": "01_product_docs/link-pr-to-issue",
  "type": "script",
  "script": ".github/scripts/link-pr-to-issue.sh",
  "phase": "01_product_docs",
  "object": ["issue"],
  "trigger": { "label": "01_product_docs/prd-docs-updater:complete" },
  "human_gate_after": false,
  "dependencies": ["01_product_docs/prd-docs-updater"],
  "description": "Finds PRs created for this issue and applies source-issue:{N} labels."
}
```

---

## Schema

The schema lives at `pipeline/schemas/pipeline.schema.json` and is
validated in CI on every PR that touches `pipeline.json`.

The schema enforces:

- Every `agent` value is unique within the file.
- Every `dependencies` entry references an agent that exists in the same
  file.
- `human_gate_label` is present iff `human_gate_after` is true.
- The dependency graph is acyclic (validator runs a topological sort).
- `phase` values are from the closed enum.
- One or more trigger shapes may be combined on a single agent; the orchestrator fires when ANY trigger condition is met.

---

## What gets generated from it

| Generated file | Description |
|---|---|
| `docs/product/agile/generated/agents.md` | One section per agent: phase, dependencies, gate, description |
| `docs/product/agile/generated/phases.md` | Agents grouped by phase, in dependency order |
| `docs/product/agile/generated/gates.md` | Every human gate, what triggers it, who approves |
| `docs/product/agile/generated/pipeline.mmd` | Full mermaid flowchart |
| `docs/product/agile/generated/pipeline-issue.mmd` | Issue subgraph |
| `docs/product/agile/generated/pipeline-pr.mmd` | PR subgraph |
| `docs/product/agile/generated/phases/{phase}.mmd` (one per phase) | Per-phase mermaid flowchart showing only the agents and boundary gates for that phase |

The generator is idempotent: running it twice on the same input produces
byte-identical output. CI runs the generator and fails the PR if any
generated file differs from what's committed.

---

## Change process

A change to `pipeline.json` is a meaningful architectural change. The
process:

1. **Open a PR** that edits `pipeline.json`. Title prefix:
   `[pipeline]`.
2. **Validate locally** with `python pipeline/validate.py`
   before pushing.
3. **Regenerate the docs** with
   `python pipeline/generators/generate_docs.py` and
   `python pipeline/generators/generate_phase_mermaid.py`.
   Commit the regenerated files in the same PR.
4. **CI validates** the schema, the acyclicity, and the freshness of
   generated files.
5. **Standards owner approves** any change that:
   - Adds or removes an agent
   - Adds or removes a human gate
   - Changes a phase boundary
   - Modifies dependency edges
6. The orchestrator reloads the file at the start of every run. There
   is no separate deploy step.

---

## Adding a new agent step

1. Add an entry to `pipeline.json` (the graph). Validate.
2. Add a prompt at `.claude/agents/{agent}.md` (the behaviour).
3. Regenerate docs.
4. Bootstrap labels:
   `bash .github/scripts/status.sh bootstrap {agent}`.
5. Open a PR with all three. Standards owner approves.

The order matters: the graph entry comes first because the orchestrator
will not invoke an agent that isn't declared in `pipeline.json`, even if
the prompt file exists.

## Adding a new script step

1. Add an entry to `pipeline.json` with `"type": "script"` and a `"script"` path.
2. Write the script at the declared path. It must be executable and emit an
   `AI_AGILE_STATUS:` sentinel (see [§ Script steps](#script-steps)).
3. Regenerate docs.
4. Bootstrap labels: `bash .github/scripts/status.sh bootstrap {step-name}`.
5. Open a PR with both. Standards owner approves.

No `.claude/agents/` prompt file is needed for script steps.

---

## Removing an agent

Removing an agent is rare. The process:

1. Confirm no `:complete` labels for the agent exist on any open issue
   or PR. If they do, those items must close or migrate first.
2. Remove the entry from `pipeline.json`.
3. Update any agent that listed it as a dependency.
4. Regenerate docs.
5. Move the prompt to `.claude/agents/parking_lot/`.
6. Standards owner approves.

The audit log branch retains the agent's history. The label set on
closed issues retains the agent's `:complete` markers. Nothing is
rewritten.

---

## git_ops — Orchestrator PR lifecycle

Certain pipeline steps require the orchestrator to take a PR lifecycle
action on completion. This is declared in the optional `git_ops` object
on the step entry in `pipeline.json`.

### Principle

Agents own git commits (write files, `git add`, `git commit`, `git push`
to their branch). The orchestrator owns the PR object (create, ready,
merge). Agents may read issues and PRs freely; they must not call
`gh pr create`, `gh pr ready`, or `gh pr merge`. See
[P-16](02-principles.md#p-16--git-commit-ownership-two-modes).

### Automatic issue close and branch delete

- **Issue auto-close:** The `create-pr` script writes "Closes #{N}" in
  the PR body. GitHub automatically closes the linked issue when the PR
  merges. This is GitHub-native and requires no pipeline code.
- **Branch delete on merge:** When the orchestrator receives a
  `pull_request.closed` event with `merged=true`, `_wake` calls
  `delete-branch.sh` with the head branch name. This deletes `issue-{N}`
  branches immediately on merge. Non-`issue-{N}` head branches (e.g.
  `claude/*`) are skipped silently. Branches from PRs closed without
  merging are not auto-deleted — they are candidates for the
  `00_ondemand/branch-cleanup` agent, which proposes a deletion list for
  human approval before removing anything.

### `git_ops` field reference

```json
"git_ops": {
  "commit_after": true
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `commit_after` | boolean | `false` | When `true`, after the agent signals `:complete`, the orchestrator stashes working-tree changes, checks out branch `issue-{N}`, pops the stash, commits all staged changes (`"docs: {agent} updates for issue #{N}"`), and pushes. Use for agents that write files via the `Write` tool and cannot run git. |

All other git behaviour (branch prefix, commit strategy) is agent-internal and should
not be declared in `pipeline.json`.

---

## post_steps — Per-agent completion hooks

Some agent steps need to run a short deterministic script immediately after
they signal `:complete` — for example, marking a PR ready for review once the
`pr-reviewer` agent issues APPROVE. These actions are declared as an ordered
array of repo-relative script paths in the `post_steps` field:

```json
"post_steps": [
  ".github/scripts/mark-pr-ready.sh"
]
```

### How post_steps work

1. Scripts execute only when the agent signals `AI_AGILE_STATUS: complete` —
   not on `:review`, `:blocked`, or `:failed`.
2. Scripts run in declaration order. Each receives the same environment
   variables as agent steps: `$REPO`, `$ISSUE_NUMBER` (or `$PR_NUMBER`),
   `$WORK_ITEM_KIND`, `$WORK_ITEM_NUMBER`, `$AGENT_NAME`, `$AI_AGILE_ROOT`,
   `$GITHUB_TOKEN`.
3. A script that exits non-zero aborts the remaining `post_steps`; the
   orchestrator applies `{agent}:failed` and posts a recovery comment.
4. `post_steps` is only valid on agent steps. It is ignored on script steps.

### When to use post_steps

Use `post_steps` for any deterministic, agent-specific action that must run
after the agent succeeds — actions that would otherwise require a hardcoded
`if agent == "..."` branch in the orchestrator. Prefer `git_ops.commit_after`
for git operations; use `post_steps` for everything else (e.g. calling
`gh pr ready`).

---

## Session management

Each agent in `pipeline.json` may carry an optional `session` object that
controls how the orchestrator assigns a `--session-id` when it invokes the
`claude` CLI.

```json
"session": {
  "scope": "per_issue",
  "id_pattern": "ais-v1-{safe_agent}-issue-{number}"
}
```

### Fields

| Field | Required | Default | Meaning |
|---|---|---|---|
| `scope` | yes | — | `per_issue` — a distinct session for each work item. `global` — one persistent session shared across every invocation of this agent. |
| `id_pattern` | no | Built-in default for `scope` (see below) | A Python `str.format()` pattern built from the tokens listed in [§ Session ID tokens](#session-id-tokens). |

### Built-in defaults

When `id_pattern` is omitted the orchestrator derives the ID from the scope:

| Scope | Default session ID |
|---|---|
| `per_issue` | `ais-v1-{safe_agent}-issue-{number}` |
| `global` | `ais-v1-{safe_agent}` |

### When to use `global`

Use `global` for agents that accumulate useful context across issues — for
example, a doc-reviewer that builds up an internal model of the full
`docs/product/` tree. Those agents should be **idempotent** (P-11): they
start each run by re-reading the relevant source, using the session only to
carry learned heuristics, not as the source of truth.

### Session ID tokens

The following tokens are available in `id_pattern`. They are substituted by
the orchestrator before the `claude` CLI is invoked. The same values are
exported as `SESSION_ID` and `SESSION_SCOPE` environment variables so agent
prompt code can reference them in announcement JSON.

| Token | Type | Example value | Source |
|---|---|---|---|
| `{agent}` | string | `01_product_docs/prd-writer` | Full agent name from `pipeline.json` |
| `{safe_agent}` | string | `01-product-docs-prd-writer` | `{agent}` with every non-`[a-z0-9]` char replaced by `-` |
| `{phase}` | string | `01_product_docs` | Phase field from `pipeline.json` |
| `{safe_phase}` | string | `01-product-docs` | `{phase}` normalised the same way as `{safe_agent}` |
| `{number}` | integer | `42` | Work item number (issue or PR) |
| `{kind}` | string | `issue` or `pr` | Work item type |
| `{owner}` | string | `m-a-operating-system` | GitHub organisation or user name |
| `{repo_name}` | string | `ai-coding-standards2` | Repository name without owner |
| `{safe_repo}` | string | `m-a-operating-system-ai-coding-standards2` | Full `owner/repo` with every non-`[a-z0-9]` char replaced by `-` |

> **Note:** `{repo}` (with the `/`) is not a token. It contains a slash which is
> invalid in a session ID. Use `{safe_repo}` for a normalised form, or compose
> `{owner}` and `{repo_name}` separately.
>
> Only bare `{identifier}` placeholders are accepted. Patterns containing
> attribute access (`{x.y}`) or index access (`{x[y]}`) are rejected at
> runtime and will fall back to the scope default.

### Examples

```json
// Per-issue, default pattern (no id_pattern needed)
"session": { "scope": "per_issue" }
// → ais-v1-01-product-docs-prd-writer-issue-42

// Global doc-reviewer session shared across all issues (no per-issue token)
"session": { "scope": "global" }
// → ais-v1-01-product-docs-prd-docs-updater

// Custom: namespace by repo in a multi-repo setup
"session": {
  "scope": "per_issue",
  "id_pattern": "ais-v1-{safe_agent}-{repo_name}-issue-{number}"
}
// → ais-v1-01-product-docs-prd-writer-ai-coding-standards2-issue-42

// Custom: one shared session per phase across all issues
"session": {
  "scope": "global",
  "id_pattern": "ais-v1-{safe_phase}"
}
// → ais-v1-01-product-docs
```

### Constraints

- Session IDs must match `[a-z0-9][a-z0-9-]*[a-z0-9]`. The orchestrator
  sanitises the rendered value (replacing invalid chars with `-`) and logs
  a warning if it had to, so custom literal strings in `id_pattern` are
  your responsibility. Prefer the `{safe_*}` tokens for user-controlled names.
- `{title}` is deliberately **not** a token. Issue titles are
  human-authored, may contain special characters, and change over time —
  all three properties make them unsafe for session ID construction.
- `{url}` is also excluded — it contains slashes and percent-encoded chars.

> **Retry suffix.** On retry attempts (controlled by `max_retries` in `pipeline.json`), the orchestrator appends `-r{attempt}` to the session ID seed before deriving the UUID (e.g. `ais-v1-prd-writer-issue-42-r1`). This gives each retry a distinct UUID, preventing "Session ID already in use" errors when a previous CI job was killed mid-run.

---

## Why JSON, not YAML or TOML

- JSON has a published schema language (JSON Schema) with broad tooling.
- JSON is what the orchestrator reads; no parser ambiguity.
- JSON Schema validation runs in CI, IDEs, and pre-commit hooks
  uniformly.
- The cost of JSON's verbosity is low because the file is generated-from
  for human reading.
