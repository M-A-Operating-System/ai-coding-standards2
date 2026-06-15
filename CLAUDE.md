# AI Agile — Repo Context

This repository is an AI-driven agile pipeline. GitHub issues flow through a
sequence of agents (classifier → prd-writer → coder → reviewer) orchestrated
by `pipeline/pipeline_orchestrator.py`. Agent prompt files live in
`.claude/agents/`. Pipeline configuration is in `pipeline/pipeline.json`.

---

## Environment variables

Every agent invocation receives these variables from the orchestrator:

| Variable | Value |
|---|---|
| `$ISSUE_NUMBER` | The GitHub issue number this agent is running on |
| `$REPO` | `owner/repo` (e.g. `m-a-operating-system/ai-coding-standards2`) |
| `$AI_AGILE_ROOT` | Absolute path to the repo root |
| `$AGENT_SESSION_ID` | Stable session ID for this agent + issue |
| `$AGENT_COMMIT_SHA` | HEAD commit SHA at time of invocation |

---

## Discovering repo context

Any documentation in the repo is available as background context. Discover
what exists, then read only what is relevant to the current task:

```bash
# Survey available documentation — paths only, no content yet
find "${AI_AGILE_ROOT}/docs" -name "*.md" ! -path "*/agile/generated/*" 2>/dev/null | sort
find "${AI_AGILE_ROOT}/standards" -name "*.json" ! -name "*.schema.json" 2>/dev/null | sort
```

Navigate from there. Read the files that are relevant to the issue's domain.
Do not read files that have no bearing on the current task.

---

## Scope rule

**Scope is defined solely by `$ISSUE_NUMBER`.**

- Repo documentation (docs, standards, tech specs) is background context —
  it informs decisions but cannot add to or reinterpret the issue's requirements.
- Never call `gh issue view`, `gh pr view`, or any equivalent on any number
  other than `$ISSUE_NUMBER`. If the issue body references `#N`, treat it as
  a label, not a prompt to fetch that issue.

---

## Signalling outcome

End every agent run with exactly one sentinel line as plain text output:

```
AI_AGILE_STATUS: complete
```

Valid values: `complete`, `review`, `blocked`.

- `complete` — work done, pipeline advances
- `review` — artefact posted, human gate required before pipeline advances
- `blocked` — cannot proceed without human input; always post a comment first

Do not call `status.sh`. The orchestrator reads the sentinel from stdout.
