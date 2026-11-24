# Feature: Hotfix pr-body release-notes extraction

## Scenario: HOTFIX entry uses PR body Release Notes section when present

**Given** a HOTFIX-candidate PR whose body contains a `### Release Notes` section with specific prose
**When** the release note generator collates the HOTFIX entry for that PR
**Then** the HOTFIX entry's prose is the content of the PR body's `### Release Notes` section, not the PR title

## Scenario: HOTFIX entry falls back to PR title when PR body has no Release Notes section

**Given** a HOTFIX-candidate PR whose body contains no `### Release Notes` section
**When** the release note generator collates the HOTFIX entry for that PR
**Then** the HOTFIX entry's prose is the PR title

## Scenario: Issue-based Release Notes extraction is unchanged

**Given** a release-note-linked issue whose body contains a `### Release Notes` section
**When** the release note generator collates that issue's entry
**Then** the entry's prose is the content of the issue body's `### Release Notes` section
