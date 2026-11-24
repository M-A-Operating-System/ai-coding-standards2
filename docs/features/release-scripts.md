# Feature: Release Scripts

## Scenario: First PATCH tag on a repo with no prior tags is v0.0.1

**Given** a client repository has no existing vX.Y.Z tags
**When** the patch-tag step (05_continuous/pr/patch-tag) runs
**Then** the newly pushed tag is v0.0.1

## Scenario: First MINOR release on a repo with no prior tags is v0.1.0

**Given** a client repository has no existing vX.Y.Z tags
**When** the weekly-release step (05_continuous/weekly-release) runs
**Then** the newly created release tag is v0.1.0

## Scenario: PATCH tag bumps the patch component when prior tags exist

**Given** a client repository has at least one existing vX.Y.Z tag
**When** the patch-tag step runs
**Then** the newly pushed tag increments only the PATCH component of the highest existing tag

## Scenario: MINOR release bumps the minor component when prior tags exist

**Given** a client repository has at least one existing vX.Y.Z tag
**When** the weekly-release step runs
**Then** the newly created release tag increments only the MINOR component of the highest existing tag
