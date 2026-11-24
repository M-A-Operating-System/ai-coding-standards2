# Feature: Hotfix collation, categorisation, and rendering

## Scenario: Unlinked merged PR produces a HOTFIX entry

**Given** a release window containing a merged PR with no issue-closing reference
**When** `collate()` processes the release window
**Then** a HOTFIX entry is produced for that PR with the PR title as its prose

## Scenario: HOTFIX candidate carrying an excluded label is not rendered

**Given** a merged PR with no issue-closing reference that carries a label listed in `EXCLUDED_LABELS`
**When** `collate()` processes the release window
**Then** no HOTFIX entry is produced for that PR
**And** the PR is recorded in `diagnostics['excluded']`

## Scenario: HOTFIX PR number appears in prs_covered

**Given** a merged PR with no issue-closing reference that is not excluded
**When** `collate()` processes the release window
**Then** the PR number appears in `diagnostics['prs_covered']`

## Scenario: HOTFIX section is ordered immediately after Security

**Given** `collate()` has produced both a Security-classified entry and a HOTFIX entry
**When** `render_markdown()` is called on the results
**Then** the HOTFIX section appears immediately after the Security section in the rendered Markdown output

## Scenario: render_markdown renders HOTFIX entry using PR-sourced fields

**Given** a HOTFIX entry built from a merged PR with no issue-closing reference
**When** `render_markdown()` renders that entry
**Then** the rendered output uses `pr_title` and the PR URL without requiring `issue_number`, `issue_title`, or `issue_url`

## Scenario: Existing issue-linked entry path is unchanged

**Given** a merged PR with an issue-closing reference
**When** `collate()` and `render_markdown()` process the release window
**Then** the resulting entry uses `issue_title`, `issue_url`, and `issue_number` as before, with no change to the rendered output
