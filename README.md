# ai-coding-standards2

The AI Agile pipeline — a deterministic Python orchestrator plus a
catalogue of agent prompts that move every change from a GitHub issue
through to a merged PR with humans approving at well-defined gates.

This repo is **designed to be added as a git submodule** to the
project repos that consume it. The submodule provides:

- The pipeline graph (`ai-agile/pipeline/pipeline.json`)
- The orchestrator (`ai-agile/pipeline/pipeline_orchestrator.py`)
- The agent prompts (`.github/agents/{agent}.md`)
- The `status.sh` label-transition helper (`.github/scripts/status.sh`)
- The validators (`ai-agile/pipeline/validate.py` and friends)

The consuming repo provides:

- A thin GitHub Actions workflow that invokes the orchestrator
- The `ANTHROPIC_API_KEY` secret
- Optional repo-specific agents and standards

The full design is in `docs/product/agile/`. Start with
[`docs/product/agile/README.md`](docs/product/agile/README.md).

---

## Install in a consuming repo

### 1. Add the submodule

From your consuming repo's root:

```bash
git submodule add https://github.com/M-A-Operating-System/ai-coding-standards2 ai-coding-standards2
git submodule update --init --recursive
git commit -m "Add ai-coding-standards2 as submodule"
```

The submodule lives at `ai-coding-standards2/` in your repo. Pin to a
tag or specific commit when you're ready to control upgrades.

### 2. Add the orchestrator workflow

GitHub Actions only reads workflows from the consuming repo's own
`.github/workflows/` — it does **not** pick up workflows from
submodules. Copy the template below into your repo at
`.github/workflows/orchestrator.yml`:

```yaml
name: AI Agile orchestrator

on:
  issues:
    types: [opened, reopened, labeled, unlabeled]
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review, labeled, unlabeled, closed]
  schedule:
    - cron: '*/15 6-20 * * 1-5'   # backstop reconciler
  workflow_dispatch:
    inputs:
      issue_number:
        description: 'Issue or PR number (blank = all open items)'
        required: false
      dry_run:
        description: 'Dry run — log decisions without changing labels'
        type: boolean
        default: false

permissions:
  contents: read
  issues: write
  pull-requests: write

concurrency:
  group: ai-agile-${{ github.event.issue.number || github.event.pull_request.number || 'scheduled' }}
  cancel-in-progress: false

jobs:
  orchestrate:
    runs-on: ubuntu-latest
    timeout-minutes: 120

    steps:
      - uses: actions/checkout@v4
        with:
          submodules: true   # IMPORTANT: pulls in ai-coding-standards2/

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install requests jsonschema

      - run: npm install -g @anthropic-ai/claude-code

      - name: Build orchestrator args
        id: args
        run: |
          ARGS=""
          if [ -n "${{ github.event.inputs.issue_number }}" ]; then
            ARGS="--issue ${{ github.event.inputs.issue_number }}"
          elif [ "${{ github.event_name }}" = "issues" ]; then
            ARGS="--issue ${{ github.event.issue.number }} --kind issue"
          elif [ "${{ github.event_name }}" = "pull_request" ]; then
            ARGS="--issue ${{ github.event.pull_request.number }} --kind pr"
          fi
          [ "${{ github.event.inputs.dry_run }}" = "true" ] && ARGS="$ARGS --dry-run"
          echo "args=$ARGS" >> "$GITHUB_OUTPUT"

      - name: Run orchestrator
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          AI_AGILE_ROOT: ${{ github.workspace }}/ai-coding-standards2
        run: |
          python ai-coding-standards2/ai-agile/pipeline/pipeline_orchestrator.py \
            --repo "$GITHUB_REPOSITORY" \
            ${{ steps.args.outputs.args }}
```

Commit it.

### 3. Add the secret

Add `ANTHROPIC_API_KEY` to your consuming repo's secrets
(Settings → Secrets and variables → Actions → New repository secret).

### 4. Bootstrap the labels

Once, from your consuming repo's root, after the submodule is
checked out locally:

```bash
bash ai-coding-standards2/.github/scripts/status.sh bootstrap-all
```

This creates every `{agent}:{status}` label and every gate label in
your consuming repo so the orchestrator can apply them later.

