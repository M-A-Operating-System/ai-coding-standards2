<!-- GENERATED FILE -- DO NOT EDIT.
     Source: pipeline/pipeline.json
     Generator: pipeline/generators/generate_docs.py
     Regenerate: python3 pipeline/generators/generate_docs.py -->

# Pipeline Steps

What runs, what starts it, what must finish first, and where a human
decides -- one section per flow, because the pipeline defines flows,
not a flow. This is the process definition (AS-1): `pipeline.json` is
authoritative and these tables are a view of it.

## Flows

| Flow | Applies to | Naming |
|---|---|---|
| `standard-delivery` | kind `issue` | branch `issue-{number}`; PR `docs` on `issue-{number}-docs` (does not close the issue); PR `code` on `issue-{number}` (closes the issue) |
| `epic-completion` | kind `issue`; labels `epic` | -- |
| `codebase-review` | kind `issue` | -- |
| `sizer` | kind `issue` | -- |
| `new-agent` | kind `issue` | branch `issue-{number}` |
| `standards-migrator` | kind `issue` | -- |
| `branch-cleanup` | kind `issue` | -- |
| `issue-cleanup` | kind `issue` | -- |
| `blocker` | kind `issue` | -- |

## Flow: `standard-delivery`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `01_product_docs/issue-classifier` | agent | `item` | event `issue.opened` | -- | -- |
| `01_product_docs/prd-writer` | agent | `item` | `issue-classifier:complete` | `01_product_docs/issue-classifier` | `prd-writer:approved` |
| `01_product_docs/create-docs-pr` | script | `item` | `prd-writer:complete` | `01_product_docs/prd-writer` | -- |
| `01_product_docs/prd-docs-updater` | agent | `item` | `create-docs-pr:complete` | `01_product_docs/create-docs-pr` | `prd-docs-updater:approved` |
| `01_product_docs/merge-docs-pr` | script | `item` | `prd-docs-updater:complete` | `01_product_docs/prd-docs-updater` | -- |
| `01_product_docs/create-pr` | script | `item` | `merge-docs-pr:complete` | `01_product_docs/merge-docs-pr` | -- |
| `03_execute/coder` | agent | `item` | `create-pr:complete` | `01_product_docs/create-pr` | -- |
| `03_execute/ci-gate` | script | `item` | `coder:complete` | `03_execute/coder` | -- |
| `03_execute/merge-conflict` | agent | `item` | `ci-gate:complete` | `03_execute/ci-gate` | `merge-conflict:approved` |
| `03_execute/pr-reviewer` | agent | `item` | `merge-conflict:complete` | `03_execute/merge-conflict` | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `01_product_docs/issue-classifier` | -- | -- | `2` |
| `01_product_docs/prd-writer` | -- | `epic`, `blocked` | `2` |
| `01_product_docs/create-docs-pr` | `spike` | `epic`, `blocked` | -- |
| `01_product_docs/prd-docs-updater` | `spike` | `epic`, `blocked` | `2` |
| `01_product_docs/merge-docs-pr` | `spike` | `epic`, `blocked` | -- |
| `01_product_docs/create-pr` | `spike` | `epic`, `blocked` | -- |
| `03_execute/coder` | `spike` | `epic`, `blocked` | `1` |
| `03_execute/ci-gate` | `spike` | `epic`, `blocked` | `1` |
| `03_execute/merge-conflict` | `spike` | `epic`, `blocked` | `1` |
| `03_execute/pr-reviewer` | `spike` | `epic`, `blocked` | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `01_product_docs/issue-classifier` | -- | -- |
| `01_product_docs/prd-writer` | -- | -- |
| `01_product_docs/create-docs-pr` | -- | `commit_after=false`, `commits_to="docs"` |
| `01_product_docs/prd-docs-updater` | -- | `commit_after=true`, `commits_to="docs"` |
| `01_product_docs/merge-docs-pr` | -- | `commit_after=false`, `commits_to="docs"` |
| `01_product_docs/create-pr` | -- | `commit_after=false`, `commits_to="code"` |
| `03_execute/coder` | `Bash(git log *)`, `Bash(git diff *)`, `Bash(git rev-parse *)`, `Bash(python *)`, `Bash(python3 *)`, `Bash(pip *)` _(+63 more)_ | `commit_after=true`, `commits_to="code"` |
| `03_execute/ci-gate` | -- | -- |
| `03_execute/merge-conflict` | `Bash(gh api *)`, `Bash(gh pr checks *)`, `Bash(gh pr comment *)`, `Bash(gh run view *)`, `Bash(gh run list *)`, `Bash(git fetch *)` _(+8 more)_ | -- |
| `03_execute/pr-reviewer` | `Bash(gh pr review *)`, `Bash(gh pr ready *)`, `Bash(gh api *)`, `Bash(gh pr checks *)`, `Bash(gh run view *)` | `commit_after=false` |

