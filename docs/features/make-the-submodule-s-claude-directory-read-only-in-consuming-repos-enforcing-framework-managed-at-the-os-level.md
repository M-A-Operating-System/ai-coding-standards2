# Feature: Make the Submodule's .claude/ Directory Read-only in Consuming Repos

## Scenario: commit_after agent creates worktree outside .claude after root relocation
**Given** a consuming repo has completed `--full` onboarding with `_WORKTREE_ROOT` relocated outside `.claude/`
**When** a `commit_after` agent (coder, prd-docs-updater, or new-agent) triggers worktree creation
**Then** the worktree is created in the relocated path and the agent run completes without a permission error
<!-- R1 -->

## Scenario: write to locked .claude symlink target fails with permission error
**Given** a consuming repo has completed `--full` onboarding with `.claude/` locked read-only at both directory and individual file level
**When** any process attempts to write or edit a file under the real `.claude/` target directory
**Then** the OS returns a permission error and the file content remains unchanged
<!-- R2 -->

## Scenario: submodule update succeeds and re-applies read-only lock
**Given** a consuming repo's `.claude/` is locked read-only from a prior onboarding run
**When** a submodule pointer bump followed by an onboarding re-run is executed
**Then** `git submodule update` completes without error, updated content is written, and `.claude/` is locked read-only again on completion
<!-- R3 -->

## Scenario: Windows copy-tree files are write-protected after onboarding
**Given** a Windows consuming repo has completed `--full` onboarding using the copy-tree path
**When** a process attempts to write or edit a file under the `.claude/` copy
**Then** the OS rejects the write, confirming platform-equivalent protection to the POSIX symlink path
<!-- R4; note: acceptance criterion also accepts explicit deferral with a filed follow-up issue in place of this scenario -->

## Scenario: agent self-edit on ai-coding-standards2 working tree is not blocked
**Given** an agent run (coder, prd-docs-updater, or new-agent) targets the `ai-coding-standards2` working tree
**When** the agent writes to `.claude/agents/` or `standards/` via Write or Edit
**Then** the write succeeds, confirming the lock mechanism detects the framework source repo and does not apply
<!-- R5 -->
