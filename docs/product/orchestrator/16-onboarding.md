# Onboarding — Adding ai-coding-standards2 to a Consuming Repo

`get_started.py` wires the `ai-coding-standards2` submodule into a consuming
repository. It handles cross-platform differences (Windows vs Linux) and sets
up a daily sync workflow so the consuming repo stays in sync with the submodule
automatically.

---

## Modes

`get_started.py` is **one script that is run twice during onboarding**, and the
run type decides how much work it does. **There is no default mode** — you must
pass one of `--seed` or `--full` (`--force` is an overwrite modifier, not a
mode); running it with no run type is an
error. This is the single most common source of onboarding confusion, so read
this first.

| Run | Command | What it installs | Who runs it |
|---|---|---|---|
| **Seed** (step 1) | `get_started.py --seed` | The **two seed workflows** (`ai_orchestrator.yml` + `ai_emergency_stop.yml`), the root-level `CLAUDE.md` link, and `.gitignore` entries. Nothing else. | A developer, locally |
| **Full** (step 2) | `get_started.py --full --force` | **Everything** — all workflows, the whole-`.claude` symlink, the `standards` symlink, the local `adrs/` folder, requirements, the root-level `CLAUDE.md` link. | The Onboard job, on a Linux runner |

Running `get_started.py` with no run type prints an error listing the choices
and exits without touching the consuming repo — it never guesses a mode.

The two runs are two steps of the same flow: seed drops the two seed workflows
(ai_orchestrator.yml, which GitHub needs to run the Onboard job, plus the
emergency-stop kill switch); the Onboard job then re-runs the script in full
mode to lay down (and commit) the rest of the non-workflow files.

In code these are the `run_seed()` and `run_full()` functions in
`get_started.py`; the module docstring lists exactly what each installs.

### `--seed` (recommended for new installs)

Drops the two seed workflows — `ai_orchestrator.yml` and
`ai_emergency_stop.yml` (the operator's kill switch) — into the consuming
repo's `.github/workflows/`, links the root-level `CLAUDE.md` to
`.claude/CLAUDE.md` (see below), and adds `.gitignore` entries. The developer
commits those and pushes. The orchestrator workflow's built-in setup job then
does the rest on a Linux runner (see Bootstrap flow below). Seed mode
deliberately installs almost nothing else — ai_orchestrator.yml is enough to
bootstrap step 2, and the emergency stop ships alongside it so a runaway
pipeline can be halted from the very first commit (it reads nothing from the
submodule, so it works before the full wiring exists).

`CLAUDE.md` is a relative symlink (a plain byte-copy on Windows, which has no
unprivileged symlinks) to `.claude/CLAUDE.md` — the baseline behavioral
guidelines and repo-navigation notes that ship with the submodule. Claude
Code's project-memory auto-load and `coder.md`'s own spec-reading step both
look for `CLAUDE.md` at the repo root, not inside `.claude/`, so this
root-level link is what actually makes it discoverable. The symlink's target
doesn't need to exist yet at seed time — it starts resolving once the Onboard
job wires up the rest of `.claude/` — and a project's own pre-existing,
hand-authored `CLAUDE.md` is never overwritten without `--force`.

```bash
python ai-coding-standards2/get_started.py --seed
```

### Full run (`--full`)

Requested explicitly with `--full` — there is no bare default that does this.
Add `--force` to overwrite existing files. This is what the Onboard job runs on
a Linux runner (as `--full --force`), and what you would run locally with
`--full` if you skip the seed bootstrap:

| Step | What happens |
|---|---|
| Verify location | Confirms the script is running from inside a submodule of a consuming repo |
| Install workflows | Copies orchestrator and sync workflows into `.github/workflows/`, inserting a scoped `git submodule update --init -- {name}` step after checkout steps (only the ai-coding-standards2 submodule, never any other submodule the consuming repo may have registered) |
| Install standards | On Linux/macOS: creates a single directory symlink `standards → submodule/standards`. On Windows: copies the tree. Standards are framework-owned and read verbatim |
| Install ADRs | Seeds a project-owned `adrs/adrs.json` (once, never overwritten). ADRs live in their own local folder — outside the symlinked `standards/` — so `standards/` can be a whole-folder symlink |
| Install Claude setup | On Linux/macOS: creates a single directory symlink `.claude → submodule/.claude`, so the consuming repo inherits its ENTIRE Claude Code setup (agents, slash commands, `AGENTS.md`, `settings.json`) from the submodule. On Windows: copies the tree. The parent keeps no Claude config of its own. **The run fails** if the consuming repo already has its own real `.claude` directory (it will not be silently deleted) — back it up and remove it, or set `AI_AGILE_REPLACE_CLAUDE=1` to replace it deliberately |
| Link CLAUDE.md | Links the root-level `CLAUDE.md` to `.claude/CLAUDE.md` (a byte-copy on Windows). Also runs during `--seed`, so this step is a no-op here for a repo onboarded that way; it exists here too for a developer who runs `--full` directly. Never overwrites a project's own pre-existing `CLAUDE.md` without `--force` |
| Add .gitignore entries | Gitignores the whole-folder symlinks (`.claude`, `standards`, `CLAUDE.md`) so they are not committed as normal files; the setup job force-commits the symlink blobs. The `adrs/` folder is NOT gitignored — it stays committed |
| Untrack managed paths | Removes previously-tracked managed paths from the git index (`git rm --cached`) — migration from old installs |
| Print follow-up | Prints the checklist of manual steps needed to complete setup |

Use `--force` to overwrite existing files; `--dry-run` to preview without writing.

Full mode is also how the orchestrator's built-in setup (Onboard) job calls this
script — it runs `get_started.py --full --force` on a Linux runner to lay down
the managed paths.

---

## Platform behaviour: Linux vs Windows

| Aspect | Linux / macOS | Windows |
|---|---|---|
| `.claude` | Whole-folder directory symlink into the submodule — committed by the setup job as a tiny git blob; gitignored as a normal path | Full copy of the tree — gitignored, committed by the setup job |
| `standards` | Whole-folder directory symlink into the submodule — committed by the setup job; gitignored as a normal path | Full copy of the tree — gitignored, committed by the setup job |
| `adrs/` | Real local folder, committed normally (never symlinked, never overwritten) | Real local folder, committed normally |
| Bootstrap path | `--seed` commit → trigger setup job | `--seed` commit → trigger setup job |

### Why the split?

Creating directory symlinks on Windows requires elevated privileges that most
developers and VS builds do not have. Committing the symlink blob from a Linux
runner means developers who clone the consuming repo on any platform inherit the
framework's Claude setup and standards without running `get_started.py` again.
On Linux the symlink resolves live to the submodule's content, so there is no
drift to repair and no sync workflow.

> **Local clones must init the submodule.** The `.claude` and `standards`
> symlinks point **into** the submodule, so they only resolve when the submodule
> is checked out. A developer who clones the parent repo without the submodule
> will see dangling `.claude` / `standards` links and **no agents in Claude
> Code's `/agents` view** until they run `git submodule update --init` (or cloned
> with `git clone --recurse-submodules`). The local `adrs/` folder is a real
> folder and works without the submodule. CI is unaffected — the orchestrator
> reads the framework straight from the submodule and every workflow checkout
> inits the ai-coding-standards2 submodule by name (`git submodule update
> --init -- ai-coding-standards2`), never any other submodule the consuming
> repo may have registered.