## Flow: `epic-completion`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `04_evaluate/epic-closer` | script | `item` | children `all_closed` | -- | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `04_evaluate/epic-closer` | -- | -- | -- |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `04_evaluate/epic-closer` | -- | -- |

## Flow: `codebase-review`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `00_ondemand/codebase-reviewer` | agent | `item` | `codebase-reviewer:requested` | -- | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `00_ondemand/codebase-reviewer` | -- | -- | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `00_ondemand/codebase-reviewer` | `Bash(gh issue create *)`, `Bash(git log *)` | -- |

## Flow: `sizer`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `00_ondemand/sizer` | agent | `item` | `sizer:requested` | -- | `sizer:review` |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `00_ondemand/sizer` | -- | -- | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `00_ondemand/sizer` | `Bash(gh issue create *)`, `Bash(gh api *)` | -- |

## Flow: `new-agent`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `00_ondemand/new-agent` | agent | `item` | `new-agent:requested` | -- | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `00_ondemand/new-agent` | -- | -- | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `00_ondemand/new-agent` | `Edit(.claude/agents/**)` | `commit_after=true` |

## Flow: `standards-migrator`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `00_ondemand/standards-migrator` | agent | `item` | `standards-migrator:requested` | -- | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `00_ondemand/standards-migrator` | -- | -- | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `00_ondemand/standards-migrator` | `Bash(gh issue create *)`, `Bash(python3 *)` | -- |

## Flow: `branch-cleanup`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `00_ondemand/branch-cleanup` | agent | `item` | `branch-cleanup:requested` | -- | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `00_ondemand/branch-cleanup` | -- | -- | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `00_ondemand/branch-cleanup` | `Bash(gh api *)`, `Bash(gh pr list *)`, `Bash(gh issue comment *)`, `Bash(gh issue view *)` | -- |

## Flow: `issue-cleanup`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `00_ondemand/issue-cleanup` | agent | `item` | `issue-cleanup:requested` | -- | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `00_ondemand/issue-cleanup` | -- | -- | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `00_ondemand/issue-cleanup` | `Bash(gh api *)`, `Bash(gh issue list *)`, `Bash(gh issue view *)`, `Bash(gh issue comment *)`, `Bash(gh issue close *)`, `Bash(gh pr list *)` | -- |

## Flow: `blocker`

### Sequence and gates

| Step | Kind | Unit | Trigger | Depends on | Human gate |
|---|---|---|---|---|---|
| `00_ondemand/blocker` | script | `item` | `blocker:requested` | -- | -- |

### Exclusions and retries

| Step | Excluded classifications | Excluded labels | Max retries |
|---|---|---|---|
| `00_ondemand/blocker` | -- | -- | `1` |

### Entitled activities

| Step | Additional entitlements | Git operations |
|---|---|---|
| `00_ondemand/blocker` | -- | -- |

## Entitlements granted to every step

Under AS-1 the tables above must be complete: an entitlement that does
not appear there or here is not granted.

**Granted to every step:** `Write`, `Edit`, `Bash(gh issue view *)`, `Bash(gh issue comment *)`, `Bash(gh issue edit *)`, `Bash(gh issue list *)`, `Bash(gh pr view *)`, `Bash(gh pr comment *)`, `Bash(gh pr list *)`, `Bash(gh pr diff *)`, `Bash(gh api repos/*/issues/*)`, `Bash(gh api repos/*/pulls/*)`, `Bash(gh api repos/*/issues*)`, `Bash(gh api repos/*/pulls*)`, `Bash(gh api "repos/*/issues/*)`, `Bash(gh api "repos/*/pulls/*)`, `Bash(gh api "repos/*/issues*)`, `Bash(gh api "repos/*/pulls*)`, `Bash(gh api --method * repos/*/issues*)`, `Bash(gh api --method * "repos/*/issues*)`, `Bash(cat *)`, `Bash(grep *)`, `Bash(find *)`, `Bash(cd *)`, `Read`, `Glob`, `Grep`
