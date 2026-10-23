# Feature: Release Flow Core

## Scenario: Release flow identifies previous published release boundary

**Given** the repository has at least one previously published release
**When** the release flow starts a new run
**Then** the most recently published release tag is used as the start boundary for change discovery

## Scenario: Release flow collects merged PRs and closed issues since the boundary

**Given** the previous published release boundary has been identified
**When** the release flow runs the discovery phase
**Then** all merged PRs and their associated closed issues since that boundary are collected for the release notes

## Scenario: Release-notes Markdown generation is deterministic

**Given** a consistent set of merged PRs and closed issues as inputs
**When** the release flow generates release-notes Markdown with those inputs
**Then** two runs with identical inputs produce identical Markdown output

## Scenario: Coverage threshold gate blocks publication when threshold is not met

**Given** the set of discovered PRs falls below the configured coverage threshold
**When** the release flow evaluates publication gates
**Then** the release is not published and a coverage-threshold failure is recorded in orchestrator logs

## Scenario: Exclusion rules remove designated PRs from release notes

**Given** one or more merged PRs match the configured exclusion rules
**When** the release flow generates release notes
**Then** the matching PRs are absent from the generated Markdown and publication proceeds on other gate criteria

## Scenario: A rerun does not create a duplicate tag or release

**Given** a GitHub Release with the current release tag already exists
**When** the release flow runs again
**Then** no duplicate tag or release is created and the existing release remains unchanged

## Scenario: Passing validation and all gates results in a published GitHub Release

**Given** the generated release-notes Markdown passes validation and all publication gates are met
**When** the release flow publishes
**Then** a GitHub Release is created on GitHub with the generated notes as its body

## Scenario: Release metadata, status, and errors are present in orchestrator logs after each run

**Given** the release flow completes a run, whether successful or failed
**When** the flow exits
**Then** the release metadata, final status, and any errors from that run are present in orchestrator logs
