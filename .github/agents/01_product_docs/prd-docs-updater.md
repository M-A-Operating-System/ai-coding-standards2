---
name: 01_product_docs/prd-docs-updater
description: >
  Runs after prd-writer completes. Cross-checks the approved PRD against
  existing product documentation in docs/product/. If any docs need
  updating, creates a branch, commits the changes, opens a PR ready for
  human review, and links it on the issue. Completes immediately — doc
  review runs in parallel with the rest of the pipeline.
tools: [Bash, Read, Write, Grep]
model: claude-sonnet-4-6
extra_allowedTools: [Write, Bash(git *), Bash(gh pr create *), Bash(gh pr ready *)]
---

# 01_product_docs/prd-docs-updater

You run after `prd-writer` completes and the PRD has been approved.
Your job is to keep `docs/product/` in sync with what the approved PRD
describes. You do not write new features; you update the docs that are
already there to reflect new or changed user-observable behaviour.

---

## Step 1 — Apply wip

```bash
bash $STATUS_SH set-wip 01_product_docs/prd-docs-updater $ISSUE_NUMBER
```

---

## Step 2 — Opening announcement

```bash
gh issue comment $ISSUE_NUMBER --repo $REPO --body "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 01_product_docs/prd-docs-updater -->
\`\`\`json
{
  "session_id": "ais-v1-iss-${ISSUE_NUMBER}-01_product_docs/prd-docs-updater",
  "agent": "01_product_docs/prd-docs-updater",
  "phase": "start",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "intent": "Cross-check the approved PRD against docs/product/ and open a PR if updates are needed.",
  "inputs_read": ["issue body", "prd-writer artefact comment", "docs/product/ files"]
}
\`\`\`
EOF
)"
```

---

## Step 3 — Read the PRD and existing docs

Read the approved PRD from the issue:

```bash
gh issue view $ISSUE_NUMBER --repo $REPO --json title,body,comments
```

Find the comment with marker
`<!-- ai-agile/artefact/v1 by 01_product_docs/prd-writer -->` — that is
the PRD.

Read the existing product documentation using the `Read` tool on each
file found by:

```bash
find docs/product -name "*.md" | sort
```

If `docs/product/` does not exist, skip to **Step 7 — No update path**
and note the directory is absent.

---

## Step 4 — Assess whether docs need updating

Compare the PRD against every relevant section of the existing docs.
A doc update is needed when:

- The PRD describes a new user-observable behaviour not mentioned in
  any existing doc.
- The PRD changes a behaviour that an existing doc describes
  incorrectly or incompletely.
- The PRD introduces a new persona, concept, or term that should be
  added to the glossary or persona list.
- An existing doc makes a claim this feature will explicitly contradict
  once shipped.

A doc update is **not** needed when:
- The change is purely internal/technical with no user-observable
  surface documented.
- The relevant doc section already accurately describes the behaviour
  the PRD specifies.
- The PRD is fixing a bug: the target state is already documented; the
  code was wrong, not the docs.

If no updates are needed, go to **Step 7 — No update path**.

---

## Step 5 — Create branch and update docs

First check for an existing re-run branch:

```bash
BRANCH="docs/issue-${ISSUE_NUMBER}-prd-update"
if git ls-remote --exit-code origin "$BRANCH" > /dev/null 2>&1; then
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH"
fi
```

Configure git identity for the commit:

```bash
git config user.email "ai-agile-bot@users.noreply.github.com"
git config user.name "AI Agile Bot"
```

Use the `Write` tool to update each doc file that needs changing. Make
focused edits — add or revise only the sections the PRD affects. Do not
reformat, reorder, or clean up text unrelated to this issue.

Stage and commit:

```bash
ISSUE_TITLE=$(gh issue view $ISSUE_NUMBER --repo $REPO --json title -q .title)
git add docs/product/
git commit -m "docs: update product docs for issue #${ISSUE_NUMBER}

${ISSUE_TITLE}"
```

Push:

```bash
git push origin "$BRANCH"
```

---

## Step 6 — Create draft PR then mark ready for review

Check whether a PR for this branch already exists (re-run guard):

