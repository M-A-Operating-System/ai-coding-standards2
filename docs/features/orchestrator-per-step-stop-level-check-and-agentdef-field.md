# Feature: Orchestrator per-step stop level check and AgentDef field

## Scenario: AgentDef defaults stop_on_level to 1 when pipeline.json omits stopOnLevel

**Given** a step definition in pipeline.json has no stopOnLevel field
**When** AgentDef is constructed for that step
**Then** the step's stop_on_level is 1

## Scenario: is_pipeline_stopped returns the active stop level integer

**Given** a .pipeline-stop marker with level 2 is present in the repository
**When** is_pipeline_stopped() is called
**Then** it returns the integer 2

## Scenario: pipeline-stop marker without level field defaults to level 3

**Given** a .pipeline-stop marker with no level field is present in the repository
**When** is_pipeline_stopped() is called
**Then** it returns 3

## Scenario: level-1 stop blocks only steps at or below stop_on_level 1

**Given** the active stop level is 1 and three steps exist with stop_on_level 1, 2, and 3 respectively
**When** each step's eligibility is evaluated in headless mode
**Then** the step with stop_on_level 1 is blocked and the steps with stop_on_level 2 and 3 proceed

## Scenario: level-2 stop blocks steps at or below stop_on_level 2

**Given** the active stop level is 2 and three steps exist with stop_on_level 1, 2, and 3 respectively
**When** each step's eligibility is evaluated in headless mode
**Then** steps with stop_on_level 1 and 2 are blocked and the step with stop_on_level 3 proceeds

## Scenario: level-3 stop blocks all steps

**Given** the active stop level is 3 and three steps exist with stop_on_level 1, 2, and 3 respectively
**When** each step's eligibility is evaluated in headless mode
**Then** all three steps are blocked

## Scenario: interactive run logs stop level and does not block steps

**Given** the run mode is interactive and the active stop level is 1
**When** a step with stop_on_level 1 has its eligibility evaluated
**Then** the step is not blocked and the stop level is logged
