# Audit Log

**Stale on where the record is kept.** This document describes stdout capture as
the persistent record. That is no longer the design: the audit stream is
appended to the protected orphan branch `ai-agile/log`, because a workflow log
exists only for headless runs. See MI-6 in [`PRODUCT.md`](PRODUCT.md). The
event schema below is unaffected.

The audit log is a stream of structured JSON lines emitted by the orchestrator.
Operators can filter with `jq` if needed.

---

## Mechanism

The orchestrator emits one JSON line per event:

```python
print(json.dumps({...}), flush=True)
```

No log file is written to disk during orchestrator runs. Stdout is the
only output channel for audit events.

---

## Event schema

Every line is one JSON object:

```json
{
  "ts": "2026-05-04T14:23:11Z",
  "event": "agent.complete",
  "agent": "01_product_docs/prd-writer",
  "issue": 42,
  "status": "complete"
}
```

**Required fields.** Every event includes at minimum:

| Field | Type | Description |
|---|---|---|
| `ts` | ISO-8601 string | Timestamp of the event |
| `event` | string | Event type (see below) |
| `agent` | string or null | Agent name from `pipeline.json`. null for system-level events with no associated agent (e.g. `system.tick`, `system.emergency_stop`) |
| `issue` | number or null | Work item number (null for PR work items and global events) |
| `status` | string | Resulting status (`complete`, `review`, `blocked`, `failed`, or internal state) |

**Extended fields.** Emitted alongside required fields; may be null:

| Field | Type | Description |
|---|---|---|
| `detail` | string or null | Human-readable detail for the event (stop reason, exit code, mode, etc.) |
| `session_id` | string | Deterministic session identifier for this (object, agent) pair |
| `object` | object or null | `{"kind": "issue"\|"pr", "id": number, "repo": "owner/repo"}` |
| `actor` | object | Identifies the run's trigger. For scheduled/unattended runs (`--headless`): `{"kind": "orchestrator", "id": "github-actions", "human": null}`. For human-initiated runs (e.g. `/maos-run`, omitting `--headless`): `{"kind": "orchestrator", "id": <actor-id>, "human": true}`. The distinction is set by the `--headless` flag passed to `pipeline_orchestrator.py`; see `11-orchestrator.md`. |
| `ref` | string or null | Reserved; always null |
| `duration_ms` | integer or null | Wall-clock duration of the agent run in milliseconds |

---

## Event types

| Event | Emitted when |
|---|---|
| `agent.invoked` | Orchestrator launched the agent subprocess |
| `agent.complete` | Agent emitted `AI_AGILE_STATUS: complete`; or gate promotion completed |
| `agent.review` | Agent emitted `AI_AGILE_STATUS: review` |
| `agent.blocked` | Agent emitted `AI_AGILE_STATUS: blocked` |
| `agent.failed` | Agent crashed or timed out without a sentinel |
| `gate.approved` | Human applied the gate label; gate promotion ran |
| `lock.reclaimed` | Stale `:wip` was force-reclaimed |
| `system.emergency_stop` | Stop marker detected; orchestrator exited without invoking agents |

---

## Accessing the log

Audit events appear in the GitHub Actions run log, interleaved with
other orchestrator output. Because each event is a complete JSON object
on its own line, they can be extracted from a captured log:

```bash
# Show all audit events
cat run-log.txt | grep '"event":' | jq .

# Filter by event type
cat run-log.txt | grep '"event":' | jq 'select(.event == "agent.failed")'

# Filter by issue
cat run-log.txt | grep '"event":' | jq 'select(.issue == 42)'
```

GitHub Actions retains run logs per the repository's log retention
setting (default: 90 days). For long-term audit retention, pipe the
log to an external sink via a workflow step or a GitHub Actions
log-streaming integration.

---

## What this gives us

- **Traceability.** Every status transition is captured in the run log.
- **Simplicity.** No additional write target — GitHub Actions captures
  stdout natively.
- **Filterability.** Standard `jq` queries work without custom tooling.
