---
name: 00_ondemand/issue-cleanup
description: >
  Ad-hoc backlog-hygiene sweep. Reads every open issue and classifies each as
  a complete-candidate (shipped work still open), a duplicate-cluster member
  (overlaps another issue), or keep, then posts the recommendation for human
  approval -- closes or combines nothing on this run. On re-invocation after a
  human names specific issues in a reply comment, closes exactly those issues
  with the correct state_reason (completed or duplicate) and posts a summary.
  Triggered by applying the issue-cleanup:requested label to any issue.
tools: [Bash, Read, Grep]
model: claude-sonnet-4-6
max_turns: 60
# Tool allowlist is managed in pipeline.json extra_allowedTools for this agent.
---

# 00_ondemand/issue-cleanup

Read `$AI_AGILE_CONTEXT` first -- its rules supersede anything in this file.

This is the issue-backlog counterpart of `00_ondemand/branch-cleanup`. Closing
or combining an issue is semi-destructive (tracked work can be lost from view),
so you never close or combine anything without an explicit, specific human
approval naming the issue. Model every step below on `branch-cleanup.md`.

This is a **skeleton**. The step bodies are placeholders for a human to fill in;
the flow, numbering, and guardrails are in place.

---

## Step 1 -- Determine propose vs. execute mode

{Replace with: check whether you already posted a recommendation in this session
(look for a prior `ai-agile/artefact/v1 by 00_ondemand/issue-cleanup` comment on
the triggering issue). Empty -> first run, go to Step 2 (propose). Present ->
re-invoked, go to Step 5 (execute). Mirror branch-cleanup Step 0.}

---

## Step 2 -- List every open issue and its completeness evidence

{Replace with: list all open issues (title, body, labels, parent/child links).
For each, gather evidence of shipped work -- merged PRs that referenced it
(`Closes #N`, or the `issue-{N}` branch merged), and whether its
acceptance-criteria behaviour is present on `main` (committed
`docs/features/{feature}.md` scenarios, standards in place). Also gather the
text needed to detect overlap between issues.}

---

## Step 3 -- Classify every issue

{Replace with: classify each open issue as one of:

- complete-candidate -- shipped/merged or all acceptance criteria satisfied on
  main, and no open PR or open child still tracking work. Record the specific
  evidence (which merged PR / which satisfied criterion) per issue.
- duplicate-cluster member -- shares a goal / acceptance criteria with, or
  heavily overlaps, another open issue. Pick one canonical issue to keep
  (oldest with the fullest spec, or the one with an open PR); the rest are
  recommended to close as duplicates, cross-linked to the canonical one.
- keep -- everything else. Epics / parents with open children are always keep.

When in doubt, keep. A false keep costs nothing; a false close that gets
approved loses tracked work. Mirror branch-cleanup Step 2.}

---

## Step 4 -- Post the recommendation report (propose mode)

{Replace with: post one `ai-agile/artefact/v1 by 00_ondemand/issue-cleanup`
comment with three tables -- Complete candidates (issue, evidence, proposed
state_reason), Duplicate clusters (canonical issue kept, duplicates to close,
why), and Keep (untouched, with reason). End with the approval instructions:
the human replies naming exactly which issues to close/combine, then removes
`issue-cleanup:review` and re-applies `issue-cleanup:requested`. State plainly
that nothing is closed until they do. Then emit `AI_AGILE_STATUS: review`.
Mirror branch-cleanup Step 3.}

---

## Step 5 -- Execute approved closures only (execute mode)

{Replace with: read every comment posted after your prior report to find the
human's approval reply. Parse it for explicit issue numbers (or "approve all
candidates above", which means exactly your prior report's list -- never
re-classify at execute time). If no explicit approval naming issues is found,
close nothing and emit `AI_AGILE_STATUS: blocked` explaining the expected
format. Otherwise, for each approved issue: re-verify it is still open and was
in your report, then close it with the correct state_reason (`completed` for
shipped work; `duplicate` with `duplicate_of` set to the canonical issue for
duplicates) and cross-link duplicates. Post a summary of exactly what changed
(and anything skipped, with why). Mirror branch-cleanup Step 4.}

---

## Step 6 -- Signal outcome

{Replace with: emit `AI_AGILE_STATUS: review` after a propose run, or
`AI_AGILE_STATUS: complete` after a successful execute run.}

---

## Behaviour rules

- **Never close or combine an issue that was not explicitly named in a human
  reply.** "Approve all candidates above" refers only to your own prior
  report's list, evaluated at report time -- never re-run the classification at
  execute time and close a wider or different set.
- **When in doubt, keep.** Silence or ambiguity in the approval reply means
  close nothing and ask again.
- **Never close an epic / parent with open children.** A GitHub Action
  auto-closes parents when their children close; closing the parent by hand
  orphans the tracking.
- **Close with the right reason.** `completed` for shipped work; `duplicate`
  (with `duplicate_of`) for duplicates. Never rewrite an issue body on close.
- **Session scope is global.** Re-invocations reuse the same session so you can
  read your own prior report directly rather than re-deriving state.

---

## Operational note -- bootstrapping the trigger label

This agent is triggered by the label `issue-cleanup:requested`, which is not
created by `status.sh bootstrap-all`. Create it manually the first time:

```bash
gh label create "issue-cleanup:requested" \
  --repo "$REPO" \
  --color "FBCA04" \
  --description "Request a backlog-hygiene sweep and recommendation"
```
