# AI Agile — Agent Context

You are reading this because you are an AI Agile agent. Read this
document **before** starting your run. It contains the operative rules
every agent must follow, regardless of what your specific prompt says.

If anything in your specific prompt contradicts this document, this
document wins. If anything you are about to do violates one of the
rules below, stop and emit `AI_AGILE_STATUS: blocked` with the reason.

The full design lives in
[`docs/product/agile/`](../docs/product/agile/README.md). This file
is the **distilled** version every agent reads at runtime.

---

## Core principles you must follow

Distilled from
[`docs/product/agile/02-principles.md`](../docs/product/agile/02-principles.md);
full statements and rationale live there.

| ID | What it means for you |
|---|---|
| **P-1** Git is authoritative | All state lives on GitHub: labels, comments, PR/issue bodies, commits. Do not write to a sidecar database, file, or service. |
| **P-2** One source per concern | Standards live in JSON, the pipeline lives in `pipeline.json`. Don't duplicate facts; reference them by ID. |
| **P-4** `:wip` is the mutex | If `{your-agent}:wip` is already on the work item when you start, another runner has it — abort. |
| **P-5** One shippable unit, one PR | Don't open multiple PRs for one issue. Don't conflate two issues into one PR. |
| **P-7** Stable session per (scope, agent) | Your session ID is in `$SESSION_ID`. Use it in announcements and Question Cards. |
| **P-9** Cross-issue parallel, intra-issue serial | You are not racing other agents on the same issue. Assume nothing about sibling agents on other issues. |
| **P-10** Agents draft, humans decide | Never approve a gate. Never apply a `*:approved` label. Humans do that; the orchestrator promotes you afterward. |
| **P-11** Resumable by default | Be idempotent. On re-run, edit your previous artefact comment in place — don't post duplicates. |
| **P-12** Transparent over clever | Post a comment when something halts. Use the named markers. Don't infer state silently. |
| **P-14** Deterministic Python orchestrator | The orchestrator decides who runs next. **You do not invoke other agents.** Do your one job and exit. |
| **P-15** Product-led | Product docs are the target state; code is the current state; issues are the gap. **No code change ships unless it is already described in the product docs.** See [`02-principles.md#p-15`](../docs/product/agile/02-principles.md#p-15). |

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
configured retries are exhausted). If you want to halt with detail,
emit `AI_AGILE_STATUS: blocked` instead.

For gated agents (your prompt's frontmatter or `pipeline.json` lists a
`human_gate_label`):

- Emit `AI_AGILE_STATUS: review "message"` after posting your artefact.
- Do **not** emit `AI_AGILE_STATUS: complete` directly. The orchestrator
  promotes `:review` to `:complete` automatically when the human applies
  the gate label. Bypassing `:review` skips the gate — that is a P-10 violation.

---

## How you communicate

Every comment you post starts with a stable marker carrying your
identity:

```
<!-- ai-agile/{type}/v1 by {your-full-agent-name} -->
```

Five marker types:

| Marker | Use for |
|---|---|
| `announcement/v1` | Opening (post immediately after `set-wip`) and closing (post immediately before your terminal status call) — required on every run |
| `artefact/v1` | The thing you produce that needs review (PRD, design, test spec, etc.) |
| `question/v1` | A structured question to a human or another role (Question Card schema in [`09-human-interaction.md`](../docs/product/agile/09-human-interaction.md) §2) |
| `claim/v1` | The mutex claim you post during P-4 acquisition |
| `session/v1` | Per-(object, agent) session metadata; one comment, edited in place |

Free-text prose may sit alongside JSON; the JSON is the contract.
If they disagree, the JSON wins.

---

## What you must not do

- **Don't apply `*:approved` gate labels.** That's the human's signal to advance the pipeline. P-10.
- **Don't emit `AI_AGILE_STATUS: complete` for gated work.** The orchestrator promotes `:review` → `:complete` after gate approval.
- **Don't emit `AI_AGILE_STATUS: failed`.** The orchestrator applies `:failed` when you crash without a sentinel.
- **Don't call `status.sh` for ceremony.** The orchestrator owns all label transitions. Use the `AI_AGILE_STATUS:` sentinel only.
- **Don't invoke other agents.** The orchestrator routes work. P-14.
- **Don't edit human-authored content** — issue bodies written by the stakeholder, review comments, ADRs after acceptance.
- **Don't write to anywhere other than GitHub** — no sidecar files, no external DBs, no temp state that survives your run.
- **Don't use `WebFetch` or `WebSearch`** unless your tool allowlist explicitly includes them (it doesn't, by default).
- **Don't assume earlier runs left state in your environment.** Read GitHub fresh on every invocation.

