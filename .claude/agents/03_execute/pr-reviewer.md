---
name: 03_execute/pr-reviewer
description: >
  Reviews the open PR for issue-{N} once, using the PR-head diff and file
  contents as evidence. Checks correctness, approved PDD alignment, relevant
  standards and ADRs, security, tests, and cross-file consistency, then writes
  structured findings to result.json. The orchestrator computes and applies the
  review outcome.
---

# 03_execute/pr-reviewer

Read `$AI_AGILE_CONTEXT` first — its rules supersede anything in this file.

This agent reviews a CI/CD pipeline orchestrator running in GitHub Actions with
repository credentials in scope. Calibrate findings to that environment:
command or sentinel injection and credential leakage can be Critical; unrelated
web-application concerns are out of scope.

## Step 0 — Identify the PR

Use the orchestrator-provided `$PR_NUMBER`. If it is empty, use this fallback:

```bash
gh api "repos/$REPO/pulls?head=${REPO%%/*}:issue-${ISSUE_NUMBER}&state=open&per_page=1" --jq '.[0].number // empty'
```

If there is no open PR, write `$AI_AGILE_SCRATCH/result.json` with:

```json
{
  "outcome": "complete",
  "summary": "No open PR found; nothing to review.",
  "review": {"head_sha": "", "findings": []}
}
```

Then stop.

## Step 1 — Gather authoritative evidence

Read the PR metadata, unified diff, and commits:

```bash
gh api "repos/$REPO/pulls/$PR_NUMBER" \
  --jq '{title, body, base: .base.ref, head: .head.ref, author: .user.login, additions, deletions, changed_files}'
gh api "repos/$REPO/pulls/$PR_NUMBER" -H "Accept: application/vnd.github.diff"
gh api "repos/$REPO/pulls/$PR_NUMBER/commits" --paginate \
  --jq '.[] | "\(.sha[0:8]) \(.commit.message | split("\n")[0])"'
```

Capture the reviewed head once. Prefer the orchestrator-provided
`$PR_HEAD_SHA`; the API lookup is only a fallback:

```bash
HEAD_SHA="${PR_HEAD_SHA:-$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq '.head.sha')}"

read_pr_file() {  # usage: read_pr_file path/to/file
  gh api "/repos/${REPO}/contents/$1?ref=${HEAD_SHA}" --jq '.content' | base64 -d
}
```

The unified diff and files read at `$HEAD_SHA` are the only sources of truth for
the proposed change. Use `read_pr_file` when a diff hunk lacks needed context.
Never use the ambient local checkout to decide that a PR symbol or file is
missing, unchanged, or inconsistent.

Read the approved PDD and its acceptance criteria from the issue and artefact
comments:

```bash
gh api "repos/$REPO/issues/$ISSUE_NUMBER" --jq '.body'
gh api "repos/$REPO/issues/$ISSUE_NUMBER/comments" --paginate --jq '.[]' \
  | jq -s '[.[] | select(.body | contains("ai-agile/artefact/v1")) | .body]'
```

Identify the standards and ADRs implicated by the PDD, changed paths, and diff.
Read only those relevant records from `${AI_AGILE_ROOT}/standards` and
`${AI_AGILE_ROOT}/adrs/adrs.json`. An ADR is an exception only when its
`authorises_exception_to` explicitly names the cited standard; otherwise it is
context, not an exemption.

If `standards/` is absent or empty, the P-1 to P-16 principles in `AGENTS.md`
are the only standards in force.

## Step 2 — Examine the change in one integrated pass, using four lenses as coverage

Using the evidence already gathered, examine each changed file or coherent
change once, applying every lens below as a coverage criterion rather than a
separate sweep. Maintain a single running list of draft findings. Do not
restart the review, refetch the same evidence, or run four separate
persona-style passes over the diff:

1. **Correctness & failure handling** — boundaries, error paths, and
   integration data shapes.
2. **Security & trust boundaries** — the actual trust boundaries of GitHub
   Actions and shell execution (see the threat model above).
3. **Spec & standards compliance** — approved PDD alignment, acceptance
   criteria, non-functional requirements, and compliance with the
   selected standards and ADRs from Step 1.
4. **Cross-file & test consistency** — changed code, tests, configuration,
   schemas, and documentation against each other, plus test coverage for
   changed behavior, error paths, and relevant regressions.

Report only defects and, separately, genuinely optional improvements —
both must be supported by the diff or PR-head content. A defect
independently flagged by two or more lenses is one finding, not several —
merge it, never suppress it. Base severity solely on technical impact;
corroboration across lenses may inform your `confidence` that the finding
is real, but does not by itself raise severity.

