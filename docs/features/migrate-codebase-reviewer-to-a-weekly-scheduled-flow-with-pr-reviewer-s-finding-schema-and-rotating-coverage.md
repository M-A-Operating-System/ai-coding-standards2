# Feature: Migrate Codebase-Reviewer To A Weekly Scheduled Flow With Pr-Reviewer S Finding Schema And Rotating Coverage

## Scenario: codebase-review flow is triggered by schedule only

**Given** the pipeline configuration in pipeline.json has been updated
**When** the orchestrator evaluates the codebase-review flow's trigger configuration
**Then** the flow uses a schedule-based trigger at the flow level and an event-schedule trigger at the step level, with no label or issue trigger remaining in the codebase-review flow

## Scenario: codebase-reviewer produces findings in pr-reviewer schema shape

**Given** the codebase-reviewer agent has completed a review pass
**When** its output findings are inspected
**Then** each finding contains the fields id (RV-NNN), category (defect or improvement), type, severity, confidence, path, line, evidence, and fix, with effort present for improvements and standard and adr optional, matching pr-reviewer's schema field-for-field

## Scenario: Agent requests review issue creation through result.json

**Given** the codebase-reviewer has completed its review cycle
**When** it writes its result
**Then** the creates_issue field in result.json is populated with the new issue title, body, and labels, and the agent makes no direct gh issue create call

## Scenario: Each weekly cycle produces a distinct new findings issue

**Given** a prior "Technical Review" issue from a previous cycle already exists
**When** the next weekly scheduled run completes
**Then** a new "Technical Review - {date}" issue is created for the current cycle rather than appending findings to the prior cycle's issue

## Scenario: Agent selects only next-due components based on coverage tracker

**Given** a durable coverage tracker records the last-reviewed date for each codebase component
**When** the codebase-reviewer runs a scheduled cycle
**Then** it selects only the components with the earliest last-reviewed date that fit within the cycle's budget, reviews only those components, and updates the tracker with the new review date

## Scenario: Finding already open in a prior cycle is not re-filed

**Given** a still-open "Technical Review" issue from a prior cycle contains a finding at a specific path and line
**When** the codebase-reviewer identifies the same defect at that same location in the current cycle
**Then** it does not file a new finding for that location and instead records a cross-reference to the existing issue and finding ID in the cycle summary

## Scenario: test_scheduled_flows.py confirms codebase-review is a scheduled agent flow

**Given** the pytest suite is run
**When** the test case for the codebase-review flow in tests/test_scheduled_flows.py executes
**Then** the flow is confirmed as a scheduled, agent-type step with no work-item dependency, and the test passes
