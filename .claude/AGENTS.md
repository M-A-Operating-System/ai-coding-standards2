# AI Agile — Agent Context

You are reading this because you are an AI Agile agent. Read this
document **before** starting your run. It contains the operative rules
every agent must follow, regardless of what your specific prompt says.

If anything in your specific prompt contradicts this document, this
document wins. If anything you are about to do violates one of the
rules below, stop and emit `AI_AGILE_STATUS: blocked` with the reason.

The full design lives in
[`docs/product/orchestrator/`](../docs/product/orchestrator/README.md). This file
is the **distilled** version every agent reads at runtime.

---

## Core principles you must follow

Distilled from
[`docs/product/orchestrator/02-principles.md`](../docs/product/orchestrator/02-principles.md);
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
| **P-11** Resumable by default | Be idempotent: a re-run must not double-apply an effect — no second PR, no second branch, no re-applied label. Artefacts are append-only: post a new artefact each run, headed `(Re-run)`, and never rewrite a previous one. |
| **P-12** Transparent over clever | Post a comment when something halts. Use the named markers. Don't infer state silently. |
| **P-14** Deterministic Python orchestrator | The orchestrator decides who runs next. **You do not invoke other agents.** Do your one job and exit. |
| **P-15** Product-led | Product docs are the target state; code is the current state; issues are the gap. **No code change ships unless it is already described in the product docs.** See [`02-principles.md#p-15`](../docs/product/orchestrator/02-principles.md#p-15). |

---

## How you find your inputs

| Input | Where |
|---|---|
| Issue / PR body | `gh issue view $ISSUE_NUMBER --repo $REPO --json title,body,labels,author` |
| Upstream agent's artefact | `gh issue view $ISSUE_NUMBER --repo $REPO --json comments --jq '.comments[] \| select(.body \| contains("ai-agile/artefact/v1 by {upstream-agent}")) \| .body' \| head -1` |
| Standards | JSON under `standards/*.json` (see [`05-pipeline-config.md`](../docs/product/orchestrator/05-pipeline-config.md)) |
| Pipeline graph | Don't read it. The orchestrator routes work; focus on your task. |
| Prior runs of yourself | Read them, don't rewrite them. Find your prior artefact to head this run `(Re-run)` and to see what you said last time; post a new one (P-11). |

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
| `AI_AGILE_EXECUTION_MODE` | Always `headless` for orchestrator-spawned subprocesses. The `/run-agent` interactive path sets it to `interactive` instead. |
| `AI_AGILE_SCRATCH` | Per-run scratch directory, created empty before your run and removed after it. Write working files here; see "How you communicate". |

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
| `question/v1` | A structured question to a human or another role (Question Card schema in [`09-human-interaction.md`](../docs/product/orchestrator/09-human-interaction.md) §2) |
| `claim/v1` | The mutex claim you post during P-4 acquisition |
| `session/v1` | Per-(object, agent) session metadata; one comment, edited in place |

Free-text prose may sit alongside JSON; the JSON is the contract.
If they disagree, the JSON wins.

Working files stay out of the repo. Your scratch directory is
`$AI_AGILE_SCRATCH`, given as an absolute path in your Runtime context below.

**Create working files with the `Write` tool, at that absolute path.** Every
agent has `Write`, and it needs no shell quoting -- which is why it is the
route to use for a body containing JSON or a fenced block. Then post the file
by path:

```bash
gh api --method POST "repos/$REPO/issues/$PR_NUMBER/comments" \
  -F body=@"$AI_AGILE_SCRATCH/body.md"
```

Two rules, and nothing else to remember:

- **Never write to a relative path.** A bare filename resolves against the
  repository root, not your scratch directory.
- **Do not create or delete the directory.** The orchestrator creates it empty
  before your run and removes it after, so it is always there and never holds a
  previous attempt's files.

---

## Todo lists

Use the `TodoWrite` tool freely during your run to keep a working list of
steps. It is internal to your session -- not visible on GitHub, does not
survive the run -- and is not a substitute for GitHub artefacts. Persistent
todos in issue/PR bodies (build plans, acceptance criteria, open questions)
are different: they live **in the body of the issue or PR they belong to** --
never in a comment, a file, or a sub-issue -- and you only write them if your
specific prompt instructs you to. The body is the single, visible,
edited-in-place source of truth for what work remains.

**Only rewrite the subsection you own**, leaving the others untouched, and
**never remove a checked item** -- they are the audit trail. Marker format,
subsection owners, and checkbox syntax:
[`13-todos.md`](../docs/product/orchestrator/13-todos.md).

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

## What you must not do

- **Don't edit human-authored content** — issue bodies written by the stakeholder, review comments, ADRs after acceptance.
- **Don't keep state outside GitHub** — no sidecar files in the repo, no external DBs, nothing carried from one run to the next. Working files during a run belong in the scratch directory (see "How you communicate") and nowhere else.
- **Don't use `WebFetch` or `WebSearch`** unless your tool allowlist explicitly includes them (it doesn't, by default).
- **Don't assume earlier runs left state in your environment.** Read GitHub fresh on every invocation.

---

## Where to look for more detail

| Topic | Location |
|---|---|
| Full design (vision, principles, lifecycle, status model, gates, audit log, interaction protocol, todos, roadmap, orchestrator design, agent spec) | [`docs/product/orchestrator/`](../docs/product/orchestrator/README.md) — start with the README |
| Pipeline graph (who runs after whom, gates, triggers) | [`pipeline/pipeline.json`](pipeline/pipeline.json) — the orchestrator reads this; you don't |
| Status definitions (colours, semantics, transitions) | [`pipeline/statuses.json`](pipeline/statuses.json) |
| Architecture & product standards (load + apply by `STD` ID) | `standards/*.json` |
| ADRs (architecture decisions of record) | `standards/adrs.json` |
| Question Card schema | [`docs/product/orchestrator/09-human-interaction.md`](../docs/product/orchestrator/09-human-interaction.md) §2 |
| Todos in issue/PR bodies (read protocol, write protocol, marker conventions) | [`docs/product/orchestrator/13-todos.md`](../docs/product/orchestrator/13-todos.md) |

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
