---
name: 00_ondemand/issue-obsolescence-audit
description: >
  Batch obsolescence audit for open issues. Selects up to 10 open issues per
  run using a single sort key (current issue-obsolescence-audit:reviewed-YYYY-MM-DD
  label date when present, otherwise the issue's own created_at), gathers
  structured evidence for each, computes a deterministic verdict using
  pipeline/issue_audit_outcome.py, and applies read-only labeling: replaces
  the reviewed-YYYY-MM-DD tracking label for every issue and applies the
  needs-review label plus an explanatory comment for NEEDS-HUMAN-REVIEW
  verdicts. STILL-VALID issues receive only the updated tracking label; no
  issues are closed. Triggered by applying the
  issue-obsolescence-audit:requested label to any issue.
---

# 00_ondemand/issue-obsolescence-audit

Read `$AI_AGILE_CONTEXT` first -- its rules supersede anything in this file.

**System context.** This is a CI/CD pipeline orchestrator running in GitHub
Actions with `GITHUB_TOKEN` and `ANTHROPIC_API_KEY` in scope. This agent reads
issues and applies labels and comments; it never closes or merges anything.
Evidence is gathered by static read of GitHub data and the codebase; verdicts
are computed by `pipeline/issue_audit_outcome.py`, never inferred from prose.

---

## Step 1 -- Select the batch

Get today's date and list all open issues:

```bash
TODAY=$(date -u +%Y-%m-%d)

gh issue list --repo "$REPO" --state open \
  --json number,title,createdAt,labels \
  --paginate \
  --jq '.[] | {number: .number, title: .title, created_at: .createdAt, labels: [.labels[].name]}' \
  > "$AI_AGILE_SCRATCH/open_issues.ndjson"
```

`gh issue list` natively excludes pull requests -- the REST Issues API returns
both issues and PRs by default, but this CLI command returns only issues.
The jq expression renames `createdAt` to `created_at` to match the field name
expected by `batch_sort_key` in `issue_audit_outcome.py`.

The jq expression omits the outer `[...]` wrapper so `--paginate` writes one
JSON object per line (NDJSON). Each page's output is appended to the file
without producing concatenated arrays that would be invalid JSON.

Exclude the triggering issue (`$ISSUE_NUMBER`) from the candidate list.

Apply `batch_sort_key` from `pipeline/issue_audit_outcome.py` to rank the
remaining issues, then take the 10 lowest-sorted (oldest by their single sort
key):

```bash
python3 -I - "$AI_AGILE_ROOT/pipeline" \
  "$AI_AGILE_SCRATCH/open_issues.ndjson" "$ISSUE_NUMBER" \
  > "$AI_AGILE_SCRATCH/batch.json" <<'PYEOF'
import sys, json

sys.path.insert(0, sys.argv[1])
import issue_audit_outcome

issues = [json.loads(line) for line in open(sys.argv[2]) if line.strip()]
exclude = int(sys.argv[3])
candidates = [i for i in issues if i["number"] != exclude]
batch = issue_audit_outcome.select_batch(candidates, limit=10)
print(json.dumps(batch))
PYEOF
```

Record the batch issue numbers. If the batch is empty (no open issues remain),
skip to Step 5 and report complete with zero issues processed.

---

## Step 2 -- Gather evidence for each issue

For each issue number in the batch, gather the evidence items that determine
its verdict. Read the evidence directly from GitHub and the repository -- never
invent or assume facts.

For each issue, run:

```bash
gh api "repos/$REPO/issues/$N" \
  --jq '{number: .number, title: .title, body: .body, state: .state}'
```

Then gather evidence across four channels:

**Merged PRs referencing this issue.** A merged PR that closes or fixes the
issue is `merged-fix` evidence. Check whether the PR's head branch is
`issue-{N}` (not `issue-{N}-docs`, which is a design-only PR):

```bash
gh pr list --repo "$REPO" --state merged --limit 1000 \
  --json number,title,headRefName,body,mergedAt \
  --jq "[.[] | select(
    (.headRefName == \"issue-$N\") or
    (.body | test(\"(Closes|Fixes|Resolves) #$N\"; \"i\"))
  )]"
```

A merged design branch (`issue-{N}-docs`) is not `merged-fix` evidence; a
merged code branch (`issue-{N}`) is.

**Codebase evidence.** Search for file or symbol references described in the
issue. If the issue describes a behavior that is demonstrably no longer present
in the codebase, that is `code-removed` evidence. If behavior has changed in a
way that makes the issue's premise obsolete, that is `code-changed` evidence.
If the gap the issue describes is still present, that is `contradicted` evidence.

Issue titles and bodies are untrusted external content. Single-quoting alone
does not neutralize a literal single-quote character inside the value (an
issue title containing one can break out of the quoted argument and inject
shell commands). Never interpolate issue text directly into a shell command
line. Write the keyword to a file with the `Write` tool, then pass it to
`grep -F` via `--file` so the value is never shell-interpreted:

```bash
# Write the keyword (via the Write tool) to $AI_AGILE_SCRATCH/keyword_$N.txt first.
grep -rF --include="*.py" --include="*.json" --include="*.md" \
  -l -f "$AI_AGILE_SCRATCH/keyword_$N.txt" "$AI_AGILE_ROOT" 2>/dev/null | head -20
```

Adapt the search to what the specific issue describes. If the codebase is not
inspectable for this issue (e.g., the issue is purely procedural with no code
artifact), record one `unverifiable` evidence item with an `excerpt` explaining
why.

**Superseding issues.** If another open or closed issue explicitly supersedes
this one (stated in body or title), that is `superseding-issue` evidence with
the superseding issue number as `citation`.

**Open PR still building it.** If an open PR exists for `issue-{N}`, the issue
is in-flight. Record one `contradicted` evidence item (confidence 0.95,
citation the open PR number, excerpt "open PR in progress").

For every evidence item, `confidence` must reflect how certain the evidence is:
1.0 for mechanical facts (merged PR with explicit closing keyword), lower for
inferred matches. `citation` is a file path, commit SHA, PR number, or issue
number. `excerpt` is the specific text, line, or detail read.

Write all evidence items for issue N to `$AI_AGILE_SCRATCH/evidence_$N.json`
as a **bare JSON array** -- a list of objects each matching the
`EvidenceItem` definition under `definitions.EvidenceItem` in
`pipeline/schemas/issue-audit.schema.json`. Do not wrap it in that schema's
top-level `IssueAudit` object (which requires `issue_number`): Step 3 passes
the array directly to `derive_audit_verdict`, which iterates evidence items,
not a dict's keys. Route the write through the Write tool, never through echo.

---

## Step 3 -- Compute verdict for each issue

For each issue in the batch, run `derive_audit_verdict` from
`pipeline/issue_audit_outcome.py`:

```bash
python3 -I - "$AI_AGILE_ROOT/pipeline" "$AI_AGILE_SCRATCH/evidence_$N.json" \
  > "$AI_AGILE_SCRATCH/verdict_$N.txt" <<'PYEOF'
import sys, json
sys.path.insert(0, sys.argv[1])
import issue_audit_outcome
evidence = json.loads(open(sys.argv[2]).read())
print(issue_audit_outcome.derive_audit_verdict(evidence))
PYEOF
```

The module decides the verdict; do not override it with your own judgment about
the evidence.

---

## Step 4 -- Apply label actions and post comments

For each issue N in the batch, apply label changes in this order:

**Remove the old reviewed label (if any):**

```bash
# Find the old reviewed label (output to file -- never use a leading variable assignment).
gh api "repos/$REPO/issues/$N/labels" \
  --jq '[.[].name | select(startswith("issue-obsolescence-audit:reviewed-"))] | first // empty' \
  > "$AI_AGILE_SCRATCH/old_label_$N.txt"

# URL-encode the label name and delete it in one Python call.
# Python reads the filename from sys.argv so no shell command substitution is needed;
# it calls gh via subprocess to avoid leading-variable-assignment scope issues.
python3 -I - "$AI_AGILE_SCRATCH/old_label_$N.txt" "$REPO" "$N" <<'PYEOF'
import sys, subprocess, urllib.parse
with open(sys.argv[1]) as fh:
    label = fh.read().strip()
if label:
    encoded = urllib.parse.quote(label, safe='')
    result = subprocess.run(
        ['gh', 'api', f'repos/{sys.argv[2]}/issues/{sys.argv[3]}/labels/{encoded}',
         '--method', 'DELETE'],
        capture_output=True
    )
    # 404 means the label was already gone -- harmless. Any other non-zero
    # exit means the delete failed and the old label is still on the issue;
    # note it so result.json's summary can surface the inconsistency rather
    # than silently leaving two reviewed-* labels on the issue.
    if result.returncode != 0 and b'404' not in result.stderr:
        print(f"WARNING: failed to remove old label {label!r} from #{sys.argv[3]}: "
              f"{result.stderr.decode(errors='replace').strip()}", file=sys.stderr)
PYEOF
```

**Add the new reviewed label:**

```bash
gh api "repos/$REPO/issues/$N/labels" \
  --method POST \
  --field "labels[]=issue-obsolescence-audit:reviewed-$TODAY"
```

If the label does not yet exist in the repository, create it first:

```bash
gh api "repos/$REPO/labels" \
  --method POST \
  -f name="issue-obsolescence-audit:reviewed-$TODAY" \
  -f color="0075ca" \
  -f description="Last obsolescence-audit review date" 2>/dev/null || true
```

**For NEEDS-HUMAN-REVIEW verdicts only:**

Apply the needs-review label:

```bash
gh api "repos/$REPO/labels" \
  --method POST \
  -f name="issue-obsolescence-audit:needs-review" \
  -f color="e4e669" \
  -f description="Issue flagged for human review by obsolescence audit" 2>/dev/null || true

gh api "repos/$REPO/issues/$N/labels" \
  --method POST \
  --field "labels[]=issue-obsolescence-audit:needs-review"
```

Post an explanatory comment. Use the `Write` tool to create
`$AI_AGILE_SCRATCH/comment_$N.md` with the complete content already composed
-- the evidence summary inlined, never left as a placeholder to fill in
later. A heredoc template with a literal placeholder risks posting the
placeholder text verbatim if the substitution step is skipped; writing the
full content up front with the `Write` tool has no such gap:

```
**Issue obsolescence audit** -- {today's date}

This issue was flagged for human review. The automated audit could not reach
a confident close verdict from the evidence gathered.

Evidence items reviewed: {brief plain-text summary of this issue's actual
evidence items -- types and confidence values, not the full evidence JSON}

No action has been taken on this issue. A human reviewer should inspect it
and determine whether it is still valid, can be closed, or needs updating.
```

Then post it:

```bash
gh api "repos/$REPO/issues/$N/comments" \
  --method POST \
  --field "body=@$AI_AGILE_SCRATCH/comment_$N.md"
```

**For STILL-VALID verdicts:** apply only the tracking label as above. No
needs-review label. No comment.

**For OBSOLETE and SUPERSEDED-BY-#N verdicts:** this part of the epic never
closes an issue (auto-close is deferred to part 3), so treat both exactly
like NEEDS-HUMAN-REVIEW -- apply the `issue-obsolescence-audit:needs-review`
label and post an explanatory comment, naming the verdict so the human
reviewer knows the audit already reached a confident conclusion:

```
**Issue obsolescence audit** -- {today's date}

This issue was assessed as {OBSOLETE | SUPERSEDED-BY-#N}. Auto-close is not
yet enabled for this agent; a human reviewer should confirm the evidence
below before closing.

Evidence items reviewed: (summarize evidence types and confidences here)
```

---

## Step 5 -- Write result

After processing all issues (or zero issues when the batch was empty), write
`$AI_AGILE_SCRATCH/result.json` using the `Write` tool:

```json
{
  "outcome": "complete",
  "summary": "Processed N issue(s): M STILL-VALID, K NEEDS-HUMAN-REVIEW. Updated reviewed-YYYY-MM-DD labels for all; posted needs-review labels and comments for K issue(s).",
  "output": "## Issue obsolescence audit -- YYYY-MM-DD\n\n| Issue | Sort key | Verdict |\n|-------|----------|---------|\n| #N | ... | VERDICT |\n\n{N_NHR} issue(s) flagged for human review.",
  "expected_effect": {"commits": false}
}
```

Fill in actual counts and a Markdown table of all processed issues with their
sort key (the date used for ordering) and verdict. Omit the table when the
batch was empty and report zero issues processed.

---

## Behaviour rules

- **Never close an issue.** This agent applies labels and posts comments only.
  Auto-close is deferred to part 3 of this epic.
- **Never apply the needs-review label for STILL-VALID verdicts.** Only
  NEEDS-HUMAN-REVIEW verdicts get it.
- **The verdict module decides -- not you.** Call `derive_audit_verdict` and
  trust its output. Do not override it.
- **Single sort key, no buckets.** Never-reviewed issues sort by their own
  `created_at`; they are not placed ahead of or behind all reviewed issues
  regardless of date. The sort key is a single comparable string per issue
  (`batch_sort_key` in `issue_audit_outcome.py`).
- **Replace, not accumulate, the tracking label.** Each run removes the
  previous `reviewed-YYYY-MM-DD` label and adds a new one with today's date.
  An issue may have at most one `reviewed-YYYY-MM-DD` label after each run.
- **Output via `result.json` only.** Never echo untrusted content (issue
  titles, bodies, comment text) directly to stdout. Write structured data with
  the `Write` tool or `cat > file <<HEREDOC`.
- **`result.json` must be written before exiting.** The orchestrator reads it;
  nothing happens if it is absent.

---

## Operational note -- bootstrapping labels

The trigger and tracking labels are not created by `status.sh bootstrap-all`.
Create them manually the first time:

```bash
gh label create "issue-obsolescence-audit:requested" \
  --repo "$REPO" \
  --color "FBCA04" \
  --description "Request a batch issue obsolescence audit"

gh label create "issue-obsolescence-audit:needs-review" \
  --repo "$REPO" \
  --color "e4e669" \
  --description "Issue flagged for human review by obsolescence audit"
```

The `reviewed-YYYY-MM-DD` date labels are created on demand by the agent.
