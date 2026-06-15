# Status Model

The pipeline runs on labels. Every agent's lifecycle is recorded as a label
of the form `{agent-name}:{status}` on the issue or PR. The orchestrator
reads labels, decides who runs next, and applies status changes via the
shared script `.github/scripts/status.sh`.

The canonical definition is in `pipeline/statuses.json`
(see [P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated)).
Every transition also emits an event to the audit log branch
(see [`08-audit-log.md`](08-audit-log.md)) so that the cross-session
timeline is intact even after labels are mutated. This document describes
the model in product terms.

---

## The eight statuses

| Status | Colour | Meaning | Set by | Cleared by |
|---|---|---|---|---|
| `requested` | Amber | A human has explicitly requested this agent to run | Human | Orchestrator (replaced by `:wip` on invocation) |
| `wip` | Yellow | Agent is actively running | Orchestrator | Orchestrator (replaced by outcome) |
| `complete` | Green | Agent finished successfully | Orchestrator (on sentinel or gate-label) | Never |
| `approved` | Blue | Human has approved the agent's output at a configured human gate | Human | Never |
| `review` | Purple | Agent has finished and is requesting human review | Orchestrator (on sentinel) | Orchestrator (on gate-label) **or** Human (rejects by removing) |
| `blocked` | Red-orange | Agent cannot proceed without human help | Orchestrator (on sentinel) | Human (after fixing the cause) |
| `failed` | Red | Agent crashed with a technical error | Orchestrator | Human (after debugging) |
| `skipped` | Light blue | Agent was intentionally bypassed | Human | Never |

