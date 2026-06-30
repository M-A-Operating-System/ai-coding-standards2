# ai-coding-standards2

The AI Agile pipeline — a deterministic Python orchestrator plus a
catalogue of agent prompts that move every change from a GitHub issue
through to a merged PR with humans approving at well-defined gates.

This repo is **designed to be added as a git submodule** to the
project repos that consume it. The submodule provides:

- The pipeline graph (`pipeline/pipeline.json`)
- The orchestrator (`pipeline/pipeline_orchestrator.py`)
- The agent prompts (`.claude/agents/{agent}.md`)
- The `status.sh` label-transition helper (`.github/scripts/status.sh`)
- The validators (`pipeline/validate.py` and friends)

The consuming repo provides:

- A thin GitHub Actions workflow that invokes the orchestrator
- The `ANTHROPIC_API_KEY` secret
- Optional repo-specific agents and standards

The full design is in `docs/product/orchestrator/`. Start with
[`docs/product/orchestrator/README.md`](docs/product/orchestrator/README.md).

---

## Install in a consuming repo

> **Security notice:** Do **not** install this pipeline on a public
> repository where untrusted users can open issues. The `coder` agent
> runs with `Bash(*)` access and has `ANTHROPIC_API_KEY`,
> `GITHUB_TOKEN`, and `AI_AGILE_BOT_TOKEN` in its environment. It
> processes issue bodies that any GitHub user can write. This
> combination is safe for private repos with trusted contributors only.

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

### 2. Run `get_started.py --seed`

```bash
python ai-coding-standards2/get_started.py --seed
```

This drops a single file — `orchestrator.yml` — into `.github/workflows/`
and adds `.gitignore` entries. That is all you need to commit locally.
The workflow itself handles all remaining setup on a Linux runner (symlinks,
slash commands, standards, remaining workflows).

### 3. Commit and push

```bash
git add .gitmodules ai-coding-standards2 \
        .github/workflows/orchestrator.yml \
        .gitignore
git commit -m "Add ai-coding-standards2 submodule"
git push
```

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
> [`docs/product/orchestrator/09-human-interaction.md`](docs/product/orchestrator/09-human-interaction.md#4-agent-identity)
> for the full rationale and the planned migration path to a GitHub
> App.

### 5. Run the first-time setup

Go to: **Actions → Pipeline Orchestrator → Run workflow → ✓ First-time setup → Run**.

The workflow checks out the repo with its submodule on a Linux runner, runs
`get_started.py --force`, creates the `.claude/agents` symlink, copies slash
commands and standards, drops the remaining workflow files (`sync-claude.yml`,
`bootstrap-labels.yml`, `label-cleanup.yml`), and commits everything.

After it completes, open an issue with a problem statement and acceptance
criteria. The workflow fires on `issues.opened`; expect labels
`01_product_docs/issue-classifier:wip` → `:complete`, plus a classification
comment from the agent.

If the issue is missing required fields, you'll see
`01_product_docs/issue-classifier:blocked` and a corrective comment instead.

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
git add .github/workflows/
git commit -m "Refresh ai-coding-standards2 wrapper files"
```

`.claude/agents`, `.claude/commands/`, and `standards/` are managed by the
daily `sync-claude.yml` workflow and should not be committed manually.

Look at the submodule's CHANGELOG (when one exists) or the diff
between tags to know whether re-running is needed. If neither the
workflow nor any slash command changed, no re-run is required.

---

## Repo layout

```
.
├── README.md                                # this file
├── get_started.py                           # one-shot wiring script for consuming repos
├── docs/product/orchestrator/               # full design + roadmap
│   ├── README.md                            # reading order
│   ├── 01-vision.md ... 16-onboarding.md
│   └── glossary.md
├── .github/
│   ├── scripts/status.sh                    # label transitions helper
│   └── workflows/                           # this repo's own CI (does not run from a consuming repo)
│       ├── orchestrator.yml                 # all phases, contents:write
│       └── validate-pipeline.yml
├── .claude/
│   └── agents/                              # agent prompts, one subdir per phase
│       ├── 00_ondemand/                     # human-triggered agents (codebase-reviewer, standards-migrator)
│       ├── 01_product_docs/
│       │   └── issue-classifier.md
│       ├── 02_design/
│       ├── 03_execute/
│       ├── 04_evaluate/
│       ├── 05_continuous/
│       └── _templates/agent-template.md     # template for new agents
└── pipeline/
    ├── pipeline.json                        # the agent dependency graph (source of truth)
    ├── pipeline_orchestrator.py             # the deterministic Python orchestrator
    ├── statuses.json                        # canonical status definitions
    ├── validate.py                          # pipeline.json validator
    ├── generators/                          # doc generators (generate_phase_mermaid.py, …)
    └── schemas/pipeline.schema.json
```

The numeric prefixes on the per-phase agent directories (`01_…` →
`05_…`, plus `00_ondemand` for human-triggered agents) make `ls` show
phases in lifecycle order. Agent names in `pipeline.json` and on labels
carry the same prefix:

```
01_product_docs/issue-classifier
02_design/architect
03_execute/coder
04_evaluate/retrospective-writer
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

- [`docs/product/orchestrator/README.md`](docs/product/orchestrator/README.md) — the full design index
- [`docs/product/orchestrator/10-roadmap.md`](docs/product/orchestrator/10-roadmap.md) — MVP scope and rollout phases
- [`docs/product/orchestrator/11-orchestrator.md`](docs/product/orchestrator/11-orchestrator.md) — orchestrator technical design
- [`docs/product/orchestrator/12-agent-spec.md`](docs/product/orchestrator/12-agent-spec.md) — agent prompt-file spec
- [`docs/product/orchestrator/16-onboarding.md`](docs/product/orchestrator/16-onboarding.md) — onboarding a consuming repo
