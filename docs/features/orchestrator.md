# Feature: Orchestrator

## Scenario: A post_step failure after a genuinely successful agent run does not discard that success

**Given** an agent completes its own work correctly (e.g. `pr-reviewer` posts APPROVE and the PR is confirmed ready)
**When** a subsequent `post_steps` script for that same pipeline entry fails
**Then** the issue does not end up labeled `{agent}:failed` in a way that misrepresents the agent's actual, successful outcome

## Scenario: mark-pr-ready.sh does not fail when the PR is already ready

**Given** a PR that is already `draft: false` (marked ready by another path -- the driver's MCP assist, or the agent's own action)
**When** `mark-pr-ready.sh` runs as a post_step
**Then** it detects the PR is already ready and exits 0 without attempting the blocked `gh pr ready` call

## Scenario: Retrying after this specific failure converges instead of looping

**Given** `pr-reviewer:failed` was applied solely because of this post_step failure, in a session where `gh pr ready` is structurally blocked
**When** a human clears the label and the orchestrator retries
**Then** the retry does not deterministically hit the identical failure again -- it either succeeds or fails for a genuinely new reason
