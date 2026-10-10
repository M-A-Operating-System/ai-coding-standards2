# Feature: Release

## Scenario: A pipeline PR is categorized by its classification

**Given** an issue classified `enhancement` whose code PR is opened by the pipeline
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

## Scenario: A doc-bearing / bug / tech-debt PR lands in the right bucket

**Given** PRs classified `bug` and `tech-debt`
**Then** they appear under "Fixes" and "Maintenance" respectively

## Scenario: Per-PR merge pushes a PATCH tag with no GitHub Release

**Given** a PR has just been merged to main and the current latest tag is vX.Y.Z
**When** the per-PR tagging workflow runs
**Then** a new tag vX.Y.(Z+1) is pushed to the repository and no GitHub Release entry is created for that tag

## Scenario: Weekly release bumps MINOR and publishes a Release when PRs merged during the week

**Given** one or more PRs have merged to main since the last vX.Y.0 weekly release tag, each having already created a PATCH tag
**When** the weekly release workflow runs
**Then** a new vX.(Y+1).0 tag is pushed and a GitHub Release with generated notes is published

## Scenario: Weekly release skips when nothing merged since last weekly release

**Given** no commits have been pushed to main since the last vX.Y.0 weekly release tag
**When** the weekly release workflow runs
**Then** no new tag is pushed and no new GitHub Release is created

## Scenario: Manual MAJOR tag push triggers a GitHub Release without automation

**Given** a maintainer manually pushes a v(X+1).0.0 annotated tag to the repository
**When** the release workflow's push-tags trigger fires
**Then** a GitHub Release is published for that tag and no workflow has automatically computed or pushed a new MAJOR version tag
