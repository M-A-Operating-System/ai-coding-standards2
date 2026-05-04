# Lifecycle

Every change passes through seven phases. Each phase has clearly defined
inputs, outputs, agents, and (where applicable) a human gate. The orchestrator
enforces the order via the dependency graph in `.claude/pipeline.json`.

```
issue opened
  ┌────────────────────────────────────────────────────────┐
  │ 1. Product docs                                         │
  │     issue-classifier → prd-writer [GATE prd:approved]   │
  │     → product-standards-checker → impact-assessor       │
  │     → dependency-resolver → ticket-sizer                │
  │     [GATE size:approved]                                │
  └────────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ 2. Technical docs                                       │
  │     architect [GATE design:approved] → adr-proposer     │
  └────────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ 3. Testing spec                                         │
  │     test-spec-writer → test-coverage-auditor            │
  │     [GATE test-spec:approved]                           │
  └────────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ 4. Build plan                                           │
  │     task-decomposer → dependency-planner                │
  │     [GATE plan:approved]                                │
  └────────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ 5. Execute                                              │
  │     coder (one PR per task)                             │
  │     → standards-compliance-reviewer                     │
  │     → migration-validator (SQL only)                    │
  │     → pr-reviewer [GATE pr:approved]                    │
  └────────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ 6. Test                                                 │
  │     test-writer → test-runner → coverage-enforcer       │
  │     [GATE coverage:approved]                            │
  └────────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌────────────────────────────────────────────────────────┐
  │ 7. Evaluate                                             │
  │     release-noter → retrospective-writer                │
  │     → standards-evolver (weekly)                        │
  │     [GATE standards-proposal:approved]                  │
  └────────────────────────────────────────────────────────┘
```

---

## What each phase produces

| Phase | Primary artefact | Lives at |
|---|---|---|
| 1. Product docs | PRD, sized ticket, dependency map | Issue comments + child issues |
| 2. Technical docs | Technical design, ADR drafts | Issue comments + `ai-agile/standards/adrs.json` |
| 3. Testing spec | Numbered Gherkin scenarios | Issue comment |
| 4. Build plan | Ordered task list | Child issues + dependency graph |
| 5. Execute | One PR per task | GitHub PRs |
| 6. Test | Test files, coverage report | PR + CI artefacts |
| 7. Evaluate | Changelog, retrospective, standards proposals | `CHANGELOG.md`, retrospective comment, new issues |

---

## How the pipeline advances

The orchestrator is invoked on three triggers:

1. **Label events.** Any time a label is added or removed on an issue or PR,
   the orchestrator re-evaluates eligibility.
2. **PR events.** PR opened, synchronised, merged, or closed.
3. **Schedule.** Every 15 minutes during working hours, as a backstop.

For each work item it:

1. Reads the current label set.
2. For each agent, checks whether (a) the trigger condition is satisfied,
   (b) every dependency has applied its `:complete` label, and (c) every
   required human gate label is present.
3. If yes, applies `{agent}:wip` and invokes the agent via the Claude CLI.
4. The agent does its work and applies exactly one terminal status:
   `:complete`, `:review`, or `:blocked`.
5. If the agent crashed without setting a status, the orchestrator applies
   `:failed` and posts a comment.

A halted pipeline (review, blocked, failed) resumes the moment a human
removes the offending label. There is no separate "retry" button.

---

## Forks in the path

Two cases interrupt the linear flow:

**1. The ticket is too big.** If the `ticket-sizer` returns XL, the parent
issue does not advance to the architect. Instead the human breaks the parent
into child tickets, and each child re-enters the pipeline at
`issue-classifier`. The parent waits.

**2. SQL changes.** When the `coder` opens a PR that touches `**/*.sql`, the
`migration-validator` runs in addition to the standard reviewers. Merge is
blocked on naming, RLS, and type violations regardless of the standard
review path.

---

## End-to-end happy path

A typical small ticket flows like this:

| Time | Event |
|---|---|
| T+0 | Stakeholder opens issue |
| T+2m | `issue-classifier` validates required fields |
| T+5m | `prd-writer` posts PRD; `prd-writer:review` applied |
| T+1h | Stakeholder approves; applies `prd:approved` |
| T+5m | `product-standards-checker`, `impact-assessor`, `dependency-resolver` run in sequence |
| T+10m | `ticket-sizer` posts size; `ticket-sizer:review` applied |
| T+30m | Engineer applies `size:approved` |
| T+15m | `architect` posts technical design; `architect:review` applied |
| T+1h | Engineer applies `design:approved` |
| T+5m | `adr-proposer` runs (no ADRs needed in this case) |
| T+10m | `test-spec-writer` and `test-coverage-auditor` run; `test-coverage-auditor:review` applied |
| T+30m | Engineer applies `test-spec:approved` |
| T+10m | `task-decomposer`, `dependency-planner` run; `dependency-planner:review` applied |
| T+15m | Engineer applies `plan:approved` |
| T+30m | `coder` opens PR; reviewers run; `pr-reviewer:review` applied |
| T+1h | Engineer applies `pr:approved` |
| T+10m | `test-writer`, `test-runner`, `coverage-enforcer` run; `coverage-enforcer:review` applied |
| T+15m | Engineer applies `coverage:approved`; PR is merged |
| T+5m | `release-noter` opens changelog PR, closes child issues |
| T+5m | `retrospective-writer` posts retrospective on parent issue |
| Weekly | `standards-evolver` reviews retrospectives, drafts proposals |

Total wall-clock human time: minutes. Total elapsed time: hours.
