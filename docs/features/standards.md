# Feature: Standards

## Scenario: An ADR can record a decision that overrides no standard

**Given** a repo wants to record an architecture decision that contradicts no standard
**When** an entry is added to `adrs/adrs.json` with no `authorises_exception_to`
**Then** `validate_standards.py` accepts the file

## Scenario: Override behaviour is unchanged

**Given** an ADR that lists a standard in `authorises_exception_to`
**When** `pr-reviewer` raises a finding against that standard
**Then** it cites the ADR ID and downgrades the finding to Informational, exactly as today

## Scenario: A decision-only ADR does not waive anything

**Given** an ADR with no `authorises_exception_to`
**When** `pr-reviewer` raises a finding against any standard
**Then** the finding is not downgraded, and the ADR is available as context only

## Scenario: A consuming repo can record its own decisions

**Given** a consuming repo with the seeded project-owned `adrs/adrs.json`
**When** it adds a decision-only ADR about its own application architecture
**Then** the file validates and the entry survives a framework update, because `adrs/` is never overwritten

## Scenario: The decision is legible, not just asserted

**Given** a decision-only ADR
**When** it is reviewed
**Then** it carries the context that prompted it, the decision, and its consequences -- not only a one-line rationale
