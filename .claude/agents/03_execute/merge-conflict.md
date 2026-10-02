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

**Avoid denied command shapes in the first place.** A leading variable
assignment in front of a command substitution -- `VAR=$(gh api ...)` or
`VAR=$(git ...)` -- does not reliably match this agent's command allowlist,
because the line's first token is the assignment, not `gh`/`git`. Every
command below instead runs as its own line with the permitted command
leading, redirects its output to a file, and loads that file into a shell
variable with `read` (also not an assignment-first line) -- never
reconstruct this back into a `VAR=$(...)` one-liner.

**If a command is denied or a required check fails anyway.** If the
tool-permission system still refuses to run a command, do not retry the
identical denied form and do not proceed as if the check had succeeded.
Retry at most once, and only with a directly permitted equivalent shape. If
evidence still cannot be gathered after that retry, stop and write
`$AI_AGILE_SCRATCH/result.json` with `outcome: "blocked"` and the concrete
command and reason in `summary`, rather than guessing or reporting a result
that was never actually determined. Exception: Step 1's own
mergeable-state-unknown-after-retry fallback (below) is a deliberate,
already-reasoned degraded-mode advance -- GitHub's own asynchronous
computation genuinely has no answer yet, which is not a denied command or a
failure to work around -- so it is not a case this rule overrides.

**Steps 2 and 3 run as one Bash invocation each, start to cleanup.** Both
steps mutate the shared checkout (a scratch branch, a rebase or merge in
progress) and rely on their own `trap ... EXIT` to undo that no matter where
the block stops. A trap only protects commands run in the *same* shell
process: splitting either block across more than one Bash tool call would
leave a later call's mutations unprotected by the earlier call's trap. If an
individual command inside one of these blocks is denied, do not split the
rest into a separate invocation to work around it -- within that same
invocation, manually run the equivalent of the trap's own cleanup (abort
any in-progress rebase/merge, check out `$_ORIG_REF`, delete the scratch
branch) before the block ends, then write `outcome: "blocked"`.

---

## Step 0 — Orient and find the PR

The orchestrator already resolves the open PR for this issue when it exists
(issue #431/#433) -- `$PR_NUMBER` arrives already set. Use it directly and
skip the `gh api` lookup below; it exists only as a fallback for the (should
not happen in practice) case where it's unset.

```bash
cat "$AI_AGILE_CONTEXT"
```

If `$PR_NUMBER` is not already set, run this standalone fallback lookup (not
combined with the check above in the same invocation, so it matches the
`--allowedTools` allowlist on its own):

```bash
gh api "repos/$REPO/pulls?head=${REPO%%/*}:issue-${ISSUE_NUMBER}&state=open&per_page=1" --jq '.[0].number // empty'
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
gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.mergeable_state' >/tmp/_mc_mergeable
read -r MERGEABLE </tmp/_mc_mergeable
```

`mergeable_state` will be `dirty` (has conflicts), `unknown` (not yet computed),
or one of `clean`/`blocked`/`behind`/`unstable` (all conflict-free). GitHub
computes this asynchronously, so if `unknown` is returned retry once after 15
seconds:

```bash
if [[ "$MERGEABLE" == "unknown" ]]; then
  sleep 15
  gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.mergeable_state' >/tmp/_mc_mergeable
  read -r MERGEABLE </tmp/_mc_mergeable
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
gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.base.ref' >/tmp/_mc_base_branch
gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.head.ref' >/tmp/_mc_head_branch
read -r BASE_BRANCH </tmp/_mc_base_branch
read -r HEAD_BRANCH </tmp/_mc_head_branch

git config user.email "github-actions[bot]@users.noreply.github.com"
git config user.name "github-actions[bot]"
git fetch origin "$BASE_BRANCH" "$HEAD_BRANCH"

# Registered before the checkout below mutates anything, so a denied or
# failing command anywhere after this line -- not just the two explicit
# fall-through paths -- still restores the original branch and removes the
# scratch branch instead of leaving it behind for the next invocation.
git rev-parse --abbrev-ref HEAD >/tmp/_mc_orig_ref
read -r _ORIG_REF </tmp/_mc_orig_ref
trap 'git rebase --abort 2>/dev/null || true; git checkout "$_ORIG_REF" 2>/dev/null || true; git branch -D _rebase_attempt 2>/dev/null || true' EXIT

git checkout -B _rebase_attempt "origin/${HEAD_BRANCH}"

if git rebase "origin/${BASE_BRANCH}"; then
    # Rebase succeeded — push and complete without human gate. Cleanup runs
    # via the trap above on exit.
    git push --force-with-lease origin "_rebase_attempt:${HEAD_BRANCH}"
    echo "REBASED: PR branch rebased onto ${BASE_BRANCH} automatically — no conflicts remain."
    exit 0
fi

# Rebase had conflicts itself -- fall through to manual analysis. Cleanup
# runs via the trap above on exit.
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
gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.base.ref' >/tmp/_mc_base_branch
gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.head.ref' >/tmp/_mc_head_branch
read -r BASE_BRANCH </tmp/_mc_base_branch
read -r HEAD_BRANCH </tmp/_mc_head_branch

# Fetch both sides
git fetch origin "$BASE_BRANCH" "$HEAD_BRANCH"

# Registered before the checkout below mutates anything, so a denied or
# failing command anywhere after this line still restores the original
# branch and removes the scratch branch instead of leaving it behind.
git rev-parse --abbrev-ref HEAD >/tmp/_mc_orig_ref
read -r _ORIG_REF </tmp/_mc_orig_ref
trap 'git merge --abort 2>/dev/null || true; git checkout "$_ORIG_REF" 2>/dev/null || true; git branch -D _conflict_assess 2>/dev/null || true' EXIT

# -B (not -b): force-create/reset in case a prior interrupted run left this
# branch behind -- -b would fail on a name collision and silently fall
# through to merging on whatever branch was checked out before it.
git checkout -B _conflict_assess "origin/${HEAD_BRANCH}"
git merge --no-commit "origin/${BASE_BRANCH}" 2>&1 || true

# List conflicted files
git diff --name-only --diff-filter=U >/tmp/_mc_conflicted_files
echo "Conflicted files:"
cat /tmp/_mc_conflicted_files

# For each conflicted file, show the full conflict diff. Iterates the file
# directly (not a $CONFLICTED_FILES variable) -- the same leading-assignment
# avoidance as everywhere else in this step.
while IFS= read -r f; do
  echo "=== $f ==="
  git diff HEAD -- "$f"
done </tmp/_mc_conflicted_files
# Clean up runs via the trap above on exit.
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
  "summary": "Found merge conflicts on PR #${PR_NUMBER}; wrote a prioritised resolution plan in output for the orchestrator to post.",
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
