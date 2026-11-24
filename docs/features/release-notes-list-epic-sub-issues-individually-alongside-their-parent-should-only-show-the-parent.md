# Feature: Release notes list epic sub-issues individually alongside their parent should only show the parent

## Scenario: Sub-issue is excluded from generated release notes

**Given** issue #614 carries the label "parent-issue:608"
**And** a merged PR references "Closes #614"
**When** the release notes generator runs
**Then** the generated release notes do not contain a top-level entry for issue #614

## Scenario: Parent epic issue appears normally in generated release notes

**Given** issue #608 does not carry any label matching the "parent-issue:" prefix
**And** a merged PR references "Closes #608"
**When** the release notes generator runs
**Then** the generated release notes contain a top-level entry for issue #608

## Scenario: Excluded sub-issue is recorded in diagnostics with reason

**Given** issue #614 carries the label "parent-issue:608"
**And** a merged PR references "Closes #614"
**When** the release notes generator runs
**Then** diagnostics["excluded"] contains an entry for issue #614 with reason "sub-issue of #608"