---

## Bootstrap flow (all platforms)

The recommended path is identical on Windows, macOS, and Linux because the
heavy lifting happens on a GitHub-hosted Linux runner, not locally.

**Step 1 — Local seed commit**

Run `get_started.py --seed`. It writes the two seed workflows
(`ai_orchestrator.yml` + `ai_emergency_stop.yml`) and updates `.gitignore`,
then exits.

```bash
python ai-coding-standards2/get_started.py --seed
git add .gitmodules ai-coding-standards2 \
        .github/workflows/ai_orchestrator.yml \
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

Go to: **Actions → AI - Orchestrator → Run workflow → tick Onboard → Run**.

The job checks out the repo with its submodule on a Linux runner, runs
`get_started.py --full --force`, creates the whole-folder `.claude` and `standards`
symlinks, seeds the local `adrs/` folder, bootstraps the pipeline labels, and
commits the **non-workflow** files directly to the default branch (or to an
`ai-standards-setup` branch if branch protection rules block a direct push — in
that case, open a PR from that branch). It never pushes a `.github/workflows/*`
file — the two pipeline workflows were committed in the seed step — so the
Onboard token needs no `workflow` scope.

The `ai_emergency_stop.yml` workflow is the operator kill switch:
emergency-stop writes a `.pipeline-stop` marker (which the orchestrator checks
before invoking any agent) and cancels in-flight runs. There is no restart
workflow — restarting is just clearing the committed marker (`git rm
.pipeline-stop` and push; `--clear-stop` only removes the local file and must
still be committed and pushed to resume the hosted pipeline), which an owner can run at any
time; the stop workflow's run summary prints these instructions. Unlike the
other installed workflows, the emergency stop is copied **without** the
submodule-init step injected — it reads nothing from the submodule, so it must
not depend on a submodule fetch to run when you need to stop the pipeline.

After the job completes, open a test issue with a problem statement and
acceptance criteria to confirm the pipeline is live.

---

## Keeping in sync — no sync workflow

There is no daily sync workflow. On a Linux runner `.claude` and `standards` are
whole-folder symlinks into the submodule, so they always resolve to the
submodule's current content — there is no drift between a committed copy and the
submodule to reconcile.

To take a new framework version, **bump the submodule pointer** (a normal commit
in the consuming repo); the symlinks reflect the new content automatically. If a
consuming repo ever needs its symlinks re-laid or new-agent labels created after
such a bump, re-run the Onboard job (`get_started.py --full --force` + label
bootstrap).

---

## Epic auto-close — no separate workflow needed

Epic completion is handled by the orchestrator's existing scheduled sweep —
no extra workflow file is installed for this behaviour.

On each sweep tick, the orchestrator checks every open issue that carries
the `epic` label. If all `parent-issue:{N}`-labeled siblings of that epic
are closed, the orchestrator re-processes the parent as a work item so it
can advance through its own next eligible pipeline step. Today that step is
closure with a completion comment (replicating what the former
`close-epic-on-children-complete.yml` workflow did). The mechanism is
intentionally general: future pipeline steps added to epics (such as a
whole-feature review) plug in without revisiting this check.

**Accepted latency trade-off.** Because the check runs on the periodic sweep
rather than on an `issues.closed` event, there is an inherent delay of up to
one sweep interval (currently ~30 minutes between weekday ticks, 6 AM–8 PM)
between the last sub-issue being closed and the parent epic being processed.
This is an explicit, accepted trade-off in exchange for a simpler mechanism
with no dependency on catching a specific webhook event.

`close-epic-on-children-complete.yml` has been retired; it is neither
installed by `get_started.py` nor needed by consuming repos. If a consuming
repo has this workflow committed from an older install, it can be removed:

```bash
git rm .github/workflows/close-epic-on-children-complete.yml
git commit -m "chore: remove retired epic-close workflow (handled by orchestrator sweep)"
git push
```

---

## Managed paths and .gitignore

`get_started.py` adds the following entries to the consuming repo's `.gitignore`:

```
.claude
standards
```

These are the whole-folder symlinks; gitignoring them keeps them from being
committed as normal files (and stops Windows copies being committed by hand).
The setup (Onboard) job uses `git add -f` to override `.gitignore` when
committing the symlink blobs on behalf of the bot. The project-owned
`adrs/` folder is **not** gitignored — it is committed normally.

---

## Migration from tracked copies

Older installs may have `.claude/agents/`, `.claude/commands/`,
`.claude/settings.local.json`, and per-file `standards/*.json` tracked in git as
committed copies. Running `get_started.py` (any version with
`untrack_managed_paths`) will call `git rm --cached -r` on each tracked managed
path — including the whole `.claude` and `standards` paths — to remove them from
the index without deleting local files.

**Upgrading from a version with the retired workflows.** A repo onboarded before
the workflow cleanup has `ai_sync_claude.yml`, `ai_bootstrap_labels.yml`, and
`ai_label_cleanup.yml` committed in its own `.github/workflows/`. `get_started`
does not delete stale workflow files, and those old crons keep firing (the old
sync workflow will even re-commit removed files), so delete them by hand once:

```bash
git rm .github/workflows/ai_sync_claude.yml \
       .github/workflows/ai_bootstrap_labels.yml \
       .github/workflows/ai_label_cleanup.yml
git commit -m "chore: remove retired AI Agile workflows"
git push
```

Label creation now runs in the Onboard job, and the symlinks resolve live into
the submodule, so nothing replaces those workflows.

---

## How paths resolve

The orchestrator resolves two kinds of path, from two different roots:

| Root | How it is derived | Used for |
|---|---|---|
| `SUBMODULE_ROOT` | From `__file__` (the location of `pipeline_orchestrator.py`), **never** from an env var | The framework's own files: agent prompts (`.claude/agents/*.md`), agent scripts, `status.sh`, `AGENTS.md`, `pipeline.json` |
| `AI_AGILE_ROOT` env var | The consuming repo root (set to `${{ github.workspace }}` by the installed `ai_orchestrator.yml`; falls back to `SUBMODULE_ROOT` when unset) | Repo-root data and runtime markers: the `standards/` symlink, the local `adrs/adrs.json`, the `.pipeline-stop` / `.pipeline-pause` markers, and the value passed to each agent subprocess |

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

On the interactive side, the parent repo's **entire** `.claude` folder is a
symlink **into** this submodule, so Claude Code's `/agents` view (and every
slash command and setting) shows exactly this submodule's set, and there is no
local `.claude` for the parent to diverge into. The parent keeps no Claude
config of its own. Together these make the framework a single, authoritative
definition of the agentic SDLC: drop the submodule in, and the parent inherits
the whole pipeline, agents, and gates without forking the framework locally.
(Standards are defined centrally here too — the framework owns them and a
project does not add its own. The only locally-owned artifact is the project's
ADRs in `adrs/adrs.json`, seeded once and never overwritten.)

To change an agent, change it here — open a PR against this repo, or pin the
parent's submodule to a fork you control. Both routes keep the parent repo's
copy of the framework identical to a known, reviewed commit.
