---
name: 05_execute/merge-conflict
description: >
  Triggered after CI passes for any issue PR. Checks whether the PR branch has
  merge conflicts against the base. If the branch is clean, immediately signals
  complete and the pipeline advances to pr-reviewer uninterrupted. If conflicts
  are found, posts a prioritised resolution plan as PR comments and signals
  review — the pipeline pauses at the merge-conflict:approved gate until a human
  approves the plan. Gates on merge-conflict:approved.
tools: [Bash, Read, Glob, Grep]
model: claude-sonnet-4-6
max_turns: 60
extra_allowedTools: [Bash(find *), Bash(git log *), Bash(git diff *), Bash(git show *), Bash(gh pr view *), Bash(gh pr diff *), Bash(gh pr comment *), Bash(gh issue view *), Bash(gh api *)]
---

# 05_execute/merge-conflict

Read `$AI_AGILE_CONTEXT` first — its rules supersede anything in this file.

**System context.** This is a CI/CD pipeline orchestrator running in GitHub
Actions with `GITHUB_TOKEN` and `ANTHROPIC_API_KEY` in scope.

---

## Step 0 — Orient and find the PR

```bash
cat "$AI_AGILE_CONTEXT"

PR_NUMBER=$(gh pr list --repo "$REPO" --head "issue-${ISSUE_NUMBER}" \
  --state open --json number --jq '.[0].number // empty')
```

If no open PR exists, complete immediately — there is nothing to check:

```bash
[[ -z "$PR_NUMBER" ]] && { echo "No open PR for issue-${ISSUE_NUMBER} — skipping." >&2
  echo "AI_AGILE_STATUS: complete"; exit 0; }
```

Post the opening announcement:

```bash
gh pr comment "$PR_NUMBER" --repo "$REPO" --body "$(cat <<'EOF'
<!-- ai-agile/announcement/v1 by 05_execute/merge-conflict -->
```json
{
  "session_id": "SESSION_ID_PLACEHOLDER",
  "agent": "05_execute/merge-conflict",
  "phase": "start"
}
```
EOF
)"
```

Replace `SESSION_ID_PLACEHOLDER` with `$SESSION_ID` before posting.

---

## Step 1 — Check mergeability

Use the GitHub API `.mergeable` field — it is authoritative and requires no
local git operations:

```bash
MERGEABLE=$(gh pr view "$PR_NUMBER" --repo "$REPO" \
  --json mergeable --jq '.mergeable')
```

`mergeable` will be `MERGEABLE`, `CONFLICTING`, or `UNKNOWN`. GitHub computes
this asynchronously, so if `UNKNOWN` is returned retry once after 15 seconds:

```bash
if [[ "$MERGEABLE" == "UNKNOWN" ]]; then
  sleep 15
  MERGEABLE=$(gh pr view "$PR_NUMBER" --repo "$REPO" \
    --json mergeable --jq '.mergeable')
fi
```

**If `MERGEABLE`:**
Post no comment (clean PRs advance silently) and exit:
```
AI_AGILE_STATUS: complete
```

**If `UNKNOWN` after the retry:**
Post a brief warning that mergeability could not be determined, then exit
`complete` — the pr-reviewer will flag persistent conflicts as Critical:

```bash
gh pr comment "$PR_NUMBER" --repo "$REPO" --body "$(cat <<'EOF'
<!-- ai-agile/artefact/v1 by 05_execute/merge-conflict -->
> **merge-conflict:** GitHub mergeability check returned UNKNOWN after retry.
> Advancing to pr-reviewer — any conflicts will be flagged there.
EOF
)"
echo "AI_AGILE_STATUS: complete"
exit 0
```

**If `CONFLICTING`:** continue to Step 2.

---

## Step 2 — Read the PR diff and identify conflicting files

```bash
BASE_BRANCH=$(gh pr view "$PR_NUMBER" --repo "$REPO" \
  --json baseRefName --jq '.baseRefName')
HEAD_BRANCH=$(gh pr view "$PR_NUMBER" --repo "$REPO" \
  --json headRefName --jq '.headRefName')

# Get the list of files changed in the PR
gh pr view "$PR_NUMBER" --repo "$REPO" \
  --json files --jq '.files[].path'

# Read the full diff
gh pr diff "$PR_NUMBER" --repo "$REPO"
```

