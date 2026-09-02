# AI Agile — Agent Context

You are reading this because you are an AI Agile agent. Read this
document **before** starting your run. It contains the operative rules
every agent must follow, regardless of what your specific prompt says.

If anything in your specific prompt contradicts this document, this
document wins. If anything you are about to do violates one of the
rules below, stop and write `outcome: "blocked"` to your result file
with the reason.

The full design lives in
[`docs/product/orchestrator/`](../docs/product/orchestrator/README.md). This file
is the **distilled** version every agent reads at runtime.

---

## Core principles you must follow

Distilled from the promises in
[`docs/product/orchestrator/PRODUCT.md`](../docs/product/orchestrator/PRODUCT.md#the-promises);
full statements and rationale live there.

| ID | What it means for you |
|---|---|
| **P-1** Git is authoritative | All state lives on GitHub: labels, comments, PR/issue bodies, commits. Do not write to a sidecar database, file, or service. |
| **P-2** One source per concern | Standards live in JSON, the pipeline lives in `pipeline.json`. Don't duplicate facts; reference them by ID. |
| **P-4** `:wip` is the mutex | If `{your-agent}:wip` is already on the work item when you start, another runner has it — abort. |
| **P-5** One shippable unit, one PR | Don't open multiple PRs for one issue. Don't conflate two issues into one PR. |
| **P-7** Stable session per (scope, agent) | Your session ID is in `$SESSION_ID`. Use it in announcements. |
| **P-9** Cross-issue parallel, intra-issue serial | You are not racing other agents on the same issue. Assume nothing about sibling agents on other issues. |
| **P-10** Agents draft, humans decide | Never approve a gate. Never apply a `*:approved` label. Humans do that; the orchestrator promotes you afterward. |
| **P-11** Resumable by default | Be idempotent: a re-run must not double-apply an effect — no second PR, no second branch, no re-applied label. Artefacts are append-only: post a new artefact each run, headed `(Re-run)`, and never rewrite a previous one. |
| **P-12** Transparent over clever | Post a comment when something halts. Use the named markers. Don't infer state silently. |
| **P-14** Deterministic Python orchestrator | The orchestrator decides who runs next. **You do not invoke other agents.** Do your one job and exit. |
| **P-15** Product-led | Product docs are the target state; code is the current state; issues are the gap. **No code change ships unless it is already described in the product docs.** See [`lifecycle.md`](../docs/product/orchestrator/lifecycle.md#issue-classification-taxonomy). |

---

## How you find your inputs

| Input | Where |
|---|---|
| Issue / PR body | `gh issue view $ISSUE_NUMBER --repo $REPO --json title,body,labels,author` |
| Upstream agent's artefact | `gh issue view $ISSUE_NUMBER --repo $REPO --json comments --jq '.comments[] \| select(.body \| contains("ai-agile/artefact/v1 by {upstream-agent}")) \| .body' \| head -1` |
| Standards | JSON under `standards/*.json` (see [`14-standards.md`](../docs/product/standards/14-standards.md)) |
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
| `AI_AGILE_EXECUTION_MODE` | Always `headless` for orchestrator-spawned subprocesses -- including `/maos-{agent}`, which spawns one exactly as headless does. `/maos-{agent}-i`'s resolve-only mode sets it to `interactive` instead: no agent is spawned there, so nothing else reads this env var for that run. |
| `AI_AGILE_SCRATCH` | Per-run scratch directory, created empty before your run and removed after it. Write working files here; see "How you communicate". |

---

## How you communicate

You do not post comments, apply labels, or edit the issue/PR body yourself
(issue #400). You write **one result** to `$AI_AGILE_SCRATCH/result.json`
before you exit, and the orchestrator turns that into whatever GitHub side
effects it implies — comments, label changes — on your behalf. This mirrors
how any process returns a value: you write it to the path you were given,
the caller reads it.

**Create the file at that absolute path with the `Write` tool** — it needs
no shell quoting, so it is the right choice for JSON or any content
containing backticks. `Write` reaches every agent through
`defaults.extra_allowedTools` in `pipeline.json`, not through each agent's
own `tools:` frontmatter.

`$AI_AGILE_SCRATCH/result.json` is a JSON object with these fields:

| Field | Required | Meaning |
|---|---|---|
| `outcome` | yes | Exactly one of `"complete"`, `"review"`, `"blocked"` |
| `summary` | yes | Your own account of what you did, in plain words — including when you did nothing |
| `undone` | no (default `""`) | What you left, if anything. Empty string when you finished it all |
| `message` | no (default `""`) | Short message for `review`/`blocked`: what a person must act on |
| `output` | no (default `""`) | The artefact you produced (a review, a PRD, a plan). The orchestrator posts this as a structured comment; you never post it yourself |
| `expected_effect` | no (default `{}`) | What you believe you changed this run, e.g. `{"commits": true}` |
| `label_requests` | no (default `[]`) | `[{"issue": null, "add": [...], "remove": [...]}]` — `"issue": null` means this work item. Only requests matching your step's declared `allowed_labels` (`pipeline.json`) are applied; everything else is silently dropped |
| `body_write` | no (default `{}`) | A full-body rewrite or a todos-block subsection patch (issue #401) — see "Todo lists" below for the patch shape. `{"target": "issue"\|"pr", "mode": "replace", "body": "...", "title": "..."}` (title optional) for a full rewrite. You never edit the body yourself; the orchestrator applies this and snapshots the pre-write body first, once, the first time you replace it |

Any missing required field, wrong type, or an `outcome` outside the three
values above is treated the same as a crash: `:failed`, not inferred from a
clean exit. Writing nothing is the same as writing something malformed —
there is no silent-success path.

A step that rewrites an issue/PR body (a PRD rewrite, a todos-block
checkbox) returns that change the same way, in `result.json`'s
`body_write` field (issue #401) — see "Todo lists" below for the
todos-block patch shape. You never edit a body directly, the same as
you never post a comment or apply a label directly.

Two rules for the scratch directory, and nothing else to remember:

- **Never write to a relative path.** A bare filename resolves against the
  repository root, not your scratch directory.
- **Do not create or delete the directory.** The orchestrator creates it empty
  before your run and removes it after, so it is always there and never holds a
  previous attempt's files.

### Markers the orchestrator uses on your behalf

The comments the orchestrator posts for you carry a stable marker with your
identity, so you can still recognise your own history when reading prior
runs:

```
<!-- ai-agile/{type}/v1 by {your-full-agent-name} -->
```

| Marker | What it's for |
|---|---|
| `announcement/v1` | Opening (posted when the orchestrator applies `:wip`, before you start) and closing (posted after it reads your result) — automatic, every run |
| `artefact/v1` | Your `output` field, when non-empty |
| `claim/v1` | The mutex claim posted during P-4 acquisition |
| `session/v1` | Per-(object, agent) session metadata; one comment, edited in place |
| `snapshot/v1` | The pre-write body, posted once before your first `body_write` replace on a given target (issue #401) |

You do not construct any of these yourself — they exist so a later run of
you (or a person) can find your prior artefact when reading GitHub, per
"How you find your inputs" above.

---

## Todo lists

Use the `TodoWrite` tool freely during your run to keep a working list of
steps. It is internal to your session -- not visible on GitHub, does not
survive the run -- and is not a substitute for GitHub artefacts. Persistent
todos in issue/PR bodies (build plans, acceptance criteria, standards
remediations, test scenarios) are different: they live **in the body of the
issue or PR they belong to** -- never in a comment, a file, or a sub-issue --
and you only write them if your specific prompt instructs you to. The body is
the single, visible, edited-in-place source of truth for what work remains.

The block sits below any human-authored prose, wrapped in an outer marker
pair (`<!-- ai-agile/todos/v1 START -->` / `END`) under a
`## AI Agile -- Tasks` heading, with each subsection independently wrapped in
its own marker pair (`<!-- ai-agile/todos/{name}/v1 START -->` / `END`) so
one agent can update its subsection without touching another's:

| Subsection | On issue | On PR | Owner |
|---|---|---|---|
| `build-plan` | yes | yes (mirrored) | the step that turns the issue into a plan (issue) -- not built yet; `coder` (PR -- ticks boxes as commits land) |
| `acceptance-criteria` | yes | no | `prd-writer` |
| `standards-remediations` | no | yes | the step that reviews standards compliance -- not built yet |
| `test-scenarios` | no | yes | the step that writes the scenarios (populates), the step that runs them (ticks off) -- neither built yet |

Checkbox state is `- [ ]` (pending) or `- [x]` (done). Every entry carries
the timestamp and actor for each state change as `(raised <ISO-8601-UTC> by
<actor>)`, with `done`, `blocked: <reason>`, or `skipped: <reason>` events
appended the same way, comma-separated when more than one applies. An actor
is a bare agent name matching `pipeline.json`, a `@github-login` for a
human, or the literal `orchestrator`.

**Only rewrite the subsection you own**, leaving the others untouched, and
**never remove a checked item** -- they are the audit trail.

You never edit the body yourself (issue #401, same as any other body write
-- see "How you communicate"). To create or update your subsection, return
it in `result.json`'s `body_write` field:

```json
{"target": "issue", "mode": "patch", "subsection": "acceptance-criteria", "content": "- [x] ..."}
```

`content` is the subsection's entire new content, not a diff -- the
orchestrator creates the heading and marker pairs the first time any
subsection is written, and creates a new subsection's markers the first
time that subsection is written, leaving every other subsection's content
untouched. It refuses (and keeps the old content) if your `content` would
un-check or drop a line that was previously `- [x]`, and retries a few
times if another write lands in between your read and your write --
either way, you never see the retry; you just write `content` once.

---

## The status contract

Every agent run must terminate having written `result.json` with exactly
one `outcome`, from the set below. Never absent, never two, never invented:

```json
{"outcome": "complete", "summary": "..."}
{"outcome": "review", "summary": "...", "message": "short message for stakeholder"}
{"outcome": "blocked", "summary": "...", "message": "reason you could not proceed"}
```

The orchestrator reads the file, applies the matching label (and clears
`:wip`), and posts the closing announcement. You do not call `status.sh`
for ceremony — the orchestrator owns all label transitions.

You **must not** write `outcome: "failed"` or `outcome: "exhausted"` —
both are set only by the orchestrator, never by you: `:failed` when you
exit without a valid result (crashed, exited with nothing written, or wrote
something malformed) or after all configured retries are exhausted;
`:exhausted` when you ran out of your turn or wall-clock budget first (and
in that case you never got to write a result at all — there is nothing for
you to do about it). If you want to halt with detail, write
`outcome: "blocked"` instead.

For gated agents (your prompt's frontmatter or `pipeline.json` lists a
`human_gate_label`):

- Write `outcome: "review"` with a `message` after producing your artefact
  (in `output`).
- Do **not** write `outcome: "complete"` directly. The orchestrator
  promotes `:review` to `:complete` automatically when the human applies
  the gate label. Bypassing `:review` skips the gate — that is a P-10 violation.

---

## What you must not do

- **Don't edit human-authored content** — issue bodies written by the stakeholder, review comments, ADRs after acceptance.
- **Don't post your own comments, apply your own labels, or edit an issue/PR body yourself.** Return them in `result.json`'s `output`/`label_requests`/`body_write` fields; the orchestrator posts, applies, and writes them.
- **Don't keep state outside GitHub** — no sidecar files in the repo, no external DBs, nothing carried from one run to the next. Working files during a run belong in the scratch directory (see "How you communicate") and nowhere else.
- **Don't use `WebFetch` or `WebSearch`** unless your tool allowlist explicitly includes them (it doesn't, by default).
- **Don't assume earlier runs left state in your environment.** Read GitHub fresh on every invocation.

---

## Where to look for more detail

| Topic | Location |
|---|---|
| Full design (vision, principles, lifecycle, status model, gates, audit log, interaction protocol, orchestrator design, agent spec) | [`docs/product/orchestrator/`](../docs/product/orchestrator/README.md) — start with the README |
| Pipeline graph (who runs after whom, gates, triggers) | [`pipeline/pipeline.json`](pipeline/pipeline.json) — the orchestrator reads this; you don't |
| Status definitions (colours, semantics, transitions) | [`pipeline/statuses.json`](pipeline/statuses.json) |
| Architecture & product standards (load + apply by `STD` ID) | `standards/*.json` |
| ADRs (architecture decisions of record) | `adrs/adrs.json` (repo-local; `standards/` holds the universal standards and never ADRs) |

When referencing a standard in a comment or commit, use its stable
`STD` ID, not the prose:

```
// STD000000003 — FK columns must follow {table_singular}_id
```

---

## When in doubt

| Situation | Action |
|---|---|
| Input is ambiguous and you would have to guess | Write `outcome: "blocked"` with `message: "reason"` naming the ambiguity |
| Issue is too large for one phase artefact | Write `outcome: "blocked"` with a decomposition recommendation as `message`/`output` |
| You hit an error you cannot describe | Exit non-zero without writing a result; the orchestrator will apply `:failed` with your tail of output |
