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
| Agent statuses | `{agent}:{status}` labels ([Status model](06-status-model.md)) |
| Human gates | `{gate}:approved` labels ([Human gates](07-human-gates.md)) |
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

```markdown
<!-- ai-agile/todos/v1 START -->
## AI Agile — Tasks

<!-- ai-agile/todos/build-plan/v1 START -->
### Build plan

- [x] Add `last_login_at` column to `users` table (#43)
- [ ] Wire up middleware to update on each request (#44)
- [ ] Add Gherkin scenarios and tests (#45)

<!-- ai-agile/todos/build-plan/v1 END -->

<!-- ai-agile/todos/acceptance-criteria/v1 START -->
### Acceptance criteria

- [ ] Login updates `last_login_at` within 1 second
- [ ] `last_login_at` survives session expiry
- [ ] Every update produces an audit log entry

<!-- ai-agile/todos/acceptance-criteria/v1 END -->

<!-- ai-agile/todos/open-questions/v1 START -->
### Open questions

- [ ] Q-ais-v1-iss-42-architect-001 — schema choice (asked of: engineer)

<!-- ai-agile/todos/open-questions/v1 END -->

_Last updated by `task-decomposer` at 2026-05-04T14:23:11Z_
<!-- ai-agile/todos/v1 END -->
```

The outer marker pair (`ai-agile/todos/v1`) wraps the whole block. Each
subsection has its own marker pair so agents can update one subsection
without parsing or rewriting the others.

---

## Standard subsections

| Subsection marker | On issue body | On PR body | Owner |
|---|---|---|---|
| `ai-agile/todos/build-plan/v1` | yes | yes (mirrored from issue) | `task-decomposer` (issue), `coder` (PR — updates as commits land) |
| `ai-agile/todos/acceptance-criteria/v1` | yes | no | `prd-writer` (populates after `prd:approved`) |
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

Two annotations may follow the task text in parentheses to convey
non-binary state without breaking GitHub rendering:

| Annotation | Meaning |
|---|---|
| `(blocked: <reason>)` | Cannot proceed; reference a Question Card or `:blocked` agent if applicable |
| `(skipped: <reason>)` | Intentionally not done; the writing agent or human takes responsibility |

GitHub renders the checkbox regardless of annotation, so the visual
state stays accurate. Examples:

```markdown
- [ ] Wire up middleware (blocked: waiting on Q-ais-v1-iss-42-architect-001)
- [x] Add migration
- [ ] ~~Add legacy auth path~~ (skipped: ADR-0019 retires legacy auth)
```

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

A typical issue body after the product-docs phase has run:

```markdown
# Track last-login timestamp on user records

We need to know when each user last successfully authenticated, so that
we can show "last seen" in the admin UI and prune stale accounts.

The admin UI mock is in #38.

<!-- ai-agile/todos/v1 START -->
## AI Agile — Tasks

<!-- ai-agile/todos/acceptance-criteria/v1 START -->
### Acceptance criteria

- [ ] Login updates `last_login_at` within 1 second
- [ ] `last_login_at` survives session expiry
- [ ] Every update produces an audit log entry

<!-- ai-agile/todos/acceptance-criteria/v1 END -->

<!-- ai-agile/todos/build-plan/v1 START -->
### Build plan

- [ ] Add `last_login_at` column to `users` table (#43)
- [ ] Wire up middleware to update on each request (#44)
- [ ] Add Gherkin scenarios and tests (#45)

<!-- ai-agile/todos/build-plan/v1 END -->

_Last updated by `task-decomposer` at 2026-05-04T14:23:11Z_
<!-- ai-agile/todos/v1 END -->
```

The prose above the marker block is the stakeholder's original issue.
Agents never modify it.

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

