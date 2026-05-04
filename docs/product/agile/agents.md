# Agents

Each agent owns one job in the lifecycle. Agents are stateless: they read the
issue, the PR, and the standards files, produce an artefact, and apply a
status label. They never call each other directly — the orchestrator decides
who runs next based on labels.

This page describes each agent in product terms. The full machine-readable
definition is in `.claude/pipeline.json`. The full prompt is in
`.claude/agents/{agent-name}.md`.

---

## Phase 1 — Product docs

### issue-classifier

**Owns.** First-pass triage of every newly opened issue.

**Does.** Classifies the issue as `bug`, `feature`, `chore`, or `spike`.
Validates that required fields are present (acceptance criteria, stakeholder).
Rejects malformed issues with a corrective comment that the stakeholder can
act on.

**Output.** A classification comment and the appropriate type label.

**Human gate.** None.

### prd-writer

**Owns.** The Product Requirements Document.

**Does.** Reads the issue, asks clarifying questions if needed, and produces
a PRD covering: problem statement, user stories, success metrics,
out-of-scope items, and explicit acceptance criteria.

**Output.** A single PRD comment on the issue.

**Human gate.** Stakeholder applies `prd:approved`.

### product-standards-checker

**Owns.** Compliance of the PRD against active product-layer standards.

**Does.** Cross-references the PRD against every active standard with
`standard_type: product`. Flags violations by STD ID before any design work
begins.

**Output.** A compliance report comment. May raise standards-violation issues.

**Human gate.** None — non-blocking unless a `required` violation is found.

### impact-assessor

**Owns.** The blast radius of the proposed change.

**Does.** Identifies affected layers, services, files, and data models.
Flags if the scope crosses more than one bounded context.

**Output.** An impact report comment.

**Human gate.** None.

### dependency-resolver

**Owns.** External dependencies of the work.

**Does.** Identifies open tickets that must complete first, third-party APIs
required, data prerequisites, and team dependencies. Halts on unresolved hard
dependencies.

**Output.** A dependency report comment. May apply `:blocked` if a hard
dependency is unresolved.

**Human gate.** None at the agent level — but `:blocked` halts the pipeline.

### ticket-sizer

**Owns.** Whether the ticket fits a single development cycle.

**Does.** Applies an S / M / L / XL size. If XL, mandates decomposition into
child tickets before any design work begins.

**Output.** A size comment. If XL, halts and waits for the human to break the
parent into child issues.

**Human gate.** Engineer applies `size:approved`.

---

## Phase 2 — Technical docs

### architect

**Owns.** The technical design.

**Does.** Produces a design covering data model changes, API contracts,
component boundaries, integration points, and non-functional requirements.
Flags candidates for ADRs.

**Output.** A design document comment.

**Human gate.** Engineer applies `design:approved`.

### adr-proposer

**Owns.** Architecture Decision Record drafts.

**Does.** Reviews the technical design for non-obvious decisions, deviations
from existing standards, or significant tradeoffs. Drafts ADR stubs in the
required JSON schema.

**Output.** Either a "no ADRs required" comment or one or more ADR draft
comments. Drafts are added to `ai-agile/standards/adrs.json` by a human.

**Human gate.** None — non-blocking. Drafts are reviewed at the next gate.

---

## Phase 3 — Testing spec

### test-spec-writer

**Owns.** The testing specification.

**Does.** Generates numbered Gherkin scenarios (`SC-001`, `SC-002`, …) from
the PRD acceptance criteria and the technical design. Distinguishes unit,
integration, and E2E scope.

**Output.** A test spec comment with numbered scenarios.

**Human gate.** None — followed immediately by the auditor.

### test-coverage-auditor

**Owns.** Completeness of the test spec.

**Does.** Verifies every PRD acceptance criterion maps to at least one
scenario. Verifies every API endpoint and data mutation has a test case.
Blocks on gaps.

**Output.** A coverage report comment. Halts on gaps.

**Human gate.** Engineer applies `test-spec:approved`.

---

## Phase 4 — Build plan

### task-decomposer

**Owns.** Breaking the parent issue into implementation tasks.

**Does.** Produces ordered child issues, each scoped to a single file or
concern, each carrying a done condition and references to applicable STD IDs.

