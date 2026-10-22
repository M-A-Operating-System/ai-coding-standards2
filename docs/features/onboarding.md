# Feature: Onboarding

## Scenario: Bump job advances submodule pointer when behind

**Given** the `ai-coding-standards2` submodule in the consuming repo points to a commit behind the latest commit on its default branch
**When** a user triggers `ai_orchestrator.yml` via workflow_dispatch with `bump` set to `true`
**Then** the submodule pointer is advanced to the latest commit on the default branch and the change is committed to the consuming repo

## Scenario: Bump job exits cleanly when submodule is already current

**Given** the `ai-coding-standards2` submodule in the consuming repo already points to the latest commit on its default branch
**When** a user triggers `ai_orchestrator.yml` via workflow_dispatch with `bump` set to `true`
**Then** no new commit is created in the consuming repo and the job completes successfully without error

## Scenario: Onboarding refresh runs after submodule pointer is advanced

**Given** a workflow_dispatch trigger with `bump: true` advances the submodule pointer
**When** the pointer commit step completes
**Then** `get_started.py --full --force` runs, the pipeline-label bootstrap completes, and the resulting managed-file changes are staged and committed, leaving symlinks, labels, and managed files consistent with the bumped version

## Scenario: Bump job does not run on other triggers

**Given** the `ai_orchestrator.yml` workflow is triggered by any event other than a workflow_dispatch with `bump: true`
**When** the workflow run completes
**Then** the `Bump` job is skipped and none of its steps execute

## Scenario: Shared workflow steps appear in one place, not duplicated

**Given** `ai_orchestrator.yml` defines both the `onboard` and `Bump` jobs
**When** the file content is inspected
**Then** the `get_started.py` invocation, the pipeline-label bootstrap, and the stage-and-commit step are defined in a single shared composite action or reusable job called by both `onboard` and `Bump`, with no verbatim duplication of those steps between the two job definitions

## Scenario: Documentation presents Bump job as recommended sync path

**Given** a user consults `docs/product/orchestrator/16-onboarding.md` for instructions on taking a new framework version
**When** they read the "Keeping in sync" section
**Then** the document presents triggering the `Bump` job via workflow_dispatch as the recommended one-click path and retains the still-valid manual procedure alongside it

## Scenario: CI test suite passes on the modified workflow file

**Given** the `ai_orchestrator.yml` file has been modified to add the `bump` input and `Bump` job
**When** the full `pytest` suite and `python3 pipeline/validate.py` are executed against the repository
**Then** all tests pass and no validation errors are reported