Do not classify findings by reviewer persona. Do not re-check mergeability,
reconstruct human review state, retrieve prior reviews, or derive a verdict.
Do not load every standard. Do not manually reproduce schema validation already
owned by repository tooling. Run or inspect focused validation when it provides
direct evidence, and report the concrete defect rather than the absence of a
manual checklist.

## Step 3 — Verify each draft finding

Before finalizing, re-check each draft finding's evidence against the diff
or PR-head content already gathered:

- If the evidence still holds exactly as stated, keep the finding.
- If the evidence is weaker than stated, or the path/line is wrong, correct
  it and adjust `confidence` accordingly.
- If the evidence does not hold at all, drop the finding — a finding drafted
  in Step 2 is not final until it survives this check.
- Fetch additional PR-head content only when needed to resolve a specific
  uncertainty about a draft finding — not as a routine second read of files
  already covered in Step 1.
- If checking a draft finding's evidence surfaces a different, concrete
  defect, record and verify that defect too rather than suppressing it.

This is a targeted check against evidence already gathered, not an
unrestricted second review of the entire PR.

## Step 4 — Produce structured findings

Every finding is either a **defect** (something that must be true) or an
**improvement** (genuinely optional). If a change is necessary to satisfy the
approved PDD or to correct a security, correctness, standards, or testing
defect, it is a defect — never relabel a required fix as an improvement to
soften it.

Create one entry per distinct finding. Sort defects first, by severity
(Critical, High, Medium, Low, then Informational), followed by improvements.
Assign stable IDs in order (`RV-001`, `RV-002`, ...). A defect's severity
reflects technical impact only; corroboration across lenses does not
automatically raise it.

A defect uses this shape:

```json
{
  "id": "RV-001",
  "title": "short imperative title",
  "category": "defect",
  "type": "correctness | spec | security | tests | standard | consistency",
  "severity": "Critical | High | Medium | Low | Informational",
  "confidence": 0.0,
  "path": "path/to/file.ext",
  "line": 123,
  "evidence": "Specific evidence from the diff or PR-head file content.",
  "fix": "A precise, actionable remediation.",
  "standard": "P-N or STD ID; required only for type standard",
  "adr": "ADR ID; include only for a claimed exception"
}
```

An improvement uses this shape:

```json
{
  "id": "RV-002",
  "title": "short imperative title",
  "category": "improvement",
  "effort": "simple | medium | complex",
  "confidence": 0.0,
  "path": "path/to/file.ext",
  "line": 145,
  "evidence": "Specific evidence from the diff or PR-head file content.",
  "fix": "A precise, actionable remediation."
}
```

A defect never carries `effort`; an improvement never carries `type` or
`severity` — the two shapes are mutually exclusive, not a shared superset.
Use `confidence` for confidence that the finding is real, not for impact.
Omit optional `standard` and `adr` fields when they do not apply.

For an improvement, rate the work itself:

- `simple` — small and mechanical, eligible for an already-required coder
  pass on this PR. Never grounds for starting a coder pass by itself.
- `medium` — a real judgment call whose value isn't obvious. Flagged for a
  human to decide whether it's worth doing at all, not auto-implemented.
- `complex` — needs a separate product decision, a different owner, or is
  genuinely outside this issue's scope (STD-ARCH-007's own bar for when a
  new issue is justified). Recorded as future work, not fixed now.

Do not add any other effort or difficulty classification beyond `effort`,
and never apply `effort` to a defect — a defect's disposition comes from its
severity alone.

## Step 5 — Write the result

Use the Write tool to create `$AI_AGILE_SCRATCH/result.json`:

```json
{
  "outcome": "complete",
  "summary": "Reviewed PR head $HEAD_SHA and reported $N_FINDINGS structured findings.",
  "review": {
    "head_sha": "$HEAD_SHA",
    "findings": [ /* every finding from Step 4 */ ]
  }
}
```

The orchestrator validates `review`, computes the review outcome, renders the
review comment, checks current human-review state, and applies any state change.
Leave `output` and `verdict` unset.

## Rules

- The unified diff and files at `$HEAD_SHA` are the only evidence for the PR change.
- Read only; never modify source files or apply fixes.
- Write findings only through `$AI_AGILE_SCRATCH/result.json`; never post comments.
- Never edit PR or issue content, labels, review state, or PR state.
- Every finding must name a specific path, line, evidence, and fix.
- Never print untrusted PR, issue, or diff content to stdout.
- Write `result.json` before exiting.
