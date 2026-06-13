# AI Agile — Agent Context

You are reading this because you are an AI Agile agent. Read this
document **before** starting your run. It is the shortest correct
description of what AI Agile is, why it exists, and the rules you
must follow regardless of what your specific agent prompt says.

If anything in your specific prompt contradicts this document, this
document wins. If anything you are about to do violates one of the
rules below, stop and `set-blocked` with the reason.

The full design lives in
[`docs/product/agile/`](../docs/product/agile/README.md). This file
is the **distilled** version every agent reads at runtime.

---

## What AI Agile is

A **product-led agile pipeline**. The product, not the code, is the
source of truth for what should exist.

### The flow

```
product strategy  →  product docs  →  technical spec  →  code  →  testable spec
                     (target state)   (how to build)    (current   (proves it works)
                                                         state)
```

The arrows point left-to-right. **Never right-to-left.** You do not
let the code shape the product docs; you do not let the build plan
shape the design; you do not let the technical spec shape the PRD.
Each phase is constrained by the artefact that precedes it.

### The four artefacts and their roles

| Artefact | What it is | Authority |
|---|---|---|
| **Product strategy** ([`docs/product/agile/01-vision.md`](../docs/product/agile/01-vision.md), [`02-principles.md`](../docs/product/agile/02-principles.md), [`03-personas.md`](../docs/product/agile/03-personas.md)) | Why we exist; who we serve; the rules of how we build | Authoritative — sets direction |
| **Product documentation** (`docs/product/`) | The **target state** we are aiming for, in user-observable terms | **Authoritative TARGET state** |
| **Roadmap** ([`10-roadmap.md`](../docs/product/agile/10-roadmap.md)) | The plan to reach the target state through phases of user-benefitting (or technical-intermediate) outcomes | Describes realisable outcomes; sequencing only |
| **Technical specs** (designs, ADRs, test specs) | How the target state will be built | Derived from product docs; never invents new requirements |
| **Code** | The system as it actually is right now | **Authoritative CURRENT state** |

### The gap is GitHub issues

The gap between **product docs (target)** and **code (current)** is
the backlog. Every issue is one of:

- An **enhancement** — work to move code closer to the target state.
- A **bug** — code that has drifted from the target state and must
  return.

(Chores and refactors are technical-intermediate work the roadmap
sequences toward a user-benefitting outcome; they are still tied to a
product-doc target, not orphan technical preference.)

### The hard rule

> **You do not start coding something that is not already fully
> described in the product docs.**

This is non-negotiable. It applies to every agent in the pipeline:

- An issue without a stakeholder-approved PRD does not get a
  technical design, a test spec, a build plan, or a coder
  invocation. The lifecycle gates this automatically — `01_product_docs/prd-writer:approved`
  is upstream of every later phase's dependency check.
- A PR that lands code with no corresponding entry in `docs/product/`
  does not merge. The reviewer rejects it; the work item moves the
  product docs forward first, then the code.
- If a stakeholder wants something the product docs don't yet
  describe, the issue moves the **product docs forward first**, then
  (in a separate or sequenced piece of work) the code.
- Bugs are special: by definition the code has drifted from the
  product-docs target. The fix is to correct the code. If the bug
  reveals that the product docs themselves were under-specified, the
  fix is *first* to clarify the product docs, *then* to correct the
  code.

If you find yourself drafting code-shaped work (technical design,
test spec, build plan, code itself) for an issue whose PRD has not
been approved, **stop**. The pipeline is out of order. `set-blocked`
with the reason "PRD not approved; cannot proceed to {your phase}".

### What "product-led" means in practice

- Every issue answers **"what changes for the user?"** before "how do
  we build it?".
- The PRD names personas, user stories, and Gherkin acceptance
  criteria — not API endpoints or table schemas. Implementation
  detail in a PRD is a smell.
- Technical work that does not serve a user-observable outcome (or a
  technical-intermediate state on the roadmap toward one) is a chore,
  sized and reviewed differently. It still requires a target-state
  entry in the product docs (e.g. a non-functional requirement or a
  capability statement).
- "Done" is defined by acceptance criteria the stakeholder approved
  in the PRD — not by "code was written" or "tests pass". Code can
  be perfect against a wrong PRD; that's still wrong.

---

## The lifecycle in three sentences

1. **Per-ticket phases (1–4):** Product docs → Design → Execute →
   Evaluate. Each phase takes the previous phase's artefact as input
   and produces the next phase's input. Design covers technical docs,
   testing spec, and build plan; Execute covers build and test.
2. **Continuous phase (5):** Three loops — Learn (improve the pipeline
   itself), Gap assessment (find drift between design and
   implementation), and Tech debt (surface remediation opportunities).
   They run on schedule, not per ticket.
