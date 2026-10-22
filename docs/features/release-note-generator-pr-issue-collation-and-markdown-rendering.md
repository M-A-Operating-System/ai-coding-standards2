# Feature: Release-note generator: PR/issue collation and Markdown rendering

## Scenario: Query and paginate merged PRs within UTC date range

**Given** a repository contains merged PRs within the specified window, open PRs, draft PRs, and closed-unmerged PRs
**When** the generator runs with a UTC start and end timestamp
**Then** only PRs merged within the window are included in the collated set, with all pages of results present

## Scenario: Deduplicate issues closed by multiple PRs

**Given** two distinct merged PRs within the time window both reference a closing keyword for the same issue
**When** the generator runs
**Then** that issue appears exactly once in the release notes output

## Scenario: Apply documented behavior for issues reopened after merge

**Given** an issue was closed by a merged PR within the time window and has since been reopened
**When** the generator runs
**Then** the issue is handled according to the documented reopened-issue policy and is not silently included as though it were still closed

## Scenario: Include issue title, URL, and Release Notes prose in the correct category

**Given** a merged PR closes an issue that has a classification label and a populated Release Notes section
**When** the generator runs
**Then** the output Markdown lists the issue's title, URL, and Release Notes prose exactly once in the section that matches the issue's classification

## Scenario: Exclude issues carrying excluded labels

**Given** a merged PR closes an issue labeled `dependencies`
**When** the generator runs
**Then** that issue does not appear in the release notes output

## Scenario: Fall back to PR classification when issue has no classification label

**Given** a merged PR closes an issue that has no classification label
**When** the generator runs
**Then** the issue appears in the release notes section matching the PR's classification

## Scenario: Emit diagnostic and apply fallback for missing Release Notes section

**Given** a merged PR closes an issue that has no Release Notes section
**When** the generator runs
**Then** a diagnostic entry is emitted for the missing content and the issue appears in the output using the PR title as fallback, without fabricated prose

## Scenario: Dry-run produces reproducible output without publishing

**Given** the generator is invoked with `--dry-run` and an explicit date range
**When** the generator is run twice with identical parameters
**Then** the output is identical both times and no content is published or modified externally
