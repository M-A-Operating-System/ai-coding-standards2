# Feature: Github Actions Workflow Integration: Replace Auto-generated Release Notes

## Scenario: Release workflow publishes notes using notes-file flag

**Given** the release.yml workflow is configured to use the Python generator
**When** the Wednesday release workflow runs for a new version tag
**Then** gh release create is called with --notes-file release-notes.md and not --generate-notes, and the tag and version semantics are unchanged

## Scenario: Window start uses prior published release boundary

**Given** a prior published release exists in the repository
**When** the Python generator determines the window start for release notes
**Then** the most recently published release tag is used as the window start rather than the latest patch tag

## Scenario: Discrepancy between tag and commit window boundaries triggers CI diagnostic

**Given** the tag-based window start and the commit-based window start differ
**When** the Python generator computes the release window
**Then** a diagnostic message identifying the discrepancy is written to the CI log

## Scenario: Shadow-run comparison confirms full coverage before production cutover

**Given** GitHub-generated release notes exist for a prior release
**When** the historical shadow-run comparison is executed
**Then** the comparison report confirms all PRs and issues present in the GitHub-generated notes are also present in the Python generator output

## Scenario: PRs outside selected window excluded with diagnostics in CI log

**Given** the release window is computed and some merged PRs fall outside it
**When** the Python generator produces release notes for the window
**Then** PRs merged outside the window are absent from the release notes and the CI log contains diagnostics naming the excluded PRs