3. **Humans gate every phase transition** that affects user-visible
   outcomes (PRD, design, test spec, plan, PR, coverage); agents
   transition automatically only between non-gated steps.

The full graph is in
[`pipeline/pipeline.json`](pipeline/pipeline.json). The
orchestrator reads it; you don't. You receive an invocation, do your
one job, and report status.

---

## Core principles you must follow

These are distilled from
[`docs/product/agile/02-principles.md`](../docs/product/agile/02-principles.md).
The full statements and rationale live there.

| ID | What it means for you |
|---|---|
| **P-1** Git is authoritative | All state lives on GitHub: labels, comments, PR/issue bodies, commits. Do not write to a sidecar database, file, or service. |
| **P-2** One source per concern | Standards live in JSON, the pipeline lives in `pipeline.json`. Don't duplicate facts; reference them by ID. |
| **P-4** `:wip` is the mutex | If `{your-agent}:wip` is already on the work item when you start, another runner has it — abort. |
| **P-5** One shippable unit, one PR | Don't open multiple PRs for one issue. Don't conflate two issues into one PR. |
| **P-7** Stable session per (scope, agent) | Your session ID is in `$SESSION_ID`. For `per_issue` agents it is `ais-v1-{safe_agent}-issue-{number}`; for `global` agents it is `ais-v1-{safe_agent}`. The orchestrator passes it as `--session-id` — you don't compute it. Use `$SESSION_ID` in announcements and Question Cards. |
| **P-9** Cross-issue parallel, intra-issue serial | You are not racing other agents on the same issue. You may be racing your siblings on other issues — assume nothing about their state. |
| **P-10** Agents draft, humans decide | Never approve a gate. Never apply a `*:approved` label. Humans do that; the orchestrator promotes you afterward. |
| **P-11** Resumable by default | Be idempotent. If you re-run after rejection, edit your previous comment in place — don't post duplicates. |
| **P-12** Transparent over clever | Post a comment when something halts. Use the named markers. Don't infer state silently. |
| **P-13** Draft PRs early, one branch per PR | (For Execute-phase agents.) Open the PR on the first commit, not at the end. |
| **P-14** Deterministic Python orchestrator | The orchestrator decides who runs next. **You do not invoke other agents.** Do your one job and exit. |
| **P-15** Product-led | Product docs are the target state; code is the current state; issues are the gap. **No code change ships unless it is already described in the product docs.** See "What AI Agile is" above. |

---

## The status contract

Every agent run must terminate with **exactly one** of three sentinel
lines printed to stdout:

```
AI_AGILE_STATUS: complete
AI_AGILE_STATUS: review "short message for stakeholder"
AI_AGILE_STATUS: blocked "reason you could not proceed"
```

The orchestrator reads this sentinel, applies the matching label (and
clears `:wip`), and posts the closing announcement. You do not call
`status.sh` for ceremony — the orchestrator owns all label transitions.

You **must not** emit `AI_AGILE_STATUS: failed`. The orchestrator
applies `:failed` if you exit non-zero without a sentinel (or after all
configured retries are exhausted). If you find yourself wanting to
"mark failed", emit `AI_AGILE_STATUS: blocked` instead — `:failed` is
for crashes the agent cannot describe.

For gated agents (your prompt's frontmatter or `pipeline.json` lists a
`human_gate_label`):

- Emit `AI_AGILE_STATUS: review "message"` after posting your artefact.
- Do **not** emit `AI_AGILE_STATUS: complete` directly. The orchestrator
  promotes `:review` to `:complete` automatically when the human applies
  the gate label. If you bypass `:review`, you have skipped the gate —
  that is a P-10 violation.

---

## How you communicate

Every comment you post starts with a stable marker carrying your
identity:

```
<!-- ai-agile/{type}/v1 by {your-full-agent-name} -->
```

Five marker types, used for these purposes:

| Marker | Use for |
|---|---|
| `announcement/v1` | Opening (post immediately after `set-wip`) and closing (post immediately before your terminal status call) — required on every run |
| `artefact/v1` | The thing you produce that needs review (PRD, design, test spec, etc.) |
| `question/v1` | A structured question to a human or another role (Question Card schema in `docs/product/agile/09-human-interaction.md` §2) |
| `claim/v1` | The mutex claim you post during P-4 acquisition |
| `session/v1` | Per-(object, agent) session metadata; one comment, edited in place |

Free-text prose may sit alongside the JSON; the JSON is the contract.
If they disagree, the JSON wins.

---

## What you must not do

- **Don't apply `*:approved` gate labels.** That's the human's signal
  to advance the pipeline. P-10.
- **Don't emit `AI_AGILE_STATUS: complete` for gated work.** The
  orchestrator promotes `:review` → `:complete` after gate approval.
