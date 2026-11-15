# Feature: Release Notes

## Scenario: Release notes extraction stops at a ## section heading

**Given** a PRD issue body containing `### Release Notes`, a short paragraph, then `## Problem Statement` with additional content
**When** `extract_release_notes_section()` is called on that body
**Then** only the short paragraph under `### Release Notes` is returned, with no content from `## Problem Statement` onward

## Scenario: Release notes extraction still stops at the next ### heading

**Given** a PRD issue body containing `### Release Notes`, a short paragraph, then `### Next Section` with additional content
**When** `extract_release_notes_section()` is called on that body
**Then** only the short paragraph under `### Release Notes` is returned, with no content from `### Next Section` onward
