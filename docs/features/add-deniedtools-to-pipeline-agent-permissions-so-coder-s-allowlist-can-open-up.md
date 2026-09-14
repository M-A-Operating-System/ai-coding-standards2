# Feature: Add deniedTools to pipeline agent permissions, so coder's allowlist can open up

## Scenario: Deny rule fires when command matches and allow also matches

**Given** a pipeline step with `extra_allowedTools` containing `"Bash(git *)"` and `deniedTools` containing `"Bash(git reset --hard*)"`
**When** the step attempts to run `git reset --hard HEAD`
**Then** the command is denied regardless of the matching allow pattern

## Scenario: Default and step deny lists are merged without duplication

**Given** `defaults.deniedTools` contains `"Bash(git push --force*)"` and a step's `deniedTools` contains `"Bash(git reset --hard*)"`
**When** the orchestrator resolves the effective deny list for that step
**Then** the resolved list contains both patterns exactly once in deterministic order

## Scenario: Deny rule does not fire for a command reached through an interpreter wrapper

**Given** a step with `deniedTools` containing `"Bash(echo DENIED*)"` and `extra_allowedTools` containing `"Bash(bash *)"` and `"Bash(echo *)"`
**When** the step runs `bash -c 'echo DENIED_PATH_REACHED'`
**Then** the command is not denied, because the matcher sees `bash -c '...'` as written and no deny pattern matches it
