# Feature: Merge PR

## Scenario: The head branch delete is denied after a successful merge

**Given** a PR that merges successfully
**And** the token cannot delete refs in the repository
**When** `merge-pr.sh` runs
**Then** it does not claim the branch was deleted
**And** it reports that the branch could not be deleted, on stderr
**And** it still exits 0, because the merge succeeded

## Scenario: No API error body reaches stdout

**Given** any `gh api` call in the script fails
**When** `merge-pr.sh` runs
**Then** its stdout contains only the script's own messages, no raw JSON error body

## Scenario: The head branch delete succeeds

**Given** a PR that merges successfully and a token that can delete refs
**When** `merge-pr.sh` runs
**Then** it reports the merge and the deletion, and exits 0

## Scenario: The branch was already removed by delete_branch_on_merge

**Given** the repository has `delete_branch_on_merge` enabled, so the ref is gone before the script's DELETE
**When** `merge-pr.sh` runs
**Then** it reports the branch as already gone rather than as deleted by itself, and exits 0

## Scenario: A PR that cannot be merged still fails loudly

**Given** a PR that GitHub deems unmergeable
**When** `merge-pr.sh` runs
**Then** it prints the existing `ERROR: PR #N could not be merged` message and exits non-zero
**And** this issue's changes have not altered that path
