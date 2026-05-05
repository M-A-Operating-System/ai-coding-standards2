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

---

## Step 1 — Apply wip

```bash
bash .github/scripts/status.sh set-wip agent-name $ISSUE_NUMBER
```

For PR-side agents, replace `$ISSUE_NUMBER` with `$PR_NUMBER` and use
the corresponding PR commands throughout.

---

## Step 2 — Opening announcement

Post the structured opening announcement so the timeline records that
this run started, what its intent was, and what inputs it read. The
schema is defined in `docs/product/agile/09-human-interaction.md` §3.

```bash
gh issue comment $ISSUE_NUMBER --repo $REPO --body "$(cat <<'EOF'
<!-- ai-agile/announcement/v1 -->
\`\`\`json
{
  "session_id": "ais-v1-iss-$ISSUE_NUMBER-agent-name",
  "agent": "agent-name",
  "phase": "start",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "intent": "Replace with one-sentence statement of what this run will do.",
  "inputs_read": ["issue body"]
}
\`\`\`
EOF
)"
```

Update `inputs_read` after the next step to reflect what was actually
read (issue body, comment IDs, files, PRs).

---

## Step 3 — Read inputs

Gather the context the agent needs. Operate from what is read at runtime;
do not assume state from prior runs.

```bash
# Issue body and metadata
gh issue view $ISSUE_NUMBER --repo $REPO --json title,body,labels,comments

# Specific upstream artefacts (PRD, design, test spec) — adjust to taste
gh issue view $ISSUE_NUMBER --repo $REPO --json comments \
  -q '.comments[] | select(.body | contains("ai-agile/artefact/v1")) | .body'

# Files in the repo if needed
find ai-agile/standards -name "*.json" ! -name "*.schema.json"
```

Replace the examples above with the actual reads this agent needs.

---

## Step 4 — Do the work

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

## Step 5 — Closing announcement

Post the closing announcement immediately before the terminal status
call. The orchestrator emits `agent.complete` / `agent.review` /
`agent.blocked` to the audit log on this comment.

```bash
gh issue comment $ISSUE_NUMBER --repo $REPO --body "$(cat <<'EOF'
<!-- ai-agile/announcement/v1 -->
\`\`\`json
{
  "session_id": "ais-v1-iss-$ISSUE_NUMBER-agent-name",
  "agent": "agent-name",
  "phase": "end",
  "ended_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "outcome": "complete",
  "summary": "Replace with one-sentence statement of what this run produced.",
  "artefacts": ["comment {comment-id}"]
}
\`\`\`
EOF
)"
```

Set `outcome` to match the terminal status: `complete`, `review`, or
`blocked`.

---

## Step 6 — Act on findings

Branch by outcome. Reach exactly one of the three terminal calls below.
The orchestrator applies `:failed` if the agent exits without one.

**Path A — success, no human gate (non-gated agents only):**

```bash
bash .github/scripts/status.sh set-complete agent-name $ISSUE_NUMBER
```

**Path B — work done, awaiting human gate (gated agents only):**

```bash
bash .github/scripts/status.sh set-review agent-name $ISSUE_NUMBER \
  "Artefact posted above. Apply {gate-label} to advance the pipeline."
```

The orchestrator promotes `:review` → `:complete` when the human applies
the gate label. Do not apply `:complete` directly for gated work — see
`docs/product/agile/06-status-model.md`.

**Path C — cannot finish without human help:**

```bash
bash .github/scripts/status.sh set-blocked agent-name $ISSUE_NUMBER \
  "Specific reason — what is missing, what decision is needed."
```

Use `set-blocked` when the agent has hit a real obstacle. Do not use it
as a shortcut for ambiguity that the agent could resolve.

---

## Behaviour rules

- Replace this list with hard constraints specific to this agent.
- Use 3–10 bullets. Be specific and testable.
- Examples of useful rules:
  - "Do not edit the issue body — it is human-authored."
  - "Post one artefact comment per run, not many."
  - "Reference STD IDs by their stable identifier; do not inline the
    standard text."
  - "If the input is ambiguous, `set-blocked` rather than guessing."
  - "Do not invoke other agents; the orchestrator handles routing."
- Avoid vague rules like "be concise" or "be helpful" — they do not
  constrain anything.
