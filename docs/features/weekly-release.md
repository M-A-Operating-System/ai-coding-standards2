# Feature: Weekly Release

## Scenario: First automated run uses 7-day window when no prior release exists

**Given** the repository has no GitHub Release
**When** the weekly-release flow runs
**Then** the release-notes window starts 7 days before the run timestamp, not from `1970-01-01T00:00:00Z`

## Scenario: Existing release anchor is preserved for subsequent runs

**Given** the repository has at least one prior GitHub Release with a known publish date
**When** the weekly-release flow runs
**Then** the release-notes window starts from that release's publish date, unchanged

## Scenario: No-prior-release unit test asserts 7-day fallback

**Given** `tests/test_weekly_release_flow.py` contains a test for the no-prior-release path
**When** the test suite runs
**Then** the no-prior-release test passes and asserts a window start of 7 days before the run timestamp