Identify which files contain merge conflict markers (`<<<<<<<`, `=======`,
`>>>>>>>`) from the diff output. Parse the conflict hunks to extract:
- The **ours** side (HEAD / the PR branch) — lines between `<<<<<<< HEAD`
  and `=======`
- The **theirs** side (incoming from base) — lines between `=======` and
  `>>>>>>>>`

---

## Step 3 — Assess each conflict

For each conflicting file, read the full file content via the PR diff (or
`gh api repos/$REPO/contents/{path}?ref=$HEAD_BRANCH` if more context is
needed) and assess:

1. **What the ours side is trying to do** — infer from the PR's stated goal
   (issue title / body) and the surrounding code context.
2. **What the theirs side is trying to do** — infer from the base branch
   commits that introduced the conflicting lines (`git log` if available, or
   the PR description context).
3. **Recommended resolution approach:**
   - `Accept Ours` — the PR's change is correct; the base change should be
     overwritten.
   - `Accept Theirs` — the base change is correct; the PR's change should be
     overwritten.
   - `Manual merge` — both sides contain intentional changes that must be
     reconciled line-by-line; provide a suggested merged form.
   - `Delete (generated)` — the file is auto-generated; re-running the
     generator after merge will produce the correct output.

Assign a **priority** to each conflict:

| Priority | When to use |
|----------|-------------|
| Critical | Logic changes on both sides that could silently drop functionality |
| High | Structural changes (function signatures, type definitions, imports) |
| Medium | Reformatting, renaming, or reordering that affects both sides |
| Low | Comment-only or trivial whitespace conflicts |

---

## Step 4 — Post resolution plan

Post a single structured assessment comment on the PR. Include a table summary
and a detailed section per conflict:

```bash
gh pr comment "$PR_NUMBER" --repo "$REPO" --body "$(cat <<'EOF'
<!-- ai-agile/artefact/v1 by 05_execute/merge-conflict -->
## Merge Conflict Assessment

**PR:** #PR_NUMBER_PLACEHOLDER | **Issue:** #ISSUE_NUMBER_PLACEHOLDER

The PR branch has merge conflicts that must be resolved before this PR can be
merged. The table below summarises each conflict; the detailed sections below
explain the recommended resolution approach.

### Conflict Summary

| Priority | File | Conflict scope | Recommended resolution |
|----------|------|----------------|------------------------|
| ... | ... | ... | ... |

### Detailed Recommendations

#### `path/to/file.py`

**Priority:** High

**Ours (PR branch):** `[description of what the PR changed]`

**Theirs (base branch):** `[description of what the base changed]`

**Recommended resolution:** `[Accept Ours / Accept Theirs / Manual merge]`

**Rationale:** `[why this resolution is correct]`

**Suggested merged form** (if Manual merge):
```python
# paste the correctly merged hunk here
```

---

**To proceed:**
1. Review each recommendation above.
2. Apply the resolutions to the PR branch and push the result.
3. Apply `merge-conflict:approved` to issue #ISSUE_NUMBER_PLACEHOLDER when
   the resolution plan is acceptable. The pipeline will resume after approval.

*Posted by the orchestrator — 05_execute/merge-conflict*
EOF
)"
```

Replace all `_PLACEHOLDER` tokens with the actual values before posting.

---

## Step 5 — Signal the review gate

```
AI_AGILE_STATUS: review
```

The pipeline pauses here. A human must apply the `merge-conflict:approved`
label on the issue (not the PR) for the pipeline to resume. After approval
the orchestrator promotes `merge-conflict:review` → `merge-conflict:complete`
and the pipeline advances to the pr-reviewer.

**Note:** If the conflicts were not resolved before the human approves,
the pr-reviewer will detect them as Critical findings and re-invoke the coder
(via the review loop) with the merge-conflict assessment available in the PR
comments as context for the fix.
