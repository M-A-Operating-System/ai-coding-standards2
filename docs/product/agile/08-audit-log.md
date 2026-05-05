# Audit Log

The audit log is an append-only record of every event in the AI Agile
pipeline, across every issue, every PR, every session, every agent. It
lives on a dedicated, protected Git branch and is the cross-session
timeline that complements the live state held on issues and PRs.

This is the implementation of [P-3](02-principles.md#p-3--immutable-audit-log-branch).

---

## Branch

| Property | Value |
|---|---|
| Branch name | `ai-agile/log` |
| Type | Orphan (no shared history with `main`) |
| Force-push | Disabled (branch protection rule) |
| Delete | Disabled (branch protection rule) |
| Direct push | Disabled — writes go through the orchestrator's PR-less commit path |
| Writers | The orchestrator service account only |
| Readers | Anyone with repo read access |
| Rebase or rewrite | Forbidden — appends only |

The orphan structure means the log branch shares no commit history with
`main`. It is a parallel timeline. This keeps the log branch small,
independent of code history, and trivially separable for archival.

---

## File layout

```
events/
  YYYY/
    MM/
      DD.jsonl          ← one file per UTC day
metadata/
  schema.json           ← JSON Schema for an event line
  README.md             ← regenerated index of date range and counts
```

One file per UTC day. Each file is JSON Lines (one JSON object per line,
newline-terminated, no trailing comma).

---

## Event schema

Every line in a `DD.jsonl` is one event:

```json
{
  "ts": "2026-05-04T14:23:11.482Z",
  "event_type": "agent.complete",
  "session_id": "ais-v1-mos-acs2-iss-42-7d3a9c1b",
  "iter": 1,
  "object": { "kind": "issue", "id": 42, "repo": "m-a-os/acs2" },
  "agent": "prd-writer",
  "actor": { "kind": "agent", "id": "runner-7f3a", "human": null },
  "outcome": { "status": "complete", "detail": null },
  "ref": {
    "issue_url": "https://github.com/m-a-os/acs2/issues/42",
    "comment_id": 192837461,
    "commit_sha": null,
    "pr_url": null
  },
  "duration_ms": 28471
}
```

**Required fields.** `ts`, `event_type`, `session_id`, `iter`, `object`,
`actor`, `outcome`.

**`actor.kind`** is one of `agent`, `human`, `orchestrator`, `system`.
Human actors record the GitHub login; agent actors record the runner
instance ID.

The schema is at `ai-agile/log/metadata/schema.json` and validated by
the orchestrator before write. Malformed events are dropped with a
`system.malformed_event` event recorded in their place.

---

## What gets logged

Every state-changing action emits one event. The set is closed (no ad-hoc
event types) and aligns with the event vocabulary used by the
orchestrator:

| Category | Event types |
|---|---|
| Session | `session.created`, `session.resumed`, `session.terminated` |
| Issue | `issue.created`, `issue.updated`, `issue.labeled`, `issue.unlabeled`, `issue.linked`, `issue.closed`, `issue.reopened` |
| PR | `pr.draft_opened`, `pr.draft_synchronized`, `pr.draft_ready`, `pr.review_submitted`, `pr.merged`, `pr.closed` |
| Agent | `agent.invoked`, `agent.complete`, `agent.review`, `agent.blocked`, `agent.failed`, `agent.skipped` |
| Lock | `lock.acquired`, `lock.released`, `lock.reclaimed_stale` |
| Gate | `gate.requested`, `gate.approved`, `gate.rejected` |
| System | `system.tick`, `system.malformed_event`, `system.config_reloaded` |

What is *not* logged:

- The full text of agent prompts (referenced by file path only).
- The full text of generated artefacts (referenced by `comment_id` or
  `commit_sha`).
- Personally identifying information beyond the GitHub login already
  visible on the issue.

The log captures *that* something happened and *where the artefact
lives*, not the artefact itself. The artefacts live on the issue or PR
(P-1).

---

## Write protocol

The orchestrator is the only writer. Per-event flow:

1. The orchestrator builds the event object in memory.
2. It validates against the schema. If invalid, replace with
   `system.malformed_event` referencing the original.
3. It appends the event to an in-memory buffer keyed by today's date.
4. At the end of the run (or every N seconds for long-running sweeps),
   the orchestrator commits the day's buffer to the log branch:

   ```
   git fetch origin ai-agile/log
   git checkout ai-agile/log
   # append buffer to events/YYYY/MM/DD.jsonl, creating dirs as needed
   git add events/YYYY/MM/DD.jsonl
   git commit -m "log: append N events for YYYY-MM-DD"
   git push origin ai-agile/log
   ```

5. On push conflict (another orchestrator instance committed first), the
   orchestrator pulls, re-applies its buffer to the (possibly updated)
   day file, and pushes again. JSONL append is order-tolerant — the
   `ts` field gives canonical ordering on read.

**One commit per batch, not per event.** Per-event commits would make
the branch unmanageable at swarm scale. Per-day batching keeps the
commit log readable while the JSON `ts` preserves per-event timing.

---

## Read protocol

Readers clone or fetch the branch and grep / parse JSONL:

```bash
# Show a single session's history
git -C log-clone show ai-agile/log:events/2026/05/04.jsonl \
  | jq 'select(.session_id == "ais-v1-…")'

# Count events by type for a day
git -C log-clone show ai-agile/log:events/2026/05/04.jsonl \
  | jq -r '.event_type' | sort | uniq -c

# Trace a single object across days
for f in $(git -C log-clone ls-tree -r --name-only ai-agile/log -- events/); do
  git -C log-clone show "ai-agile/log:$f" \
    | jq 'select(.object.id == 42)'
done
```

A small CLI (`ai-agile/log/cli.py`) wraps these patterns.

---

## Retention

Indefinite. The log is the audit record. There is no rotation, no
deletion, no compaction.

If size becomes a concern years out, archival is handled by:

1. Detaching old date ranges into a separate archive branch
   (`ai-agile/log-archive-YYYY`).
2. Replacing the detached files with a tombstone listing the archive
   location.

This is a future operation requiring a standards-owner ADR.

---

## What this gives us

- **Replay.** Reconstruct any session's history from the JSONL.
- **Cross-session analytics.** Count events by phase, by agent, by
  duration; surface bottlenecks.
- **Tamper detection.** Force-push protection plus per-day commit
  signatures mean any rewrite is visible in the reflog.
- **SLA evidence.** Wall-clock between gate request and approval is in
  the data.
- **Standards-evolver input.** The weekly run reads the log, not the
  issues, to identify recurring violations and bottlenecks.

---

## Relationship to issues and PRs

| Concern | Lives on | Why |
|---|---|---|
| Live state of one work item | Its issue + linked PRs | P-1 — all on GitHub |
| Historical timeline of all work | `ai-agile/log` branch | P-3 — append-only, cross-session |
| Pipeline graph | `ai-agile/pipeline/pipeline.json` | P-2 — single source of truth |
| Standards | `ai-agile/standards/*.json` | P-2 — single source of truth |

Each has a clear owner and no overlap.