- [x] Add `last_login_at` column to `users` table (#43)
- [x] Wire up middleware to update on each request (#44)
- [ ] Add Gherkin scenarios and tests (#45)

<!-- ai-agile/todos/build-plan/v1 END -->

<!-- ai-agile/todos/standards-remediations/v1 START -->
### Standards remediations

- [ ] STD000000007 — activity log entry missing for failed login attempts

<!-- ai-agile/todos/standards-remediations/v1 END -->

<!-- ai-agile/todos/test-scenarios/v1 START -->
### Test scenarios

- [x] Successful login updates `last_login_at`
- [ ] Failed login does **not** update `last_login_at`
- [ ] Concurrent logins serialise correctly

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

`ai-agile/pipeline/validate_todos_block.py` runs on every PR that
modifies an issue or PR body (via the orchestrator) and checks:

1. Markers are paired — every START has a matching END.
2. Subsections are nested correctly inside the outer block.
3. Every checkbox follows GitHub's `- [ ]` or `- [x]` syntax.
4. The "Last updated" footer is present and parseable.
5. No agent has written to a subsection it does not own.

Bodies that fail validation cannot be saved. The orchestrator emits a
`body.validation_failed` audit event and rolls back the write attempt.

---

## Cross-ticket agent trackers

Some agents — the **improvement agents** in Phases 8, 9, and 10, plus
codebase-wide agents like `reverse-doc` — do work that is fundamentally
cross-ticket. Their *outputs* are GitHub issues (gap-issues,
debt-issues, knowledge-artefact issues, refactor proposals); those
issues then enter the per-ticket pipeline like any other work.

But the agent itself also has **internal tasks** it must complete to
do its job correctly: modules to scan, PRDs to walk, ADRs to revisit,
candidates to dedupe and rank. These tasks are not outputs — they are
the agent's own backlog. They need a place to live, and per the
storage rule above, that place is **a GitHub issue body**.

### The tracker issue

Every long-running agent has exactly one **tracker issue** in the
repo. It is opened once when the agent is first added to the pipeline
and remains open for the lifetime of the agent.

| Convention | Value |
|---|---|
| Title | `[agent-tracker] {agent-name}` |
| Label | `agent-tracker:{agent-name}` |
| State | Open for the lifetime of the agent |
| Body | Standard todos block with subsections owned by the agent |
| Closed when | The agent is retired (rare); never as part of normal operation |

The tracker is **not** a feature issue — it does not flow through the
per-ticket pipeline. The orchestrator skips it for all agents except
the one whose name it tracks.

### Tracker subsections

| Subsection marker | Holds |
|---|---|
| `ai-agile/todos/scan-targets/v1` | Things the agent must visit (modules, PRDs, ADRs, files) |
| `ai-agile/todos/investigations/v1` | Multi-run investigations the agent has opened and not closed |
| `ai-agile/todos/follow-ups/v1` | Tasks queued for the next run because they exceeded this run's budget |
| `ai-agile/todos/deferrals/v1` | Items the agent decided not to act on, with reason |

Each entry has a stable issue-key suffix (per the issue-key standard)
so re-runs do not duplicate it.

### Example — `gap-assessor` tracker body

```markdown
# Tracker — gap-assessor

This is the working backlog for the `gap-assessor` agent. It runs
weekly and updates the subsections below. Outputs (gap-issues) are
filed as separate issues and linked from the items here when filed.

<!-- ai-agile/todos/v1 START -->
## AI Agile — Tasks

<!-- ai-agile/todos/scan-targets/v1 START -->
### Scan targets

- [x] PRD #42 — last-login tracking (last walked 2026-05-03)
- [x] PRD #51 — admin user-listing (last walked 2026-05-03)
- [ ] PRD #58 — bulk export (added to backlog 2026-05-04)
- [ ] PRD #61 — invitation flow (added to backlog 2026-05-04)

<!-- ai-agile/todos/scan-targets/v1 END -->

<!-- ai-agile/todos/investigations/v1 START -->
### Investigations

- [ ] GAP-AC-a3f2c1 — PRD #51 AC "list paginates above 100 rows"
  has no matching test; opened 2026-05-03; awaiting test-suite scan
  to confirm the gap is real before filing
- [ ] GAP-VIS-7e9b04 — vision says "self-service onboarding"; no
  email verification capability detected; cross-checking with
  product-standards-checker before filing

<!-- ai-agile/todos/investigations/v1 END -->

<!-- ai-agile/todos/follow-ups/v1 START -->
### Follow-ups for next run

- [ ] Re-walk PRD #38 — admin UI mock referenced; check whether the
  shipped UI matches the mock's acceptance criteria

<!-- ai-agile/todos/follow-ups/v1 END -->

<!-- ai-agile/todos/deferrals/v1 START -->
### Deferred (not acted on)

- [ ] GAP-DEP-d12f88 — PRD #19 acceptance criterion "supports IE11"
  no longer applies (deferred: ADR-0014 dropped IE support)

<!-- ai-agile/todos/deferrals/v1 END -->

_Last updated by `gap-assessor` at 2026-05-04T03:00:14Z_
<!-- ai-agile/todos/v1 END -->
```

### Read/write protocol

Identical to the standard protocol. The agent finds its tracker by
label query:

```bash
TRACKER=$(gh issue list --repo $REPO --label "agent-tracker:gap-assessor" \
  --state open --json number -q '.[0].number')
```

Then reads, updates, and writes back the body using the same
ETag-protected protocol as feature issues. The mutex
(`gap-assessor:wip` on the tracker issue) ensures two scheduled runs
cannot collide on the body.

### Outputs vs todos

The distinction matters and is enforced by convention:

| Concept | Lives where | Lifetime |
|---|---|---|
| **Tracker todos** | The agent's tracker issue body | Persistent across runs; checked off as work completes |
| **Agent outputs** | Separate GitHub issues (gap-issues, debt-issues, etc.) | Each output is its own issue, runs through the per-ticket pipeline |

When a tracker investigation results in filing an output issue, the
tracker entry is checked off and annotated with the output issue
number:

```markdown
- [x] GAP-AC-a3f2c1 — PRD #51 AC pagination gap → filed as #82
```

This gives a one-click trail from the agent's internal task to the
work it produced.

---

## Retired: `agent-todo-standard.md`

The old `.claude/agents/agent-todo-standard.md` is superseded by this
document. The previous line-oriented format
(`[X] - Raised: MM/DD/YY | ... | Completed: MM/DD/YY`) is replaced by
standard markdown task lists in tracker-issue bodies. The change
unifies the format across feature issues, PRs, and agent trackers, and
makes the worklog visible in the GitHub UI rather than buried in a
file.

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
