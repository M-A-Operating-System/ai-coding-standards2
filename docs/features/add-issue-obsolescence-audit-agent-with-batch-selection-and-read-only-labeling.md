# Feature: Add Issue Obsolescence Audit Agent With Batch Selection And Read-Only Labeling

## Scenario: audit run selects at most ten issues by ascending single sort key
**Given** a repository has more than ten open issues with a mix of never-reviewed and previously-reviewed issues
**When** the agent processes an `issue-obsolescence-audit:requested` trigger
**Then** exactly ten issues are selected, ordered ascending by their `issue-obsolescence-audit:reviewed-YYYY-MM-DD` label date when present, or by the issue `created_at` for issues that have no such label, with no separate buckets for reviewed versus unreviewed issues

## Scenario: tracking label is replaced for every issue in the batch
**Given** a batch of issues has been selected for obsolescence audit
**When** the agent completes processing the batch
**Then** each issue's previous `issue-obsolescence-audit:reviewed-YYYY-MM-DD` label is removed and a new one with today's date is applied, regardless of that issue's verdict

## Scenario: NEEDS-HUMAN-REVIEW verdict triggers needs-review label and comment
**Given** an issue in the audit batch is assigned a NEEDS-HUMAN-REVIEW verdict
**When** the agent records the verdict for that issue
**Then** the `issue-obsolescence-audit:needs-review` label is applied to the issue and an explanatory comment is posted on it

## Scenario: STILL-VALID verdict updates only the tracking label
**Given** an issue in the audit batch is assigned a STILL-VALID verdict
**When** the agent records the verdict for that issue
**Then** only the `issue-obsolescence-audit:reviewed-YYYY-MM-DD` tracking label is updated, no `issue-obsolescence-audit:needs-review` label is applied, and no additional comment is posted
