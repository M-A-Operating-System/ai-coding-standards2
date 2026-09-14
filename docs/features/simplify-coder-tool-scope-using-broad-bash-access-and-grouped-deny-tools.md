# Feature: Simplify Coder Tool Scope Using Broad Bash Access And Grouped Deny Tools

## Scenario: Coder step grants broad Bash access and inherits default tools

**Given** the coder step in pipeline.json is updated
**When** its tool configuration is inspected
**Then** extra_allowedTools contains "Bash" and the inherited default tools include Read, Write, Edit, Glob, and Grep

## Scenario: Direct form of a denied command is blocked

**Given** the coder step has deniedTools containing "Bash(git reset --hard*)"
**When** a coder agent calls Bash with the argument "git reset --hard HEAD"
**Then** the tool call is denied by the permission system

## Scenario: Denied command reached through an interpreter wrapper is not blocked

**Given** the coder step has deniedTools containing "Bash(git reset --hard*)"
**And** extra_allowedTools contains "Bash"
**When** a coder agent calls Bash with the argument "bash -c 'git reset --hard HEAD'"
**Then** the tool call is not denied, because the matcher sees the wrapper invocation as written
**And** this is documented as the deny list's known limitation, not treated as a defect
