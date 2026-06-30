# Onboarding — Adding ai-coding-standards2 to a Consuming Repo

`get_started.py` wires the `ai-coding-standards2` submodule into a consuming
repository. It handles cross-platform differences (Windows vs Linux) and sets
up a daily sync workflow so the consuming repo stays in sync with the submodule
automatically.

---

## Modes

### `--seed` (recommended for new installs)

Drops only `orchestrator.yml` into the consuming repo's `.github/workflows/`
and adds `.gitignore` entries. The developer commits those two things and pushes.
The orchestrator workflow then does the rest on a Linux runner (see below).

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
| `.claude/agents` | Relative directory symlink — committed via sync-claude.yml as a tiny git blob | Individual file copies — gitignored |
| `.claude/commands/` | Gitignored — committed via sync-claude.yml | Gitignored — committed via sync-claude.yml |
| `standards/` | Base files gitignored (`adrs.json` stays committed) | Base files gitignored (`adrs.json` stays committed) |
| Bootstrap path | Two-step: seed commit on Linux, then trigger sync-claude.yml | Two-step: seed commit on Windows, then trigger sync-claude.yml |

### Why the split?

Creating directory symlinks on Windows requires elevated privileges that most
developers and VS builds do not have. Committing the symlink blob on Linux means
developers who clone on any platform get agent visibility in Claude Code without
running `get_started.py` again. The sync workflow rebuilds the symlink on every
Linux runner run.

---

## Windows bootstrap (two-step process)

When a developer first adds the submodule on a Windows machine (e.g. via Visual
Studio), the full environment cannot be built locally. The recommended workflow:

**Step 1 — Seed commit from Windows**

Run `get_started.py` on Windows. It will:
- Copy workflow files into `.github/workflows/` (these are **not** gitignored)
- Add `.gitignore` entries
- Create local copies of agents, commands, and standards (all gitignored)

Commit only the seed files:
```
git add .gitmodules ai-coding-standards2 \
        .github/workflows/ \
        .gitignore
git commit -m "chore: add ai-coding-standards2 submodule and seed workflows"
git push
```

**Step 2 — Trigger sync workflow (Linux runner)**

Go to Actions → **Sync AI Agile .claude directory** → Run workflow.

The `sync-claude.yml` workflow runs `get_started.py --force` on a Linux runner,
which creates the directory symlink for `.claude/agents` and force-stages all
managed paths. It then commits and pushes the result. After this run, the repo
has the full environment and the daily sync keeps it up to date.

---

## sync-claude.yml — daily sync workflow

The `sync-claude.yml` workflow (installed by `get_started.py` into the consuming
repo's `.github/workflows/`) runs daily at 06:00 UTC and on demand:

1. Checks out the consuming repo **with submodules**
2. Runs `python ai-coding-standards2/get_started.py --force`
3. Force-stages all managed paths with `git add -f` (needed because managed
   paths are listed in `.gitignore` to protect Windows developers)
4. Commits and pushes if anything changed

This ensures the consuming repo tracks submodule updates automatically and
recovers from any drift between the committed symlink blob and the submodule.

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
