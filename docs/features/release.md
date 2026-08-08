# Feature: Release

## Scenario: A pipeline PR is categorized by its classification

**Given** an issue classified `feature` whose code PR is opened by the pipeline
**When** a release is cut that includes that PR
**Then** the PR appears under the "Features" category in the generated notes, not under "Other"

## Scenario: release.yml categories match labels that PRs actually carry

**Given** `.github/release.yml`
**When** its category labels are compared to the labels the pipeline applies to PRs
**Then** every non-catch-all category references a label the pipeline puts on PRs (no dead categories)

## Scenario: Unlabeled hand-authored PRs still appear

**Given** a PR opened outside the pipeline with no classification label
**When** a release is cut
**Then** that PR still appears (under the `"*"` -> Other catch-all), i.e. nothing is dropped

## Scenario: A doc-bearing / bug / toil PR lands in the right bucket

**Given** PRs classified `bug` and `toil`
**Then** they appear under "Fixes" and "Maintenance" respectively
