---
name: 03_execute/merge-conflict
description: >
  Triggered after CI passes for any issue PR. Checks whether the PR branch has
  merge conflicts against the base. If the branch is clean, immediately signals
  complete and the pipeline advances to pr-reviewer uninterrupted. If conflicts
  are found, posts a prioritised resolution plan as PR comments and signals
  review — the pipeline pauses at the merge-conflict:approved gate until a human
  approves the plan. Gates on merge-conflict:approved.
---

# 03_execute/merge-conflict

Read `$AI_AGILE_CONTEXT` first — its rules supersede anything in this file.

**System context.** This is a CI/CD pipeline orchestrator running in GitHub
Actions with `GITHUB_TOKEN` and `ANTHROPIC_API_KEY` in scope.

---

## Step 0 — Orient and find the PR

```bash
cat "$AI_AGILE_CONTEXT"

OWNER="${REPO%%/*}"
PR_NUMBER=$(gh api \
  "repos/$REPO/pulls?head=${OWNER}:issue-${ISSUE_NUMBER}&state=open&per_page=1" \
  --jq '.[0].number // empty')
```

If no open PR exists, there is nothing to check. Detect this first:

```bash
if [[ -z "$PR_NUMBER" ]]; then
  echo "NO_PR: No open PR for issue-${ISSUE_NUMBER} — skipping."
fi
```

If the block above printed a `NO_PR: ...` line, write `$AI_AGILE_SCRATCH/result.json`
using the Write tool now and stop — do not continue to Step 1:

```json
{
  "outcome": "complete",
  "summary": "No open PR for issue-${ISSUE_NUMBER} — nothing to check."
}
```

---

## Step 1 — Check mergeability

Use the GitHub API `.mergeable_state` field — it is authoritative and requires
no local git operations:

```bash
MERGEABLE=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.mergeable_state')
```

`mergeable_state` will be `dirty` (has conflicts), `unknown` (not yet computed),
or one of `clean`/`blocked`/`behind`/`unstable` (all conflict-free). GitHub
computes this asynchronously, so if `unknown` is returned retry once after 15
seconds:

```bash
if [[ "$MERGEABLE" == "unknown" ]]; then
  sleep 15
  MERGEABLE=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.mergeable_state')
fi
```

**If not `dirty` or `unknown` (e.g. `clean`):**
Write `$AI_AGILE_SCRATCH/result.json` using the Write tool — no `output`
(clean PRs advance silently) — and stop:

```json
{
  "outcome": "complete",
  "summary": "PR #${PR_NUMBER} mergeable_state is ${MERGEABLE} — no conflicts."
}
```

**If `unknown` after the retry:**
Write `$AI_AGILE_SCRATCH/result.json` with a brief warning that mergeability
could not be determined, then stop — the pr-reviewer will flag persistent
conflicts as Critical:

```json
{
  "outcome": "complete",
  "summary": "GitHub mergeability check returned UNKNOWN after retry for PR #${PR_NUMBER}.",
  "output": "> **merge-conflict:** GitHub mergeability check returned UNKNOWN after retry.\n> Advancing to pr-reviewer — any conflicts will be flagged there."
}
```

**If `dirty`:** continue to Step 2.

---

## Step 2 — Attempt rebase-first resolution

Before analysing individual conflicts, attempt a rebase of the PR branch onto
the base branch. Most "conflicting" PRs are simply diverged from main — a clean
rebase resolves them automatically with no human input required.

```bash
# Resolve the PR's base and head branches before using them -- they drive every
# git command in this step. (Step 3 re-resolves them for the manual path.)
BASE_BRANCH=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.base.ref')
HEAD_BRANCH=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.head.ref')

git config user.email "github-actions[bot]@users.noreply.github.com"
git config user.name "github-actions[bot]"
git fetch origin "$BASE_BRANCH" "$HEAD_BRANCH"
git checkout -B _rebase_attempt "origin/${HEAD_BRANCH}"

if git rebase "origin/${BASE_BRANCH}"; then
    # Rebase succeeded — push and complete without human gate
    git push --force-with-lease origin "_rebase_attempt:${HEAD_BRANCH}"
    git checkout - 2>/dev/null || true
    git branch -D _rebase_attempt 2>/dev/null || true
    echo "REBASED: PR branch rebased onto ${BASE_BRANCH} automatically — no conflicts remain."
    exit 0
fi

# Rebase had conflicts itself — abort and fall through to manual analysis
git rebase --abort 2>/dev/null || true
git checkout - 2>/dev/null || true
git branch -D _rebase_attempt 2>/dev/null || true
```

If the block above printed a `REBASED: ...` line, write
`$AI_AGILE_SCRATCH/result.json` using the Write tool now and stop — do not
continue to Step 3:

