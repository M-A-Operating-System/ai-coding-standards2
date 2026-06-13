# Agent file changes required for issue #100

These changes could not be applied directly to `.claude/agents/` in this session
due to the interactive permission model. Apply them by running:

```
python3 scripts/update_agent_files.py
```

Or apply manually using the diffs below.

---

## `.claude/agents/03_execute/pr-reviewer.md`

### 1. Frontmatter description — add human review hard block sentence

**Old (line ~10):**
```
  On APPROVE marks the PR ready for human review. Gates on pr-reviewer:approved.
```

**New:**
```
  Cannot APPROVE when any unresolved human REQUEST_CHANGES reviews exist on
  the PR -- this is a hard block regardless of automated findings. On APPROVE
  with no unresolved human reviews, marks the PR ready for human review.
  Gates on pr-reviewer:approved.
```

### 2. Frontmatter extra_allowedTools — add `Bash(gh api *)`

**Old:**
```yaml
extra_allowedTools: [..., Bash(gh issue view *)]
```

**New:**
```yaml
extra_allowedTools: [..., Bash(gh issue view *), Bash(gh api *)]
```

### 3. Add Step 1.5 (between Step 1 and Step 2)

Insert the following before `## Step 2 — Read the spec`:

````markdown
---

## Step 1.5 — Check for unresolved human reviews

Fetch PR reviews and determine whether any human reviewer (non-bot) has an
unresolved `CHANGES_REQUESTED` state. A reviewer's current state is their
latest review ordered by `submitted_at`. `DISMISSED` reviews are resolved.
Bot accounts (`.user.type == "Bot"`) are excluded.

```bash
HUMAN_BLOCK_REVIEWERS=$(gh api "/repos/${REPO}/pulls/${PR_NUMBER}/reviews" \
  --jq '[.[] | select(.user.type != "Bot")]
    | group_by(.user.login)
    | map(sort_by(.submitted_at) | last)
    | map(select(.state == "CHANGES_REQUESTED") | "@" + .user.login)
    | join(", ")')
```

If `$HUMAN_BLOCK_REVIEWERS` is non-empty:

- Set `VERDICT=REQUEST CHANGES` (hard block — takes priority over all other findings).
- Prepend the following to `FINDING_BODY` **before** any automated findings:

```
### HR-001 — Unresolved human REQUEST_CHANGES block APPROVE   [High]

**Persona:** Human Review Block
**Reviewer(s):** $HUMAN_BLOCK_REVIEWERS

**Description:** One or more human reviewers have submitted REQUEST_CHANGES
reviews that are not resolved (not yet dismissed or superseded by an APPROVE).
The pr-reviewer cannot issue APPROVE while unresolved human reviews exist,
regardless of automated findings.

**Remediation:** Address the human reviewer's feedback. Each listed reviewer
must submit an APPROVE or DISMISSED review to clear the block.
```

Do **not** skip the remaining review steps — continue reading the diff so the
combined report is useful to the coder.
````

### 4. Update Step 8 verdict

**Old:**
```markdown
## Step 8 — Verdict

- Any Critical, High, or Medium finding → **REQUEST CHANGES**
- Low or Informational only (or zero findings) → **APPROVE**
- ADR-covered findings downgraded to Informational never block APPROVE
```

**New:**
```markdown
## Step 8 — Verdict

- `$HUMAN_BLOCK_REVIEWERS` is non-empty → **REQUEST CHANGES** (hard block; takes priority over all other findings)
- Any Critical, High, or Medium finding → **REQUEST CHANGES**
- Low or Informational only (or zero findings) AND `$HUMAN_BLOCK_REVIEWERS` is empty → **APPROVE**
- ADR-covered findings downgraded to Informational never block APPROVE (but human block still does)
```

---

## `.claude/agents/03_execute/coder.md`

### 1. Frontmatter description — add human-review-pending trigger

**Old (lines ~8-10):**
```
- **Mode B — Address feedback:** A `review-cycle:N` label (N ≥ 1) is present
  on the issue, indicating the pr-reviewer requested changes. Discover the
  associated PR via the GitHub data model. Read review comments, fix the code,
  post a response. The orchestrator commits and pushes.
```

**New:**
```
- **Mode B — Address feedback:** A `review-cycle:N` label (N ≥ 1) OR a
  `human-review-pending` label is present on the issue. `review-cycle:N`
  means the pr-reviewer requested changes; `human-review-pending` means
  pr-reviewer approved but unresolved human REQUEST_CHANGES reviews exist.
  In both cases: discover the associated PR, read review comments AND human
  REQUEST_CHANGES reviews, fix the code, post a response. The orchestrator
  commits and pushes.
```

### 2. Step 0 — also check for `human-review-pending`

**Old (in the `## Step 0 — Detect mode` bash block):**
```bash
REVIEW_CYCLE_LABEL=$(gh issue view "$ISSUE_NUMBER" --repo "$REPO" --json labels \
  --jq '.labels[].name | select(startswith("review-cycle:"))' \
  | head -1)

if [ -n "$REVIEW_CYCLE_LABEL" ]; then
```

**New:**
```bash
REVIEW_CYCLE_LABEL=$(gh issue view "$ISSUE_NUMBER" --repo "$REPO" --json labels \
  --jq '.labels[].name | select(startswith("review-cycle:"))' \
  | head -1)

HUMAN_REVIEW_PENDING=$(gh issue view "$ISSUE_NUMBER" --repo "$REPO" --json labels \
  --jq '.labels[].name | select(. == "human-review-pending")' \
  | head -1)

if [ -n "$REVIEW_CYCLE_LABEL" ] || [ -n "$HUMAN_REVIEW_PENDING" ]; then
```

Also update the Step 0 introductory text:

**Old:**
```
Check for a `review-cycle:N` label on the issue. Its presence (N ≥ 1) means
the pr-reviewer previously requested changes — this is Mode B. Absence means
Mode A (initial build).
```

**New:**
```
Check for Mode B trigger labels on the issue:
- `review-cycle:N` (N ≥ 1): the pr-reviewer previously requested changes
- `human-review-pending`: pr-reviewer approved but unresolved human
  REQUEST_CHANGES reviews exist — a free re-invoke was triggered

Absence of both means Mode A (initial build).
```

### 3. B1 — Fetch human REQUEST_CHANGES reviews via REST API

In `### B1 — Read all review feedback`, after the inline reviews block, add:

```bash
# Unresolved human REQUEST_CHANGES reviews — latest state per reviewer, bots excluded
HUMAN_BLOCK_REVIEWERS=$(gh api "/repos/${REPO}/pulls/${PR_NUMBER}/reviews" \
  --jq '[.[] | select(.user.type != "Bot")]
    | group_by(.user.login)
    | map(sort_by(.submitted_at) | last)
    | map(select(.state == "CHANGES_REQUESTED") | "@" + .user.login)
    | join(", ")')
```

### 4. B2 — Human REQUEST_CHANGES classified as Required

In `### B2 — Categorise the feedback`, update the Required row:

**Old:**
```
| **Required** | Correctness bug, security issue, spec violation, failing test | Yes — block merge if not fixed |
```

**New:**
```
| **Required** | Correctness bug, security issue, spec violation, failing test, or unresolved human REQUEST_CHANGES review (listed in `$HUMAN_BLOCK_REVIEWERS`) | Yes — block merge if not fixed |
```
