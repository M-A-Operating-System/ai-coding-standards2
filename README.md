# ai-coding-standards2

The AI Agile pipeline — a deterministic Python orchestrator plus a
catalogue of agent prompts that move every change from a GitHub issue
through to a merged PR with humans approving at well-defined gates.

This repo is **designed to be added as a git submodule** to the
project repos that consume it. The submodule provides:

- The pipeline graph (`ai-agile/pipeline/pipeline.json`)
- The orchestrator (`ai-agile/pipeline/pipeline_orchestrator.py`)
- The agent prompts (`.claude/agents/{agent}.md`)
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

The whole flow is four shell commands plus one secret. The
`get_started.py` script does the bulk of the wiring.

### 1. Add the submodule

From your consuming repo's root:

```bash
git submodule add https://github.com/M-A-Operating-System/ai-coding-standards2 ai-coding-standards2
git submodule update --init --recursive
```

The submodule lives at `ai-coding-standards2/` in your repo. Pin to a
tag or specific commit when you're ready to control upgrades.

### 2. Run `get_started.py`

```bash
python ai-coding-standards2/get_started.py
```

This script:

- Detects the consuming repo's root (via `git rev-parse --show-superproject-working-tree`).
- Drops the orchestrator workflow into your `.github/workflows/orchestrator.yml`. (GitHub Actions only reads workflows from the consuming repo's own `.github/`; it cannot pick them up from submodules.)
- Copies the slash commands from `ai-coding-standards2/.claude/commands/` into your `.claude/commands/`, rewriting any submodule-relative paths so they resolve from your repo's root.
- Writes `.claude/settings.local.json` setting `AI_AGILE_ROOT=ai-coding-standards2` so anyone running the orchestrator manually from your repo's root finds the right `pipeline.json`, `status.sh`, and agent prompts.

Re-run with `--force` to overwrite existing files; with `--dry-run` to preview.

### 3. Bootstrap the labels

```bash
bash ai-coding-standards2/.github/scripts/status.sh bootstrap-all \
     ai-coding-standards2/ai-agile/pipeline/pipeline.json
```

This creates every `{agent}:{status}` label and every gate label in
your repo so the orchestrator can apply them later.

### 4. Set up the bot account and secrets

The orchestrator runs under a **dedicated GitHub user account** rather
than the workflow's auto-provisioned `GITHUB_TOKEN`. This makes every
label, comment, and PR review in the timeline visibly attributable to
the bot (vs a human contributor), and isolates the bot's rate-limit
quota from real users.

#### a. Create the bot account

One-time, per organisation:

1. Sign out, sign up for a new GitHub account at
   `https://github.com/join`. Suggested handle: `<org>-ai-agile-bot`.
   Use an email address you control (an alias on the team's mailbox
   works well).
2. Sign in to the bot account, enable 2FA, and add it as a
   collaborator (or org member with `write` permission) on every repo
   that will use this orchestrator.

#### b. Generate the bot's PAT

While signed in as the bot:

1. Go to Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token.
2. Set the resource owner to the org (or to the bot user for
   single-repo trials), pick the repos this token can access, and
   grant these repository permissions:
   - **Issues** — Read and write
   - **Pull requests** — Read and write
   - **Contents** — Read and write *(needed when `coder` lands later;
     read-only is enough for Phase 1 Slice 1)*
   - **Metadata** — Read (auto-selected)
3. Set an expiry — 90 days is a reasonable default; calendar a
   reminder to rotate.
4. Copy the token (you only see it once).

#### c. Store the secrets in your repo

In the consuming repo (signed in as a human admin):
Settings → Secrets and variables → Actions → New repository secret.

| Secret | Value |
|---|---|
| `AI_AGILE_BOT_TOKEN` | The bot's PAT from step (b) |
| `ANTHROPIC_API_KEY` | Your Anthropic API key (lives on the consuming repo, **not** in this submodule) |

Both secrets are repo-scoped. Neither leaves the workflow runner.

> **Why not the auto `GITHUB_TOKEN`?** The auto token shows the
> workflow itself as the actor — every action looks like it came from
> "github-actions[bot]", indistinguishable from any other workflow.
> A dedicated bot user gives the AI Agile pipeline its own avatar
> and login so reviewers can see at a glance which actions are
> agent-driven vs human-driven. See
> [`docs/product/agile/09-human-interaction.md`](docs/product/agile/09-human-interaction.md#4-agent-identity)
> for the full rationale and the planned migration path to a GitHub
> App.

### 5. Commit and open a test issue

```bash
git add .gitmodules ai-coding-standards2 .github/workflows/orchestrator.yml .claude/
git commit -m "Wire up ai-coding-standards2 orchestrator"
git push
```

Open an issue with a problem statement and acceptance criteria. The
workflow fires on `issues.opened`; expect labels
`01_product_docs/issue-classifier:wip` → `:complete`, plus a
classification comment from the agent.

If the issue is missing required fields, you'll see
`01_product_docs/issue-classifier:blocked` and a corrective comment
instead.

---

## How paths resolve

The orchestrator is path-agnostic and infers everything from one
of two roots:

| Variable | Default | Used for |
|---|---|---|
| `AI_AGILE_ROOT` env var | The directory three levels above `pipeline_orchestrator.py` (i.e. the repo root containing `.github/` and `ai-agile/`) | Locating `status.sh` and agent prompt files |
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
adding its own agents at `<consuming-repo>/.claude/agents/{agent}.md`,
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

### What auto-flows vs. what needs `get_started.py --force`

After a submodule bump, **most things just work** because the
orchestrator reads them straight from the submodule:

- Agent prompts (`.claude/agents/{phase}/*.md`) — read via `AI_AGILE_ROOT`
- `pipeline.json`, `status.sh`, validators — read via `AI_AGILE_ROOT`
- Schema and CI checks — referenced by their submodule paths

A small set of files were copied into your repo by `get_started.py`
and **don't** auto-update:

- `.github/workflows/orchestrator.yml` (GitHub Actions can't read workflows from submodules)
- `.claude/commands/*.md` (path rewrites are baked in at install time)

If those have changed in the new submodule version, re-run:

```bash
python ai-coding-standards2/get_started.py --force
git add .github/workflows/orchestrator.yml .claude/
git commit -m "Refresh ai-coding-standards2 wrapper files"
```

Look at the submodule's CHANGELOG (when one exists) or the diff
between tags to know whether re-running is needed. If neither the
workflow nor any slash command changed, no re-run is required.

---

## Repo layout

```
.
├── README.md                                # this file
├── get_started.py                           # one-shot wiring script for consuming repos
├── docs/product/agile/                      # full design (target state) + roadmap
│   ├── README.md                            # reading order
│   ├── 01-vision.md ... 13-todos.md
│   └── 10-roadmap.md                        # MVP scope and rollout phases
├── .github/
│   ├── agents/                              # agent prompts, one subdir per phase
│   │   ├── 01_product_docs/
│   │   │   └── issue-classifier.md
│   │   ├── 02_technical_docs/               # added in future Phase 1 slices
│   │   ├── 03_testing_spec/
│   │   ├── 04_build_plan/
│   │   ├── 05_execute/
│   │   ├── 06_test/
│   │   ├── 07_evaluate/
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

The numeric prefixes on the per-phase agent directories (`01_…` →
`10_…`) make `ls` show phases in lifecycle order. Agent names in
`pipeline.json` and on labels carry the same prefix:

```
01_product_docs/issue-classifier
02_technical_docs/architect
05_execute/coder
07_evaluate/retrospective-writer
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
