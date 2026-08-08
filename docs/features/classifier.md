# Feature: Classifier

## Scenario: A clear vulnerability is classified security

**Given** an open issue whose body describes a concrete vulnerability (e.g. an auth bypass or SQL injection)
**When** `issue-classifier` runs
**Then** it classifies the issue as `security`, applies `classification: security`, and applies the `[SECURITY]` title prefix

## Scenario: Security outranks bug

**Given** an issue that is both a defect and a security vulnerability
**When** `issue-classifier` runs
**Then** it classifies `security`, not `bug`

## Scenario: Ambiguous items are not over-classified

**Given** an issue that only vaguely alludes to security ("this might be unsafe") without a concrete vulnerability
**When** `issue-classifier` runs
**Then** it does NOT classify `security` (it classifies `bug`/other or requests clarification)

## Scenario: Security items are scheduled first

**Given** an open `classification: security` item and other eligible non-security items
**When** the orchestrator selects the next work item
**Then** the security item is picked before the non-security items

## Scenario: Review is preserved

**Given** a security item proceeding through the pipeline
**When** it reaches `pr-reviewer` and the human gates
**Then** those steps still run (expedited != unreviewed); the coder's change includes a regression test proving the vulnerability is fixed
