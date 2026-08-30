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
| **P-15** Product-led | Product docs are the target state; code is the current state; issues are the gap. **No code change ships unless it is already described in the product docs.** See [`04-lifecycle.md`](../docs/product/orchestrator/04-lifecycle.md#issue-classification-taxonomy). |

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
| `AI_AGILE_EXECUTION_MODE` | Always `headless` for orchestrator-spawned subprocesses. The `/run-agent` interactive path sets it to `interactive` instead. |
| `AI_AGILE_SCRATCH` | Per-run scratch directory, created empty before your run and removed after it. Write working files here; see "How you communicate". |

---

## How you communicate

Every comment you post starts with a stable marker carrying your
identity:

```
<!-- ai-agile/{type}/v1 by {your-full-agent-name} -->
```

Four marker types:

| Marker | Use for |
|---|---|
| `announcement/v1` | Opening (post immediately after `set-wip`) and closing (post immediately before your terminal status call) — required on every run |
| `artefact/v1` | The thing you produce that needs review (PRD, design, test spec, etc.) |
| `claim/v1` | The mutex claim you post during P-4 acquisition |
| `session/v1` | Per-(object, agent) session metadata; one comment, edited in place |

Free-text prose may sit alongside JSON; the JSON is the contract.
If they disagree, the JSON wins.

Working files stay out of the repo. Your scratch directory is
`$AI_AGILE_SCRATCH`, given as an absolute path in your Runtime context below.

**Create working files at that absolute path**, using whichever of these two
fits -- there is no third option:

- **`Write`** for a body you compose yourself. It needs no shell quoting, so it
  is the right choice for JSON or any body containing backticks -- a heredoc
  body with backticks is scanned for command substitution and refused.
  `Write` reaches every agent through `defaults.extra_allowedTools` in
  `pipeline.json`, not through each agent's own `tools:` frontmatter.
- **`cat > "${AI_AGILE_SCRATCH:-/tmp}/name.md" <<EOF`** when the body must interpolate
  shell variables you hold at runtime (`$SESSION_ID`, `$VERDICT`). Quote the
  delimiter (`<<'EOF'`) to suppress expansion. Start the command with `cat` --
  a leading variable assignment matches no allowlist pattern and is denied.

### Posting a comment -- the only supported form

This is the same for every agent, on both issues and PRs. Stage the body by
either route above, then post it by path:

```bash
gh api --method POST "repos/$REPO/issues/$WORK_ITEM_NUMBER/comments" \
  -F body=@"${AI_AGILE_SCRATCH:-/tmp}/body.md"
```

A PR is an issue as far as this endpoint is concerned, so `issues/{n}/comments`
posts to both -- use `$PR_NUMBER` in place of `$WORK_ITEM_NUMBER` when your
step targets a PR.

Two forms you will see in older prompts. Neither works; do not copy them:

| Form | Why it fails |
|---|---|
| `gh pr comment` / `gh pr review` / `gh pr ready` | GraphQL. Returns 403 in a restricted session |
| `--body "$(cat <<EOF ... EOF)"` | `$(` is command substitution, which scope enforcement refuses outright |

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
todos in issue/PR bodies (build plans, acceptance criteria, standards
remediations, test scenarios) are different: they live **in the body of the
issue or PR they belong to** -- never in a comment, a file, or a sub-issue --
and you only write them if your specific prompt instructs you to. The body is
the single, visible, edited-in-place source of truth for what work remains.

The block sits below any human-authored prose, wrapped in an outer marker
pair (`<!-- ai-agile/todos/v1 START -->` / `END`) under a
`## AI Agile — Tasks` heading, with each subsection independently wrapped in
its own marker pair (`<!-- ai-agile/todos/{name}/v1 START -->` / `END`) so
one agent can update its subsection without touching another's:

| Subsection | On issue | On PR | Owner |
|---|---|---|---|
| `build-plan` | yes | yes (mirrored) | `task-decomposer` (issue), `coder` (PR -- ticks boxes as commits land) |
| `acceptance-criteria` | yes | no | `prd-writer` |
| `standards-remediations` | no | yes | `standards-compliance-reviewer` |
| `test-scenarios` | no | yes | `test-spec-writer` (populates), `test-runner` (ticks off) |

Checkbox state is `- [ ]` (pending) or `- [x]` (done). Every entry carries
the timestamp and actor for each state change as `(raised <ISO-8601-UTC> by
<actor>)`, with `done`, `blocked: <reason>`, or `skipped: <reason>` events
appended the same way, comma-separated when more than one applies. An actor
is a bare agent name matching `pipeline.json`, a `@github-login` for a
human, or the literal `orchestrator`.

**Only rewrite the subsection you own**, leaving the others untouched, and
**never remove a checked item** -- they are the audit trail.

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
| Input is ambiguous and you would have to guess | Emit `AI_AGILE_STATUS: blocked "reason"` naming the ambiguity |
| Issue is too large for one phase artefact | Emit `AI_AGILE_STATUS: blocked` with a decomposition recommendation |
| You hit an error you cannot describe | Exit non-zero; the orchestrator will apply `:failed` with your tail of output |
