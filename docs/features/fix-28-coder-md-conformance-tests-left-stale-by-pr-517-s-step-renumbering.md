# Feature: Fix 28 coder.md Conformance Tests Left Stale by PR #517 Step Renumbering

## Scenario: test suite passes with no coder-related failures

**Given** the test suite is run on the current branch without modifications to coder.md
**When** `python3 -m pytest tests/ -q` completes
**Then** 0 test failures related to coder.md conformance are reported

## Scenario: removed or rewritten test includes rationale

**Given** a test from the 28 failing tests is removed or rewritten as part of the fix
**When** the fix is submitted
**Then** each removed or rewritten test includes a comment or note explaining why the guarded behaviour no longer applies after PR #517

## Scenario: coder.md is not modified

**Given** coder.md is at its current post-PR-517 state
**When** the fix is applied
**Then** coder.md is unchanged from its pre-fix state
