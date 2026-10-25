# Feature: Preserve issue titles and release-note narratives when opening draft PRs

## Scenario: PR title matches the issue title verbatim

**Given** an issue title longer than 60 characters
**When** create-pr.sh opens a draft PR for that issue
**Then** the PR title equals the issue title exactly, with no branch-name prefix and no truncation

## Scenario: Release Notes section is copied into the PR body

**Given** an issue with a `### Release Notes` section containing prose, followed by another heading
**When** create-pr.sh opens a draft PR for that issue
**Then** the PR body contains `Closes #N` plus the Release Notes heading and its prose only, stopping before the next heading

## Scenario: No Release Notes section leaves the PR body unchanged

**Given** an issue with no `### Release Notes` section
**When** create-pr.sh opens a draft PR for that issue
**Then** the PR body is `Closes #N`, exactly as today
