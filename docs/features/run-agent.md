# Feature: Run-agent

## Scenario: Concurrent invocations write distinct scope files

**Given** two `/run-agent` sessions are active simultaneously in the same working tree
**When** each session writes its scope file at step 3
**Then** the two scope files are at distinct paths and each contains only the allowlist for its own agent

## Scenario: One run finishing does not disable enforcement for the other

**Given** two `/run-agent` sessions are active in the same working tree
**When** the first session completes and its step-7 cleanup removes its own scope file
**Then** the second session's scope file still exists and its tool calls are evaluated against its own allowlist rather than permitted unconditionally

## Scenario: Absence of scope file for a session means outside a run

**Given** no `/run-agent` session is active for the current session key
**When** the hook evaluates an ordinary (non-/run-agent) tool call
**Then** the hook exits without restricting the call, preserving normal behaviour for callers outside `/run-agent`

## Scenario: Regression test in CI validates concurrent isolation

**Given** the concurrent-scope regression test runs in CI with two scope files present for distinct sessions
**When** one session's scope file is deleted
**Then** the other session's tool calls continue to be evaluated against its own allowlist, and the test passes
