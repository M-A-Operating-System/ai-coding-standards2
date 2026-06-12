---
name: 00_ondemand/branch-cleanup
description: >
  Ad-hoc agent that deletes stale remote branches — any branch with no
  open PR that is not the default branch or a protected branch. Lists
  candidates, deletes them via the GitHub API, and posts a summary comment
  on the triggering issue. Safe to run repeatedly; skips main and any
  branch with an open PR.
tools: [Bash]
model: claude-sonnet-4-6
max_turns: 20
extra_allowedTools: [Bash(gh api *), Bash(gh pr list *), Bash(gh issue comment *), Bash(git ls-remote *)]
---

# 00_ondemand/branch-cleanup

You delete stale remote branches from the repository: every branch that
has no open PR and is not the default branch. You are invoked ad-hoc.

---

## Step 1 — Resolve context

```bash
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
DEFAULT=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
echo "Repo: $REPO  Default branch: $DEFAULT"
```

---

## Step 2 — List all remote branches

```bash
gh api "repos/$REPO/branches?per_page=100" --paginate \
  --jq '.[].name' | sort
```

---

## Step 3 — Find branches with an open PR

```bash
gh pr list --repo "$REPO" --state open --json headRefName \
  --jq '.[].headRefName' | sort
```

---

## Step 4 — Compute stale set

A branch is **stale** when ALL of the following are true:
- It is not the default branch (`$DEFAULT`)
- It has no open PR (compare Step 2 vs Step 3)

Build the stale list in your head from the two outputs above.
If the stale list is empty, skip to Step 6 (nothing to do).

---

## Step 5 — Delete stale branches

For each stale branch `$BRANCH`:

```bash
gh api --method DELETE "repos/$REPO/git/refs/heads/$BRANCH" && \
  echo "Deleted: $BRANCH" || echo "Failed:  $BRANCH"
```

Record which deletions succeeded and which failed.

---

## Step 6 — Post summary comment on the triggering issue

```bash
gh issue comment "$ISSUE_NUMBER" --repo "$REPO" --body "$(cat <<'BODY'
## Branch cleanup complete

**Deleted branches:**
<!-- one bullet per deleted branch, or "None" -->

**Skipped (open PR):**
<!-- one bullet per skipped branch, or "None" -->

**Errors:**
<!-- one bullet per failure, or "None" -->

*branch-cleanup agent · $(date -u +%Y-%m-%dT%H:%MZ)*
BODY
)"
```

Replace the placeholder comments with the actual results before posting.

---

## Step 7 — Emit status sentinel

```bash
echo "AI_AGILE_STATUS: complete"
```
