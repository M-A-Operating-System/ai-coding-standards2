# Feature: Add level input to ai_emergency_stop.yml workflow

## Scenario: Emergency stop workflow accepts level choice input with default
**Given** the ai_emergency_stop workflow definition specifies a level input with choices 1, 2, and 3 and a default value of 3
**When** the workflow is triggered without an explicit level value
**Then** the workflow treats the stop level as 3

## Scenario: Pipeline-stop marker includes the chosen level field
**Given** the ai_emergency_stop workflow is triggered with level 2
**When** the workflow writes the .pipeline-stop marker file
**Then** the .pipeline-stop file contains a level field set to 2

## Scenario: Run summary describes what the chosen level stops
**Given** the ai_emergency_stop workflow is triggered with level 1
**When** the workflow run completes and writes the run summary
**Then** the run summary states that level 1 stops AI agents only
