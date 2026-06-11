---
name: agent-name
description: >
  One paragraph describing what this agent does and when it runs.
  Replace this placeholder with the actual description before adding
  to the pipeline. Surfaces in the generated agent catalogue at
  docs/product/agile/generated/agents.md.
tools: [Bash, Read, Grep]
model: claude-sonnet-4-6
---

# agent-name

Replace this paragraph with the agent's role statement. State what the
agent owns, when it runs (which phase / which trigger), and what artefact
it produces. Keep to two or three sentences. Reference the relevant
sections of the design docs (`docs/product/agile/`) when behaviour
depends on a documented protocol.

The orchestrator applies `:wip`, posts the opening announcement, and
provides `$ISSUE_NUMBER`, `$REPO`, `$AGENT_SESSION_ID`, and
`$AGENT_COMMIT_SHA` before invoking this agent. After the agent exits,
the orchestrator reads the `AI_AGILE_STATUS:` sentinel from stdout,
applies the outcome label, and posts the closing announcement.

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
spec, gap report, etc.), post it as a fenced comment with the
`ai-agile/artefact/v1` marker:

```bash
gh issue comment $ISSUE_NUMBER --repo $REPO --body "$(cat <<'EOF'
<!-- ai-agile/artefact/v1 -->
## {Artefact title}

{Artefact body — markdown}
EOF
)"
```

If the agent produces a structured question for a human, use the
Question Card schema (see `docs/product/agile/09-human-interaction.md`
§2) with the `ai-agile/question/v1` marker.

---

## Step 3 — Signal outcome

End your run by outputting — as plain text, not a bash command — exactly
one sentinel line as your final text response:

```
AI_AGILE_STATUS: complete
```

Valid values: `complete`, `review`, `blocked`.

- Use `complete` when the work is done and no human gate is needed.
- Use `review` when you have produced an artefact that needs human
  approval before the pipeline advances (gated agents only).
- Use `blocked` when you cannot proceed without human input — ambiguous
  requirements, missing data, or a decision that exceeds your authority.
  Always post a comment explaining the blocker before emitting this.

The orchestrator applies the corresponding label and posts the closing
announcement. Do not call `status.sh` — it is no longer used by agents.

---

## Behaviour rules

- Replace this list with hard constraints specific to this agent.
- Use 3–10 bullets. Be specific and testable.
- Examples of useful rules:
  - "Do not edit the issue body — it is human-authored."
  - "Post one artefact comment per run, not many."
  - "Reference STD IDs by their stable identifier; do not inline the
    standard text."
  - "If the input is ambiguous, emit `AI_AGILE_STATUS: blocked` rather
    than guessing."
  - "Do not invoke other agents; the orchestrator handles routing."
  - "Do not call `status.sh` — signal outcome via `AI_AGILE_STATUS:`
    sentinel only."
- Avoid vague rules like "be concise" or "be helpful" — they do not
  constrain anything.
