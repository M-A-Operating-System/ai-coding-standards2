# Onboarding — Adding ai-coding-standards2 to a Consuming Repo

`get_started.py` wires the `ai-coding-standards2` submodule into a consuming
repository. It handles cross-platform differences (Windows vs Linux) and sets
up a daily sync workflow so the consuming repo stays in sync with the submodule
automatically.

---

## Modes

### `--seed` (recommended for new installs)

Drops `orchestrator.yml` into the consuming repo's `.github/workflows/` and
adds `.gitignore` entries. The developer commits those two things and pushes.
The orchestrator workflow's built-in setup job then does the rest on a Linux
runner (see Bootstrap flow below).

```bash
python ai-coding-standards2/get_started.py --seed
```

### Full run (default)

Running without `--seed` performs all wiring locally:

| Step | What happens |
|---|---|
| Verify location | Confirms the script is running from inside a submodule of a consuming repo |
| Install agents | On Linux/macOS: creates a relative directory symlink `.claude/agents → submodule/.claude/agents/`. On Windows: copies agent files individually |
| Install commands | Copies slash commands from the submodule into `.claude/commands/`, rewriting submodule-relative paths |
| Install workflows | Copies orchestrator and sync workflows into `.github/workflows/`, inserting `submodules: true` into checkout steps |
| Install standards | Copies `standards/*.json` (excluding schema files) into the consuming repo's `standards/` |
| Add .gitignore entries | Marks copied/symlinked paths as gitignored to prevent accidental commits on Windows |
| Untrack managed paths | Removes previously-tracked managed paths from the git index (`git rm --cached`) — migration from old installs |
| Write settings | Creates `.claude/settings.local.json` with `AI_AGILE_ROOT=.` (consuming repo root) so agents resolve `standards/` and `.claude/agents/` from the repo root |
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
`bootstrap-labels.yml`, `label-cleanup.yml`), and commits everything directly
to the default branch (or to an `ai-standards-setup` branch if branch
protection rules block a direct push — in that case, open a PR from that
branch).

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
workflow env (the installed `orchestrator.yml` does this) so the
orchestrator finds `status.sh` and agent prompts under the submodule,
not under the consuming repo's root.

The orchestrator passes both `AI_AGILE_ROOT` and the resolved
`STATUS_SH` to every agent subprocess via env. Agent prompts
reference `$STATUS_SH` rather than a hardcoded path, so they work
identically in both layouts.

---

## Adding repo-specific agents (planned)

Out of MVP scope. Today every agent prompt lives in the submodule.
Once the submodule is stable, the design supports the consuming repo
adding its own agents at `<consuming-repo>/.claude/agents/{agent}.md`,
which override (or extend) the submodule's set. This requires a small
orchestrator change to consult two agent directories. Tracked in the
[roadmap](10-roadmap.md).
