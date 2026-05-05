# Agent Specification

Every agent has exactly one prompt file at `.github/agents/{agent-name}.md`.
This document defines the required shape of that file: the YAML frontmatter
schema, the required body sections, the tool allowlist policy, and the
status-transition contract.

When adding a new agent, the **graph entry in `pipeline.json` lands
first** (per [`05-pipeline-config.md`](05-pipeline-config.md) — the
orchestrator will not invoke an agent that is not declared in
`pipeline.json` even if a prompt file exists). The prompt file lands
in the same PR and must conform to this spec; CI validates the
frontmatter and the required body markers on every PR that touches
`.github/agents/` and refuses to merge until both halves are in
place.

---

## Naming convention

Every agent name carries its phase as a prefix, separated by a forward
slash:

```
{phase}/{short-name}
```

Examples: `product-docs/issue-classifier`, `technical-docs/architect`,
`execute/coder`, `evaluate/retrospective-writer`,
`learn/metrics-aggregator`.

The phase prefix is one of the ten phase identifiers defined in
[`04-lifecycle.md`](04-lifecycle.md):

| Per-ticket | Continuous |
|---|---|
| `product-docs` | `learn` |
| `technical-docs` | `gap-assessment` |
| `testing-spec` | `tech-debt` |
| `build-plan` | |
| `execute` | |
| `test` | |
| `evaluate` | |

The short-name is lowercase-hyphenated with no spaces or underscores.

**Why prefix.** A glance at any label, comment, or audit-log line
reveals which phase the agent belongs to without consulting
`pipeline.json`. It also prevents future name collisions across phases
(e.g. a hypothetical `execute/dependency-resolver` could coexist with
`product-docs/dependency-resolver` if the design ever requires it).

**Constraint.** An agent's phase prefix is part of its identity. If
its phase changes, the agent is treated as renamed: a new entry
replaces the old one in `pipeline.json`, the old prompt file is moved
to the parking lot, and existing closed work keeps the old name in
its audit trail. Renaming is rare; no Phase-1 agent is expected to
move phases after launch.

---

## File location

```
.github/agents/{phase}/{short-name}.md
```

So `product-docs/issue-classifier` lives at
`.github/agents/product-docs/issue-classifier.md`.

- The directory **is** the phase prefix; the orchestrator computes the
  file path by treating the agent name's `/` as a directory separator.
- The filename and the frontmatter `name:` field together must match
  the `agent` field in `pipeline.json`.

A copy-paste starting point lives at
[`.github/agents/_templates/agent-template.md`](../../../.github/agents/_templates/agent-template.md).

---

## YAML frontmatter

The file begins with a YAML block delimited by `---`:

```yaml
---
name: product-docs/agent-name
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
| `name` | yes | string | Format `{phase}/{short-name}`; matches the file's path under `.github/agents/`; matches `pipeline.json` `agent` field; lowercase-hyphenated short-name |
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
| `Bash` | Runs shell commands (gh CLI, git, status.sh, test runners) | Most agents need this |
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
| **Classifier / sizer** | `product-docs/issue-classifier`, `product-docs/ticket-sizer` | `[Bash, Read]` |
| **Document drafter** | `product-docs/prd-writer`, `technical-docs/architect`, `testing-spec/test-spec-writer`, `evaluate/retrospective-writer`, `evaluate/release-noter` | `[Bash, Read, Grep]` |
| **Validator / reviewer** | `execute/standards-compliance-reviewer`, `execute/migration-validator`, `execute/pr-reviewer`, `testing-spec/test-coverage-auditor` | `[Bash, Read, Glob, Grep]` |
| **Decomposer / planner** | `build-plan/task-decomposer`, `product-docs/dependency-resolver`, `product-docs/impact-assessor` | `[Bash, Read, Glob, Grep]` |
| **ADR proposer** | `technical-docs/adr-proposer` (folded into `technical-docs/architect` per roadmap) | `[Bash, Read]` |
| **Coder** | `execute/coder` | `[Bash, Read, Edit, Write, Glob, Grep]` |
| **Test writer / runner** | `test/test-writer`, `test/test-runner` | `[Bash, Read, Edit, Write, Glob, Grep]` |
| **Standards evolver** | `evaluate/standards-evolver` | `[Bash, Read, Glob, Grep, Edit]` |
| **Phase 8/9/10 meta-agents** | `learn/metrics-aggregator`, `gap-assessment/gap-assessor`, `tech-debt/debt-finder`, etc. | `[Bash, Read, Glob, Grep]` |
| **Phase 8 prompt mutator** | `learn/prompt-tuner` | `[Bash, Read, Edit]` (edits agent prompt files only) |

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
| `claude-opus-4-7` | Hardest reasoning: `technical-docs/architect`, `execute/pr-reviewer`, `learn/process-reviewer`, `evaluate/standards-evolver` |
| `claude-sonnet-4-6` | Default for most agents — drafters, decomposers, validators |
| `claude-haiku-4-5` | Fast, cheap, deterministic: `product-docs/issue-classifier`, `product-docs/ticket-sizer`, `evaluate/release-noter`, `learn/metrics-aggregator` |

Choosing a more expensive model than necessary wastes budget without
improving outcomes. Choosing a cheaper model than necessary produces
poor artefacts that fail review and re-run anyway. The default is
Sonnet; deviations should be deliberate.

---

## Body structure

The body of the file is plain Markdown. It must contain the following
sections, in this order, identified by their headers.

### Required sections

| Section | Header | Purpose |
|---|---|---|
| 1. Role statement | First paragraph(s) under `# {agent-name}` | Plain-English description of what the agent owns |
| 2. Step 1 — Apply wip | `## Step 1 — Apply wip` | The `set-wip` call |
| 3. Step 2 — Opening announcement | `## Step 2 — Opening announcement` | Post the `<!-- ai-agile/announcement/v1 -->` start comment ([`09-human-interaction.md`](09-human-interaction.md) §3) |
| 4. Read-input steps | `## Step 3 — Read inputs` (and further steps as needed) | Gather context from issue/PR body, comments, files |
| 5. Work steps | `## Step N — {action}` | The actual work — drafting, validating, editing |
| 6. Closing announcement | `## Step N+1 — Closing announcement` | Post the closing `<!-- ai-agile/announcement/v1 -->` comment |
| 7. Terminal status step | `## Step N+2 — Act on findings` | Branches: `set-complete`, `set-review`, or `set-blocked` |
| 8. Behaviour rules | `## Behaviour rules` | Bullet list of constraints; what the agent must / must not do |

