# Human Interaction

This document defines how humans and agents communicate during a
session. Two concerns are covered together because they're two halves
of the same thing: agents need a way to ask, humans need a way to
answer, and both need to be auditable, machine-readable, and built on
GitHub-native primitives ([P-1](02-principles.md#p-1--git-is-authoritative)).

- **Section 1** — the interaction model: how agents reach humans, and
  how humans reach agents back.
- **Section 2** — the **Question Card**: a stable JSON schema for any
  structured question an agent asks of a human (or another role).

---

## 1. Interaction model

### Agent → Human

When an agent needs a human's input it posts a **structured comment** —
never free-text-only. The structure is a fenced JSON block under a
stable marker so that a human reading the issue, an agent re-reading
the issue, and the orchestrator scanning for state all parse the same
content.

Markers used:

| Purpose | Marker |
|---|---|
| Session metadata for an `(object, agent)` pair | `<!-- ai-agile/session/v1 by {agent-name} -->` |
| A question requiring an answer | `<!-- ai-agile/question/v1 by {agent-name} -->` |
| An artefact awaiting review (PRD, design, spec) | `<!-- ai-agile/artefact/v1 by {agent-name} -->` |
| A claim during mutex acquisition (P-4) | `<!-- ai-agile/claim/v1 by {agent-name} -->` |
| Opening / closing announcement | `<!-- ai-agile/announcement/v1 by {agent-name} -->` |
| Snapshot of human-authored content before agent rewrite (e.g. issue title/body before `prd-writer` rewrites them per the [P-10](02-principles.md#p-10--agents-draft-humans-decide) carve-out) | `<!-- ai-agile/snapshot/v1 by {agent-name} -->` |

Every marker carries the **actor** as a `by {actor-name}` suffix.
The actor is the agent's full phase-prefixed name (e.g.
`01_product_docs/prd-writer`) for agent-posted comments, or the
literal `orchestrator` for orchestrator-posted comments (gate
prompts, `:failed` recovery messages, etc.).

This matters because every agent posts under the same bot account
(see [§4](#4-agent-identity)), so the GitHub-side actor is
identical for all of them — the marker is the only place each
agent's identity surfaces in the timeline. Reviewers can grep one
line per comment to see which agent posted what; tooling that wants
"all artefacts from `02_design/architect`" needs only a
regex on the marker, not JSON parsing of the body. The actor
convention mirrors the line-level `by <actor>` annotations used in
the todos block (see [`13-todos.md`](13-todos.md#timestamp-and-actor-format)).

Free-text prose may appear *alongside* the JSON block — the human is
expected to read it. The JSON block is the machine-readable contract.
If they disagree, the JSON wins.

**Three types of agent→human posts.**

| Type | Example | Marker | Resolution |
|---|---|---|---|
| **Artefact for review** | "Here is the PRD." | `artefact/v1` | Human applies the gate label (e.g., `01_product_docs/prd-writer:approved`) or removes `:review` to reject |
| **Question** | "Should we extend `users` or create a new table?" | `question/v1` | Human answers via the Question Card protocol (Section 2) |
| **Status report** | "I am blocked because…" | `question/v1` of type `clarification` | Human resolves the cause, then removes `:blocked` |

### Human → Agent

Humans use **GitHub-native primitives** that already work everywhere.
Nothing to learn beyond ordinary GitHub usage:

| Action | What it means |
|---|---|
| **Apply a gate label** (e.g., `01_product_docs/prd-writer:approved`) | Approve at this gate. The orchestrator then removes the agent's `:review` label and applies `:complete`. Humans never apply `{agent}:complete` directly. |
| **Remove a `:review` label without a gate label** | Reject; the agent re-runs and reads feedback comments |
| **Remove a `:blocked` label** | Unblock (after fixing the cause); the agent re-runs |
| **Apply a `:skipped` label** | Take responsibility for bypassing this agent ([Status model](06-status-model.md)) |
| **Inline comment on a PR diff or artefact line** | Targeted feedback on a specific line; the agent reads inline comments on its next run |
| **Edit the agent's comment in place** | Correct a draft; the edit is in the issue's history |
| **Reply to a Question Card** | Answer a structured question (Section 2) |
| **GitHub reaction (👍 👎 🚀 ❤️)** | Quick non-binding signal; not load-bearing |

**The label is the binding decision.** Comments and edits are colour
on top. The orchestrator advances the pipeline when a label changes,
not when a comment is posted.

**The orchestrator owns transitions out of `:review`.** When a gate
label appears, the orchestrator promotes the agent from `:review` to
`:complete`. When `:review` is removed without a gate label, the agent
is rejected and re-runs. Humans interact with **gate labels** and with
removing `:review`/`:blocked` — they never touch `:complete`
themselves. See
[`06-status-model.md`](06-status-model.md#gated-agents-the-review--complete-transition).

### Why not free text only

Free-text-only conversation forces every agent to LLM-parse human
replies. That's slow, expensive, non-deterministic, and breaks the
[P-14](02-principles.md#p-14--deterministic-python-orchestrator-with-sole-routing-authority)
guarantee that routing is unit-testable Python.

Structured cards + GitHub primitives give a deterministic input space:
labels → routing decisions, JSON answers → agent inputs. Humans can
still write prose; the structured part is what the system acts on.

---

## 2. Question Cards

### What it is

A Question Card is a JSON-fenced comment that captures a single
question from one role to another. It lives on the issue or PR the
question pertains to. It has a stable schema. It is the only
sanctioned way for an agent to ask a human something that requires a
structured answer.

### Marker and discovery

Every Question Card begins with the marker
`<!-- ai-agile/question/v1 by {asking-agent} -->` on its own line,
followed by the JSON in a fenced ```` ```json ```` block. The
orchestrator and any agent can find pending questions on an issue by
grepping for the marker (and questions from a specific agent by
extending the regex to include the `by` suffix).

### Schema

```json
{
  "id": "Q-{session_id}-{seq}",
  "type": "clarification | decision | approval | assignment | validation",
  "asked_by": "{agent-name}",
  "asked_of": "stakeholder | engineer | standards-owner | security-owner | data-owner | any",
  "asked_at": "2026-05-04T14:23:11.482Z",
  "prompt": "Plain-English question, ideally one paragraph.",
  "context": "Optional extra context the answerer may need.",
  "options": [
    {
      "key": "A",
      "label": "Extend the existing users table",
      "consequence": "Adds three columns; one migration.",
      "label_to_apply": "answer:Q-…:A"
    },
    {
      "key": "B",
      "label": "Create a new user_profiles table",
      "consequence": "New table; FK to users; two migrations.",
      "label_to_apply": "answer:Q-…:B"
    }
  ],
  "required_fields": ["rationale"],
  "blocks_pipeline": true,
  "state": "open",
  "answer": null,
  "answered_by": null,
  "answered_at": null
}
```

**Field notes.**

- `id` is deterministic from `(session_id, sequence)`. Re-running the
  agent never produces a duplicate.
- `type` is closed to five values:
  - `clarification` — agent needs more information to proceed.
  - `decision` — agent needs the human to pick an option.
  - `approval` — agent requests sign-off on something not already
    covered by a gate label.
  - `assignment` — agent needs to hand off to a specific role
    (e.g., "data owner please review this migration").
  - `validation` — agent wants confirmation of its understanding
    before proceeding.
- `asked_of` names a persona, not a person. The orchestrator tags the
  appropriate humans based on persona-to-user mapping (kept in a
  separate config file).
- `options[]` is optional. If present, the human answers by applying
  the `label_to_apply` corresponding to their choice. If absent, the
  human answers by editing the card to fill in `answer`.
- `blocks_pipeline` — when true, the agent applies `:blocked` and
  the orchestrator halts the pipeline for this object until the
  question is answered.
- `state` transitions: `open` → `answered` (terminal) or `open` →
  `withdrawn` (the agent decides the question is no longer needed
  and retracts it).

### Answering

Two answer paths, depending on whether the question has options.

**With options:**

1. The human reads the card.
2. They apply the `label_to_apply` for their chosen option (e.g.,
   `answer:Q-…:A`).
3. The orchestrator detects the label, finds the matching question,
   sets `state: answered`, fills in `answer`, `answered_by`,
   `answered_at` by editing the card in place.
4. The orchestrator emits a `question.answered` event to the audit
   log and removes `:blocked` if it was set.
5. The asking agent re-runs and reads the answered card.

**Without options (free-text):**

1. The human edits the card directly, filling in `answer`,
   `answered_by`, `answered_at`, and any `required_fields`.
2. They change `state` to `answered`.
3. The orchestrator detects the edit (via webhook on issue-comment
   edited), validates the schema, and emits the audit event.
4. The asking agent re-runs and reads the answered card.

### Lifecycle

```
asked
  └─ open ──► answered (terminal — agent re-runs and reads the answer)
       │
       └─ withdrawn (terminal — agent retracted; never answered)
```

A Question Card is **never deleted**. Withdrawn cards remain on the
issue with `state: withdrawn` for the audit trail.

### Question types — when to use which

| Type | When |
|---|---|
| `clarification` | Agent has a hole in its inputs. "What does 'real-time' mean here — sub-second, sub-minute, or sub-hour?" |
| `decision` | Agent has multiple viable paths and a human must pick. "A or B?" |
| `approval` | Agent wants sign-off on something without a pre-defined gate. "OK to use the new dependency `lodash@4.x`?" |
| `assignment` | Agent needs a specific role to act. "Data owner: please confirm GDPR scope of the new field." |
| `validation` | Agent wants confirmation of its understanding before going further. "I read your PRD as ruling out admin users — confirm?" |

If none of the five fits, the agent should re-think whether it
actually has a question, or split into two.

### Examples

**Decision question (architect needs schema choice):**

````
<!-- ai-agile/question/v1 by 02_design/architect -->
```json
{
  "id": "Q-ais-v1-iss-42-02_design/architect-001",
  "type": "decision",
  "asked_by": "02_design/architect",
  "asked_of": "engineer",
  "asked_at": "2026-05-04T14:23:11.482Z",
  "prompt": "Where should the new 'last_login_at' field live?",
  "context": "It is read on every authenticated request. The users table is wide and has hot writes.",
  "options": [
    {
      "key": "A",
      "label": "Add to users table",
      "consequence": "Simplest read path. Bumps users row size by 8 bytes.",
      "label_to_apply": "answer:Q-ais-v1-iss-42-02_design/architect-001:A"
    },
    {
      "key": "B",
      "label": "New user_sessions table",
      "consequence": "Decouples hot writes; one extra read per request.",
      "label_to_apply": "answer:Q-ais-v1-iss-42-02_design/architect-001:B"
    }
  ],
  "required_fields": [],
  "blocks_pipeline": true,
  "state": "open",
  "answer": null,
  "answered_by": null,
  "answered_at": null
}
```
````

**Clarification question (issue-classifier needs missing info):**

````
<!-- ai-agile/question/v1 by 01_product_docs/issue-classifier -->
```json
{
  "id": "Q-ais-v1-iss-42-01_product_docs/issue-classifier-001",
  "type": "clarification",
  "asked_by": "01_product_docs/issue-classifier",
  "asked_of": "stakeholder",
  "asked_at": "2026-05-04T11:02:00Z",
  "prompt": "What is the success metric for this feature? The issue body does not state one.",
  "context": null,
  "options": [],
  "required_fields": ["answer"],
  "blocks_pipeline": true,
  "state": "open",
  "answer": null,
  "answered_by": null,
  "answered_at": null
}
```
````

---

## What is *not* a Question Card

To keep the protocol clean, these are explicitly **not** questions —
they have their own mechanisms:

| Concept | Mechanism |
|---|---|
| Approval at a known gate (PRD, design, spec, etc.) | Gate label (e.g., `01_product_docs/prd-writer:approved`) — see [`07-human-gates.md`](07-human-gates.md) |
| Status of an agent on an object | `{agent}:{status}` label — see [`06-status-model.md`](06-status-model.md) |
| Lock on an `(object, agent)` pair | `:wip` label + claim comment — see [P-4](02-principles.md#p-4--wip-is-the-mutex) |
| Cross-issue dependency | GitHub `blocked-by` issue link — see [P-9](02-principles.md#p-9--cross-issue-parallel-intra-issue-serial) |
| Standards violation | Issue raised by `standards-compliance-reviewer` |

A Question Card is for **structured asks that don't fit any of the
above**. If a new ask comes up frequently and would map cleanly to a
gate, propose a new gate rather than reusing the question protocol.

---

## Summary

- **Agents reach humans** via structured comments under stable
  markers. Free-text prose may sit alongside; the JSON block is the
  contract.
- **Humans reach agents** via GitHub-native primitives — labels,
  inline comments, edits, reactions. The label is the binding
  decision.
- **Questions** use the Question Card schema. Five types, two answer
  paths (option-label or in-place edit), never deleted, fully
  auditable.
- **Gates, status, locks, cross-issue dependencies, and standards
  violations** are **not** questions — they have their own
  mechanisms.

---

## 3. Agent announcements

Every agent posts **two structured comments per run**: an opening
announcement when it starts, and a closing summary when it finishes.
This makes the timeline self-explanatory in the GitHub UI — anyone
scrolling the issue can see at a glance which agent ran, when, what
it read, and what it produced.

Both comments use the marker
`<!-- ai-agile/announcement/v1 by {agent-name} -->`.

**Opening announcement** (posted immediately after `status.sh set-wip`):

````
<!-- ai-agile/announcement/v1 by 01_product_docs/prd-writer -->
```json
{
  "session_id": "ais-v1-iss-42-01_product_docs/prd-writer",
  "agent": "01_product_docs/prd-writer",
  "phase": "start",
  "started_at": "2026-05-04T11:02:00Z",
  "intent": "Drafting PRD from issue body and any clarifying comments.",
  "inputs_read": ["issue body", "comment 192837461"]
}
```
````

**Closing announcement** (posted immediately before the terminal
`status.sh` call):

````
<!-- ai-agile/announcement/v1 by 01_product_docs/prd-writer -->
```json
{
  "session_id": "ais-v1-iss-42-01_product_docs/prd-writer",
  "agent": "01_product_docs/prd-writer",
  "phase": "end",
  "ended_at": "2026-05-04T11:04:31Z",
  "outcome": "review",
  "summary": "PRD posted; requesting stakeholder review.",
  "artefacts": ["comment 192837982"]
}
```
````

**Rules.**

- Start and end announcements are *required*, not optional. An agent
  that exits without a closing announcement is treated as having
  crashed and is marked `:failed` by the orchestrator.
- The opening announcement is for transparency. The closing
  announcement is for replay — `artefacts` lists the comments,
  PRs, files, or issues the agent produced this run.
- Free-text prose is allowed alongside the JSON, but the JSON is the
  contract. The orchestrator parses only the JSON.
- The audit log emits `agent.invoked` on the opening announcement
  and `agent.complete` / `agent.review` / `agent.blocked` on the
  closing announcement, mirroring the comment.

---

## 4. Agent identity

Agents act under a **dedicated GitHub user account**, separate from
any human contributor and separate from the workflow's
auto-provisioned `GITHUB_TOKEN`. Suggested handle convention:
`<org>-ai-agile-bot`.

**Why a dedicated identity.**

- **Audit clarity.** A separate account makes it visually obvious in
  the GitHub UI whether a comment, label, or commit came from a human
  or an agent. Distinct avatar, distinct login, no ambiguity.
- **Permission scoping.** The bot's PAT can be scoped to exactly the
  resource permissions the agents need — no admin, no secrets access,
  no settings — narrower than any human admin would have.
- **Audit-log fidelity.** The `actor.kind` field in the audit log
  events (see [`08-audit-log.md`](08-audit-log.md)) becomes verifiable
  from the GitHub login itself, not just a hint we set in the JSON.
- **Quota and rate-limit isolation.** The bot's API usage doesn't
  compete with human contributors' GitHub quota.

**Why not the workflow's auto `GITHUB_TOKEN`?** The auto token shows
the workflow itself as the actor — every action looks like it came
from `github-actions[bot]`, indistinguishable from any other workflow
running in the repo. Reviewers cannot tell agent activity apart from
unrelated CI activity in the timeline.

### Two implementation paths

There are two production-acceptable ways to back the bot identity.
The MVP uses (B); (A) is the production target.

| Path | Status |
|---|---|
| (A) **GitHub App** with short-lived installation tokens | Production target. App tokens auto-rotate every hour, scopes are per-installation, no per-seat cost, app comments visibly carry the `[bot]` suffix. Migration tracked in the roadmap. |
| (B) **Dedicated user account + fine-grained PAT** | **Current** (MVP). Simpler to set up but requires manual PAT rotation (90-day expiry recommended) and may consume one seat on per-seat-billed orgs. |

### Setup (current — option B)

The consuming repo's install steps are documented in the submodule
README. Summary:

1. Create a new GitHub user account (suggested handle:
   `<org>-ai-agile-bot`) with 2FA enabled, and add it as a
   `write`-permission collaborator on every consuming repo.
2. Generate a fine-grained PAT scoped to those repos with
   **Issues: Read & Write**, **Pull requests: Read & Write**,
   **Contents: Read & Write** (Phase 1 Slice 1 needs only the first
   two; Contents-write is needed when `coder` lands).
3. Store as the `AI_AGILE_BOT_TOKEN` secret on each consuming repo.
4. The orchestrator workflow reads `AI_AGILE_BOT_TOKEN` (not
   `GITHUB_TOKEN`) and passes it through to all `gh` and orchestrator
   API calls.

### Migration path to (A)

When ready to move to a GitHub App:

1. Create the App on the org, install on the consuming repos, store
   the App ID and private key as repo or org secrets.
2. Change the workflow's `Run orchestrator` step to use
   `actions/create-github-app-token@v1` to mint an installation token
   at job start, replacing `${{ secrets.AI_AGILE_BOT_TOKEN }}`.
3. Revoke the bot user's PAT and reduce the bot user's repo
   permissions (or remove the account entirely once App-only
   operation is confirmed).

The orchestrator code itself does not change — both paths produce a
`GITHUB_TOKEN` env var that the orchestrator consumes opaquely.
