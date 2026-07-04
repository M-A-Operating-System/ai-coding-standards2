# Onboarding — Adding ai-coding-standards2 to a Consuming Repo

`get_started.py` wires the `ai-coding-standards2` submodule into a consuming
repository. It handles cross-platform differences (Windows vs Linux) and sets
up a daily sync workflow so the consuming repo stays in sync with the submodule
automatically.

---

## Modes

`get_started.py` is **one script that is run twice during onboarding**, and
the `--seed` flag decides how much work it does. This is the single most
common source of onboarding confusion, so read this first.

| Run | Command | What it installs | Who runs it |
|---|---|---|---|
| **Seed** (step 1) | `get_started.py --seed` | **Only** `orchestrator.yml` + `.gitignore` entries. Nothing else. | A developer, locally |
| **Full** (step 2) | `get_started.py --force` | **Everything** — all workflows, the agents symlink, slash commands, standards, settings, requirements. | The Onboard job, on a Linux runner |

The two runs are two steps of the same flow: seed drops the one workflow file
GitHub needs to run the Onboard job; the Onboard job then re-runs the script
in full mode to lay down (and commit) the rest. The daily `sync-claude.yml`
workflow also runs the full mode (`--force`) to repair drift.

In code these are the `run_seed()` and `run_full()` functions in
`get_started.py`; the module docstring lists exactly what each installs.

### `--seed` (recommended for new installs)

Drops `orchestrator.yml` into the consuming repo's `.github/workflows/` and
adds `.gitignore` entries. The developer commits those two things and pushes.
The orchestrator workflow's built-in setup job then does the rest on a Linux
runner (see Bootstrap flow below). Seed mode deliberately installs almost
nothing — it is only enough to bootstrap step 2.

```bash
python ai-coding-standards2/get_started.py --seed
```

### Full run (default / `--force`)

Running without `--seed` performs all wiring. This is what the Onboard job
runs on a Linux runner (and what you would run locally if you skip the seed
bootstrap):

| Step | What happens |
|---|---|
| Verify location | Confirms the script is running from inside a submodule of a consuming repo |
| Install agents | On Linux/macOS: creates a relative directory symlink `.claude/agents → submodule/.claude/agents/`. On Windows: copies agent files individually |
| Install commands | Copies slash commands from the submodule into `.claude/commands/`, rewriting submodule-relative paths |
| Install workflows | Copies orchestrator and sync workflows into `.github/workflows/`, inserting `submodules: true` into checkout steps |
| Install standards | Copies `standards/*.json` (excluding schema files) into the consuming repo's `standards/` |
| Add .gitignore entries | Marks copied/symlinked paths as gitignored to prevent accidental commits on Windows |
| Untrack managed paths | Removes previously-tracked managed paths from the git index (`git rm --cached`) — migration from old installs |
| Write settings | Creates `.claude/settings.local.json` with `AI_AGILE_ROOT=.` (consuming repo root) so a manually-run orchestrator resolves repo-root data (`standards/`, control markers) from the repo root. Agent prompts always come from the submodule, not this path |
| Print follow-up | Prints the checklist of manual steps needed to complete setup |

Use `--force` to overwrite existing files; `--dry-run` to preview without writing.

The `--force` flag is also how the orchestrator's built-in setup job and the daily
`sync-claude.yml` workflow call this script — they run `get_started.py --force`
on a Linux runner to keep managed paths in sync.

---

## Platform behaviour: Linux vs Windows

| Aspect | Linux / macOS | Windows |
|---|---|---|
| `.claude/agents` | Relative directory symlink — committed by the setup job as a tiny git blob | Individual file copies — gitignored |
| `.claude/commands/` | Gitignored — committed by the setup job and kept current by sync-claude.yml | Gitignored — committed by the setup job and kept current by sync-claude.yml |
| `standards/` | Base files gitignored (`adrs.json` stays committed) | Base files gitignored (`adrs.json` stays committed) |
| Bootstrap path | `--seed` commit → trigger setup job | `--seed` commit → trigger setup job |

### Why the split?

Creating directory symlinks on Windows requires elevated privileges that most
developers and VS builds do not have. Committing the symlink blob from a Linux
runner means developers who clone the consuming repo on any platform get agent
visibility in Claude Code without running `get_started.py` again. The daily
sync-claude.yml workflow rebuilds the symlink on every Linux runner run.

> **Local clones must init the submodule.** The `.claude/agents` symlink
> points **into** the submodule, so it only resolves when the submodule is
> checked out. A developer who clones the parent repo without the submodule
> will see a dangling `.claude/agents` link and **no agents in Claude Code's
> `/agents` view** until they run `git submodule update --init` (or cloned
> with `git clone --recurse-submodules`). Copied slash commands still work in
> that state; only the symlinked agents depend on the submodule being present.
> CI is unaffected — the orchestrator reads agents straight from the submodule
> and every workflow checkout uses `submodules: true`.

---

## Bootstrap flow (all platforms)

The recommended path is identical on Windows, macOS, and Linux because the
heavy lifting happens on a GitHub-hosted Linux runner, not locally.

**Step 1 — Local seed commit**

Run `get_started.py --seed`. It writes one file (`orchestrator.yml`) and
updates `.gitignore`, then exits.

```bash
python ai-coding-standards2/get_started.py --seed
git add .gitmodules ai-coding-standards2 \
        .github/workflows/orchestrator.yml \
        .gitignore
git commit -m "Add ai-coding-standards2 submodule"
git push
```

**Step 2 — Add secrets**

