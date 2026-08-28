# Todos

Todos for in-flight work live **in the body of the issue or PR they
belong to** — never as a separate comment, never as a separate file,
never as a sub-issue. The body is the single, visible, edited-in-place
source of truth for what work remains.

This document defines the storage format, the section ownership rules,
and the read/write protocol agents and humans use to keep the body
consistent.

---

## Scope

The following are **todos** under this spec:

- Build-plan child tasks produced by `task-decomposer` (Phase 4)
- Acceptance criteria copied from the approved PRD (Phase 1)
- Standards remediations raised by `standards-compliance-reviewer`
  (Phase 5, PR side only)
- Open Question Cards awaiting human answers (any phase)
- Test scenarios pending implementation (Phase 6, PR side only)

The following are **not** todos and have their own mechanism:

| Concept | Mechanism |
|---|---|
| Agent statuses | `{agent}:{status}` labels ([The state machine](PRODUCT.md#the-state-machine)) |
| Human gates | `{gate}:approved` labels ([Human gates](04-lifecycle.md#human-gates)) |
| Cross-issue dependencies | GitHub `blocked-by` issue links |
| Per-agent internal task backlogs (cross-ticket agents) | See "Cross-ticket agent trackers" below — these live in a dedicated tracker issue body, one per agent |
| Standards proposals | Issues filed by `standards-evolver` |

---

## Storage

| Object | Where todos live |
|---|---|
| Issue (the shippable unit) | Issue body, in the todos block |
| PR (the working unit) | PR body, in the todos block |
| Sub-issue (a child task) | Sub-issue body, in the todos block (typically empty — the parent owns the build plan) |

There is exactly one todos block per body. It is appended at the end of
the body, below any human-authored prose. The block is delimited by
stable markers so the orchestrator and agents can find and update it
without touching surrounding content.

---

## The todos block

The block is structured as an outer marker pair (`ai-agile/todos/v1`)
wrapping the whole block, a `## AI Agile — Tasks` heading, one or more
subsections (each with its own marker pair so agents can update one
subsection without parsing or rewriting the others), and a
`_Last updated_` footer. For example, the open-questions subsection:

```markdown
<!-- ai-agile/todos/open-questions/v1 START -->
### Open questions

- [ ] Q-ais-v1-iss-42-architect-001 — schema choice (raised 2026-05-04T14:23Z by orchestrator, asked of: engineer)

<!-- ai-agile/todos/open-questions/v1 END -->
```

See the [PR body example](#pr-body-example) below for a complete block
showing the outer markers, heading, multiple subsections, and footer
together.

---

## Standard subsections

| Subsection marker | On issue body | On PR body | Owner |
|---|---|---|---|
| `ai-agile/todos/build-plan/v1` | yes | yes (mirrored from issue) | `task-decomposer` (issue), `coder` (PR — updates as commits land) |
| `ai-agile/todos/acceptance-criteria/v1` | yes | no | `prd-writer` (populates after `01_product_docs/prd-writer:approved`) |
| `ai-agile/todos/open-questions/v1` | yes | yes | Orchestrator (updated when Question Cards open / answer / withdraw) |
| `ai-agile/todos/standards-remediations/v1` | no | yes | `standards-compliance-reviewer` |
| `ai-agile/todos/test-scenarios/v1` | no | yes | `test-spec-writer` (populates), `test-runner` (ticks off as scenarios pass) |

A subsection that has no entries is omitted, not left empty. When all
items in a subsection are checked or no longer apply, the writing agent
removes the subsection markers and content together.

---

## Status semantics

The body uses GitHub's native task-list rendering. Two states are
authoritative:

| Marker | Meaning |
|---|---|
| `- [ ]` | Pending |
| `- [x]` | Done |

Every entry carries the timestamp and actor for each state change,
annotated as `(raised …)`, `(done …)`, `(blocked …: <reason>)`, or
`(skipped …: <reason>)`. Multiple events on the same entry are
concatenated with commas in the order they occurred; GitHub renders the
checkbox regardless of annotation, so the visual state stays accurate.
The full annotation grammar — event formats, timestamp grammar, and
actor grammar — is defined in
[Timestamp and actor format](#timestamp-and-actor-format) below.

---

## Read protocol

Agents read todos by fetching the body and parsing between the markers.

```bash
gh issue view $ISSUE_NUMBER --repo $REPO --json body -q '.body' \
  | sed -n '/<!-- ai-agile\/todos\/build-plan\/v1 START -->/,/<!-- ai-agile\/todos\/build-plan\/v1 END -->/p'
```

The orchestrator and the validator use the same regex on the markers.
There is no JSON parsing or structured-API call — the body is rendered
markdown and parsed as text.

To find the next pending task:

```bash
# returns the first unchecked line in the build-plan subsection
gh issue view $ISSUE_NUMBER --repo $REPO --json body -q '.body' \
  | awk '/<!-- ai-agile\/todos\/build-plan\/v1 START -->/{f=1;next} /<!-- ai-agile\/todos\/build-plan\/v1 END -->/{f=0} f && /^- \[ \]/' \
  | head -1
```

---

## Write protocol

A body update is **section-scoped**: the agent rewrites only the
content between one subsection's markers, leaving other subsections and
the surrounding body unchanged.

```
1. Read the current body and its ETag (Last-Modified header).
2. Locate the subsection markers the agent owns.
3. Splice in the new subsection content between the markers.
4. PATCH the issue/PR with If-Match: <etag>.
5. On 412 Precondition Failed:
   → another writer landed in between; re-read and retry (max 3 times).
6. On 3 consecutive 412s:
   → emit a `body.write_conflict` audit event and set-blocked.
```

The ETag protocol is identical to the optimistic-concurrency pattern the
orchestrator uses elsewhere. Agents that write to the body must use the
shared helper at `.github/scripts/body_update.sh`, which encapsulates
the read-update-retry loop.

**Multiple agents writing in parallel.** Two agents updating different
subsections in the same body can collide on step 4 (ETag mismatch),
because the body is one resource. The retry loop resolves this in
practice — the second writer re-reads, finds its target subsection
unchanged, and rewrites successfully on the second attempt. The mutex
on `(object, agent)` (P-4) means at most one instance of any given
agent runs against a body at any time, so retries are bounded.

**Subsection markers must always come back together.** Stripping one
END marker without its START is forbidden — the validator rejects
malformed bodies. The CI check `validate_todos_block.py` runs on every
PR that includes a body change.

---

## Issue body example

After the product-docs phase, an issue body carries the stakeholder's
original prose followed by the todos block with the
`acceptance-criteria` and `build-plan` subsections (acceptance-criteria
first, then build-plan, each populated as shown in the [PR body
example](#pr-body-example) below but with all items unchecked). The
prose above the marker block is the stakeholder's original issue; agents
never modify it.

---

## PR body example

A typical PR body partway through implementation:

```markdown
Implements last-login tracking. Closes #42.

## Approach

- Adds the column with a default of `NULL` (existing rows get the
  default; backfill not needed for the use case).
- Middleware updates `last_login_at` on every authenticated request.
- One audit log row per update, per `STD000000007`.

<!-- ai-agile/todos/v1 START -->
## AI Agile — Tasks

<!-- ai-agile/todos/build-plan/v1 START -->
### Build plan

- [x] Add `last_login_at` column to `users` table (#43) (raised 2026-05-04T14:23Z by task-decomposer, done 2026-05-04T15:48Z by coder)
- [x] Wire up middleware to update on each request (#44) (raised 2026-05-04T14:23Z by task-decomposer, done 2026-05-04T16:31Z by coder)
- [ ] Add Gherkin scenarios and tests (#45) (raised 2026-05-04T14:23Z by task-decomposer)

<!-- ai-agile/todos/build-plan/v1 END -->

<!-- ai-agile/todos/standards-remediations/v1 START -->
### Standards remediations

- [ ] STD000000007 — activity log entry missing for failed login attempts (raised 2026-05-04T16:38Z by standards-compliance-reviewer)

<!-- ai-agile/todos/standards-remediations/v1 END -->

<!-- ai-agile/todos/test-scenarios/v1 START -->
### Test scenarios

- [x] Successful login updates `last_login_at` (raised 2026-05-04T13:02Z by test-spec-writer, done 2026-05-04T16:40Z by test-runner)
- [ ] Failed login does **not** update `last_login_at` (raised 2026-05-04T13:02Z by test-spec-writer)
- [ ] Concurrent logins serialise correctly (raised 2026-05-04T13:02Z by test-spec-writer)

<!-- ai-agile/todos/test-scenarios/v1 END -->

_Last updated by `coder` at 2026-05-04T16:42:09Z_
<!-- ai-agile/todos/v1 END -->
```

`coder` updates the build-plan checkboxes as it commits each child
task. `standards-compliance-reviewer` adds remediation lines as it
finds them and removes them when fixed. `test-runner` ticks off
scenarios as they pass.

---

## Lifecycle

| Event | Effect on the todos block |
|---|---|
| Issue opened | No block yet |
| `prd-writer` finishes | `acceptance-criteria` subsection added |
| `task-decomposer` finishes | `build-plan` subsection added |
| Question Card opens | `open-questions` subsection added (or item appended) |
| Question Card answered/withdrawn | Item removed; subsection removed if empty |
| `coder` opens draft PR | PR body created with `build-plan` mirrored from issue |
| Each commit | `coder` checks the corresponding build-plan box on the PR |
| `standards-compliance-reviewer` runs | `standards-remediations` items added/removed |
| Issue closed | Block remains (the audit trail is in the body history) |

The block persists on closed issues and merged PRs as a record of what
was done. It is never deleted.

---

## CI validation

`pipeline/validate_todos_block.py` runs on every PR that
modifies an issue or PR body (via the orchestrator) and checks:

1. Markers are paired — every START has a matching END.
2. Subsections are nested correctly inside the outer block.
3. Every checkbox follows GitHub's `- [ ]` or `- [x]` syntax.
4. Every entry has a `(raised <ISO-8601-UTC> by <actor>)` annotation.
5. Checked items (`[x]`) have a `done <ISO-8601-UTC> by <actor>`
   annotation in addition to `raised`.
6. Blocked / skipped annotations follow the
   `(blocked <ts> by <actor>: <reason>)` /
   `(skipped <ts> by <actor>: <reason>)` form.
7. Timestamps parse as ISO 8601 UTC with the trailing `Z`.
8. Every actor matches one of: a known agent name in
   `pipeline.json`, a `@github-login` for humans, or the literal
   `orchestrator`.
9. The "Last updated" footer is present and parseable.
10. No agent has written to a subsection it does not own.

Bodies that fail validation cannot be saved. The orchestrator emits a
`body.validation_failed` audit event and rolls back the write attempt.

---

## Cross-ticket improvement agents — no tracker, individual issues

Some agents — the **improvement agents** in the continuous phase (`05_continuous`), plus
codebase-wide agents like `reverse-doc` — do work that is fundamentally
cross-ticket. Their **outputs** are GitHub issues (gap-issues,
debt-issues, knowledge-artefact issues, refactor proposals); each
finding becomes its own issue, which then runs through the per-ticket
pipeline like any other work.

These agents do **not** maintain a long-lived tracker issue or backlog
file. Each scheduled run is self-contained:

1. Read inputs (the codebase, PRDs, ADRs, audit log) at run start.
2. Apply the agent's rules to discover candidate findings.
3. For each finding, generate the deterministic issue key
   (`{AGENT}-{CATEGORY}-{HASH}`) and check whether an open issue with
   that key already exists.
4. File a new issue per new finding. Skip findings whose key already
   has an open issue (de-duplication).
5. Exit.

State is reconstructed from GitHub on each run, per P-11. There is no
"scan target backlog" or "investigation list" carried between runs —
the next run re-derives those from the same inputs and arrives at the
same set of findings minus anything already filed.

### Where the agent's todos live

The "todos" for a cross-ticket agent's finding live in the body of
**that finding's issue**, not in a separate tracker. Each filed issue
is the unit of work, and its body uses the standard todos block to
hold:

- Acceptance criteria for resolving the finding
- Investigation steps a human or downstream agent must take
- Cross-references to related findings or ADRs

### Within a single run — TodoWrite

Within one scheduled run, an agent may use Claude's runtime
`TodoWrite` tool to track in-progress steps (which file to scan next,
which PRD to walk, which finding to dedupe). This is **runtime
ephemeral state**, not persistent. It does not survive the run and is
not stored in GitHub. It is purely a tool for the agent to keep its
own multi-step plan organised inside one invocation.

### Outputs are first-class issues

| Concept | Mechanism |
|---|---|
| Agent runs | Scheduled (weekly / monthly / daily, per `pipeline.json`) |
| Per-finding issue | Filed by the agent; carries the issue-key as part of its title; flows through the per-ticket pipeline |
| Per-finding todos | In the filed issue's body, in the standard todos block |
| Across-run state | None — each run re-derives findings from current inputs |
| Duplicate prevention | Issue-key check at file time; same key never produces two open issues |

This keeps the cross-ticket agents stateless, simple, and aligned with
P-11 (resumable by default).

---

## Timestamp and actor format

Every checklist item carries, for each state change (`raised`, `done`,
`blocked`, `skipped`), the timestamp the event occurred **and** the
actor that performed it. This makes the body a self-contained audit
trail without needing to cross-reference issue history or the audit
log.

### Format

Each event is appended to the task text in parentheses as
`<event> <timestamp> by <actor>`, with multiple events comma-separated:

```
(raised 2026-05-04T14:23Z by task-decomposer, done 2026-05-05T09:11Z by coder)
```

| State | Format |
|---|---|
| Pending | `- [ ] {task} (raised <ts> by <actor>)` |
| Done | `- [x] {task} (raised <ts> by <actor>, done <ts> by <actor>)` |
| Blocked | `- [ ] {task} (raised <ts> by <actor>, blocked <ts> by <actor>: <reason>)` |
| Skipped | `- [ ] ~~{task}~~ (raised <ts> by <actor>, skipped <ts> by <actor>: <reason>)` |

### Timestamp grammar

ISO 8601 UTC with minute precision: `YYYY-MM-DDTHH:MMZ`. Seconds are
omitted to keep the line readable; the audit log retains full
precision (see [`PRODUCT.md`](PRODUCT.md#mi-6----you-can-believe-what-the-system-tells-you)).

Properties:

- Unambiguous across locales (no `MM/DD` vs `DD/MM` confusion).
- Lexicographically sortable.
- Parseable by every standard library.
- The `Z` suffix makes timezone explicit; agents and humans in
  different timezones see the same value.

### Actor grammar

The actor is one of:

| Actor type | Format | Example |
|---|---|---|
| Agent | bare agent name (no `@`) matching `pipeline.json` | `task-decomposer`, `coder`, `pr-reviewer` |
| Human | GitHub login prefixed with `@` | `@alice`, `@bob-eng` |
| Orchestrator | the literal `orchestrator` (used for orchestrator-driven changes such as Question Card open/close) | `orchestrator` |

The leading `@` is the only thing that distinguishes humans from
agents in the line. CI validation rejects entries where the actor is
not present or does not match one of the three forms.

### Why every event carries an actor

The actor makes each line self-contained (a reviewer sees who did what without scrolling history or the audit log), disambiguates multi-writer sections (e.g. build-plan, owned by `task-decomposer` on the issue side and `coder` on the PR side, with human overrides showing `by @alice`), and mirrors the `body.updated` audit event that names the same actor.

### Footer

The `_Last updated by <actor> at <timestamp>_` footer at the bottom of the block names the most recent writer to the block as a whole; it is informational, while the line-level annotations are the source of truth for per-entry history.

---

## Retired: `agent-todo-standard.md`

The old `.claude/agents/agent-todo-standard.md` is superseded by this
document. The previous line-oriented format
(`[X] - Raised: MM/DD/YY | ... | Completed: MM/DD/YY`) is replaced by
standard markdown task lists with ISO 8601 timestamps, in the body of
the relevant issue or PR. The change unifies the format across all
todos, makes them visible in the GitHub UI, and removes the parallel
file-based state.

---

## Anti-patterns

Things that look reasonable but break the model:

| Don't | Why |
|---|---|
| Track todos in a separate comment | Comment edits don't render task-list state in the issue summary or in GitHub project views; visibility suffers |
| Track todos as sub-issues | Forces a sub-issue per task; clutter for issues with many small steps; fragments the audit trail |
| Track todos in a `.todo` file in the repo | Body is the user-facing surface; a file is invisible during review |
| Edit human prose to insert checkboxes | Human-authored content is never modified; use the delimited block |
| Remove a checked item from the body | The body is the audit trail; checked items remain so reviewers can see what was done |
| Write outside subsection markers | The validator rejects this; only the surrounding agent owns the unstructured content |