**Output.** Child issues linked back to the parent.

**Human gate.** None.

### dependency-planner

**Owns.** The build order across child tasks.

**Does.** Analyses inter-task dependencies, identifies the critical path,
flags tasks that can run in parallel.

**Output.** A build plan comment with the dependency graph.

**Human gate.** Engineer applies `plan:approved`.

---

## Phase 5 — Execute

### coder

**Owns.** The implementation of each child task.

**Does.** Implements one task at a time in dependency order. Opens a PR per
task with the prefix `[coder]`. Self-reviews against the done condition and
the linked Gherkin scenario(s). Follows applicable STDs.

**Output.** One PR per task. Commits use Conventional Commits.

**Human gate.** None at the coder level — gated by `pr-reviewer`.

### standards-compliance-reviewer

**Owns.** Conformance of changed files to active architecture standards.

**Does.** Runs on every PR and on a daily schedule. Reviews changed files
against active standards, raises issues with STD ID and rationale, and
proposes diffs for simple fixes.

**Output.** Issues prefixed `[standards-compliance-reviewer]` for each
violation. May post inline review comments.

**Human gate.** None — but `required` violations block merge via the
`pr-reviewer`.

### migration-validator

**Owns.** SQL migration files.

**Does.** Triggered only on PRs that touch `**/*.sql`. Confirms migrations
are forward-only, idempotent, and follow database-layer naming, RLS, and
typing standards.

**Output.** A validation comment. Blocks merge on violations.

**Human gate.** None — but failures block merge.

### pr-reviewer

**Owns.** Final review of the PR against the design and test spec.

**Does.** Checks scope creep, confirms implementation matches the
architecture decisions, verifies all `required` STD violations are resolved.

**Output.** A PR review (approve or request changes).

**Human gate.** Engineer applies `pr:approved`.

---

## Phase 6 — Test

### test-writer

**Owns.** Implementing the tests defined in the spec.

**Does.** For each scenario in the test spec, writes a test named to its
scenario ID (`SC-001`, …). Follows testing-layer standards.

**Output.** Test files committed to the PR.

**Human gate.** None.

### test-runner

**Owns.** Running the suite.

**Does.** Runs the full test suite. Posts pass/fail summary, coverage delta,
and failing scenario IDs.

**Output.** A PR comment with the test result. Blocks merge on failure or
coverage regression.

**Human gate.** None — but failures block merge.

### coverage-enforcer

**Owns.** Coverage against the test spec.

**Does.** Compares the actual test coverage against the spec thresholds.
Flags acceptance criterion scenarios that have no passing test.

**Output.** A coverage report comment.

**Human gate.** Engineer applies `coverage:approved`.

---

## Phase 7 — Evaluate

### release-noter

**Owns.** The changelog entry and the closure of the parent issue.

**Does.** On PR merge, generates a changelog entry from the PRD and the
merged PR. Opens a follow-up PR to add it to `CHANGELOG.md`. Closes all
child task issues. Posts a completion summary on the parent issue.

**Output.** A changelog PR + closing comment on the parent issue.

**Human gate.** None.

### retrospective-writer

**Owns.** A structured retrospective for every closed parent issue.

**Does.** Records phase durations, standards violations raised, test spec
completeness at build start, PRD changes after design, and improvement
suggestions.

**Output.** A retrospective comment on the closed parent issue.

**Human gate.** None.

### standards-evolver

**Owns.** Proposing evolution of the standards based on observed reality.

**Does.** Runs weekly. Reviews recent retrospectives and recurring violation
patterns. Drafts new or updated standards in the JSON schema format. Opens
an issue per proposal for human review.

**Output.** One issue per proposed standard, each with the draft JSON inline.

**Human gate.** Standards owner applies `standards-proposal:approved`.

---

## Cross-cutting agent properties

Every agent in the pipeline:

- Reads `.claude/AGENTS.md` at the start of every session for shared context.
- Calls `bash .github/scripts/status.sh set-wip <agent> <number>` immediately
  on start.
- Calls exactly one of `set-complete`, `set-review`, or `set-blocked` before
  exit.
- Never applies labels directly — always via `status.sh`.
- References standards by STD ID in any artefact it produces.
