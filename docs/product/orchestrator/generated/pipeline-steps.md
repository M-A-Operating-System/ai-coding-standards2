<!-- GENERATED FILE -- DO NOT EDIT.
     Source: pipeline/pipeline.json
     Generator: pipeline/generators/generate_docs.py
     Regenerate: python3 pipeline/generators/generate_docs.py -->

# Pipeline Steps

What runs, what starts it, what must finish first, and where a human
decides. This is the process definition (AS-1): `pipeline.json` is
authoritative and this table is a view of it.

## Sequence and gates

| Step | Kind | Trigger | Depends on | Human gate |
|---|---|---|---|---|
| `01_product_docs/issue-classifier` | agent | event `issue.opened` | -- | -- |
| `01_product_docs/prd-writer` | agent | `issue-classifier:complete` | `01_product_docs/issue-classifier` | `prd-writer:approved` |
| `01_product_docs/create-docs-pr` | script | `prd-writer:complete` | `01_product_docs/prd-writer` | -- |
| `01_product_docs/create-pr` | script | `merge-docs-pr:complete` | `01_product_docs/merge-docs-pr` | -- |
| `01_product_docs/prd-docs-updater` | agent | `create-docs-pr:complete` | `01_product_docs/create-docs-pr` | `prd-docs-updater:approved` |
| `01_product_docs/merge-docs-pr` | script | `prd-docs-updater:complete` | `01_product_docs/prd-docs-updater` | -- |
| `03_execute/coder` | agent | `create-pr:complete` | `01_product_docs/create-pr` | -- |
| `03_execute/ci-gate` | script | `coder:complete` | `03_execute/coder` | -- |
| `03_execute/merge-conflict` | agent | `ci-gate:complete` | `03_execute/ci-gate` | `merge-conflict:approved` |
| `03_execute/pr-reviewer` | agent | `merge-conflict:complete` | `03_execute/merge-conflict` | -- |
| `00_ondemand/codebase-reviewer` | agent | `codebase-reviewer:requested` | -- | -- |
| `00_ondemand/sizer` | agent | `sizer:requested` | -- | `sizer:review` |
| `00_ondemand/new-agent` | agent | `new-agent:requested` | -- | -- |
| `00_ondemand/standards-migrator` | agent | `standards-migrator:requested` | -- | -- |
| `00_ondemand/branch-cleanup` | agent | `branch-cleanup:requested` | -- | -- |
| `00_ondemand/issue-cleanup` | agent | `issue-cleanup:requested` | -- | -- |
| `00_ondemand/blocker` | script | `blocker:requested` | -- | -- |

## Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `01_product_docs/issue-classifier` | -- | -- | `2` |
| `01_product_docs/prd-writer` | -- | `epic`, `blocked` | `2` |
| `01_product_docs/create-docs-pr` | `spike` | `epic`, `blocked` | -- |
| `01_product_docs/create-pr` | `spike` | `epic`, `blocked` | -- |
| `01_product_docs/prd-docs-updater` | `spike` | `epic`, `blocked` | `2` |
| `01_product_docs/merge-docs-pr` | `spike` | `epic`, `blocked` | -- |
| `03_execute/coder` | `spike` | `epic`, `blocked` | `1` |
| `03_execute/ci-gate` | `spike` | `epic`, `blocked` | `1` |
| `03_execute/merge-conflict` | `spike` | `epic`, `blocked` | `1` |
| `03_execute/pr-reviewer` | `spike` | `epic`, `blocked` | `1` |
| `00_ondemand/codebase-reviewer` | -- | -- | `1` |
| `00_ondemand/sizer` | -- | -- | `1` |
| `00_ondemand/new-agent` | -- | -- | `1` |
| `00_ondemand/standards-migrator` | -- | -- | `1` |
| `00_ondemand/branch-cleanup` | -- | -- | `1` |
| `00_ondemand/issue-cleanup` | -- | -- | `1` |
| `00_ondemand/blocker` | -- | -- | `1` |

## Entitled activities

What each step is permitted to do. Under AS-1 this table must be
complete: an entitlement that does not appear here is not granted.

**Granted to every step:** `Write`, `Edit`, `Bash(gh issue view *)`, `Bash(gh issue comment *)`, `Bash(gh issue edit *)`, `Bash(gh issue list *)`, `Bash(gh pr view *)`, `Bash(gh pr comment *)`, `Bash(gh pr list *)`, `Bash(gh pr diff *)`, `Bash(gh api repos/*/issues/*)`, `Bash(gh api repos/*/pulls/*)`, `Bash(gh api repos/*/issues*)`, `Bash(gh api repos/*/pulls*)`, `Bash(gh api "repos/*/issues/*)`, `Bash(gh api "repos/*/pulls/*)`, `Bash(gh api "repos/*/issues*)`, `Bash(gh api "repos/*/pulls*)`, `Bash(gh api --method * repos/*/issues*)`, `Bash(gh api --method * "repos/*/issues*)`, `Bash(cat *)`, `Bash(grep *)`, `Bash(find *)`, `Bash(cd *)`, `Read`, `Glob`, `Grep`

| Step | Additional entitlements | Git operations |
|---|---|---|
| `01_product_docs/issue-classifier` | -- | -- |
| `01_product_docs/prd-writer` | -- | -- |
| `01_product_docs/create-docs-pr` | -- | -- |
| `01_product_docs/create-pr` | -- | -- |
| `01_product_docs/prd-docs-updater` | -- | `commit_after=true` |
| `01_product_docs/merge-docs-pr` | -- | -- |
| `03_execute/coder` | `Bash(git *)`, `Bash(python *)`, `Bash(python3 *)`, `Bash(pip *)`, `Bash(pip3 *)`, `Bash(uv *)` _(+61 more)_ | `commit_after=true` |
| `03_execute/ci-gate` | -- | -- |
| `03_execute/merge-conflict` | `Bash(gh api *)`, `Bash(gh pr checks *)`, `Bash(gh pr comment *)`, `Bash(gh run view *)`, `Bash(gh run list *)`, `Bash(git fetch *)` _(+8 more)_ | -- |
| `03_execute/pr-reviewer` | `Bash(gh pr review *)`, `Bash(gh pr ready *)`, `Bash(gh api *)`, `Bash(gh pr checks *)`, `Bash(gh run view *)` | `commit_after=false` |
| `00_ondemand/codebase-reviewer` | `Bash(gh issue create *)`, `Bash(git log *)` | -- |
| `00_ondemand/sizer` | `Bash(gh issue create *)`, `Bash(gh api *)` | -- |
| `00_ondemand/new-agent` | `Edit(.claude/agents/**)` | `commit_after=true` |
| `00_ondemand/standards-migrator` | `Bash(gh issue create *)`, `Bash(python3 *)` | -- |
| `00_ondemand/branch-cleanup` | `Bash(gh api *)`, `Bash(gh pr list *)`, `Bash(gh issue comment *)`, `Bash(gh issue view *)` | -- |
| `00_ondemand/issue-cleanup` | `Bash(gh api *)`, `Bash(gh issue list *)`, `Bash(gh issue view *)`, `Bash(gh issue comment *)`, `Bash(gh issue close *)`, `Bash(gh pr list *)` | -- |
| `00_ondemand/blocker` | -- | -- |