- **Don't emit `AI_AGILE_STATUS: failed`.** The orchestrator applies
  `:failed` when you crash without a sentinel — you cannot self-report failure.
- **Don't call `status.sh` for ceremony.** set-wip, announcements, and
  label transitions are owned by the orchestrator. Use the `AI_AGILE_STATUS:`
  sentinel only.
- **Don't invoke other agents.** The orchestrator routes work. P-14.
- **Don't edit human-authored content** — issue bodies written by
  the stakeholder, review comments, ADRs after acceptance.
- **Don't write to anywhere other than GitHub** — no sidecar files,
  no external DBs, no temp state that survives your run.
- **Don't use `WebFetch` or `WebSearch`** unless your tool allowlist
  explicitly includes them (it doesn't, by default — security note in
  `12-agent-spec.md`).
- **Don't assume earlier runs left state in your environment.** Read
  GitHub fresh on every invocation.

---

## How you find your inputs

| Input | Where |
|---|---|
| Issue / PR body | `gh issue view $ISSUE_NUMBER --repo $REPO --json title,body,labels,author` |
| Upstream agent's artefact | `gh issue view $ISSUE_NUMBER --repo $REPO --json comments --jq '.comments[] \| select(.body \| contains("ai-agile/artefact/v1 by {upstream-agent}")) \| .body' \| head -1` |
| Standards | JSON under `standards/*.json` (see `docs/product/agile/05-pipeline-config.md`) |
| Pipeline graph | Don't read it. The orchestrator routes work; you focus on your task. |
| Prior runs of yourself | Edit-in-place: re-runs find the prior comment, edit it (P-11). Don't post duplicates. |

Environment variables the orchestrator exports for you:

| Variable | Meaning |
|---|---|
| `AI_AGILE_ROOT` | Absolute path to the consuming repo root — where `standards/` and `.claude/agents/` live after `get_started.py` installation. In standalone dev mode (running ai-coding-standards2 directly), equals the submodule root. |
| `AI_AGILE_CONTEXT` | Absolute path to **this file** |
| `REPO` | `owner/repo` of the consuming repository |
| `ISSUE_NUMBER` | Set when the work item is an issue |
| `PR_NUMBER` | Set when the work item is a PR |
| `WORK_ITEM_KIND` | `issue` or `pr` |
| `WORK_ITEM_NUMBER` | Numeric ID, regardless of kind |
| `SESSION_ID` | The human-readable session key for this invocation (e.g. `ais-v1-01-product-docs-prd-writer-issue-42`). Use it in `session_id` fields of announcement/artefact JSON so runs are traceable. |
| `SESSION_SCOPE` | `per_issue` or `global`. Informational — the orchestrator already passed the right `--session-id` (as a UUID v5 derived from `SESSION_ID`) to the claude CLI. |

### Session scopes

Every agent run is started by the orchestrator with `claude --session-id <uuid>`.
The `--session-id` value is a deterministic UUID v5 derived from `SESSION_ID` — the
two values look different but map 1-to-1. Always use `$SESSION_ID` (the human-readable
form) in your JSON output; the UUID is an internal CLI requirement only.

The scope controls whether `SESSION_ID` is stable across issues or unique per issue:

| Scope | Session ID format | When to use |
|---|---|---|
| `per_issue` | `ais-v1-{safe_agent}-issue-{number}` | Agents that work on one issue at a time and need no memory of other issues. Default for most agents. |
| `global` | `ais-v1-{safe_agent}` | Agents that benefit from accumulated context across all issues — e.g. doc reviewers that build up knowledge of the full `docs/product/` tree. |

The scope for each agent is configured in `pipeline/pipeline.json` under
`"session": {"scope": "..."}`. The default when omitted is `per_issue`.
Custom session ID patterns can be set via `"session": {"scope": "...", "id_pattern": "..."}`;
see `docs/product/agile/05-pipeline-config.md §Session ID tokens` for available tokens.

---

## Todo lists

Todos for in-flight work live **in the body of the issue or PR they belong to** — never in a comment, a file, or a sub-issue. The body is the single, visible, edited-in-place source of truth for what work remains.

### Runtime ephemeral vs. persistent todos

| Type | Tool | Survives run? | Visible in GitHub? |
|---|---|---|---|
| In-session task tracking | `TodoWrite` (Claude runtime tool) | No | No |
| Persistent issue/PR tasks | Body markers (see below) | Yes | Yes |

Use `TodoWrite` freely during a run to keep your multi-step plan organised. Use body markers to record build-plan items, acceptance criteria, or open questions that other agents and humans need to see.

### Body marker format

Todos in issue/PR bodies live inside a delimited block:

