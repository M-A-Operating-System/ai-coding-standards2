# Agent Specification

> **Scope: AI agent steps only.** This document covers pipeline steps with
> `"type": "agent"` (Claude CLI invocations). For `"type": "script"` steps,
> see [`05-pipeline-config.md § Script steps`](05-pipeline-config.md#script-steps).
> Script steps do not use prompt files, `status.sh`, or the tool allowlist —
> they emit an `AI_AGILE_STATUS:` sentinel to stdout instead.

Every agent has exactly one prompt file at `.claude/agents/{agent-name}.md`.
This document defines the required shape of that file: the YAML frontmatter
schema, the required body sections, the tool allowlist policy, and the
status-transition contract.

When adding a new agent, the **graph entry in `pipeline.json` lands
first** (per [`05-pipeline-config.md`](05-pipeline-config.md) — the
orchestrator will not invoke an agent that is not declared in
`pipeline.json` even if a prompt file exists). The prompt file lands
in the same PR and must conform to this spec; CI validates the
frontmatter and the required body markers on every PR that touches
`.claude/agents/` and refuses to merge until both halves are in
place.

---

## Naming convention

Every agent name carries its phase as a prefix, separated by a forward
slash:

```
{phase}/{short-name}
```

Examples: `01_product_docs/issue-classifier`, `02_technical_docs/architect`,
`05_execute/coder`, `07_evaluate/retrospective-writer`,
`08_learn/metrics-aggregator`.

The phase prefix is one of the ten phase identifiers defined in
[`04-lifecycle.md`](04-lifecycle.md):

| Per-ticket | Continuous |
|---|---|
| `01_product_docs` | `08_learn` |
| `02_technical_docs` | `09_gap_assessment` |
| `03_testing_spec` | `10_tech_debt` |
| `04_build_plan` | |
| `05_execute` | |
| `06_test` | |
| `07_evaluate` | |

The short-name is lowercase-hyphenated with no spaces or underscores.

**Why prefix.** A glance at any label, comment, or audit-log line
reveals which phase the agent belongs to without consulting
`pipeline.json`. It also prevents future name collisions across phases
(e.g. a hypothetical `05_execute/dependency-resolver` could coexist with
`01_product_docs/dependency-resolver` if the design ever requires it).

**Constraint.** An agent's phase prefix is part of its identity. If
its phase changes, the agent is treated as renamed: a new entry
replaces the old one in `pipeline.json`, the old prompt file is moved
to the parking lot, and existing closed work keeps the old name in
its audit trail. Renaming is rare; no Phase-1 agent is expected to
move phases after launch.

---

## File location

```
.claude/agents/{phase}/{short-name}.md
```

So `01_product_docs/issue-classifier` lives at
`.claude/agents/01_product_docs/issue-classifier.md`.

- The directory **is** the phase prefix; the orchestrator computes the
  file path by treating the agent name's `/` as a directory separator.
- The filename and the frontmatter `name:` field together must match
  the `agent` field in `pipeline.json`.

A copy-paste starting point lives at
[`.claude/agents/_templates/agent-template.md`](../../../.claude/agents/_templates/agent-template.md).

---

## YAML frontmatter

The file begins with a YAML block delimited by `---`:

```yaml
---
name: 01_product_docs/agent-name
description: >
  One paragraph stating what the agent does and when it runs. Surfaces
  in agent listings and the generated agents.md catalogue.
tools: [Bash, Read, Grep]
model: claude-sonnet-4-6
---
```

### Frontmatter schema

| Field | Required | Type | Constraints |
|---|---|---|---|
| `name` | yes | string | Format `{phase}/{short-name}` where phase uses numeric-prefix form (e.g. `01_product_docs`); matches the file's path under `.claude/agents/`; matches `pipeline.json` `agent` field; lowercase-hyphenated short-name |
| `description` | yes | string | One paragraph; ≤ 500 characters; states what the agent does |
| `tools` | yes | array of strings | Subset of the allowable-tools matrix below |
| `model` | yes | string | One of: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5` |

CI validates each field. Frontmatter that fails validation blocks the PR.

---

## Allowable-tools matrix

The `tools` array restricts what the LLM can do. The orchestrator passes a
matching `--allowedTools` flag to the Claude CLI when it invokes the agent.
**The frontmatter `tools` field is the source of truth**; the orchestrator
reads it to construct the CLI flag.

### Tool reference

| Tool | What it does | Default policy |
|---|---|---|
| `Bash` | Runs shell commands (gh CLI, git, test runners) | Most agents need this |
| `Read` | Reads files | Almost every agent needs this |
| `Glob` | Pattern-based file lookup | Reviewers, validators |
| `Grep` | Content search | Reviewers, validators, decomposers |
| `Edit` | In-place file edits | Coders, test writers, retrospective writer |
| `Write` | Creates files | Coders, test writers |
| `WebFetch` | Fetches URLs | Forbidden by default — see security note |
| `WebSearch` | Web search | Forbidden by default — see security note |

### Per-agent-type policy

Use the smallest tool set that lets the agent do its job. The matrix below
is the policy; any deviation requires an ADR.

| Agent type | Example agents | Tools |
|---|---|---|
| **Classifier / sizer** | `01_product_docs/issue-classifier`, `01_product_docs/ticket-sizer` | `[Bash, Read]` |
| **Document drafter** | `01_product_docs/prd-writer`, `02_technical_docs/architect`, `03_testing_spec/test-spec-writer`, `07_evaluate/retrospective-writer`, `07_evaluate/release-noter` | `[Bash, Read, Grep]` |
| **Validator / reviewer** | `05_execute/standards-compliance-reviewer`, `05_execute/migration-validator`, `05_execute/pr-reviewer`, `03_testing_spec/test-coverage-auditor` | `[Bash, Read, Glob, Grep]` |
| **Decomposer / planner** | `04_build_plan/task-decomposer`, `01_product_docs/dependency-resolver`, `01_product_docs/impact-assessor` | `[Bash, Read, Glob, Grep]` |
| **ADR proposer** | `02_technical_docs/adr-proposer` (folded into `02_technical_docs/architect` per roadmap) | `[Bash, Read]` |
| **Coder** | `05_execute/coder` | `[Bash, Read, Edit, Write, Glob, Grep]` |
| **Test writer / runner** | `06_test/test-writer`, `06_test/test-runner` | `[Bash, Read, Edit, Write, Glob, Grep]` |
| **Standards evolver** | `07_evaluate/standards-evolver` | `[Bash, Read, Glob, Grep, Edit]` |
| **Phase 8/9/10 meta-agents** | `08_learn/metrics-aggregator`, `09_gap_assessment/gap-assessor`, `10_tech_debt/debt-finder`, etc. | `[Bash, Read, Glob, Grep]` |
| **Phase 8 prompt mutator** | `08_learn/prompt-tuner` | `[Bash, Read, Edit]` (edits agent prompt files only) |

### Security note on WebFetch and WebSearch

`WebFetch` and `WebSearch` are forbidden in agent prompts by default. They
introduce two risks:

1. **Prompt injection from external content** — fetched HTML can contain
   text that influences agent behaviour.
2. **Data exfiltration** — issue/PR content can be encoded into outbound
   URLs.

If an agent genuinely needs external content, the request must be made
through a controlled endpoint (e.g., the standards repository) and the
inclusion documented as an exception ADR.

---

## Model selection policy

| Model | When to use |
|---|---|
| `claude-opus-4-7` | Hardest reasoning: `02_technical_docs/architect`, `05_execute/pr-reviewer`, `08_learn/process-reviewer`, `07_evaluate/standards-evolver` |
| `claude-sonnet-4-6` | Default for most agents — drafters, decomposers, validators |
| `claude-haiku-4-5` | Fast, cheap, deterministic: `01_product_docs/issue-classifier`, `01_product_docs/ticket-sizer`, `07_evaluate/release-noter`, `08_learn/metrics-aggregator` |

Choosing a more expensive model than necessary wastes budget without
improving outcomes. Choosing a cheaper model than necessary produces
poor artefacts that fail review and re-run anyway. The default is
Sonnet; deviations should be deliberate.

---

## Body structure

The body of the file is plain Markdown. It must contain the following
sections, in this order, identified by their headers.

### Shared context (read before drafting your own prompt)

The orchestrator injects an instruction into every agent's invocation
to read [`ai-agile/AGENTS.md`](../../../ai-agile/AGENTS.md) first.
That file is the runtime distillation of the design (principles,
status contract, marker conventions, "what you must not do"). Your
agent prompt does **not** need to repeat any of it — assume the agent
has read it.

When you write your prompt, focus on what is **specific to this
agent's job**: its inputs, the work it does, the artefact it
produces, and the rules that apply just to it. Don't restate the
status contract, the marker format, the "don't apply gate labels"
rule, etc. — those are in `AGENTS.md` and adding them to the prompt
risks drift.

### Required sections

| Section | Header | Purpose |
|---|---|---|
| 1. Role statement | First paragraph(s) under `# {agent-name}` | Plain-English description of what the agent owns |
| 2. Step 1 — Opening announcement | `## Step 1 — Opening announcement` | Post the `<!-- ai-agile/announcement/v1 by {agent-name} -->` start comment ([`09-human-interaction.md`](09-human-interaction.md) §3) |
| 3. Read-input steps | `## Step 2 — Read inputs` (and further steps as needed) | Gather context from issue/PR body, comments, files |
| 4. Work steps | `## Step N — {action}` | The actual work — drafting, validating, editing |
| 5. Closing announcement | `## Step N+1 — Closing announcement` | Post the closing `<!-- ai-agile/announcement/v1 by {agent-name} -->` comment |
| 6. Terminal status step | `## Step N+2 — Emit sentinel` | Print the terminal `AI_AGILE_STATUS:` sentinel line as the final stdout output |
| 7. Behaviour rules | `## Behaviour rules` | Bullet list of constraints; what the agent must / must not do |

### Section detail

**1. Role statement.** Two or three sentences. What the agent does, when
it runs (in terms of phase or trigger), and what artefact it produces.

**2. Step 1 — Opening announcement.** A single `gh issue comment` (or
`gh pr comment`) call posting the JSON announcement with `phase: start`
per the schema in
[`09-human-interaction.md`](09-human-interaction.md) §3.

The orchestrator applies `:wip` before invoking the agent — the agent
does not do this.

**3. Read-input steps.** Read the issue body, prior agent comments, and
any files needed. Use `gh issue view`, `gh pr view`, `cat`, `grep`,
`find`. The agent must operate from what it reads at runtime — it does
not assume any state from prior runs.

**4. Work steps.** The agent's actual job. One step per logical action.
Each step should produce something — a draft section of an artefact, a
validation finding, a check result. Avoid step soup; keep steps coarse.

**5. Closing announcement.** A single `gh issue comment` (or
`gh pr comment`) call posting the JSON announcement with `phase: end`,
`outcome` matching the terminal status, and `artefacts` listing the
comments / files / PRs produced this run.

**6. Terminal status step.** After the closing announcement, print
exactly one sentinel line as the **final stdout output**. The
orchestrator reads this line and applies the appropriate label:

```
AI_AGILE_STATUS: complete
AI_AGILE_STATUS: review "short message"
AI_AGILE_STATUS: blocked "reason"
```

`complete` — work is done, no gate required.
`review "msg"` — work is done and awaiting a human gate; `msg` is a
short description shown in the label or log.
`blocked "reason"` — the agent cannot continue without human input;
`reason` describes what is needed.

The orchestrator applies `:failed` if the agent exits without one of
these sentinels. Agents must not call `set-failed` themselves. Never
call `status.sh` — the orchestrator owns all label transitions.

**7. Behaviour rules.** A bullet list. Hard constraints the LLM must
follow. Examples:

- "Do not edit the issue body — it is human-authored."
- "Post one comment per run, not many."
- "Reference STD IDs by their stable identifier, never inline the
  standard text."
- "If the input is ambiguous, emit `AI_AGILE_STATUS: blocked \"reason\"` rather than guessing."

Behaviour rules are the last line of defence against agent misbehaviour.
They should be specific, testable, and few (3–10 bullets is typical).

---

## Status transition contract

**This contract applies to AI agent steps only.** Script steps (`type:
"script"`) signal status by printing `AI_AGILE_STATUS:` to stdout; the
orchestrator reads the sentinel and applies the label. See
[`05-pipeline-config.md § Script steps`](05-pipeline-config.md#script-steps).

Agent steps use the same sentinel mechanism: the agent prints one of
the following as its **final stdout line**, and the orchestrator reads
it and applies the label:

```
AI_AGILE_STATUS: complete
AI_AGILE_STATUS: review "short message"
AI_AGILE_STATUS: blocked "reason"
```

Every agent run must either:

- Print exactly one of the three sentinels above as its final stdout
  line — the agent's responsibility — **or**
- Crash, in which case the orchestrator applies `:failed`.

There is no fourth path. Agents that exit without a terminal sentinel
are treated as failed. Agents must not apply `:complete` for gated work
— that transition is owned by the orchestrator (see
[`06-status-model.md`](06-status-model.md#gated-agents-the-review--complete-transition)).

**Never call `status.sh`.** The orchestrator owns all label transitions.
The `:wip` label is applied by the orchestrator before invoking the
agent; agents do not set it themselves.

---

## CI validation

Every PR that touches `.claude/agents/*.md` runs
`ai-agile/pipeline/validate_agent_prompts.py`, which checks:

1. **Frontmatter parses** as YAML.
2. **Required fields** are present: `name`, `description`, `tools`,
   `model`.
3. **`name` matches the path under `.claude/agents/`** (`name: 01_product_docs/prd-writer` ↔ `.claude/agents/01_product_docs/prd-writer.md`).
4. **`name` exists** in `pipeline.json` as a declared agent.
5. **`tools` array** is a subset of the allowable-tools matrix.
6. **`model`** is one of the three allowed model IDs.
7. **Required body sections** exist (`# {agent-name}`,
   opening + closing announcement steps, `## Behaviour rules`).
8. **Terminal sentinel** is present: the agent's final stdout line must
   be one of `AI_AGILE_STATUS: complete`, `AI_AGILE_STATUS: review "msg"`,
   or `AI_AGILE_STATUS: blocked "reason"`. `status.sh` must not be
   called anywhere in the prompt.
9. **No forbidden tools.** `WebFetch` and `WebSearch` block the PR
   unless an exception ADR is referenced in the frontmatter.

PRs that fail validation cannot merge.

---

## Adding a new agent — checklist

1. Copy
   `.claude/agents/_templates/agent-template.md` to
   `.claude/agents/{new-agent}.md`.
2. Fill in the frontmatter: `name`, `description`, `tools`, `model`.
3. Replace the role statement, work steps, and behaviour rules.
4. Add the agent's entry to `ai-agile/pipeline/pipeline.json`
   (graph entry first, per [`05-pipeline-config.md`](05-pipeline-config.md)).
5. Run `python ai-agile/pipeline/validate_agent_prompts.py` locally.
6. Run `python ai-agile/pipeline/generators/generate_docs.py` to
   refresh the generated agent catalogue.
7. Bootstrap the agent's labels:
   `bash .github/scripts/status.sh bootstrap {new-agent}`.
8. Open a PR with all changes. Standards owner approves.

---

## Why this template

- **Predictability for reviewers.** Every agent file has the same shape;
  reviewing a new agent is reading deltas, not reverse-engineering
  structure.
- **Predictability for the orchestrator.** It knows how to invoke any
  agent based on the frontmatter alone — no per-agent special-casing.
- **Auditability.** The opening and closing announcements, plus the
  required terminal status call, mean every run produces a parseable
  trail without depending on the LLM remembering to log.
- **Safety.** The tool allowlist plus the no-`:failed`-from-agent rule
  bound what an agent can do and what it can claim about its own
  outcome.
