# Feature: PRD Writer

## Scenario: A pre-specified issue with the wrong notation gets Gherkin backfilled

**Given** an issue scores >=4/6 signals (pre-specified, routes to augmentation) and uses a numbered-requirements or checklist format with no Given/When/Then
**When** `prd-writer` runs Step 6e
**Then** it appends an `### Acceptance criteria (Gherkin)` section derived from the existing requirements, reaching the classification band's minimum scenario count when the source material supports it

## Scenario: Existing Gherkin coverage is left alone

**Given** a pre-specified issue whose body already contains a `### Acceptance criteria (Gherkin)` section meeting the band's minimum
**When** `prd-writer` runs Step 6e
**Then** it makes no change -- Step 6e is a no-op

## Scenario: Backfill never invents requirements

**Given** a source spec with N behavioural requirements, where N is less than the classification band's minimum
**When** `prd-writer` runs Step 6e
**Then** it derives at most N scenarios, does not invent additional ones to reach the minimum, and states the shortfall with a reason

## Scenario: Non-behavioural requirements are not padded into scenarios

**Given** a source spec containing requirements that describe only internal/structural behaviour (no user-observable surface)
**When** `prd-writer` runs Step 6e
**Then** those requirements are not converted into scenarios on their own

## Scenario: Sizer-created sub-issues are covered

**Given** a sizer-created sub-issue (detected via Step 2) with no Gherkin in its template-generated body
**When** `prd-writer` processes it
**Then** Step 6e still runs and backfills Gherkin from the sub-issue's mapped requirement range, the same as a standalone augmentation-mode issue

## Scenario: Already-approved PRDs are not silently rewritten

**Given** an issue already carrying `prd-writer:approved` from a prior run
**When** `prd-writer` is re-invoked on that issue (e.g. a later pipeline step re-triggers it)
**Then** Step 6e does not retroactively backfill Gherkin onto the already-approved spec -- backfill only applies on prd-writer's first pass

## Scenario: The derived section is clearly attributed and traceable

**Given** Step 6e derives scenarios from source requirements
**When** the section is appended
**Then** each derived scenario is tagged back to its source requirement (e.g. `<!-- R24 -->`), and the section is labelled as derived by prd-writer, not presented as if the human wrote it
