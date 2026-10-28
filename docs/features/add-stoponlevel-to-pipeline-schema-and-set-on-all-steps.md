# Feature: Add stopOnLevel to pipeline schema and set on all steps

## Scenario: Schema validation passes with stopOnLevel defined

**Given** `pipeline.schema.json` defines `stopOnLevel` as an integer enum `[1, 2, 3]` in `definitions.step.properties`
**When** `python3 pipeline/validate.py` is run against `pipeline.json`
**Then** the validator exits with code 0 and reports no errors

## Scenario: Agent-type steps carry stopOnLevel 1

**Given** `pipeline.json` is the live pipeline configuration
**When** all steps with `type: "agent"` are inspected
**Then** each step has `stopOnLevel: 1`

## Scenario: Script steps carry stopOnLevel 2

**Given** `pipeline.json` is the live pipeline configuration
**When** all ordinary pipeline script steps are inspected
**Then** each step has `stopOnLevel: 2`

## Scenario: Scheduled maintenance flows carry stopOnLevel 3

**Given** `pipeline.json` is the live pipeline configuration
**When** the four scheduled maintenance flows (`05_continuous/metrics-aggregation`, `metrics-aggregation-daily`, `metrics-report`, `00_ondemand/codebase-reviewer`) are inspected
**Then** each flow step has `stopOnLevel: 3`