### Section detail

**1. Role statement.** Two or three sentences. What the agent does, when
it runs (in terms of phase or trigger), and what artefact it produces.

**2. Step 1 — Apply wip.** Always exactly:

```bash
bash .github/scripts/status.sh set-wip {agent-name} $ISSUE_NUMBER
```

(For PR-side agents, use `$PR_NUMBER`.)

**3. Step 2 — Opening announcement.** A single `gh issue comment` (or
`gh pr comment`) call posting the JSON announcement with `phase: start`
per the schema in
[`09-human-interaction.md`](09-human-interaction.md) §3.

**4. Read-input steps.** Read the issue body, prior agent comments, and
any files needed. Use `gh issue view`, `gh pr view`, `cat`, `grep`,
`find`. The agent must operate from what it reads at runtime — it does
not assume any state from prior runs.

**5. Work steps.** The agent's actual job. One step per logical action.
Each step should produce something — a draft section of an artefact, a
validation finding, a check result. Avoid step soup; keep steps coarse.

**6. Closing announcement.** A single `gh issue comment` (or
`gh pr comment`) call posting the JSON announcement with `phase: end`,
`outcome` matching the terminal status, and `artefacts` listing the
comments / files / PRs produced this run.

**7. Terminal status step.** Branches based on outcome. Exactly one of
the three terminal calls must be reached:

```bash
# Success path — work is done and either complete or awaiting gate
bash .github/scripts/status.sh set-complete {agent} $ISSUE_NUMBER  # non-gated agents
bash .github/scripts/status.sh set-review   {agent} $ISSUE_NUMBER "<message>"  # gated agents

# Help-needed path — agent cannot finish without human input
bash .github/scripts/status.sh set-blocked  {agent} $ISSUE_NUMBER "<reason>"
```

The orchestrator applies `:failed` if the agent exits without one of
these calls. Agents must not call `set-failed` themselves.

**8. Behaviour rules.** A bullet list. Hard constraints the LLM must
follow. Examples:

- "Do not edit the issue body — it is human-authored."
- "Post one comment per run, not many."
- "Reference STD IDs by their stable identifier, never inline the
  standard text."
- "If the input is ambiguous, set-blocked rather than guessing."

Behaviour rules are the last line of defence against agent misbehaviour.
They should be specific, testable, and few (3–10 bullets is typical).

---

## Status transition contract

Every agent run must either:

- Terminate with exactly one of `set-complete`, `set-review`, or
  `set-blocked` — the agent's responsibility — **or**
- Crash, in which case the orchestrator applies `:failed`.

There is no fourth path. Agents that exit without a terminal status are
treated as failed. Agents must not apply `:complete` for gated work —
that transition is owned by the orchestrator (see
[`06-status-model.md`](06-status-model.md#gated-agents-the-review--complete-transition)).

---

## CI validation

Every PR that touches `.github/agents/*.md` runs
`ai-agile/pipeline/validate_agent_prompts.py`, which checks:

1. **Frontmatter parses** as YAML.
2. **Required fields** are present: `name`, `description`, `tools`,
   `model`.
3. **`name` matches the path under `.github/agents/`** (`name: product-docs/prd-writer` ↔ `.github/agents/product-docs/prd-writer.md`).
4. **`name` exists** in `pipeline.json` as a declared agent.
5. **`tools` array** is a subset of the allowable-tools matrix.
6. **`model`** is one of the three allowed model IDs.
7. **Required body sections** exist (`# {agent-name}`,
   `## Step 1 — Apply wip`, opening + closing announcement steps,
   `## Behaviour rules`).
8. **Status calls** appear at least once each: `set-wip` is called, and
   at least one of `set-complete`, `set-review`, or `set-blocked` is
   called.
9. **No forbidden tools.** `WebFetch` and `WebSearch` block the PR
   unless an exception ADR is referenced in the frontmatter.

PRs that fail validation cannot merge.

---

## Adding a new agent — checklist

1. Copy
   `.github/agents/_templates/agent-template.md` to
   `.github/agents/{new-agent}.md`.
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
