# Feature: Orchestrator Scheduling And Dispatch For The Weekly Release Flow

## Scenario: Weekly cron trigger dispatches the release flow

**Given** the orchestrator has the weekly release flow configured
**When** the weekly cron time fires
**Then** the orchestrator dispatches the release flow

## Scenario: Manual dispatch triggers the release flow

**Given** the orchestrator has the weekly release flow configured
**When** a manual dispatch is initiated
**Then** the orchestrator dispatches the release flow

## Scenario: No-change run skips publication and records a structured outcome

**Given** no merged PRs or closed issues exist since the last release
**When** the release flow is dispatched
**Then** the flow exits without publishing and a structured no-change outcome is recorded

## Scenario: Failed release flow re-triggers without residual state

**Given** the release flow failed during a previous run
**When** the release flow is re-triggered
**Then** the flow starts cleanly with no residual state from the prior failed run

## Scenario: Stub dispatch leaves no GitHub Release

**Given** the release flow stub is active and the 2/3 implementation is not yet merged
**When** the release flow is dispatched
**Then** no GitHub Release is created
