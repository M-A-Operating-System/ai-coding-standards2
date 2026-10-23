# Feature: Shadow Runs Parity Validation And Production Migration

## Scenario: Shadow run confirms orchestrator output matches existing release publication
**Given** the orchestrator release flow is configured in shadow (non-publishing) mode alongside the existing Wednesday workflow
**When** the Wednesday release cadence executes
**Then** the orchestrator shadow run output matches the existing GitHub-Actions-based release publication

## Scenario: Production release ownership transferred to orchestrator after parity confirmed
**Given** shadow run parity with the existing release publication has been confirmed
**When** production cutover is performed
**Then** the orchestrator release flow is the sole production owner of weekly release publication

## Scenario: Existing Wednesday workflow no longer independently publishes releases
**Given** production ownership has been cut over to the orchestrator
**When** the existing Wednesday GitHub Actions workflow runs
**Then** it does not independently publish a release and is either retired or reduced to a thin trigger

## Scenario: Migration documentation is present and accessible
**Given** the migration to orchestrator-owned release publication has been completed
**When** a developer reviews the repository
**Then** migration steps and a rollback plan are documented and accessible in the repository

## Scenario: Manual dispatch and retry continue to function after cutover
**Given** the orchestrator owns production release publication
**When** an operator manually dispatches or retries the release flow
**Then** the release completes successfully via the manual invocation
