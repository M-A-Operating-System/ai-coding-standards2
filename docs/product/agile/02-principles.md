# Principles

These are the rules AI Agile is built on. They are referenced by ID
(`P-1`, `P-2`, …) from code, agents, design docs, and reviews. A change to
any principle is a significant architectural decision and goes through an ADR.

The principles fall into three groups:

- **Architectural** (P-1 to P-4) — commitments about how the system is built.
- **Operational** (P-5 to P-9) — rules the orchestrator enforces on work.
- **Cultural** (P-10 to P-12) — how the system behaves toward people.

---

## Architectural

### P-1 — Git is authoritative

**Statement.** All pipeline state lives on GitHub: as labels, comments, PR
bodies, issue bodies, and commits on the audit log branch. The orchestrator
has no sidecar database, cache, or state file.

**Consequences.**

- Anyone can reconstruct the state of any work item by reading the issue
  and its linked PRs alone.
- Recovery from any failure is "re-read GitHub" — there is no separate
  recover-state step.
- The orchestrator may hold an in-memory cache for a single run, but it
  must be dropped on exit.
- Session-derived data (session ID, iteration, derived names) lives in a
  single JSON-bodied comment per object, identified by a stable HTML
  marker (`<!-- ai-agile/session/v1 -->`).

**Tradeoff.** GitHub becomes a hot read path. Mitigated by ETag/If-Match
conditional requests and per-run caching.

### P-2 — One machine-readable source per concern; human views are generated

**Statement.** Every structured fact about the system lives in exactly one
machine-readable file with a published JSON schema. Human-readable
documents (markdown tables, mermaid diagrams) describing those facts are
*generated* from the source and committed as build output. They are never
hand-edited.

**Sources of truth.**

| Concern | File | Schema |
|---|---|---|
| Pipeline graph | `ai-agile/pipeline/pipeline.json` | `pipeline.schema.json` |
| Status definitions | `ai-agile/pipeline/statuses.json` | `statuses.schema.json` |
| Architecture & product standards | `ai-agile/standards/*.json` | `standards.schema.json` |
| ADRs | `ai-agile/standards/adrs.json` | `adrs.schema.json` |

**Consequences.**

- A PR that edits the JSON without regenerating dependent docs fails CI.
- A PR that hand-edits a generated file fails CI.
- New concerns (e.g. agent factory recipes) get their own JSON + schema +
  generator. Prose-only definitions of system state are not allowed.

**Tradeoff.** Higher upfront cost (schema + generator per concern). Pays
off the moment a fact would otherwise have drifted across two documents.

### P-3 — Immutable audit log branch

**Statement.** Every event across every session is appended to a protected
branch (`ai-agile/log`). The branch is orphan, force-push and delete
protected, and append-only. It is the cross-session, cross-issue timeline
of everything that happened.

**Consequences.**

- The orchestrator emits one event per status transition, agent run, gate
  approval, claim, and session lifecycle change.
- Events are written as JSONL, one file per UTC day:
  `events/YYYY/MM/DD.jsonl`.
- One commit per day batches the day's events; the per-event timestamp
  is in the JSON, the commit signature covers the day's batch.
