# ADR-0001 — Retire P-3: Replace audit log branch with stdout JSON lines

**Status:** accepted

---

## Context

P-3 ("Immutable audit log branch") defined a protected orphan branch (`ai-agile/log`)
as the durable cross-session event timeline. Events were appended as JSONL files
keyed by UTC day (`events/YYYY/MM/DD.jsonl`), batched into one commit per day.

The branch mechanism was implemented in the Python orchestrator but added significant
complexity (branch creation, retry-on-conflict, base64 encoding, credential requirements)
with limited operational benefit. It was never deployed to production. GitHub Actions
already captures stdout natively, making the branch write redundant. The branch-based
design also violates the spirit of P-1 (Git is authoritative for pipeline *state*, not
for audit retention).

## Decision

Retire P-3. The orchestrator emits one structured JSON line per event to stdout:

```python
print(json.dumps({...}), flush=True)
```

GitHub Actions captures stdout natively. The workflow run log is the persistent audit
record. Log retention follows the repository's GitHub Actions log-retention setting
(default: 90 days). For long-term retention, operators pipe the log to an external
sink via a workflow step or GitHub Actions log-streaming integration.

The minimum required fields per event are: `ts` (ISO-8601), `event` (string),
`agent` (string), `issue` (number or null), `status` (string). See
[`08-audit-log.md`](../product/orchestrator/08-audit-log.md) for the full schema.

## Consequences

- **Removed:** `ai-agile/log` orphan branch, `AUDIT_LOG_BRANCH` constant,
  `_ensure_audit_log_branch()`, `write_audit_log()`, and all `audit_log` accumulator
  parameters. No git credentials or branch-protection configuration are required for
  audit writes.
- **Added:** `_emit_audit_event(event: dict)` prints one compact JSON line to stdout.
  `_make_audit_event(...)` builds the event dict.
- **Log retention:** Audit events live in GitHub Actions run logs for the configured
  retention period (repository default). This is shorter than a protected branch's
  indefinite history. Operators requiring longer retention must configure an external
  log sink.
- **Replay:** `grep` on the session ID in a downloaded run log replaces `grep` on the
  JSONL files. The same `jq` filter patterns apply.
- **P-3 is retired.** The principle ID is preserved and marked `status: retired` in
  [`02-principles.md`](../product/orchestrator/02-principles.md). P-14 still references
  "append events to the audit log" — that clause now means emit to stdout per this ADR.
