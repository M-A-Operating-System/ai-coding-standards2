<!-- GENERATED FILE -- DO NOT EDIT.
     Source: pipeline/pipeline.json
     Generator: pipeline/generators/generate_docs.py
     Regenerate: python3 pipeline/generators/generate_docs.py -->

# Agent Catalogue

Every step in the pipeline, by the flow that declares it and in
configuration order, with the description declared in `pipeline.json`.

## Flow: `standard-delivery`

- **Applies to:** kind `issue`
- **Naming:** branch `issue-{number}`; base `issue-{parent_number}`; PR `docs` on `issue-{number}-docs` (does not close the issue); PR `code` on `issue-{number}` (closes the issue)

An issue taken from description to shipped code: classify, write the PRD, publish the approved design to main on its own design branch and PR, then build, gate on CI, resolve conflicts and review the code PR. Two-phase design->build (issue #247) is expressed here as two pull requests on one flow -- the design PR (issue-{N}-docs, non-closing) merged ahead of the code PR (issue-{N}, closing).

### `01_product_docs/issue-classifier`

- **Kind:** agent
- **Phase:** `01_product_docs`

Classifies the issue as bug, feature, chore, or spike. Validates required fields (problem statement, acceptance criteria). Rejects malformed issues with a corrective comment.

### `01_product_docs/request-sizing`

- **Kind:** script
- **Phase:** `01_product_docs`
- **Script:** `scripts/request-sizing.sh`

Scripted step (issue #565): applies sizer:requested to the issue so the standalone 00_ondemand/sizer flow runs automatically before prd-writer, instead of leaving sizing to a human applying the label by hand. A lifecycle status label like sizer:requested is only the orchestrator's to write (pipeline/validate.py's lifecycle-label check forbids any agent's own allowed_labels from covering one), so this is a scripted step rather than something an agent requests directly. Idempotent.

### `01_product_docs/prd-writer`

- **Kind:** agent
- **Phase:** `01_product_docs`

Drafts a Product Requirements Document for an appropriately-sized issue. Triggers on sizer:complete (issue #565) rather than issue-classifier:complete directly, so build never starts while sizing is pending or in progress -- request-sizing applies sizer:requested automatically, and the standalone 00_ondemand/sizer flow must reach a terminal outcome before this step becomes eligible. Rewrites the issue body with the PRD in user-story + Gherkin format and waits for stakeholder approval at the prd-writer:approved gate. Skipped for epic issues (parent issues decomposed by the sizer) and issues marked blocked.

### `01_product_docs/create-docs-pr`

- **Kind:** script
- **Phase:** `01_product_docs`
- **Script:** `scripts/create-docs-pr.sh`

Scripted step (two-phase design->build, issue #247): opens the DESIGN pull request on the issue-{N}-docs branch with a non-closing body. prd-docs-updater commits the docs/product/ and docs/features/ changes to this branch; merge-docs-pr merges it to main at the prd-docs-updater:approved gate, ahead of the build phase. Thin wrapper over create-pr.sh; the branch and the non-closing body both come from this flow's naming.pull_requests entry 'docs'. Idempotent. Skipped for spike/epic/blocked issues.

### `01_product_docs/prd-docs-updater`

- **Kind:** agent
- **Phase:** `01_product_docs`

Runs after create-docs-pr opens the design PR. Copies the approved PRD's Gherkin scenarios into docs/features/{feature}.md (mechanical) and cross-checks the PRD against existing product documentation in docs/product/. Writes changes using its Write tool and commits them in its own worktree; the orchestrator then pushes the DESIGN branch (issue-{N}-docs, this flow's 'docs' pull request) so they land in the design PR. Posts a summary comment. self_gates: true -- the agent itself decides whether to gate on prd-docs-updater:approved (only when docs/product/ prose changed) or advance straight (mechanical docs/features/ copy only, or no changes needed); either way merge-docs-pr then publishes the design to main ahead of the build phase (two-phase design->build, issue #247). Skipped for spike issues. Skipped for epic/blocked issues.

### `01_product_docs/merge-docs-pr`

- **Kind:** script
- **Phase:** `01_product_docs`
- **Script:** `scripts/merge-docs-pr.sh`

Scripted step (two-phase design->build, issue #247): merges the design PR (issue-{N}-docs) to main at the prd-docs-updater:approved gate, ahead of the build phase, so every subsequent (and parallel) build is cut from a main that already carries the latest approved design and design conflicts surface at this small docs merge. Idempotent -- if no open design PR exists it exits cleanly. Refuses to auto-merge a conflicting or protection-blocked PR (emits review for human resolution) rather than forcing it. Deterministic; does not invoke Claude CLI. Skipped for spike/epic/blocked issues.

### `01_product_docs/create-pr`

- **Kind:** script
- **Phase:** `01_product_docs`
- **Script:** `scripts/create-pr.sh`

Scripted step: creates the CODE branch (issue-{N}) and opens a draft PR with 'Closes #{N}' in the body, establishing the GitHub Development sidebar link. Runs after merge-docs-pr publishes the approved design to main (two-phase design->build, issue #247), so the code branch is cut from a main that already carries the latest design. Applies source-issue:{N} label via link-pr-to-issue.sh. Coder commits accumulate in this PR. Idempotent -- exits cleanly if branch and PR already exist. Deterministic; does not invoke Claude CLI. Skipped for spike issues (spikes produce no code to ship). Skipped for epic/blocked issues.

### `03_execute/coder`

- **Kind:** agent
- **Phase:** `03_execute`

Implements one GitHub issue in the consuming repository as a defensive programmer. Reads the approved scope and relevant project context, then modifies and tests that issue's code, committing it in its own worktree as it goes -- including incremental checkpoint commits during a long run so completed progress survives budget exhaustion, and a final commit before returning so the working tree is clean. The orchestrator then pushes what was committed and owns the PR lifecycle. The draft PR was opened by create-pr and stays draft until pr-reviewer completes. Skipped for spike issues -- spikes produce research findings, not code. Skipped for epic/blocked issues.

### `03_execute/ci-gate`

- **Kind:** script
- **Phase:** `03_execute`
- **Script:** `scripts/ci-gate.sh`

Scripted CI gate: polls the GitHub check-runs for the issue PR until all checks pass (emits complete), any check fails (emits review -- the orchestrator re-invokes the coder up to 3 cycles), or the 14-minute timeout expires (emits blocked for human intervention). Posts a summary comment listing check outcomes before signalling status. Skipped for epic/blocked issues.

### `03_execute/merge-conflict`

- **Kind:** agent
- **Phase:** `03_execute`

Checks for merge conflicts on the issue PR after CI passes. If the branch is clean, immediately emits complete; self_gates (issue #425) lets that :complete stand as-is with no gate label ever applied, so the pipeline advances to pr-reviewer uninterrupted. If conflicts are found, emits review -- the pipeline pauses at the merge-conflict:approved gate until a human approves the resolution plan, then the coder is re-invoked to apply the agreed resolutions. Skipped for epic/blocked issues.

### `03_execute/pr-reviewer`

- **Kind:** agent
- **Phase:** `03_execute`

Reviews the draft PR for this issue after CI passes. Looks up the open PR by branch issue-{N}, reads the diff and linked spec, then reports each finding as either a defect (correctness, spec, security, tests, standards, or cross-file consistency) or a genuinely optional improvement -- the orchestrator computes the verdict from those findings (outcome_policy: review_findings), never trusting the model's own outcome field. A defect blocks unless its severity is Low or Informational, its confidence is below 0.8 (non-Critical only), or it is covered by a verified ADR exception; a Critical defect always blocks regardless of confidence. An improvement never blocks -- its effort instead decides its disposition (issue #506): simple is eligible for an already-required coder pass, medium is flagged for a human decision, complex is deferred into a follow-up GitHub issue the orchestrator raises. Cannot APPROVE when any unresolved human REQUEST_CHANGES reviews exist on the PR -- this is a hard block regardless of automated findings. On APPROVE, the orchestrator compares the reviewed head_sha with the PR's live head (require_head_match, issue #512 Part 3); a mismatch withholds ready-marking and re-dispatches this step on the next tick rather than approving a commit that was never reviewed. On APPROVE with a matching head and no unresolved human reviews, the orchestrator marks the issue PR ready for human review. On REQUEST CHANGES the orchestrator automatically re-invokes the coder (clearing ci-gate:complete so CI re-runs, up to 3 cycles); only after 3 failed cycles is human sign-off required. Skipped for epic/blocked issues.

## Flow: `epic-completion`

- **Applies to:** kind `issue`; labels `epic`
- **Naming:** branch `issue-{number}`; base `issue-{parent_number}`; PR `code` on `issue-{number}` (closes the issue)

Coordinating work: an epic is a parent whose children are the real work. Once all child issues (parent-issue:{N}) are closed, create-pr opens the epic's own code PR (issue-{N} -> issue-{parent_N} or -> main), then pr-reviewer reviews the accumulated diff with the same outcome_policy, review_gate, and human-gate as any other code PR. The epic closes when that PR merges via its Closes trailer.

### `04_evaluate/create-pr`

- **Kind:** script
- **Phase:** `04_evaluate`
- **Script:** `scripts/create-pr.sh`

Opens the epic's own code PR (issue-{N} -> issue-{parent_N} or -> main) once every child issue is closed. Idempotent. The Closes trailer in the PR body closes the epic when the PR merges.

### `04_evaluate/pr-reviewer`

- **Kind:** agent
- **Phase:** `04_evaluate`

Reviews the accumulated diff on the epic's issue-{N} PR after all children are closed, using the same outcome_policy, review_gate, and human-gate machinery as any other code PR. On APPROVE, marks the PR ready for human merge; the PR's Closes trailer closes the epic. On REQUEST CHANGES, :review is applied and a human must address findings before re-triggering -- there is no coder in this flow to auto-remediate.

## Flow: `codebase-review`

- **Applies to:** schedule `0 3 * * 1`
- **Naming:** --

Weekly scheduled three-persona codebase review. Rotates through codebase components across cycles, produces findings matching pr-reviewer's schema, and raises a 'Technical Review - {date}' issue via result.json. Produces no commit, so this flow declares no naming.

### `00_ondemand/codebase-reviewer`

- **Kind:** agent
- **Phase:** `00_ondemand`

Weekly three-persona codebase review (Defensive Programmer, Security Analyst, Quality Assurance). Reads a durable coverage tracker, selects the next due codebase components, reviews them using pr-reviewer's finding schema (RV-NNN), checks for duplicate findings in still-open prior review issues, and requests a 'Technical Review - {date}' issue via result.json's creates_issue field. Cross-references docs/product/ only when code intent is unclear.

## Flow: `sizer`

- **Applies to:** kind `issue`
- **Naming:** --

Sizing of an issue against a single development cycle, triggered by the sizer:requested label -- applied automatically by the standard-delivery flow's request-sizing step right after classification (issue #565), or manually by a human re-requesting sizing on an already-classified issue. Decomposes a large issue into sub-issues and marks the parent epic; produces no commit, so this flow declares no naming.

### `00_ondemand/sizer`

- **Kind:** agent
- **Phase:** `00_ondemand`

Ad-hoc issue sizer. Evaluates whether the issue fits a single development cycle. Small issues get a sizing note and emit complete directly; self_gates (issue #425) lets that :complete stand as-is with no gate label ever applied. Large issues are decomposed into ordered, independently-deliverable sub-issues; the parent is marked epic and the agent emits sizer:review so the human can inspect and edit the breakdown at the sizer:approved gate. On re-invocation after the human applies sizer:approved, emits complete (terminal for the parent). Triggered by applying the sizer:requested label to any issue.

## Flow: `new-agent`

- **Applies to:** kind `issue`
- **Naming:** branch `issue-{number}`

On-demand scaffolding of a new pipeline agent from an issue description. The only on-demand flow whose step commits, so it is the only one that declares naming.

### `00_ondemand/new-agent`

- **Kind:** agent
- **Phase:** `00_ondemand`

On-demand agent that scaffolds a new pipeline agent from a GitHub issue description. Reads the issue to determine the agent's name, phase, trigger, and purpose, then creates the agent prompt file and registers it in pipeline.json. Triggered by applying the new-agent:requested label to an issue.

## Flow: `standards-migrator`

- **Applies to:** kind `issue`
- **Naming:** --

On-demand conversion of a consuming repo's existing knowledge files into machine-readable standards, requested by a human applying a label. Presents proposals for approval rather than committing, so this flow declares no naming.

### `00_ondemand/standards-migrator`

- **Kind:** agent
- **Phase:** `00_ondemand`

Ad-hoc agent that scans the consuming repo for existing knowledge files and ground-truth artifacts, then converts the timeless rules they imply into machine-readable standards/*.json. Presents proposed standards for human approval before writing. Triggered by applying the standards-migrator:requested label to any issue.

## Flow: `branch-cleanup`

- **Applies to:** kind `issue`
- **Naming:** --

On-demand remote-branch hygiene sweep, requested by a human applying a label. Deletes branches only after a human approves the list; produces no commit, so this flow declares no naming.

### `00_ondemand/branch-cleanup`

- **Kind:** agent
- **Phase:** `00_ondemand`

Ad-hoc sweep agent. Evaluates every remote branch, classifies each as a deletion candidate or one to keep, and posts the recommendation for human approval. On re-invocation after a human approves specific branches in a reply comment, deletes exactly those branches and posts a summary. Triggered by applying the branch-cleanup:requested label to any issue.

## Flow: `issue-cleanup`

- **Applies to:** kind `issue`
- **Naming:** --

On-demand backlog-hygiene sweep, requested by a human applying a label. Closes issues only after a human names them; produces no commit, so this flow declares no naming.

### `00_ondemand/issue-cleanup`

- **Kind:** agent
- **Phase:** `00_ondemand`

Ad-hoc backlog-hygiene sweep. Reads every open issue and classifies each as a complete-candidate, a duplicate-cluster member, or keep, and posts the recommendation for human approval. On re-invocation after a human names specific issues in a reply comment, closes exactly those issues with the correct state_reason and posts a summary. Triggered by applying the issue-cleanup:requested label to any issue.

## Flow: `blocker`

- **Applies to:** kind `issue`
- **Naming:** --

On-demand reciprocation of a blockedby:/blocks: pair, requested by a human applying a label. Writes labels only, so this flow declares no naming.

### `00_ondemand/blocker`

- **Kind:** script
- **Phase:** `00_ondemand`
- **Script:** `scripts/blocker.sh`

Reciprocates a blockedby:/blocks: pair. A human applies blockedby:{N} to this issue directly -- that alone already gates eligibility -- then requests this step to add the symmetric blocks:{this} label onto issue N. Emits blocked (not failed) when no blockedby: label is present to reciprocate, so a mistaken request is visible rather than silently swallowed. Triggered by applying the blocker:requested label to any issue.

## Flow: `metrics-aggregation`

- **Applies to:** schedule `0 0 * * 1`
- **Naming:** --

Weekly aggregation of pipeline metrics (issue #533). Reads records.jsonl from the ai-agile/metrics branch, computes per-agent and blended weekly aggregate records for the previous Mon-Sun week, and appends them back into the same file. Produces no issue branch or PR; all writes go to the metrics branch via append-metrics-record.sh.

### `05_continuous/metrics-aggregation`

- **Kind:** script
- **Phase:** `05_continuous`
- **Script:** `scripts/aggregate-metrics.sh`

Computes per-agent and blended weekly aggregate records for the previous Mon-Sun week and appends them to records.jsonl on the ai-agile/metrics branch. Aggregate rows carry agent_id=metrics-aggregator (blended) or the real agent name (per-agent breakdown), period=week, and metric fields named {aggregation_fn}_{base_metric}[-{dimension}]. Idempotent: skips the append when the bucket is already aggregated.

## Flow: `metrics-aggregation-daily`

- **Applies to:** schedule `0 1 * * *`
- **Naming:** --

Daily aggregation of pipeline metrics (issue #547). Reads records.jsonl from the ai-agile/metrics branch, computes per-agent and blended daily aggregate records for the previous complete calendar day (UTC), and appends them back into the same file. Runs at 01:00 Eastern Time (America/New_York) daily to allow the previous day's data to settle. Produces no issue branch or PR; all writes go to the metrics branch via append-metrics-record.sh.

### `05_continuous/metrics-aggregation-daily`

- **Kind:** script
- **Phase:** `05_continuous`
- **Script:** `scripts/aggregate-metrics-daily.sh`

Computes per-agent and blended daily aggregate records for the previous complete calendar day and appends them to records.jsonl on the ai-agile/metrics branch. Aggregate rows carry agent_id=metrics-aggregator (blended) or the real agent name (per-agent breakdown), period=day, and metric fields named {aggregation_fn}_{base_metric}[-{dimension}]. Idempotent: skips the append when the bucket is already aggregated.

## Flow: `metrics-report`

- **Applies to:** schedule `0 2 * * 1`
- **Naming:** --

Weekly performance report (issue #534). Reads weekly-aggregate rows (period=week) and daily-aggregate rows (period=day) from the ai-agile/metrics branch, generates per-metric charts via matplotlib, assembles them into print-styled HTML, and renders a PDF via WeasyPrint. Left charts show 12 months of weekly data; right charts show 4 weeks of daily data. Runs 2 hours after metrics-aggregation on Mondays to allow the weekly aggregation step to complete first.

### `05_continuous/metrics-report`

- **Kind:** script
- **Phase:** `05_continuous`
- **Script:** `scripts/generate-metrics-report.sh`

Reads period=week rows (last 12 months) and period=day rows (last 4 weeks) from records.jsonl on the ai-agile/metrics branch. Generates paired 12-month (weekly) and 4-week (daily) charts for each metric via matplotlib (static PNG images). Assembles charts into portrait US Letter print-styled HTML with four chart rows per page and renders to PDF via WeasyPrint. By-agent metrics (cost, duration) use a per-agent total bar chart; all other metrics use dual line charts. The rendered PDF is written to AI_AGILE_SCRATCH, then committed to the ai-agile/reports branch so it persists after the run's scratch directory is removed.

## Flow: `weekly-release`

- **Applies to:** schedule `0 9 * * 3`
- **Naming:** --

Weekly release flow (issue #604). Fires on the weekly Wednesday cadence and supports manual dispatch. Determines the previous published release boundary, discovers merged PRs and closed issues since that boundary, applies publication gates (coverage threshold, duplicate-release prevention), generates deterministic release-notes Markdown, and publishes a GitHub Release. A rerun with an existing tag exits cleanly without duplicating the release.

### `05_continuous/weekly-release`

- **Kind:** script
- **Phase:** `05_continuous`
- **Script:** `scripts/run-release-flow.sh`

Determines the previous published release boundary and discovers merged PRs and closed issues since that boundary. Applies gates: exits with a structured no-change outcome when nothing is new; skips with a structured skipped outcome when the computed tag already exists; records a gate-failed outcome when the coverage threshold is not met. Otherwise generates release-notes Markdown via release_note_generator.py and creates a GitHub Release. All outcomes are recorded as structured JSON to stderr.