### 5. Open a test issue

Open an issue with a problem statement and acceptance criteria. The
workflow fires on `issues.opened`, the orchestrator picks up
`issue-classifier`, and you should see the label flow
`issue-classifier:wip` → `issue-classifier:complete`, plus a
classification comment from the agent.

If the issue is missing fields, you'll see
`issue-classifier:blocked` and a corrective comment instead.

---

## How paths resolve

The orchestrator is path-agnostic and infers everything from one
of two roots:

| Variable | Default | Used for |
|---|---|---|
| `AI_AGILE_ROOT` env var | The directory three levels above `pipeline_orchestrator.py` (i.e. the repo root containing `.github/` and `ai-agile/`) | Locating `status.sh` and agent prompts |
| `--pipeline PATH` arg | `<this_dir>/pipeline.json` | The pipeline graph |

When this repo is checked out **at the consuming repo's root**
(non-submodule mode), `AI_AGILE_ROOT` defaults to the repo root —
everything just works.

When this repo is checked out **as a submodule** at
`<consuming-repo>/ai-coding-standards2/`, set `AI_AGILE_ROOT` in the
workflow env (the template above does this) so the orchestrator
finds `status.sh` and agent prompts under the submodule, not under
the consuming repo's root.

The orchestrator passes both `AI_AGILE_ROOT` and the resolved
`STATUS_SH` to every agent subprocess via env. Agent prompts
reference `$STATUS_SH` rather than a hardcoded path, so they work
identically in both layouts.

---

## Adding repo-specific agents (advanced)

Out of MVP scope. Today every agent prompt lives in the submodule.
Once the submodule is stable, the design supports the consuming repo
adding its own agents at `<consuming-repo>/.github/agents/{agent}.md`,
which override (or extend) the submodule's set. This requires a small
orchestrator change to consult two agent directories. Track this in
the roadmap.

---

## Updating the submodule

When new agents or pipeline changes ship in this repo, the consuming
repo updates the submodule pointer:

```bash
cd ai-coding-standards2
git fetch origin
git checkout <new-tag-or-sha>
cd ..
git add ai-coding-standards2
git commit -m "Bump ai-coding-standards2 to <ref>"
```

Pin to tags for predictable upgrades. Do not track `main` directly
in production unless you want every change auto-applied.

---

## Repo layout

```
.
├── README.md                                # this file
├── docs/product/agile/                      # full design (target state) + roadmap
│   ├── README.md                            # reading order
│   ├── 01-vision.md ... 13-todos.md
│   └── 10-roadmap.md                        # MVP scope and rollout phases
├── .github/
│   ├── agents/
│   │   ├── issue-classifier.md              # agent prompt
│   │   └── _templates/agent-template.md     # template for new agents
│   ├── scripts/status.sh                    # label transitions helper
│   └── workflows/                           # this repo's own CI (does not run from a consuming repo)
│       ├── orchestrator.yml
│       └── validate-pipeline.yml
└── ai-agile/
    └── pipeline/
        ├── pipeline.json                    # the agent dependency graph (source of truth)
        ├── pipeline_orchestrator.py         # the deterministic Python orchestrator
        ├── statuses.json                    # canonical status definitions
        ├── validate.py                      # pipeline.json validator
        └── schemas/pipeline.schema.json
```

---

## Standalone use (without submodule)

This repo also runs against itself, for testing the standards. Open an
issue or PR in this repo and the same orchestrator workflow at
`.github/workflows/orchestrator.yml` fires. No changes needed. This
mode is how new agents are tested before being shipped to consuming
repos.

---

## Documentation

- [`docs/product/agile/README.md`](docs/product/agile/README.md) — the full design index
- [`docs/product/agile/10-roadmap.md`](docs/product/agile/10-roadmap.md) — MVP scope and rollout phases
- [`docs/product/agile/11-orchestrator.md`](docs/product/agile/11-orchestrator.md) — orchestrator technical design
- [`docs/product/agile/12-agent-spec.md`](docs/product/agile/12-agent-spec.md) — agent prompt-file spec
- [`docs/product/agile/13-todos.md`](docs/product/agile/13-todos.md) — todos in issue/PR bodies