- Replay (reconstruct a session's history) is `grep` on JSONL plus the
  session ID.
- The live state (P-1) and the historical timeline (P-3) are
  complementary, not redundant — issues and PRs answer "what's the state
  now?", the log branch answers "what happened?".

**Tradeoff.** A second writeable Git target per agent run. Mitigated by
batching and by the orchestrator (not agents) being the only writer.

### P-4 — `:wip` is the mutex

**Statement.** The label `{agent}:wip` is the lock for an `(object, agent)`
pair. While it is set, no other runner may pick up that pair. Acquisition
follows a claim+verify protocol so multiple runners (agent swarms) cannot
double-pick.

**Acquisition protocol.**

1. Read current labels.
2. If any `{agent}:*` status is present, abort.
3. Apply `{agent}:wip`.
4. Post a claim comment with a unique runner token.
5. Re-read claim comments. The earliest GitHub comment ID wins.
6. If we are not the winner, remove `:wip`, delete our claim, abort.
7. If we won, proceed.

**Release.** The agent applies exactly one terminal status (`complete`,
`review`, `blocked`) via `status.sh`. The orchestrator applies `:failed`
on crash.

**Stale lock recovery.** A `:wip` older than the configured agent timeout
(default 30 minutes) is reclaimed by the orchestrator. The reclaim emits
an `agent.failed` audit event.

**Consequences.**

- Cross-issue parallelism is unconstrained — many issues run agents
  concurrently.
- Intra-issue parallelism is allowed only for agents that share no
  dependency, and is serialised in practice by the orchestrator's
  eligibility check.
- A single-orchestrator deployment is naturally safe; a multi-orchestrator
  deployment uses the same protocol with no migration.

**Tradeoff.** Two extra GitHub round-trips per agent run for the
claim+verify dance. Acceptable at expected swarm volume.

---

## Operational

### P-5 — One shippable unit, one PR

**Statement.** Every PR closes exactly one *shippable-unit* issue.
Every shippable-unit issue produces at most one PR. The orchestrator
rejects multi-issue PRs at `pr.draft_opened`.

A **shippable unit** is an issue that owns a deliverable: a feature
issue, a chore issue, or a super-issue grouping smaller items. Child
issues (tasks decomposed from a parent, or bugs grouped under a
super-issue) are *not* shippable units — they are tracking and audit
units that close when their parent's PR merges.

**Consequences.**

- The PR opens against the shippable-unit issue. The branch is named for
  it. The changelog entry refers to it.
- Children attach via commit trailers (`Closes #{child}`) and close
  automatically on PR merge.
- A second PR for the same shippable unit requires the first to be
  closed and the session iteration to advance (P-7).
- `task-decomposer` produces child task issues for tracking; `coder`
  opens **one PR for the parent**, with one commit per child task.

**Tradeoff.** Forces explicit decomposition into child tasks for visibility,
without fragmenting the deliverable into many small PRs. Reviews are larger
but match the shape of the actual change.

### P-6 — Group small work under a super-issue

**Statement.** When the `ticket-sizer` returns `S` and the issue is the
Nth small bug or chore in a configured time window, the orchestrator
suggests grouping under a super-issue before sizing completes. The
super-issue becomes the shippable unit (P-5); the grouped children
attach to it and stop running their own pipelines from that point on.

**Consequences.**

- A new agent (`super-issue-grouper`) drafts the grouping. Humans
  approve via a `super-issue:approved` gate.
- On approval, the grouped child issues are linked to the super-issue
  and their individual pipelines pause. The super-issue runs through
  the full pipeline as a single unit (PRD covers all children, design
  covers all children, one PR fixes all children).
- One PR closes the super-issue and all its children on merge.
- Retrospectives roll up at the super-issue level.
- A child added to a super-issue after grouping (late-arriving bug)
  attaches to the super-issue's open session if `pr.draft_opened` has
  not yet fired; otherwise it waits for the next super-issue cycle.

**Tradeoff.** A bad child can block the whole batch. Mitigated by the
super-issue-grouper proposing tightly-scoped groupings (related area,
similar fix shape) rather than time-window dumps.

### P-7 — One session per (object, agent)

**Statement.** A session is the lifecycle of one agent's interactions
with one object. The session ID is deterministic from those three
facts and is stable forever:

```
ais-v1-{kind}-{id}-{agent}
```

| Object × Agent | Session ID |
|---|---|
| issue 42, prd-writer | `ais-v1-iss-42-prd-writer` |
| issue 42, architect | `ais-v1-iss-42-architect` |
| PR 77, coder | `ais-v1-pr-77-coder` |
| PR 77, pr-reviewer | `ais-v1-pr-77-pr-reviewer` |

Different agents on the same object have different sessions. The same
agent on different objects has different sessions. Re-runs of the same
agent on the same object resume the same session.

**Why per (object, agent).** Session granularity matches lock
granularity (P-4). The `:wip` mutex is per (object, agent); the session
that the mutex protects is the same scope. This is the smallest unit of
work the orchestrator coordinates, and it is the right unit for
identity, audit grouping, and replay.

**Consequences.**

- Lookup is unambiguous: "show me everything the architect did on
  issue 42" is one session ID; "show me everything that happened to
  PR 77" is `grep ais-v1-pr-77-`.
- Re-runs (after rejection, blocked-then-resolved, or stale-lock
  reclaim) all share the same session ID. There are no "session 1
  vs session 2" of the same agent on the same object.
- Each PR is its own object. If a PR is closed-without-merge and a
  second PR is needed, the new PR has its own ID and therefore its own
  set of (PR, agent) sessions. The issue-side sessions on the parent
  are untouched.
- Branch and PR derived names use a separate uniqueness mechanism (a
  short suffix counted from existing artefacts of the same prefix)
  rather than a session-level counter — sessions don't carry an
  iteration number.
- Audit log events carry the session ID; replay is `grep` on the ID.
  No `iter` field.

**Tradeoff.** Aggregating "all work on issue 42" requires enumerating
all (42, *) sessions rather than reading one. The fix is a thin
convenience layer in the audit-log CLI — the underlying model stays
clean.

### P-8 — Closed issue freezes the session

**Statement.** When an issue is closed, its session moves to a terminal
state. Subsequent events on the same issue are dropped unless an explicit
`issue.reopened` event arrives, which begins a new session iteration
(P-7).

**Consequences.**

- The orchestrator does not need to re-evaluate eligibility on closed
  issues, simplifying the scheduled tick.
- The audit log retains the full timeline; the live state simply freezes.

**Tradeoff.** None significant.

### P-9 — Cross-issue parallel, intra-issue serial

**Statement.** The pipeline runs many issues concurrently. Within a single
issue, the orchestrator triggers at most one agent at a time (subject to
P-4). This is a property of the eligibility check plus the mutex; it is
declared as a principle so swarms can rely on it.

**Consequences.**

- Agents within a single issue can assume they are not racing each other.
- Multi-orchestrator deployments rely on the mutex (P-4), not on global
  coordination.

**Tradeoff.** Some intra-issue throughput is left on the table when two
agents *could* run in parallel. Acceptable; safety wins.

### P-13 — Draft PRs early; one branch per PR

**Statement.** The `coder` opens a draft PR on the first commit pushed
to a feature branch, not after the work is complete. Every PR has
exactly one branch; every branch produces exactly one PR. Branches are
short-lived: deleted on merge or close.

**Why draft-early.**

- The PR object exists from the start, so PR-side agent sessions
  (`standards-compliance-reviewer`, `migration-validator`,
  `pr-reviewer`) can run as commits land — not waiting for a "ready"
  signal.
- CI runs from commit 1, catching standards and test issues early
  instead of big-bang at the end.
- Reviewers can leave inline comments as work develops; large
  surprises at the end are rarer.
- The audit log captures the PR lifecycle from `pr.draft_opened`,
  giving accurate cycle-time data.

**Why one branch per PR.**

- The branch is the working surface of the PR. A second PR off the
  same branch creates ambiguous closing relationships.
- Reusing a merged branch for new work risks resurrecting closed
  scope.
- Branch hygiene maps directly to the (object, session) model: the
  PR is the object, the branch is its working file.

**Consequences.**

- `coder` flow: create branch → first commit → open draft PR →
  continue committing per child task. The `pr.draft_opened` event
  fires once, early.
- A second attempt at the same shippable unit (after a
  closed-without-merge) creates a *new* branch with a new name; the
  old branch is preserved for the audit trail.
- GitHub setting: auto-delete branches on merge.
- Force-push within a PR's branch (rebase, fixup) is allowed; pushing
  a different branch's history into the PR's branch is not.
- The `pr.draft_ready` transition is a separate event signalling
  "the coder believes this is done"; it triggers `pr-reviewer` and
  the human gate flow.

**Tradeoff.** Reviewers see incomplete work in their PR list.
Mitigated by GitHub's draft filtering (drafts are excluded from
default review queues) and by the existing `:wip` label discipline.