In the consuming repo: Settings → Secrets and variables → Actions → New repository secret.

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `AI_AGILE_BOT_TOKEN` | A GitHub PAT for the bot account (see README.md §4) |

**Step 3 — Trigger the setup job**

Go to: **Actions → Pipeline Orchestrator → Run workflow → tick Onboard → Run**.

The job checks out the repo with its submodule on a Linux runner, runs
`get_started.py --force`, creates the `.claude/agents` symlink, copies slash
commands and standards, drops the remaining workflow files (`sync-claude.yml`,
`bootstrap-labels.yml`, `label-cleanup.yml`, `pipeline-emergency-stop.yml`,
`pipeline-restart.yml`), and commits everything directly
to the default branch (or to an `ai-standards-setup` branch if branch
protection rules block a direct push — in that case, open a PR from that
branch).

The `pipeline-emergency-stop.yml` / `pipeline-restart.yml` pair is the
operator kill switch: emergency-stop writes a `.pipeline-stop` marker (which
the orchestrator checks before invoking any agent) and cancels in-flight
runs; restart clears the marker and resumes. Unlike the other installed
workflows, these two are copied **without** `submodules: true` injected —
they read nothing from the submodule, so they must not depend on a submodule
fetch to run when you need to stop the pipeline.

After the job completes, open a test issue with a problem statement and
acceptance criteria to confirm the pipeline is live.

---

## sync-claude.yml — daily sync workflow

The `sync-claude.yml` workflow (installed by the setup job into the consuming
repo's `.github/workflows/`) runs daily at 06:00 UTC and on demand:

1. Checks out the consuming repo **with submodules**
2. Runs `python ai-coding-standards2/get_started.py --force`
3. Force-stages all managed paths with `git add -f` (needed because managed
   paths are listed in `.gitignore` to protect Windows developers)
4. Commits and pushes if anything changed

This keeps the consuming repo in sync with submodule updates automatically and
recovers from any drift between the committed symlink blob and the submodule.
It is not used for initial onboarding — the setup job in `orchestrator.yml`
handles first-time wiring.

The workflow uses `AI_AGILE_BOT_TOKEN` (falls back to `GITHUB_TOKEN`) so the
commit is attributed to the bot account and branch-protection rules that block
`GITHUB_TOKEN` pushes are bypassed.

---

## Managed paths and .gitignore

`get_started.py` adds the following entries to the consuming repo's `.gitignore`:

```
.claude/agents
.claude/commands/
.claude/settings.local.json
standards/<file>.json   # one entry per standards file
```

These entries prevent Windows developers from accidentally committing local file
copies. The `sync-claude.yml` workflow uses `git add -f` to override `.gitignore`
when committing the Linux-built symlink and copied files on behalf of the bot.

---

## Migration from tracked copies

Older installs may have `.claude/agents/`, `.claude/commands/`, and `standards/`
tracked in git as committed copies. Running `get_started.py` (any version
with `untrack_managed_paths`) will call `git rm --cached -r` on each tracked
managed path to remove it from the index without deleting local files.

---

## How paths resolve

The orchestrator resolves two kinds of path, from two different roots:

| Root | How it is derived | Used for |
|---|---|---|
| `SUBMODULE_ROOT` | From `__file__` (the location of `pipeline_orchestrator.py`), **never** from an env var | The framework's own files: agent prompts (`.claude/agents/*.md`), agent scripts, `status.sh`, `AGENTS.md`, `pipeline.json` |
| `AI_AGILE_ROOT` env var | The consuming repo root (set to `${{ github.workspace }}` by the installed `orchestrator.yml`; falls back to `SUBMODULE_ROOT` when unset) | Repo-root data and runtime markers: `standards/`, the `.pipeline-stop` / `.pipeline-pause` markers, and the value passed to each agent subprocess |

The split is what makes the framework self-contained: because agent
prompts, scripts, and `status.sh` always resolve from `SUBMODULE_ROOT`, the
pipeline runs identically whether this repo is checked out at the consuming
repo's root (non-submodule mode) or as a submodule at
`<consuming-repo>/ai-coding-standards2/`. `AI_AGILE_ROOT` only tells the
running agents where the parent repo's `standards/` and control markers
live; it never changes which agents exist or where their definitions come
from.

The orchestrator passes both `AI_AGILE_ROOT` and the resolved
`STATUS_SH` to every agent subprocess via env. Agent prompts
reference `$STATUS_SH` rather than a hardcoded path, so they work
identically in both layouts.

---

## This submodule is the sole source of agents

The agent set is defined **only** by this submodule. The orchestrator
resolves every agent prompt from the submodule itself — see
`pipeline_orchestrator.py`, where `SUBMODULE_ROOT` is derived from
`__file__` (never from `AI_AGILE_ROOT`) and agent prompts, agent scripts,
and `status.sh` are all read from under it. There is no merge with a
consuming-repo agent directory: a `.claude/agents/*.md` file placed in the
parent repo is never consulted by the pipeline.

On the interactive side, the parent repo's `.claude/agents` is a symlink
**into** this submodule, so Claude Code's `/agents` view shows exactly this
submodule's set and there is no local directory for the parent to diverge
into. Together these make the framework a single, authoritative definition
of the agentic SDLC: drop the submodule in, and the parent inherits the
whole pipeline, agents, and gates without forking the framework locally.
(Standards are the one two-tier piece — the base set comes from here and a
project may add its own standards files on top; agents and pipeline stages
are not extensible this way.)

To change an agent, change it here — open a PR against this repo, or pin the
parent's submodule to a fork you control. Both routes keep the parent repo's
copy of the framework identical to a known, reviewed commit.
