# Feature: PRD Writer

## Scenario: A pre-specified issue with the wrong notation gets Gherkin backfilled

**Given** an issue contains substantive requirements in numbered or checklist form but no Given/When/Then
**When** `prd-writer` runs Step 6d
**Then** it appends an `### Acceptance criteria (Gherkin)` section derived from the existing requirements, covering each distinct supported behavioral requirement without a scenario quota

## Scenario: Existing Gherkin coverage is left alone

**Given** a pre-specified issue whose body already contains a `### Acceptance criteria (Gherkin)` section covering all distinct behavioral requirements
**When** `prd-writer` runs Step 6d
**Then** it adds no redundant scenarios -- Step 6d is a no-op

## Scenario: Backfill never invents requirements

**Given** a source spec with N behavioural requirements, where only N distinct behavioral requirements exist
**When** `prd-writer` runs Step 6d
**Then** it derives at most N scenarios, does not invent additional scenarios to meet a classification count, and preserves any nonbehavioral requirements as explicit checks

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

## Scenario: Issue title communicates the shipped outcome in release notes

**Given** an issue with a vague or implementation-only title and an explicit expected outcome in its body
**When** prd-writer computes the title
**Then** it produces a concise, independently understandable title describing the purpose and expected outcome without inventing scope, while retaining the classification prefix

## Scenario: Existing detailed title may be improved without losing meaning

**Given** a pre-specified issue with a technically accurate but unclear title
**When** prd-writer augments the issue
**Then** it may rewrite the title for release-note clarity while preserving all stakeholder-defined scope and constraints

## Scenario: Sizer-generated sub-issue titles remain canonical

**Given** a sizer-created sub-issue with a canonical parent-number title
**When** prd-writer augments the issue
**Then** it leaves that title unchanged

## Scenario: Scenario maximum does not suppress missing coverage

**Given** an issue already has more scenarios than the former classification maximum but one distinct behavioral requirement is uncovered
**When** prd-writer assesses coverage
**Then** it derives a supported scenario for that requirement and does not stop based on the scenario count

## Scenario: Material questions are returned without direct comments

**Given** a material unanswered integration question
**When** prd-writer cannot complete the specification
**Then** it returns `outcome: "blocked"` with the question in `result.json`, without `body_write`, a Question Card, or direct GitHub comments

## Scenario: Both processing modes use the same release-note title rule

**Given** either a sparse issue or a detailed pre-specified issue with a vague title
**When** prd-writer prepares the issue title
**Then** it uses Step 7a's single outcome-oriented sentence rule with the classification prefix, without inventing benefits or changing scope

## Scenario: New PRD begins with release-note summary

**Given** a sparse issue with a supported purpose and expected outcome
**When** prd-writer drafts its PRD
**Then** it places `### Release Notes` immediately after the PRD heading, with a concise 2–4 sentence summary before `### Problem`, retaining all existing downstream section headings

## Scenario: Existing specification gains release notes without losing requirements

**Given** a detailed pre-specified issue without a release-note introduction
**When** prd-writer augments it
**Then** it inserts `### Release Notes` above the preserved specification, describing only supported purpose and outcome without changing requirements

## Scenario: Existing release notes are not duplicated

**Given** a pre-specified issue already containing `### Release Notes`
**When** prd-writer augments it
**Then** the output contains exactly one `### Release Notes` section and preserves its supported content