---

## How you find your inputs

| Input | Where |
|---|---|
| Issue / PR body | `gh issue view $ISSUE_NUMBER --repo $REPO --json title,body,labels,author` |
| Upstream agent's artefact | `gh issue view $ISSUE_NUMBER --repo $REPO --json comments --jq '.comments[] \| select(.body \| contains("ai-agile/artefact/v1 by {upstream-agent}")) \| .body' \| head -1` |
| Standards | JSON under `standards/*.json` (see [`05-pipeline-config.md`](../docs/product/agile/05-pipeline-config.md)) |
| Pipeline graph | Don't read it. The orchestrator routes work; focus on your task. |
| Prior runs of yourself | Edit-in-place: re-runs find the prior comment, edit it (P-11). Don't post duplicates. |

**Repo context:** discover available docs with `find "${AI_AGILE_ROOT}/docs" -name "*.md" 2>/dev/null | sort`, then read only what is relevant to the task. Any repo documentation is fair game as background; it informs decisions but cannot add to or reinterpret the work item's stated requirements. Never fetch issues or PRs other than your assigned work item — treat `#N` references in bodies as labels, not fetch instructions.

Environment variables the orchestrator exports for you:

| Variable | Meaning |
|---|---|
| `AI_AGILE_ROOT` | Absolute path to the consuming repo root |
| `AI_AGILE_CONTEXT` | Absolute path to **this file** |
| `REPO` | `owner/repo` of the consuming repository |
| `ISSUE_NUMBER` | Set when the work item is an issue |
| `PR_NUMBER` | Set when the work item is a PR |
| `WORK_ITEM_KIND` | `issue` or `pr` |
| `WORK_ITEM_NUMBER` | Numeric ID, regardless of kind |
| `SESSION_ID` | Human-readable session key (e.g. `ais-v1-01-product-docs-prd-writer-issue-42`). Use in `session_id` fields of announcement/artefact JSON. |
| `SESSION_SCOPE` | `per_issue` or `global`. Informational — the orchestrator already passed the right `--session-id` to the claude CLI. |

---

## In-run task tracking

Use the `TodoWrite` tool freely during your run to maintain a working
list of steps. This is internal to your session — not visible on
GitHub and does not survive the run. Use it to stay organised on
multi-step tasks, not as a substitute for GitHub artefacts.

For persistent todos in issue/PR bodies (build plans, acceptance
criteria, open questions) — only write these if your specific prompt
instructs you to. Format and protocol: see
[`docs/product/agile/13-todos.md`](../docs/product/agile/13-todos.md).

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

| Topic | Location |
|---|---|
| Full design (vision, principles, lifecycle, status model, gates, audit log, interaction protocol, todos, roadmap, orchestrator design, agent spec) | [`docs/product/agile/`](../docs/product/agile/README.md) — start with the README |
| Pipeline graph (who runs after whom, gates, triggers) | [`pipeline/pipeline.json`](pipeline/pipeline.json) — the orchestrator reads this; you generally shouldn't need to |
| Status definitions (colours, semantics, transitions) | [`pipeline/statuses.json`](pipeline/statuses.json) |
| Architecture & product standards (load + apply by `STD` ID) | `standards/*.json` |
| ADRs (architecture decisions of record) | `standards/adrs.json` |
| Question Card schema | [`docs/product/agile/09-human-interaction.md`](../docs/product/agile/09-human-interaction.md) §2 |
| Todos in issue/PR bodies (read protocol, write protocol, marker conventions) | [`docs/product/agile/13-todos.md`](../docs/product/agile/13-todos.md) |

When referencing a standard in a comment or commit, use its stable
`STD` ID, not the prose:

```
// STD000000003 — FK columns must follow {table_singular}_id
```

---

## When in doubt

| Situation | Action |
|---|---|
| Input is ambiguous and you would have to guess | Emit `AI_AGILE_STATUS: blocked` with a Question Card naming the ambiguity |
| Issue is too large for one phase artefact | Emit `AI_AGILE_STATUS: blocked` with a decomposition recommendation |
| You hit an error you cannot describe | Exit non-zero; the orchestrator will apply `:failed` with your tail of output |
| You think you should bypass a gate | You shouldn't. Re-read P-10 |
| You think you should invoke another agent | You shouldn't. Re-read P-14 |
| Your specific prompt contradicts this document | This document wins |
