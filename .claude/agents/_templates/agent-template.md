---
name: agent-name
description: >
  One paragraph describing what this agent does and when it runs.
  Replace this placeholder with the actual description before adding
  to the pipeline. Surfaces in the generated agent catalogue at
  docs/product/orchestrator/generated/agents.md.
tools: [Bash, Read, Grep]
model: claude-sonnet-4-6
---

# agent-name

Replace this paragraph with the agent's role statement. State what the
agent owns, when it runs (which phase / which trigger), and what artefact
it produces. Keep to two or three sentences. Reference the relevant
sections of the design docs (`docs/product/orchestrator/`) when behaviour
depends on a documented protocol.

The orchestrator applies `:wip`, posts the opening announcement, and
provides `$ISSUE_NUMBER`, `$REPO`, `$AGENT_SESSION_ID`, and
`$AGENT_COMMIT_SHA` before invoking this agent. After the agent exits,
the orchestrator reads `$AI_AGILE_SCRATCH/result.json`, applies the
outcome label, and posts the closing announcement and any artefact
comment / label changes on the agent's behalf.

---

## Step 1 — Read inputs

Gather the context the agent needs. Operate from what is read at runtime;
do not assume state from prior runs.

```bash
# Issue body and metadata
gh issue view $ISSUE_NUMBER --repo $REPO --json title,body,labels,comments

# Specific upstream artefacts (PRD, design, test spec) — adjust to taste
gh issue view $ISSUE_NUMBER --repo $REPO --json comments \
  -q '.comments[] | select(.body | contains("ai-agile/artefact/v1")) | .body'

# Files in the repo if needed
find "${AI_AGILE_ROOT}/standards" -name "*.json" ! -name "*.schema.json"
```

Replace the examples above with the actual reads this agent needs.

---

## Step 2 — Do the work

Replace this section with the agent's actual work. One step per logical
action — drafting a section, validating a rule, checking a constraint.
Keep steps coarse; avoid step soup.

If the agent produces an artefact for human review (PRD, design, test
spec, gap report, etc.), it goes in `result.json`'s `output` field
(Step 3) — do not post it as a comment yourself; the orchestrator does
that on your behalf.

---

## Step 3 — Write the result

Before exiting, use the Write tool to create `$AI_AGILE_SCRATCH/result.json`:

```json
{
  "outcome": "complete",
  "summary": "What you did, in plain words — including when you did nothing.",
  "undone": "",
  "message": "",
  "output": "",
  "expected_effect": {"commits": false},
  "label_requests": []
}
```

`outcome` (required): exactly one of `complete`, `review`, `blocked`.

- Use `complete` when the work is done and no human gate is needed.
- Use `review` when you have produced an artefact that needs human
  approval before the pipeline advances (gated agents only) — put the
  artefact in `output` and a short note for the reviewer in `message`.
- Use `blocked` when you cannot proceed without human input — ambiguous
  requirements, missing data, or a decision that exceeds your authority.
  Explain the blocker in `message`; do not post a separate comment.

`summary` is required; the rest default to empty/false when omitted. Never
write `outcome: "failed"` or `"exhausted"` — those are the orchestrator's
own labels, applied when you exit without a valid result file at all.

The orchestrator reads this file, applies the corresponding label, posts
the closing announcement, posts `output` as an artefact comment (if
non-empty), and applies any `label_requests` that clear this step's
declared `allowed_labels` in `pipeline.json`. Do not call `status.sh` — it
is no longer used by agents.

---

## Behaviour rules

- Replace this list with hard constraints specific to this agent.
- Use 3–10 bullets. Be specific and testable.
- Examples of useful rules:
  - "Do not edit the issue body — it is human-authored."
  - "Put at most one artefact in `output` per run, not many."
  - "Reference STD IDs by their stable identifier; do not inline the
    standard text."
  - "If the input is ambiguous, write `outcome: \"blocked\"` rather
    than guessing."
  - "Do not invoke other agents; the orchestrator handles routing."
  - "Do not call `status.sh` — signal outcome via `result.json` only."
- Avoid vague rules like "be concise" or "be helpful" — they do not
  constrain anything.
