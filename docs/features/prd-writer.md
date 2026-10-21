# Feature: PRD Writer

## Scenario: A pre-specified issue with the wrong notation gets Gherkin backfilled

**Given** an issue scores >=4/6 signals (pre-specified, routes to augmentation) and uses a numbered-requirements or checklist format with no Given/When/Then
**When** `prd-writer` runs Step 6d
**Then** it appends an `### Acceptance criteria (Gherkin)` section derived from the existing requirements, reaching the classification band's minimum scenario count when the source material supports it

## Scenario: Existing Gherkin coverage is left alone

**Given** a pre-specified issue whose body already contains a `### Acceptance criteria (Gherkin)` section covering all distinct behavioral requirements
**When** `prd-writer` runs Step 6d
**Then** it adds no redundant scenarios -- Step 6d is a no-op

## Scenario: Backfill never invents requirements

**Given** a source spec with N behavioural requirements, where N is less than the classification band's minimum
**When** `prd-writer` runs Step 6d
**Then** it derives at most N scenarios, does not invent additional ones to reach the minimum, and states the shortfall with a reason

## Scenario: Non-behavioural requirements are not padded into scenarios

**Given** a source spec containing requirements that describe only internal/structural behaviour (no user-observable surface)
**When** `prd-writer` runs Step 6d
**Then** those requirements are not converted into scenarios on their own

## Scenario: Sizer-created sub-issues are covered

**Given** a sizer-created sub-issue (detected via Step 2) with no Gherkin in its template-generated body
**When** `prd-writer` processes it
**Then** Step 6d still runs and backfills Gherkin from the sub-issue's mapped requirement range, the same as a standalone augmentation-mode issue

## Scenario: Already-approved PRDs are not silently rewritten

**Given** an issue already carrying `prd-writer:approved` from a prior run
**When** `prd-writer` is re-invoked on that issue (e.g. a later pipeline step re-triggers it)
**Then** Step 6d does not retroactively backfill Gherkin onto the already-approved spec -- backfill only applies on prd-writer's first pass

## Scenario: The derived section is clearly attributed and traceable

**Given** Step 6d derives scenarios from source requirements
**When** the section is appended
**Then** each derived scenario is tagged back to its source requirement (e.g. `<!-- R24 -->`), and the section is labelled as derived by prd-writer, not presented as if the human wrote it

## Scenario: Technical specification without user stories is preserved

**Given** an issue with explicit file structure, orchestrator sequencing, schemas and exclusions but no user stories or Gherkin
**When** prd-writer assesses it
**Then** it uses augmentation and retains all substantive requirements verbatim

## Scenario: Stakeholder architecture remains binding

**Given** an issue requiring CodeQL as a post-merge orchestrator step
**When** prd-writer prepares the issue
**Then** that execution order and integration requirement remain explicit and unchanged

## Scenario: Scenario count does not drive new requirements

**Given** an issue with one testable behavior and a classification band minimum greater than one
**When** prd-writer backfills acceptance coverage
**Then** it creates only supported scenarios and never invents requirements to meet a quota

## Scenario: Keywords do not force decomposition

**Given** a bounded issue mentioning platform or redesign
**When** prd-writer evaluates scope
**Then** it does not block solely because of those words

## Scenario: Ambiguous feedback is surfaced

**Given** stakeholder feedback whose interpretation would materially change scope
**When** prd-writer revises the issue
**Then** it identifies the ambiguity rather than silently selecting an interpretation

## Scenario: CodeQL issues retain metrics and dependency contracts

**Given** issues #586 and #587 containing post-merge sequencing, file paths, issue dependency, metric ledger requirements and exclusions
**When** prd-writer processes them
**Then** every explicit requirement remains represented and verifiable

## Scenario: Material unanswered questions block the PRD

**Given** an unresolved question materially affecting scope, architecture, or acceptance criteria
**When** prd-writer assesses the issue
**Then** it returns blocked with specific questions and no body_write, without requesting approval or advancing to sizing

## Scenario: Nonblocking questions remain visible

**Given** a clarification that does not affect implementation or acceptance
**When** prd-writer submits a PRD
**Then** it returns review and includes the question in the issue body and artefact output

## Scenario: Question handling uses existing orchestration

**Given** an unresolved material question
**When** prd-writer exits
**Then** it uses the existing blocked outcome and does not post comments or change labels directly

## Scenario: Issue title preserves scope

**Given** an existing descriptive issue title
**When** prd-writer computes a title
**Then** it retains the meaning and scope, preferring a classification prefix over substantive rephrasing