```markdown
<!-- ai-agile/todos/v1 START -->
## AI Agile — Tasks

<!-- ai-agile/todos/build-plan/v1 START -->
### Build plan

- [ ] Do the thing (raised 2026-05-04T14:23Z by coder)
- [x] Done thing (raised 2026-05-04T14:00Z by coder, done 2026-05-04T15:00Z by coder)

<!-- ai-agile/todos/build-plan/v1 END -->

_Last updated by `coder` at 2026-05-04T15:01Z_
<!-- ai-agile/todos/v1 END -->
```

Each subsection has its own marker pair. **Only rewrite the subsection you own** — leave other subsections untouched.

### Standard subsections and owners

| Subsection | Owner |
|---|---|
| `ai-agile/todos/build-plan/v1` | `task-decomposer` (issue), `coder` (PR) |
| `ai-agile/todos/acceptance-criteria/v1` | `prd-writer` |
| `ai-agile/todos/open-questions/v1` | orchestrator |
| `ai-agile/todos/standards-remediations/v1` | `standards-compliance-reviewer` (PR only) |
| `ai-agile/todos/test-scenarios/v1` | `test-spec-writer` / `test-runner` (PR only) |

A subsection with no entries is omitted entirely. Checked items are never removed — they are the audit trail.

### Checkbox and annotation format

```
- [ ] {task} (raised <ts> by <actor>)
- [x] {task} (raised <ts> by <actor>, done <ts> by <actor>)
- [ ] {task} (raised <ts> by <actor>, blocked <ts> by <actor>: <reason>)
```

- **Timestamp**: ISO 8601 UTC, minute precision — `YYYY-MM-DDTHH:MMZ`
- **Actor**: bare agent name (e.g. `coder`), `orchestrator`, or `@github-login` for humans

### Anti-patterns

- Don't track todos in comments, `.todo` files, or sub-issues
- Don't edit human-authored prose above the marker block
- Don't write to a subsection you don't own
- Don't remove checked items

---

## Where to look for more detail

This file is the runtime distillation. The full design and reference
material live in these locations — read whichever the situation
demands, not all of them on every run:

| Topic | Location |
|---|---|
| The complete design (vision, principles, lifecycle, status model, gates, audit log, interaction protocol, todos, roadmap, orchestrator design, agent spec) | [`docs/product/agile/`](../docs/product/agile/README.md) — start with the README |
| The pipeline graph (who runs after whom, gates, triggers) | [`pipeline/pipeline.json`](pipeline/pipeline.json) — but the orchestrator reads this; you generally shouldn't need to |
| Status definitions (colours, semantics, transitions) | [`pipeline/statuses.json`](pipeline/statuses.json) |
| Architecture & product standards (load + apply by `STD` ID) | `standards/*.json` (target state — populated as standards are formalised) |
| ADRs (architecture decisions of record) | `standards/adrs.json` |
| Question Card schema (when you need to ask a human something structured) | [`docs/product/agile/09-human-interaction.md`](../docs/product/agile/09-human-interaction.md) §2 |
| Todos in issue/PR bodies (read protocol, write protocol, marker conventions) | [`docs/product/agile/13-todos.md`](../docs/product/agile/13-todos.md) |

When you reference a standard in a comment or commit, use its stable
`STD` ID, not the prose:

```
// STD000000003 — FK columns must follow {table_singular}_id
```

---

## When in doubt

| Situation | Action |
|---|---|
| Input is ambiguous and you would have to guess | `set-blocked` with a Question Card naming the ambiguity |
| Issue is too large for one phase artefact | `set-blocked` with a decomposition recommendation |
| You hit an error you cannot describe | Exit non-zero; the orchestrator will apply `:failed` with your tail of output |
| You think you should bypass a gate | You shouldn't. Re-read P-10 |
| You think you should invoke another agent | You shouldn't. Re-read P-14 |
| Your specific prompt contradicts this document | This document wins |

---

## Document history

This file supersedes the earlier `.claude/AGENTS.md` from the legacy
layout (now archived on the `legacy` branch). Differences from legacy:

- **Product-led framing** is named explicitly as the system's identity.
- **Agent names** use the phase-prefixed form (`{phase}/{short-name}`),
  matching the directory layout under `.claude/agents/`.
- **Status helpers** are referenced as `$STATUS_SH` (orchestrator-
  exported), not the literal `.github/scripts/status.sh` path. Works
  identically whether this repo is checked out at the consuming
  repo's root or as a submodule under it.
- **`set-failed` is removed from the agent's allowlist.** Only the
  orchestrator applies `:failed`; agents that want to halt with detail
  use `set-blocked` instead.
- **Marker convention** carries the agent name as a `by {agent-name}`
  suffix.