---

## Cultural

### P-10 — Agents draft, humans decide

**Statement.** Agents produce artefacts. Humans approve at named gates by
applying or removing labels. No work advances past a gate without an
explicit human action.

**Consequences.**

- Eight gates are defined (see [`human-gates.md`](human-gates.md)).
- Reviewer time is spent reading artefacts, not authoring them.
- The system never edits human-authored content (issue bodies written by
  the stakeholder, review comments, ADRs after acceptance).

**Tradeoff.** Throughput is bounded by reviewer availability at gates.
This is intentional.

### P-11 — Resumable by default

**Statement.** Every state in the pipeline is reconstructable from
GitHub (P-1) plus the audit log (P-3). Any agent can be re-run without
manual recovery. There is no "rerun the build" button — removing a
status label is the universal retry.

**Consequences.**

- No agent assumes the pipeline is in any particular state. It reads
  labels and acts on what it finds.
- Crashes recover by removing `:failed` (or letting stale-lock reclaim
  apply, P-4).
- The orchestrator is restartable mid-flight without losing work.

**Tradeoff.** Agents must be idempotent — re-runs produce the same
artefact, not duplicates. This is a hard constraint on agent design.

### P-12 — Transparent over clever

**Statement.** When in doubt the system prefers an explicit comment, an
explicit label, and a named status over inferred state, silent retries,
or hidden behaviour.

**Consequences.**

- Every state change posts a comment naming the action and what the human
  should do next.
- Every gate has an explicit name; nothing is "auto-approved."
- Errors surface immediately as `:failed` with the detail in a comment.

**Tradeoff.** More label and comment noise on long-lived issues.
Acceptable.

---

## Adding or changing a principle

A principle change is an ADR. The ADR must:

1. Reference the principle ID being changed (`P-N`).
2. State the current principle, the proposed change, and the rationale.
3. List downstream changes (agents, schemas, generators, docs).
4. Be approved by a standards owner before merge.

Principle IDs are stable. A retired principle keeps its ID and is marked
`status: retired` with a pointer to its replacement.