The label format is `{agent}:{status}`, where `{agent}` is the
short agent name (see
[`12-agent-spec.md`](12-agent-spec.md#naming-convention)). Examples:
`prd-writer:wip`, `architect:review`,
`coder:failed`, `adr-proposer:skipped`,
`codebase-reviewer:requested`.

---

## Status transitions

```
                       ┌──► complete (terminal — non-gated agent)
                       │
                       │       ┌──► (human applies gate label)
                       │       │       └──► orchestrator: review→complete (terminal)
none ──► wip ──────────┼──► review ──┤
  │                    │             │
  └──► requested ──┐   │             └──► (human removes :review without gate)
                   │   │                     └──► wip ──► …
                   ↓   │
                  wip   ├──► blocked ──► (human removes) ──► wip ──► …
                        │
                        └──► failed ──┬──► (human removes) ──► wip
                                      └──► skipped (terminal)
```

- An agent can only transition out of `wip`.
- `complete` and `skipped` are terminal — once applied, they are never
  removed. `complete` says "the agent succeeded." `skipped` says "we have
  decided this agent is not applicable."
- `review`, `blocked`, and `failed` all halt the pipeline. They are not
  terminal — `:blocked` and `:failed` are resolved by the human removing
  the label; `:review` is resolved either by the orchestrator (when the
  human applies a gate label, see below) or by the human removing the
  label to reject and re-run the agent.

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
| `requested` | Human | When a human wants to trigger an agent ad-hoc, outside the normal dependency chain |
| `wip` | Orchestrator | At the start of agent invocation (replaces `:requested` if present) |
| `complete` (non-gated agent) | Orchestrator (on sentinel) | When the agent emits an outcome sentinel with `"outcome": "complete"` |
| `complete` (gated agent) | Orchestrator | When the human applies the matching gate label, promoting the agent from `:review` to `:complete` |
| `review` | Orchestrator (on sentinel) | When the agent emits an outcome sentinel with `"outcome": "review"` |
| `blocked` | Orchestrator (on sentinel) | When the agent emits an outcome sentinel with `"outcome": "blocked"` |
| `failed` | Orchestrator | When the agent exits non-zero without a terminal sentinel |
| `skipped` | Human | When a human decides this agent is not applicable |

The orchestrator is the **only writer** for all status label transitions.
Agents never apply labels directly — they emit an outcome sentinel and the
orchestrator reads the sentinel and applies the matching label. Humans never
apply `{agent}:complete` directly either — they apply the gate label and the
orchestrator promotes the agent. This keeps the transition logic in one place
and ensures every status change is consistent and auditable.

### Why the orchestrator owns all transitions

A status transition is **not a single API call** — it is a small
protocol that must hold several invariants:

| Invariant | Why it matters | How the orchestrator enforces it |
|---|---|---|
| Exactly one status label per agent at any time | Two coexisting statuses (`:wip` + `:complete`) are ambiguous and can mis-route the orchestrator | `_apply_terminal_status` removes **all** non-terminal status labels before adding the new one |
| Labels exist with the right colour and description | Manually-created labels drift across repos; reviewers can't tell statuses apart at a glance | The orchestrator reads colours from `statuses.json` and creates labels if they do not yet exist |
| Recovery comments are posted on `:review`, `:blocked`, `:failed` | Humans must know what to do when the pipeline halts; relying on every agent prompt to remember is fragile | The orchestrator posts the standard recovery comment with consistent wording on every halt |
| The format `{agent}:{status}` is canonical | Any drift breaks the orchestrator's label parsing | The orchestrator constructs label names via `AgentDef.status_label()` — no agent prompt can misformat them |

Centralising these invariants in the orchestrator means every agent
prompt collapses to emitting a single outcome sentinel and the protocol
is enforced once, in Python we can test and version-pin. Agents writing
labels directly via `gh issue edit` would have to re-implement the protocol
inline — which would drift across the 22+ agent prompts over time.

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

## Gated agents: the `:review` → `:complete` transition

Agents fall into two categories: **gated** (their dependency declares a
human gate) and **non-gated** (no gate). They reach `:complete` by
different paths.

**Non-gated agents** (e.g., `issue-classifier`, `dependency-resolver`,
`release-noter`) finish their work and emit `"outcome": "complete"` in their
sentinel. The orchestrator reads the sentinel and applies `:complete`. Done.

**Gated agents** (e.g., `prd-writer`, `architect`, `test-spec-writer`,
`pr-reviewer`) finish their work, post the artefact, and emit
`"outcome": "review"` in their sentinel. They never emit `"outcome":
"complete"` themselves. The transition from `:review` to `:complete` is the
orchestrator's job, triggered by the human applying the gate label.

**Lifecycle of a gated agent.**

```
orchestrator:  applies {agent}:wip
orchestrator:  posts opening announcement
agent:         posts artefact comment
agent:         emits outcome sentinel {"outcome": "review", ...}
orchestrator:  reads sentinel, removes :wip, applies {agent}:review

— pipeline halts; human reads artefact —

(approve path)
human:         applies gate label    → {gate}:approved
orchestrator:  detects gate label
orchestrator:  removes :review, applies :complete
orchestrator:  emits gate.approved + agent.complete to audit log
                                     → downstream agents now eligible

(reject path)
human:         posts feedback comment
human:         removes :review (no gate label applied)
orchestrator:  re-evaluates eligibility
                                     → agent re-runs, reads feedback
```

**Why the orchestrator promotes, not the human.**

- **Single writer.** All transitions out of `:review` go through one
  code path. Easier to audit, easier to test, no race between a human
  applying `prd-writer:approved` and a stale agent webhook setting
  `prd-writer:complete`.
- **Atomic from the dependency-graph point of view.** The downstream
  agent's eligibility check is one query: "is
  `prd-writer:complete` present and `prd-writer:approved`
  present?" The orchestrator guarantees these two labels appear
  together or not at all.
- **Humans do less.** Approving a gate is one click (apply label).
  The human is not asked to remember to also remove `:review` and
  apply `:complete`.
- **The audit trail is uniform.** Every agent run ends with an event
  emitted by the orchestrator (`agent.complete`, `agent.review`,
  `agent.blocked`, or `agent.failed`), regardless of whether the
  agent was gated. See [`08-audit-log.md`](08-audit-log.md).

**What the dependency check sees.**

Downstream agents declare dependencies in `pipeline.json` of the form
`requires: ["{agent}:complete", "{gate}:approved"]`. After the
orchestrator promotes, both are present, the dependency is satisfied,
and the next agent becomes eligible. A gate label without `:complete`
(or vice versa) is a transient state the orchestrator resolves on its
next tick — downstream agents do not run on it.

---

## The "skipped" escape hatch

Skipping an agent is a deliberate human action that says "this agent's
work does not apply to this ticket and I am taking responsibility for
that."

Common skip cases:

- **`adr-proposer:skipped`** — no architectural decisions in this ticket.
- **`migration-validator:skipped`** — no SQL changes (often automatic by
  path filter, but can be manual).
- **`product-standards-checker:skipped`** — pure technical chore with no
  product surface.

Skipping is treated as equivalent to `complete` for downstream
dependency resolution. There is no audit comment beyond the label
change itself, so the human is implicitly accepting accountability by
applying it.
