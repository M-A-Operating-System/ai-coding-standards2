# AGENTS.md — Pipeline Index

This file is the context entry point for all AI agents in this repository.
Read it at the start of every session. It tells you where things are,
what the conventions are, and how to use the shared tooling.

---

## Pipeline overview

All work originates from a GitHub issue. Issues flow through 7 phases.
Every phase is handled by one or more agents. Agents use status labels
to signal state. The orchestrator checks those labels and fires the next
agent automatically.

```
issue opened
  → issue-classifier       phase: product-docs
  → prd-writer             phase: product-docs       [HUMAN GATE: prd:approved]
  → product-standards-checker
  → impact-assessor
  → dependency-resolver
  → ticket-sizer                                     [HUMAN GATE: size:approved]
  → architect              phase: technical-docs     [HUMAN GATE: design:approved]
  → adr-proposer
  → test-spec-writer       phase: testing-spec
  → test-coverage-auditor                            [HUMAN GATE: test-spec:approved]
  → task-decomposer        phase: build-plan
  → dependency-planner                               [HUMAN GATE: plan:approved]
  → coder                  phase: execute
  → standards-compliance-reviewer  (PR + schedule)
  → migration-validator    (PR, SQL files only)
  → pr-reviewer                                      [HUMAN GATE: pr:approved]
  → test-writer            phase: test
  → test-runner
  → coverage-enforcer                                [HUMAN GATE: coverage:approved]
  → release-noter          phase: evaluate
  → retrospective-writer
  → standards-evolver      (weekly schedule)
```

---

## Status labels

Labels follow the format `{agent-name}:{status}`.
Full definitions: `ai-agile/pipeline/statuses.json`

| Status | Colour | Meaning | Set by |
|---|---|---|---|
| `wip` | Yellow | Agent is running | Agent (via status.sh) |
| `complete` | Green | Finished successfully | Agent (via status.sh) |
| `review` | Purple | Requesting human approval | Agent (via status.sh) |
| `blocked` | Red-orange | Cannot proceed — needs help | Agent (via status.sh) |
| `failed` | Red | Crashed without clean exit | Orchestrator |
| `skipped` | Light blue | Bypassed by human | Human |

### Status commands

Every agent uses `status.sh` for all label transitions:

```bash
bash .github/scripts/status.sh set-wip      <agent> <issue-or-pr-number>
bash .github/scripts/status.sh set-complete <agent> <issue-or-pr-number>
bash .github/scripts/status.sh set-review   <agent> <issue-or-pr-number> "<message>"
bash .github/scripts/status.sh set-blocked  <agent> <issue-or-pr-number> "<reason>"
bash .github/scripts/status.sh set-failed   <agent> <issue-or-pr-number> "<detail>"
bash .github/scripts/status.sh set-skipped  <agent> <issue-or-pr-number> "<reason>"
bash .github/scripts/status.sh show         <issue-or-pr-number>
```

**Every agent must:**
1. Call `set-wip` immediately on start
2. Call exactly one of `set-complete`, `set-review`, or `set-blocked` before exit
3. Never apply labels directly — always use `status.sh`

---

## Architecture standards

Standards are in `ai-agile/standards/`. Every standard has a stable `STD` ID.

```
ai-agile/standards/
  schemas/
    standards.schema.json   ← JSON Schema for standards files
    adrs.schema.json        ← JSON Schema for ADR files
  examples/
    standards.example.json  ← Example standards (technical + product)
    adrs.example.json       ← Example ADRs
```

When writing code, load and apply applicable standards:

```bash
find ai-agile/standards -name "*.json" ! -name "*.schema.json" | xargs cat
```

Filter by `layer`, `standard_type`, and `kind` (principle/implementation/standard).
For implementation standards, also check `language` matches the file you are writing.

Reference standards in code comments and PR descriptions using the STD ID:
```typescript
// STD000000003 — FK columns must follow {table_singular}_id
```

---

## Agent files

All agent specifications: `.github/agents/`

| Agent | File |
|---|---|
| issue-classifier | `.github/agents/issue-classifier.md` |
| prd-writer | `.github/agents/prd-writer.md` |
| product-standards-checker | `.github/agents/product-standards-checker.md` |
| impact-assessor | `.github/agents/impact-assessor.md` |
| dependency-resolver | `.github/agents/dependency-resolver.md` |
| ticket-sizer | `.github/agents/ticket-sizer.md` |
| architect | `.github/agents/architect.md` |
| adr-proposer | `.github/agents/adr-proposer.md` |
| test-spec-writer | `.github/agents/test-spec-writer.md` |
| test-coverage-auditor | `.github/agents/test-coverage-auditor.md` |
| task-decomposer | `.github/agents/task-decomposer.md` |
| dependency-planner | `.github/agents/dependency-planner.md` |
| coder | `.github/agents/coder.md` |
| standards-compliance-reviewer | `.github/agents/standards-compliance-reviewer.md` |
| migration-validator | `.github/agents/migration-validator.md` |
| pr-reviewer | `.github/agents/pr-reviewer.md` |
| test-writer | `.github/agents/test-writer.md` |
| test-runner | `.github/agents/test-runner.md` |
| coverage-enforcer | `.github/agents/coverage-enforcer.md` |
| release-noter | `.github/agents/release-noter.md` |
| retrospective-writer | `.github/agents/retrospective-writer.md` |
| standards-evolver | `.github/agents/standards-evolver.md` |

---

## Workflows

```
.github/workflows/
  pipeline-orchestrator.yml    ← Triggers on label events and every 15 min
  standards-compliance-check.yml ← Daily compliance review + PR trigger
```

---

## Running an agent manually

```bash
claude \
  --allowedTools "Bash(git *),Bash(gh *),Bash(bash .github/scripts/status.sh *),Read,Glob,Grep" \
  --max-turns 60 \
  -p "You are the {agent-name} agent defined in .github/agents/{agent-name}.md.
Follow those instructions exactly.

Repository: {OWNER/REPO}
Issue/PR number: #{NUMBER}
Title: {TITLE}"
```

---

## Key conventions

- Issue titles: descriptive, not placeholders
- PR titles: `[agent-name] {description} (#{issue})`
- Commit messages: Conventional Commits — `feat:`, `fix:`, `chore:`, `test:`
- Branch names: `task/{issue-number}-{slug}` for implementation,
  `tests/{pr-number}-{slug}` for test PRs
- All DB identifiers: `snake_case`, tables plural, columns singular
- FK columns: `{table_singular}_id`
- Never use `any` in TypeScript
- RLS enabled on every user-facing table
