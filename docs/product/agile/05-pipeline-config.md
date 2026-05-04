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

For each agent, exactly these facts:

| Field | Required | Meaning |
|---|---|---|
| `agent` | yes | Stable agent name; matches `.github/agents/{agent}.md` |
| `phase` | yes | One of: `product-docs`, `technical-docs`, `testing-spec`, `build-plan`, `execute`, `test`, `evaluate` |
| `object` | yes | Array containing `issue`, `pr`, or both |
| `trigger` | yes | One of: `{event: "..."}`, `{label: "..."}`, `{schedule: "..."}`, optionally with `path_filter` |
| `dependencies` | yes | Array of agent names that must reach `:complete` before this agent can run |
| `human_gate_after` | yes | Boolean — is there a human gate after this agent? |
| `human_gate_label` | conditional | Required if `human_gate_after` is true; the label a human applies to advance |
| `description` | yes | One-sentence statement of what the agent owns |

Anything else about an agent — its prompt, its tools, its model — lives
in `.github/agents/{agent}.md`, not in `pipeline.json`. The pipeline
file describes the *graph*, not the *behaviour*.

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
- `trigger` is exactly one of the allowed shapes.

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

## Adding a new agent

1. Add an entry to `pipeline.json` (the graph). Validate.
2. Add a prompt at `.github/agents/{agent}.md` (the behaviour).
3. Regenerate docs.
4. Bootstrap labels:
   `bash .github/scripts/status.sh bootstrap {agent}`.
5. Open a PR with all three. Standards owner approves.

The order matters: the graph entry comes first because the orchestrator
will not invoke an agent that isn't declared in `pipeline.json`, even if
the prompt file exists.

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

## Why JSON, not YAML or TOML

- JSON has a published schema language (JSON Schema) with broad tooling.
- JSON is what the orchestrator reads; no parser ambiguity.
- JSON Schema validation runs in CI, IDEs, and pre-commit hooks
  uniformly.
- The cost of JSON's verbosity is low because the file is generated-from
  for human reading.
