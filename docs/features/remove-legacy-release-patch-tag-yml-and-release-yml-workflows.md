# Feature: Remove Legacy Release Patch Tag Yml And Release Yml Workflows

## Scenario: release-patch-tag.yml is absent from the repository
**Given** the legacy workflow removal PR has been merged to main
**When** the .github/workflows directory is listed
**Then** release-patch-tag.yml is not present

## Scenario: release.yml is absent from the repository
**Given** the legacy workflow removal PR has been merged to main
**When** the .github/workflows directory is listed
**Then** release.yml is not present

## Scenario: orchestrator steps remain the sole automated release mechanisms
**Given** both legacy workflow files have been removed
**When** pipeline.json is inspected
**Then** 05_continuous/pr/patch-tag and 05_continuous/weekly-release are the only automated release-cutting steps declared
