# Feature: Add 05_continuous/pr/patch-tag Pipeline Step and push-patch-tag.sh Script

## Scenario: pipeline.json declares the patch-tag step with correct configuration
**Given** `pipeline/pipeline.json` is parsed
**When** the step named `05_continuous/pr/patch-tag` is inspected
**Then** it has `stopOnLevel` set to `3` and `expected_effect.commits` set to `false`

## Scenario: push-patch-tag.sh skips when HEAD is already tagged
**Given** `scripts/push-patch-tag.sh` exists and the current HEAD commit is already tagged
**When** `push-patch-tag.sh` is executed
**Then** no new tag is pushed and the script exits with success

## Scenario: push-patch-tag.sh increments the PATCH version when HEAD is untagged
**Given** `scripts/push-patch-tag.sh` exists and the current HEAD commit has no existing tag
**When** `push-patch-tag.sh` is executed
**Then** a new tag is pushed with the PATCH component incremented by one and all other version components unchanged

## Scenario: orchestrator invokes the patch-tag step on a merged pull request
**Given** the orchestrator is running and receives a `pull_request.closed` event with `merged: true` targeting `main`
**When** the event is processed
**Then** the `05_continuous/pr/patch-tag` step is invoked

## Scenario: no new GitHub Actions trigger block is added for the patch-tag step
**Given** the GitHub Actions workflows directory contains the same workflow files as before this change
**When** each workflow file is inspected for new `on:` trigger blocks
**Then** no workflow file contains a new `on:` trigger block introduced for the patch-tag step

## Scenario: patch-tag step is skipped at pipeline-stop level 3
**Given** the repository's `.pipeline-stop` file is set to level `3`
**When** a PR is merged to `main`
**Then** the `05_continuous/pr/patch-tag` step is not invoked
