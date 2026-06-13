"""
One-time script to apply agent file updates for issue #100.
Run: python3 scripts/update_agent_files.py
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# pr-reviewer.md
# ---------------------------------------------------------------------------
pr_reviewer = ROOT / ".claude/agents/03_execute/pr-reviewer.md"
content = pr_reviewer.read_text()

changes = 0

# 1. Update description to mention human review hard block
old_desc = "  On APPROVE marks the PR ready for human review. Gates on pr-reviewer:approved."
new_desc = (
    "  Cannot APPROVE when any unresolved human REQUEST_CHANGES reviews exist on\n"
    "  the PR -- this is a hard block regardless of automated findings. On APPROVE\n"
    "  with no unresolved human reviews, marks the PR ready for human review.\n"
    "  Gates on pr-reviewer:approved."
)
if old_desc in content:
    content = content.replace(old_desc, new_desc, 1)
    changes += 1
    print("pr-reviewer.md: description updated")
else:
    print("pr-reviewer.md: description already updated (or not found)")

# 2. Add gh api to extra_allowedTools
old_tools = "Bash(gh issue view *)]"
new_tools = "Bash(gh issue view *), Bash(gh api *)]"
if old_tools in content and "Bash(gh api *)" not in content:
    content = content.replace(old_tools, new_tools, 1)
    changes += 1
    print("pr-reviewer.md: extra_allowedTools updated")
else:
    print("pr-reviewer.md: extra_allowedTools already updated (or not found)")

# 3. Add Step 1.5 between Step 1 and Step 2
step_1_5_marker = "## Step 1.5"
if step_1_5_marker not in content:
    step_1_5 = '''
---

## Step 1.5 — Check for unresolved human reviews

Fetch PR reviews and determine whether any human reviewer (non-bot) has an
unresolved `CHANGES_REQUESTED` state. A reviewer\'s current state is their
latest review ordered by `submitted_at`. `DISMISSED` reviews are resolved.
Bot accounts (`.user.type == "Bot"`) are excluded.

```bash
HUMAN_BLOCK_REVIEWERS=$(gh api "/repos/${REPO}/pulls/${PR_NUMBER}/reviews" \\
  --jq \'[.[] | select(.user.type != "Bot")]
    | group_by(.user.login)
    | map(sort_by(.submitted_at) | last)
    | map(select(.state == "CHANGES_REQUESTED") | "@" + .user.login)
    | join(", ")\')
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

**Remediation:** Address the human reviewer\'s feedback. Each listed reviewer
must submit an APPROVE or DISMISSED review to clear the block.
```

Do **not** skip the remaining review steps — continue reading the diff so the
combined report is useful to the coder.

'''
    old_step2 = "---\n\n## Step 2 — Read the spec"
    if old_step2 in content:
        content = content.replace(old_step2, step_1_5 + "---\n\n## Step 2 — Read the spec", 1)
        changes += 1
        print("pr-reviewer.md: Step 1.5 inserted")
    else:
        print("pr-reviewer.md: Step 2 marker not found for Step 1.5 insertion")
else:
    print("pr-reviewer.md: Step 1.5 already present")

# 4. Update Step 8 verdict
old_verdict = (
    "## Step 8 — Verdict\n\n"
    "- Any Critical, High, or Medium finding → **REQUEST CHANGES**\n"
    "- Low or Informational only (or zero findings) → **APPROVE**\n"
    "- ADR-covered findings downgraded to Informational never block APPROVE"
)
new_verdict = (
    "## Step 8 — Verdict\n\n"
    "- `$HUMAN_BLOCK_REVIEWERS` is non-empty → **REQUEST CHANGES** "
    "(hard block; takes priority over all other findings)\n"
    "- Any Critical, High, or Medium finding → **REQUEST CHANGES**\n"
    "- Low or Informational only (or zero findings) AND "
    "`$HUMAN_BLOCK_REVIEWERS` is empty → **APPROVE**\n"
    "- ADR-covered findings downgraded to Informational never block APPROVE "
    "(but human block still does)"
)
if old_verdict in content:
    content = content.replace(old_verdict, new_verdict, 1)
    changes += 1
    print("pr-reviewer.md: Step 8 verdict updated")
else:
    print("pr-reviewer.md: Step 8 verdict already updated (or not found)")

pr_reviewer.write_text(content)
print(f"pr-reviewer.md: {changes} changes written")

# ---------------------------------------------------------------------------
# coder.md
# ---------------------------------------------------------------------------
coder = ROOT / ".claude/agents/03_execute/coder.md"
content = coder.read_text()
changes = 0

# 1. Update Mode B description in frontmatter/intro
old_mode_b = (
    "- **Mode B — Address feedback:** A `review-cycle:N` label (N ≥ 1) is present\n"
    "  on the issue, indicating the pr-reviewer requested changes. Discover the\n"
    "  associated PR via the GitHub data model. Read review comments, fix the code,\n"
    "  post a response. The orchestrator commits and pushes."
)
new_mode_b = (
    "- **Mode B — Address feedback:** A `review-cycle:N` label (N ≥ 1) OR a\n"
    "  `human-review-pending` label is present on the issue. `review-cycle:N`\n"
    "  means the pr-reviewer requested changes; `human-review-pending` means\n"
    "  pr-reviewer approved but unresolved human REQUEST_CHANGES reviews exist.\n"
    "  In both cases: discover the associated PR, read review comments AND human\n"
    "  REQUEST_CHANGES reviews, fix the code, post a response. The orchestrator\n"
    "  commits and pushes."
)
if old_mode_b in content:
    content = content.replace(old_mode_b, new_mode_b, 1)
    changes += 1
    print("coder.md: Mode B description updated")
else:
    print("coder.md: Mode B description already updated (or not found)")

# 2. Update Step 0 to also check for human-review-pending label
old_step0_check = (
    "Check for a `review-cycle:N` label on the issue. Its presence (N ≥ 1) means\n"
    "the pr-reviewer previously requested changes — this is Mode B. Absence means\n"
    "Mode A (initial build).\n\n"
    "```bash\n"
    "REVIEW_CYCLE_LABEL=$(gh issue view \"$ISSUE_NUMBER\" --repo \"$REPO\" --json labels \\\n"
    "  --jq '.labels[].name | select(startswith(\"review-cycle:\"))' \\\n"
    "  | head -1)\n"
    "\n"
    "if [ -n \"$REVIEW_CYCLE_LABEL\" ]; then"
)
new_step0_check = (
    "Check for Mode B trigger labels on the issue:\n"
    "- `review-cycle:N` (N ≥ 1): the pr-reviewer previously requested changes\n"
    "- `human-review-pending`: pr-reviewer approved but unresolved human\n"
    "  REQUEST_CHANGES reviews exist — a free re-invoke was triggered\n\n"
    "Absence of both means Mode A (initial build).\n\n"
    "```bash\n"
    "REVIEW_CYCLE_LABEL=$(gh issue view \"$ISSUE_NUMBER\" --repo \"$REPO\" --json labels \\\n"
    "  --jq '.labels[].name | select(startswith(\"review-cycle:\"))' \\\n"
    "  | head -1)\n"
    "\n"
    "HUMAN_REVIEW_PENDING=$(gh issue view \"$ISSUE_NUMBER\" --repo \"$REPO\" --json labels \\\n"
    "  --jq '.labels[].name | select(. == \"human-review-pending\")' \\\n"
    "  | head -1)\n"
    "\n"
    "if [ -n \"$REVIEW_CYCLE_LABEL\" ] || [ -n \"$HUMAN_REVIEW_PENDING\" ]; then"
)
if old_step0_check in content:
    content = content.replace(old_step0_check, new_step0_check, 1)
    changes += 1
    print("coder.md: Step 0 Mode B trigger updated")
else:
    print("coder.md: Step 0 Mode B trigger already updated (or not found)")

# 3. Update B1 to also fetch human REQUEST_CHANGES reviews via REST API
old_b1 = (
    "# Inline review threads and human reviews on the PR\n"
    "gh pr view \"$PR_NUMBER\" --repo \"$REPO\" --json reviews \\\n"
    "  --jq '[.reviews[] | {author: .author.login, state: .state, body: .body}]'\n"
    "\n"
    "# Human comments on the PR (excluding agent artefacts)\n"
    "gh pr view \"$PR_NUMBER\" --repo \"$REPO\" --json comments \\\n"
    "  --jq '[.comments[] | select(.body | contains(\"ai-agile/artefact/v1\") | not) | {author: .author.login, body: .body}]'"
)
new_b1 = (
    "# Inline review threads and human reviews on the PR\n"
    "gh pr view \"$PR_NUMBER\" --repo \"$REPO\" --json reviews \\\n"
    "  --jq '[.reviews[] | {author: .author.login, state: .state, body: .body}]'\n"
    "\n"
    "# Unresolved human REQUEST_CHANGES reviews — latest state per reviewer, bots excluded\n"
    "HUMAN_BLOCK_REVIEWERS=$(gh api \"/repos/${REPO}/pulls/${PR_NUMBER}/reviews\" \\\n"
    "  --jq '[.[] | select(.user.type != \"Bot\")]\n"
    "    | group_by(.user.login)\n"
    "    | map(sort_by(.submitted_at) | last)\n"
    "    | map(select(.state == \"CHANGES_REQUESTED\") | \"@\" + .user.login)\n"
    "    | join(\", \")')\n"
    "\n"
    "# Human comments on the PR (excluding agent artefacts)\n"
    "gh pr view \"$PR_NUMBER\" --repo \"$REPO\" --json comments \\\n"
    "  --jq '[.comments[] | select(.body | contains(\"ai-agile/artefact/v1\") | not) | {author: .author.login, body: .body}]'"
)
if old_b1 in content:
    content = content.replace(old_b1, new_b1, 1)
    changes += 1
    print("coder.md: B1 human reviews fetch added")
else:
    print("coder.md: B1 human reviews fetch already added (or not found)")

# 4. Update B2 to note human REQUEST_CHANGES as Required
old_b2 = (
    "| **Required** | Correctness bug, security issue, spec violation, failing test | Yes — block merge if not fixed |"
)
new_b2 = (
    "| **Required** | Correctness bug, security issue, spec violation, failing test, "
    "or unresolved human REQUEST_CHANGES review (listed in `$HUMAN_BLOCK_REVIEWERS`) "
    "| Yes — block merge if not fixed |"
)
if old_b2 in content:
    content = content.replace(old_b2, new_b2, 1)
    changes += 1
    print("coder.md: B2 Required row updated")
else:
    print("coder.md: B2 Required row already updated (or not found)")

coder.write_text(content)
print(f"coder.md: {changes} changes written")
print("Done.")