```json
{
  "outcome": "complete",
  "summary": "PR branch rebased onto ${BASE_BRANCH} automatically — no conflicts remain.",
  "output": "> **merge-conflict:** PR branch rebased onto `${BASE_BRANCH}` automatically — no conflicts remain. Advancing to pr-reviewer."
}
```

If the rebase itself conflicted, continue to Step 3 for manual conflict analysis.

---

## Step 3 — Identify conflicting files and extract conflict hunks

The PR diff (head-vs-base) shows only head-vs-base changes, not the synthetic
merge result with conflict markers — it cannot be used to identify conflicts.
Instead, simulate the merge locally:

```bash
BASE_BRANCH=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.base.ref')
HEAD_BRANCH=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.head.ref')

# Fetch both sides
git fetch origin "$BASE_BRANCH" "$HEAD_BRANCH"

# Attempt a no-commit merge against the base to surface conflict details
git checkout -b _conflict_assess "origin/${HEAD_BRANCH}" 2>/dev/null
git merge --no-commit "origin/${BASE_BRANCH}" 2>&1 || true

# List conflicted files
CONFLICTED_FILES=$(git diff --name-only --diff-filter=U)
echo "Conflicted files:"
echo "$CONFLICTED_FILES"

# For each conflicted file, show the full conflict diff
for f in $CONFLICTED_FILES; do
  echo "=== $f ==="
  git diff HEAD -- "$f"
done

# Clean up — abort the in-progress merge and restore the branch
git merge --abort 2>/dev/null || true
git checkout - 2>/dev/null || true
git branch -D _conflict_assess 2>/dev/null || true
```

Parse the conflict hunks to extract:
- The **ours** side (PR branch) — lines between `<<<<<<< HEAD` and `=======`
- The **theirs** side (base branch) — lines between `=======` and `>>>>>>>`

---

## Step 4 — Assess each conflict

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

**Hard rule — never discard the primary deliverable:** If a file is central to
what this PR was created to deliver (new functions, refactored logic, the core
change described in the issue), `Accept Theirs` on that file would silently
erase the PR's work. In that case, always choose `Manual merge` — reconcile
both sides line-by-line and provide the merged form explicitly.

Assign a **priority** to each conflict:

| Priority | When to use |
|----------|-------------|
| Critical | Logic changes on both sides that could silently drop functionality |
| High | Structural changes (function signatures, type definitions, imports) |
| Medium | Reformatting, renaming, or reordering that affects both sides |
| Low | Comment-only or trivial whitespace conflicts |

---

## Step 5 — Write result and exit

Write `$AI_AGILE_SCRATCH/result.json` using the Write tool. The `output`
field carries the structured assessment (table summary and a detailed
section per conflict) that the orchestrator posts as the artefact comment;
substitute the runtime values yourself and replace every `_PLACEHOLDER`
token before writing:

```json
{
  "outcome": "review",
  "summary": "Found merge conflicts on PR #${PR_NUMBER}; posted a prioritised resolution plan.",
  "message": "Merge conflicts found — review the resolution plan and apply merge-conflict:approved to proceed.",
  "output": "## Merge Conflict Assessment\n\n**PR:** #PR_NUMBER_PLACEHOLDER | **Issue:** #ISSUE_NUMBER_PLACEHOLDER\n\nThe PR branch has merge conflicts that must be resolved before this PR can be merged. The table below summarises each conflict; the detailed sections below explain the recommended resolution approach.\n\n### Conflict Summary\n\n| Priority | File | Conflict scope | Recommended resolution |\n|----------|------|----------------|------------------------|\n| ... | ... | ... | ... |\n\n### Detailed Recommendations\n\n#### `path/to/file.py`\n\n**Priority:** High\n\n**Ours (PR branch):** `[description of what the PR changed]`\n\n**Theirs (base branch):** `[description of what the base changed]`\n\n**Recommended resolution:** `[Accept Ours / Accept Theirs / Manual merge]`\n\n**Rationale:** `[why this resolution is correct]`\n\n**Suggested merged form** (if Manual merge):\n```python\n# paste the correctly merged hunk here\n```\n\n---\n\n**To proceed:**\n1. Review each recommendation above.\n2. If the resolution plan is acceptable, apply `merge-conflict:approved` to issue #ISSUE_NUMBER_PLACEHOLDER. The orchestrator will re-invoke the coding agent to apply the resolutions automatically.\n3. If a recommendation is wrong, add a comment explaining the correction before approving."
}
```

The pipeline pauses here. A human must apply the `merge-conflict:approved`
label on the issue (not the PR) for the pipeline to resume. After approval
the orchestrator promotes `merge-conflict:review` → `merge-conflict:complete`
and the pipeline advances to the pr-reviewer.

**Note:** If the conflicts were not resolved before the human approves,
the pr-reviewer will detect them as Critical findings and re-invoke the coder
(via the review loop) with the merge-conflict assessment available in the PR
comments as context for the fix.
