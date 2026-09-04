<!-- GENERATED FILE -- DO NOT EDIT.
     Source: pipeline/pipeline.json
     Generator: pipeline/generators/generate_docs.py
     Regenerate: python3 pipeline/generators/generate_docs.py -->

# Agent Catalogue

Every step in the pipeline, in configuration order, with the
description declared in `pipeline.json`.

## 00_ondemand

### `00_ondemand/codebase-reviewer`

- **Kind:** agent
- **Operates on:** `issue`

Ad-hoc three-persona codebase review (Defensive Programmer, Security Analyst, Quality Assurance). Reads the full codebase and creates a 'Technical Review - {date}' GitHub issue containing all findings with severity ratings and AI-actionable remediation instructions. Triggered by applying the codebase-reviewer:requested label to any issue. Cross-references docs/product/ only when code intent is unclear.

### `00_ondemand/sizer`

- **Kind:** agent
- **Operates on:** `issue`

Ad-hoc issue sizer. Evaluates whether the issue fits a single development cycle. Small issues get a sizing note (sizer:complete -- auto-approved). Large issues are decomposed into ordered, independently-deliverable sub-issues; the parent is marked epic and the agent emits sizer:review so the human can inspect and edit the breakdown. On re-invocation after the human removes sizer:review, emits complete (terminal for the parent). Triggered by applying the sizer:requested label to any issue.

### `00_ondemand/new-agent`

- **Kind:** agent
- **Operates on:** `issue`

On-demand agent that scaffolds a new pipeline agent from a GitHub issue description. Reads the issue to determine the agent's name, phase, trigger, and purpose, then creates the agent prompt file and registers it in pipeline.json. Triggered by applying the new-agent:requested label to an issue.

### `00_ondemand/standards-migrator`

- **Kind:** agent
- **Operates on:** `issue`

