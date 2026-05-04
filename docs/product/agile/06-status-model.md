# Status Model

The pipeline runs on labels. Every agent's lifecycle is recorded as a label
of the form `{agent-name}:{status}` on the issue or PR. The orchestrator
reads labels, decides who runs next, and applies status changes via the
shared script `.github/scripts/status.sh`.

The canonical definition is in `ai-agile/pipeline/statuses.json`
(see [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated)).
Every transition also emits an event to the audit log branch
(see [`08-audit-log.md`](08-audit-log.md)) so that the cross-session
timeline is intact even after labels are mutated. This document describes
the model in product terms.

---

## The six statuses

| Status | Colour | Meaning | Set by | Cleared by |
|---|---|---|---|---|
| `wip` | Yellow | Agent is actively running | Orchestrator | Orchestrator (replaced by outcome) |
| `complete` | Green | Agent finished successfully | Orchestrator | Never |
| `review` | Purple | Agent has finished and is requesting human review | Agent | Human (by approving or rejecting) |
| `blocked` | Red-orange | Agent cannot proceed without human help | Agent | Human (after fixing the cause) |
| `failed` | Red | Agent crashed with a technical error | Orchestrator | Human (after debugging) |
| `skipped` | Light blue | Agent was intentionally bypassed | Human | Never |

The label format is `{agent}:{status}`. Examples: `prd-writer:wip`,
`architect:review`, `coder:failed`, `adr-proposer:skipped`.

---

## Status transitions

```
       ┌──────► complete (terminal)
       │
none ──┴──► wip ──┼──► review ──► (human removes) ──► wip ──► …
                  │
                  ├──► blocked ──► (human removes) ──► wip ──► …
                  │
                  └──► failed ──┬──► (human removes) ──► wip
                                └──► skipped (terminal)
```

- An agent can only transition out of `wip`.
- `complete` and `skipped` are terminal — once applied, they are never
  removed. `complete` says "the agent succeeded." `skipped` says "we have
  decided this agent is not applicable."
- `review`, `blocked`, and `failed` all halt the pipeline. They are not
  terminal — a human resolves them by removing the label, after which the
  agent re-runs.

---

## Why labels and not a separate dashboard

This is a deliberate design choice with three benefits:

1. **No new tool to learn.** Approvers, engineers, and stakeholders already
   live in the GitHub UI. Labels are visible everywhere an issue is.
2. **Atomic and audited.** Every label change is a GitHub event with a
   timestamp and an actor. The full history is in the issue timeline.
3. **Resumable by removing a label.** If the orchestrator goes down, the
   pipeline state is intact. Bring it back up and it picks up from where the
   labels say it stopped.

The cost is some label noise on long-lived issues, which is acceptable.

---

## Who applies what

| Status | Who applies | When |
|---|---|---|
| `wip` | Orchestrator (via the agent's `set-wip` call) | Immediately on agent start |
| `complete` | Agent (via `set-complete`) | At successful end of the agent's run |
| `review` | Agent (via `set-review`) | When the agent has produced an artefact requiring approval |
| `blocked` | Agent (via `set-blocked`) | When the agent encounters something it cannot resolve |
| `failed` | Orchestrator | When the agent exits non-zero without a terminal status |
| `skipped` | Human | When a human decides this agent is not applicable |

Agents never apply labels directly — they always go through `status.sh`.
This keeps the transition logic in one place and ensures every status change
is consistent.

---

## Distinguishing `review`, `blocked`, and `failed`

These three statuses look superficially similar (all halt the pipeline, all
need a human) but have different meanings.

**`review`** — "I finished my work. A human needs to formally approve the
artefact I produced before the next agent runs."

Use case: `prd-writer` posts a PRD and waits for a stakeholder to approve.

The agent succeeded. The pipeline is paused for sign-off, not for help.

**`blocked`** — "I cannot finish my work. Something I cannot resolve is
preventing me from producing the artefact."

Use case: `dependency-resolver` finds an open hard dependency on a ticket
that is not even started, or `architect` finds the PRD contradicts an
existing standard and needs a human decision on which wins.

The agent did not succeed. It needs information or a decision before it can
re-run.

**`failed`** — "I crashed. Something is wrong with me, the environment, or
the inputs in a way I cannot describe."

Use case: the Claude CLI returned a non-zero exit code; a `gh` command
errored; the agent timed out.

The agent has not run successfully. A human needs to debug.

---

## Human gate labels vs. agent status labels

A human gate label is a separate, additional label that the human applies
*after* the agent's `:complete` or `:review` status. Examples: `prd:approved`,
`design:approved`. They are listed in [`human-gates.md`](human-gates.md).

Status labels and gate labels work together:

- An agent posts an artefact and applies `{agent}:review`.
- The human reads the artefact and either:
  - Approves: removes `{agent}:review` AND applies the gate label
    (e.g., `prd:approved`).
  - Rejects: removes `{agent}:review` only. The agent re-runs.

The orchestrator treats the dependency as satisfied only when both
conditions are met: the upstream agent has `:complete` AND the gate label
is present.

---

## The "skipped" escape hatch

Skipping an agent is a deliberate human action that says "this agent's work
does not apply to this ticket and I am taking responsibility for that."

Common skip cases:

- **`adr-proposer:skipped`** — no architectural decisions in this ticket.
- **`migration-validator:skipped`** — no SQL changes (often automatic by
  path filter, but can be manual).
- **`product-standards-checker:skipped`** — pure technical chore with no
  product surface.

Skipping is treated as equivalent to `complete` for downstream dependency
resolution. There is no audit comment beyond the label change itself, so
the human is implicitly accepting accountability by applying it.
