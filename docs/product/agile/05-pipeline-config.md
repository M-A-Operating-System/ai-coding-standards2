# Pipeline Configuration

The pipeline graph — every agent, every dependency, every gate, every
trigger — lives in one file: `ai-agile/pipeline/pipeline.json`. This is
the single source of truth referenced by [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated).

Anything human-readable about the pipeline (agent catalogues, phase
tables, mermaid diagrams, gate lists) is generated from this file and
committed to `docs/product/agile/generated/`. Hand-editing those generated
files is not allowed.

---

## File location

```
ai-agile/pipeline/
  pipeline.json                     ← the source of truth
  schemas/
    pipeline.schema.json            ← JSON schema (validation)
  generators/
    generate_docs.py                ← produces docs/product/agile/generated/
    generate_pipeline_mermaid.py    ← produces .mmd flowcharts
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
| `agent` | yes | Stable step name in the form `{phase}/{short-name}` (e.g. `01_product_docs/prd-writer`); matches `.github/agents/{phase}/{short-name}.md` for agent steps, or the logical name for script steps. See [`12-agent-spec.md`](12-agent-spec.md#naming-convention). |
| `type` | no | Invocation mode: `"agent"` (default) — invokes Claude CLI with the matching `.github/agents/` prompt; `"script"` — runs the file at `script` directly via bash. Existing entries with no `type` field are treated as `"agent"`. |
| `script` | conditional | Repo-relative path to the bash script to execute. Required when `type: "script"`; ignored otherwise. The script receives the same environment variables as agents and must emit an `AI_AGILE_STATUS:` sentinel to stdout (see [§ Script steps](#script-steps)). |
| `phase` | yes | One of the ten phase identifiers. Must equal the prefix in `agent`. |
| `object` | yes | Array containing `issue`, `pr`, or both |
| `trigger` | yes | One of: `{event: "..."}`, `{label: "..."}`, `{schedule: "..."}`, optionally with `path_filter` |
| `dependencies` | yes | Array of step names that must reach `:complete` before this step can run |
| `human_gate_after` | yes | Boolean — is there a human gate after this step? |
| `human_gate_label` | conditional | Required if `human_gate_after` is true; the label a human applies to advance. Gate labels are stable identifiers (e.g. `01_product_docs/prd-writer:approved`). |
| `max_retries` | no | How many times the orchestrator re-invokes this step after a `:failed` outcome before giving up (default: 0 — no retries). |
| `description` | yes | One-sentence statement of what the step owns |
| `session` | no | Session management config (agent steps only — see [§ Session management](#session-management) below). Ignored for script steps. |

Anything else about an agent step — its prompt, its tools, its model — lives
in `.github/agents/{phase}/{short-name}.md`, not in `pipeline.json`.
The pipeline file describes the *graph*, not the *behaviour*.

---

## Script steps

A pipeline step with `"type": "script"` runs a bash script directly, without
invoking Claude CLI. Use script steps for deterministic tasks that need no
reasoning — linking PRs to issues, applying labels, posting templated
comments.

### How script steps work

1. The orchestrator applies `{step}:wip` before the script runs (unlike agent
   steps, where the agent applies `:wip` itself via `status.sh`).
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

The schema lives at `ai-agile/pipeline/schemas/pipeline.schema.json` and is
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

The generator is idempotent: running it twice on the same input produces
byte-identical output. CI runs the generator and fails the PR if any
generated file differs from what's committed.

---

## Change process

A change to `pipeline.json` is a meaningful architectural change. The
process:

1. **Open a PR** that edits `pipeline.json`. Title prefix:
   `[pipeline]`.
2. **Validate locally** with `python ai-agile/pipeline/validate.py`
   before pushing.
3. **Regenerate the docs** with
   `python ai-agile/pipeline/generators/generate_docs.py`.
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
2. Add a prompt at `.github/agents/{agent}.md` (the behaviour).
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

No `.github/agents/` prompt file is needed for script steps.

---

## Removing an agent

Removing an agent is rare. The process:

1. Confirm no `:complete` labels for the agent exist on any open issue
   or PR. If they do, those items must close or migrate first.
2. Remove the entry from `pipeline.json`.
3. Update any agent that listed it as a dependency.
4. Regenerate docs.
5. Move the prompt to `.github/agents/parking_lot/`.
6. Standards owner approves.

The audit log branch retains the agent's history. The label set on
closed issues retains the agent's `:complete` markers. Nothing is
rewritten.

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

---

## Why JSON, not YAML or TOML

- JSON has a published schema language (JSON Schema) with broad tooling.
- JSON is what the orchestrator reads; no parser ambiguity.
- JSON Schema validation runs in CI, IDEs, and pre-commit hooks
  uniformly.
- The cost of JSON's verbosity is low because the file is generated-from
  for human reading.
