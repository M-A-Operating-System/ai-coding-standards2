# Feature: Pipeline

## Scenario: /maos-run works when ai-coding-standards2 is checked out as a nested submodule

**Given** a consuming repo with `ai-coding-standards2/` added as a git submodule and the whole-folder `.claude` symlink installed
**When** a human runs `/maos-run {N}` from the consuming repo's root
**Then** the driver locates and invokes `ai-coding-standards2/pipeline/pipeline_orchestrator.py`, not a nonexistent `pipeline/pipeline_orchestrator.py`

## Scenario: /maos-run continues to work in ai-coding-standards2's own repo

**Given** an interactive session working directly in ai-coding-standards2's own checkout (no nested submodule)
**When** a human runs `/maos-run {N}`
**Then** the driver locates and invokes `pipeline/pipeline_orchestrator.py` at the repo root, unchanged from current behaviour

## Scenario: Missing orchestrator script produces a clear stop, not a silent failure

**Given** neither `pipeline/pipeline_orchestrator.py` nor `ai-coding-standards2/pipeline/pipeline_orchestrator.py` exists relative to the working directory
**When** `/maos-run` is invoked
**Then** it stops and reports the missing prerequisite per the existing Fallback section, rather than attempting a tick against a path that doesn't exist
