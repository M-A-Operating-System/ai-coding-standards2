<!-- GENERATED FILE -- DO NOT EDIT.
     Source: pipeline/pipeline.json
     Generator: pipeline/generators/generate_docs.py
     Regenerate: python3 pipeline/generators/generate_docs.py -->

# Shipped Pipeline Reference

This page is generated from the shipped [pipeline definition](../../../pipeline/pipeline.json).
Steps are listed in configuration order. Dependencies, triggers, and
approval gates determine when they can run.
The approval column lists workflow labels. Pull request review and
merge happen in GitHub.

See the [Product-First process](00_README.md) for the operating model
and the [detailed pipeline tables](../orchestrator/generated/pipeline-steps.md)
for exclusions, retries, and tool permissions.

## standard-delivery

**Applies to:** kind `issue`

An issue taken from description to shipped code: classify, write the PRD, publish the approved design to main on its own design branch and PR, then build, gate on CI, resolve conflicts and review the code PR. Two-phase design->build (issue #247) is expressed here as two pull requests on one flow -- the design PR (issue-{N}-docs, non-closing) merged ahead of the code PR (issue-{N}, closing).

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `01_product_docs/issue-classifier` | agent | event `issue.opened` | -- | -- |
| `01_product_docs/request-sizing` | script | `issue-classifier:complete` | `01_product_docs/issue-classifier` | -- |
| `01_product_docs/prd-writer` | agent | `sizer:complete` | `01_product_docs/request-sizing` | `prd-writer:approved` |
| `01_product_docs/create-docs-pr` | script | `prd-writer:complete` | `01_product_docs/prd-writer` | -- |
| `01_product_docs/prd-docs-updater` | agent | `create-docs-pr:complete` | `01_product_docs/create-docs-pr` | `prd-docs-updater:approved` (when requested) |
| `01_product_docs/merge-docs-pr` | script | `prd-docs-updater:complete` | `01_product_docs/prd-docs-updater` | -- |
| `01_product_docs/create-pr` | script | `merge-docs-pr:complete` | `01_product_docs/merge-docs-pr` | -- |
| `03_execute/coder` | agent | `create-pr:complete` | `01_product_docs/create-pr` | -- |
| `03_execute/ci-gate` | script | `coder:complete` | `03_execute/coder` | -- |
| `03_execute/merge-conflict` | agent | `ci-gate:complete` | `03_execute/ci-gate` | `merge-conflict:approved` (when requested) |
| `03_execute/pr-reviewer` | agent | `merge-conflict:complete` | `03_execute/merge-conflict` | -- |

## epic-completion

**Applies to:** kind `issue`; labels `epic`

Coordinating work: an epic is a parent whose children are the real work. Once all child issues (parent-issue:{N}) are closed, create-pr opens the epic's own code PR (issue-{N} -> issue-{parent_N} or -> main), then pr-reviewer reviews the accumulated diff with the same outcome_policy, review_gate, and human-gate as any other code PR. The epic closes when that PR merges via its Closes trailer.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `04_evaluate/create-pr` | script | children `all_closed` | -- | -- |
| `04_evaluate/coder` | agent | `create-pr:complete` | `04_evaluate/create-pr` | -- |
| `04_evaluate/ci-gate` | script | `coder:complete` | `04_evaluate/coder` | -- |
| `04_evaluate/merge-conflict` | agent | `ci-gate:complete` | `04_evaluate/ci-gate` | `merge-conflict:approved` (when requested) |
| `04_evaluate/epic-pr-reviewer` | agent | `merge-conflict:complete` | `04_evaluate/merge-conflict` | -- |

## codebase-review

**Applies to:** schedule `0 3 * * 1`

Weekly scheduled three-persona codebase review. Rotates through codebase components across cycles, produces findings matching pr-reviewer's schema, and raises a 'Technical Review - {date}' issue via result.json. Produces no commit, so this flow declares no naming.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `00_ondemand/codebase-reviewer` | agent | event `schedule` | -- | -- |

## sizer

**Applies to:** kind `issue`

Sizing of an issue against a single development cycle, triggered by the sizer:requested label -- applied automatically by the standard-delivery flow's request-sizing step right after classification (issue #565), or manually by a human re-requesting sizing on an already-classified issue. Decomposes a large issue into sub-issues and marks the parent epic; produces no commit, so this flow declares no naming.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `00_ondemand/sizer` | agent | `sizer:requested` | -- | `sizer:approved` (when requested) |

## new-agent

**Applies to:** kind `issue`

On-demand scaffolding of a new pipeline agent from an issue description. The only on-demand flow whose step commits, so it is the only one that declares naming.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `00_ondemand/new-agent` | agent | `new-agent:requested` | -- | -- |

## standards-migrator

**Applies to:** kind `issue`

On-demand conversion of a consuming repo's existing knowledge files into machine-readable standards, requested by a human applying a label. Presents proposals for approval rather than committing, so this flow declares no naming.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `00_ondemand/standards-migrator` | agent | `standards-migrator:requested` | -- | -- |

## branch-cleanup

**Applies to:** kind `issue`

On-demand remote-branch hygiene sweep, requested by a human applying a label. Deletes branches only after a human approves the list; produces no commit, so this flow declares no naming.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `00_ondemand/branch-cleanup` | agent | `branch-cleanup:requested` | -- | -- |

## issue-cleanup

**Applies to:** kind `issue`

On-demand backlog-hygiene sweep, requested by a human applying a label. Closes issues only after a human names them; produces no commit, so this flow declares no naming.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `00_ondemand/issue-cleanup` | agent | `issue-cleanup:requested` | -- | -- |

## blocker

**Applies to:** kind `issue`

On-demand reciprocation of a blockedby:/blocks: pair, requested by a human applying a label. Writes labels only, so this flow declares no naming.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `00_ondemand/blocker` | script | `blocker:requested` | -- | -- |

## metrics-aggregation

**Applies to:** schedule `0 0 * * 1`

Weekly aggregation of pipeline metrics (issue #533). Reads records.jsonl from the ai-agile/metrics branch, computes per-agent and blended weekly aggregate records for the previous Mon-Sun week, and appends them back into the same file. Produces no issue branch or PR; all writes go to the metrics branch via append-metrics-record.sh.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `05_continuous/metrics-aggregation` | script | event `schedule` | -- | -- |

## metrics-aggregation-daily

**Applies to:** schedule `0 1 * * *`

Daily aggregation of pipeline metrics (issue #547). Reads records.jsonl from the ai-agile/metrics branch, computes per-agent and blended daily aggregate records for the previous complete calendar day (UTC), and appends them back into the same file. Runs at 01:00 Eastern Time (America/New_York) daily to allow the previous day's data to settle. Produces no issue branch or PR; all writes go to the metrics branch via append-metrics-record.sh.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `05_continuous/metrics-aggregation-daily` | script | event `schedule` | -- | -- |

## metrics-report

**Applies to:** schedule `0 2 * * 1`

Weekly performance report (issue #534). Reads weekly-aggregate rows (period=week) and daily-aggregate rows (period=day) from the ai-agile/metrics branch, generates per-metric charts via matplotlib, assembles them into print-styled HTML, and renders a PDF via WeasyPrint. Left charts show 12 months of weekly data; right charts show 2 months of daily data. Runs 2 hours after metrics-aggregation on Mondays to allow the weekly aggregation step to complete first.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `05_continuous/metrics-report` | script | event `schedule` | -- | -- |

## weekly-release

**Applies to:** schedule `0 9 * * 3`

Weekly release flow (issue #604). Fires on the weekly Wednesday cadence and supports manual dispatch. Determines the previous published release boundary, discovers merged PRs and closed issues since that boundary, applies publication gates (coverage threshold, duplicate-release prevention), generates deterministic release-notes Markdown, and publishes a GitHub Release. A rerun with an existing tag exits cleanly without duplicating the release.

| Step | Kind | Trigger | Depends on | Approval label |
| --- | --- | --- | --- | --- |
| `05_continuous/weekly-release` | script | event `schedule` | -- | -- |
