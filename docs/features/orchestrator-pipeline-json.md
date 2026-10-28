# Feature: Orchestrator + Pipeline.json

## Scenario: Sub-issue branches from and targets parent issue branch

**Given** issue #50 carries the label `parent-issue:42`
**When** the orchestrator resolves the base branch for issue #50
**Then** the design branch is named `issue-50-docs` and is cut from `issue-42`, the code branch is named `issue-50` and is cut from `issue-42`, and all PRs for issue #50 target `issue-42`

## Scenario: Standalone issue branches from repository default branch

**Given** an issue has no `parent-issue:{N}` label
**When** the orchestrator resolves the base branch for that issue
**Then** `flow_base_branch()` returns `None` and the issue's branches are cut from and its PRs target the repository default branch

## Scenario: Grandchild issue uses one-hop parent lookup only

**Given** issue #200 carries the label `parent-issue:100` and issue #100 carries the label `parent-issue:42`
**When** the orchestrator resolves the base branch for issue #200
**Then** the branches for issue #200 are cut from `issue-100`, not from `issue-42` or `main`, with no additional orchestrator logic beyond a single parent label lookup