Ad-hoc agent that scans the consuming repo for existing knowledge files and ground-truth artifacts, then converts the timeless rules they imply into machine-readable standards/*.json. Presents proposed standards for human approval before writing. Triggered by applying the standards-migrator:requested label to any issue.

### `00_ondemand/branch-cleanup`

- **Kind:** agent
- **Operates on:** `issue`

Ad-hoc sweep agent. Evaluates every remote branch, classifies each as a deletion candidate or one to keep, and posts the recommendation for human approval. On re-invocation after a human approves specific branches in a reply comment, deletes exactly those branches and posts a summary. Triggered by applying the branch-cleanup:requested label to any issue.

### `00_ondemand/issue-cleanup`

- **Kind:** agent
- **Operates on:** `issue`

Ad-hoc backlog-hygiene sweep. Reads every open issue and classifies each as a complete-candidate, a duplicate-cluster member, or keep, and posts the recommendation for human approval. On re-invocation after a human names specific issues in a reply comment, closes exactly those issues with the correct state_reason and posts a summary. Triggered by applying the issue-cleanup:requested label to any issue.

### `00_ondemand/blocker`

- **Kind:** script
- **Operates on:** `issue`
- **Script:** `.github/scripts/blocker.sh`

Reciprocates a blockedby:/blocks: pair. A human applies blockedby:{N} to this issue directly -- that alone already gates eligibility -- then requests this step to add the symmetric blocks:{this} label onto issue N. Emits blocked (not failed) when no blockedby: label is present to reciprocate, so a mistaken request is visible rather than silently swallowed. Triggered by applying the blocker:requested label to any issue.

## 01_product_docs

### `01_product_docs/issue-classifier`

- **Kind:** agent
- **Operates on:** `issue`

Classifies the issue as bug, feature, chore, or spike. Validates required fields (problem statement, acceptance criteria). Rejects malformed issues with a corrective comment.

### `01_product_docs/prd-writer`

- **Kind:** agent
- **Operates on:** `issue`

Drafts a Product Requirements Document for an appropriately-sized issue. Rewrites the issue body with the PRD in user-story + Gherkin format and waits for stakeholder approval at the prd-writer:approved gate. Skipped for epic issues (parent issues decomposed by the sizer) and issues marked blocked.

### `01_product_docs/create-docs-pr`

- **Kind:** script
- **Operates on:** `issue`
- **Script:** `.github/scripts/create-docs-pr.sh`

Scripted step (two-phase design->build, issue #247): opens the DESIGN pull request on the issue-{N}-docs branch with a non-closing body. prd-docs-updater commits the docs/product/ and docs/features/ changes to this branch; merge-docs-pr merges it to main at the prd-docs-updater:approved gate, ahead of the build phase. Thin wrapper over create-pr.sh (BRANCH_SUFFIX=-docs, PR_CLOSES_ISSUE=false). Idempotent. Skipped for spike/epic/blocked issues.

### `01_product_docs/create-pr`

- **Kind:** script
- **Operates on:** `issue`
- **Script:** `.github/scripts/create-pr.sh`

Scripted step: creates the CODE branch (issue-{N}) and opens a draft PR with 'Closes #{N}' in the body, establishing the GitHub Development sidebar link. Runs after merge-docs-pr publishes the approved design to main (two-phase design->build, issue #247), so the code branch is cut from a main that already carries the latest design. Applies source-issue:{N} label via link-pr-to-issue.sh. Coder commits accumulate in this PR. Idempotent -- exits cleanly if branch and PR already exist. Deterministic; does not invoke Claude CLI. Skipped for spike issues (spikes produce no code to ship). Skipped for epic/blocked issues.

### `01_product_docs/prd-docs-updater`

- **Kind:** agent
- **Operates on:** `issue`

Runs after create-docs-pr opens the design PR. Copies the approved PRD's Gherkin scenarios into docs/features/{feature}.md (mechanical) and cross-checks the PRD against existing product documentation in docs/product/. Writes changes using its Write tool -- the orchestrator then invokes commit-agent-work.sh to stage, commit, and push those changes to the DESIGN branch (issue-{N}-docs, via branch_suffix) so they land in the design PR. Posts a summary comment. self_gates: true -- the agent itself decides whether to gate on prd-docs-updater:approved (only when docs/product/ prose changed) or advance straight (mechanical docs/features/ copy only, or no changes needed); either way merge-docs-pr then publishes the design to main ahead of the build phase (two-phase design->build, issue #247). Skipped for spike issues. Skipped for epic/blocked issues.

### `01_product_docs/merge-docs-pr`

- **Kind:** script
- **Operates on:** `issue`
- **Script:** `.github/scripts/merge-docs-pr.sh`

Scripted step (two-phase design->build, issue #247): merges the design PR (issue-{N}-docs) to main at the prd-docs-updater:approved gate, ahead of the build phase, so every subsequent (and parallel) build is cut from a main that already carries the latest approved design and design conflicts surface at this small docs merge. Idempotent -- if no open design PR exists it exits cleanly. Refuses to auto-merge a conflicting or protection-blocked PR (emits review for human resolution) rather than forcing it. Deterministic; does not invoke Claude CLI. Skipped for spike/epic/blocked issues.

## 03_execute

### `03_execute/coder`

- **Kind:** agent
- **Operates on:** `issue`

Implements a GitHub issue and its sub-issues as a defensive programmer. Reads the approved PRD, docs/tech-spec/, and each sub-issue in order. Writes code using its Write/Edit tools; the orchestrator then invokes commit-agent-work.sh to stage, commit, and push all changes to the shared issue branch (issue-{N}) after the agent signals complete. The draft PR was opened by create-pr and stays draft until pr-reviewer completes. Skipped for spike issues -- spikes produce research findings, not code. Skipped for epic/blocked issues.

### `03_execute/ci-gate`

- **Kind:** script
- **Operates on:** `issue`
- **Script:** `.github/scripts/ci-gate.sh`

Scripted CI gate: polls the GitHub check-runs for the issue PR until all checks pass (emits complete), any check fails (emits review -- the orchestrator re-invokes the coder up to 3 cycles), or the 14-minute timeout expires (emits blocked for human intervention). Posts a summary comment listing check outcomes before signalling status. Skipped for epic/blocked issues.

### `03_execute/merge-conflict`

- **Kind:** agent
- **Operates on:** `issue`

Checks for merge conflicts on the issue PR after CI passes. If the branch is clean, immediately emits complete and the orchestrator auto-applies merge-conflict:approved so the pipeline advances to pr-reviewer uninterrupted. If conflicts are found, emits review -- the pipeline pauses at the merge-conflict:approved gate until a human approves the resolution plan, then the coder is re-invoked to apply the agreed resolutions. Skipped for epic/blocked issues.

### `03_execute/pr-reviewer`

- **Kind:** agent
- **Operates on:** `issue`

Reviews the draft PR for this issue after CI passes. Looks up the open PR by branch issue-{N}, reads the diff and linked spec, then posts a structured review covering correctness, design alignment, standards compliance, and security. Issues REQUEST_CHANGES for any Critical, High, or Medium finding; issues APPROVE only when all findings are Low or Informational severity. Cannot APPROVE when any unresolved human REQUEST_CHANGES reviews exist on the PR -- this is a hard block regardless of automated findings. On APPROVE with no unresolved human reviews, emits complete and the orchestrator marks the issue PR ready for human review. On REQUEST CHANGES the orchestrator automatically re-invokes the coder (clearing ci-gate:complete so CI re-runs, up to 3 cycles); only after 3 failed cycles is human sign-off required. Skipped for epic/blocked issues.