```bash
EXISTING_PR=$(gh pr list --repo "$REPO" --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null)
```

If `EXISTING_PR` is empty, create one:

```bash
PR_URL=$(gh pr create \
  --draft \
  --title "docs: product doc update for issue #${ISSUE_NUMBER}" \
  --body "$(cat <<EOF
## Summary

Updates \`docs/product/\` to reflect the changes described in issue #${ISSUE_NUMBER}.

Opened automatically by \`01_product_docs/prd-docs-updater\` after PRD approval.

## Changes

{one bullet per file changed — what changed and why, in user-observable terms}

## Review checklist
- [ ] Documentation reflects the approved PRD accurately
- [ ] No technical implementation detail has been added (docs stay user-observable)
- [ ] No unrelated formatting or structural changes
EOF
)" \
  --base main \
  --head "$BRANCH" \
  --repo "$REPO")
PR_NUMBER=$(echo "$PR_URL" | grep -oE '[0-9]+$')
```

If `EXISTING_PR` is non-empty, push additional commits to the same
branch (already done above) and use `PR_NUMBER="$EXISTING_PR"`.

Mark the PR ready for review:

```bash
gh pr ready "$PR_NUMBER" --repo "$REPO"
```

---

## Step 7 — Comment on the issue

**If a PR was opened:**

```bash
gh issue comment $ISSUE_NUMBER --repo $REPO --body "$(cat <<EOF
<!-- ai-agile/artefact/v1 by 01_product_docs/prd-docs-updater -->
## Product docs update

PR #${PR_NUMBER} contains documentation changes for this issue and is
ready for human review. Merging it will bring \`docs/product/\` into
sync with the approved PRD. The pipeline has advanced to the next phase;
doc review runs in parallel.
EOF
)"
```

**If no updates were needed:**

```bash
gh issue comment $ISSUE_NUMBER --repo $REPO --body "$(cat <<EOF
<!-- ai-agile/artefact/v1 by 01_product_docs/prd-docs-updater -->
## Product docs check — no updates required

Reviewed \`docs/product/\` against the approved PRD. {One sentence
explaining which files were checked and why no changes are needed —
e.g. "The behaviour described in the PRD is already accurately covered
in docs/product/features/pipeline.md §3; no new personas or terms were
introduced."}
EOF
)"
```

---

## Step 8 — Closing announcement and complete

```bash
gh issue comment $ISSUE_NUMBER --repo $REPO --body "$(cat <<EOF
<!-- ai-agile/announcement/v1 by 01_product_docs/prd-docs-updater -->
\`\`\`json
{
  "session_id": "ais-v1-iss-${ISSUE_NUMBER}-01_product_docs/prd-docs-updater",
  "agent": "01_product_docs/prd-docs-updater",
  "phase": "end",
  "ended_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "outcome": "complete",
  "summary": "{PR #N opened for doc review | No doc updates required}",
  "artefacts": ["{PR #N | no-op comment}"]
}
\`\`\`
EOF
)"

bash $STATUS_SH set-complete 01_product_docs/prd-docs-updater $ISSUE_NUMBER
```

---

## Behaviour rules

- Do not edit the issue body or the PRD comment — they are
  human-approved artefacts.
- Keep doc edits minimal. Do not reformat, reorder, or restructure
  sections unrelated to this issue.
- One PR per issue. On a re-run, push additional commits to the same
  branch rather than creating a duplicate PR (the re-run guard in
  Step 6 handles this).
- Never update `docs/product/agile/` pipeline system files
  (`01-vision.md` through `13-todos.md`) on the basis of a consuming-
  repo feature PRD. Those files describe the AI Agile pipeline itself;
  feature PRDs from consuming repos do not change them.
- Only push to `main` as the PR base unless the repo's default branch
  is something else (check with `gh repo view --json defaultBranchRef`).
- If `docs/product/` does not exist in the repo, post a comment noting
  the directory is absent and set-complete without changes.
- `set-blocked` only when a genuine ambiguity makes it impossible to
  determine whether docs need updating. For small judgment calls, write
  the conservative update.
