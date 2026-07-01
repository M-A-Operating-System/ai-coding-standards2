#!/usr/bin/env python3
"""
get_started.py -- wire ai-coding-standards2 into a consuming repo.

This script is run ONCE after `git submodule add ...` has placed this
repo at `<consuming-repo>/ai-coding-standards2/`. It:

  1. Verifies it's running from inside the submodule of a consuming repo.
  2. Copies the agent prompts from this submodule's .claude/agents/ into
     the consuming repo's .claude/agents/, preserving subdirectory
     structure. Agents use $AI_AGILE_ROOT for all paths so no rewriting
     is needed.
  3. Creates the consuming repo's `.claude/commands/` directory and
     copies the slash commands from this submodule into it, rewriting
     any submodule-relative paths so they resolve from the consuming
     repo's root.
  4. Drops the orchestrator workflows into the consuming repo's
     `.github/workflows/` directory. (GitHub Actions cannot pick up
     workflows from submodules; the consuming repo's own workflow dir
     is the only place they can run from.)
  5. Drops the daily .claude sync workflow into the consuming repo's
     `.github/workflows/sync-claude.yml`. This workflow re-runs this
     script with --force every day to prevent agent/command drift.
  6. Writes `.claude/settings.local.json` setting AI_AGILE_ROOT so
     anyone running the orchestrator manually from the consuming repo
     gets the right paths.
  7. Prints a short follow-up checklist (set ANTHROPIC_API_KEY,
     bootstrap labels, open a test issue).

Run from the consuming repo's root:

    python ai-coding-standards2/get_started.py

Re-run with --force after updating the submodule to pick up new agents,
commands, and workflow changes. The sync-claude.yml workflow does this
automatically every day.

Options:
    --seed       Minimal bootstrap: copy only orchestrator.yml + .gitignore.
                 Commit those two files, push, then run the workflow with the
                 "First-time setup" option to finish wiring on a Linux runner.
    --force      Overwrite existing files in the consuming repo
    --dry-run    Print what would be created/modified without writing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


SUBMODULE_ROOT = Path(__file__).resolve().parent
SUBMODULE_NAME = SUBMODULE_ROOT.name  # actual dir name, not hard-coded


# Path-rewrite rules applied to slash command markdown when copying
# from the submodule into the consuming repo's .claude/. Each rule is
# (pattern, replacement) in regex. The submodule paths get rewritten
# to the submodule-relative form so they resolve when a developer runs
# them from the consuming repo's root.
PATH_REWRITES = [
    # Bare ".github/scripts/status.sh" -> "ai-coding-standards2/.github/scripts/status.sh"
    # Negative lookbehind prevents double-prefixing already-submodule-qualified paths.
    (rf"(?<!{SUBMODULE_NAME}/)\.github/scripts/status\.sh", f"{SUBMODULE_NAME}/.github/scripts/status.sh"),
    # Bare ".github/scripts/migrate_labels.py" -> "ai-coding-standards2/.github/scripts/migrate_labels.py"
    (rf"(?<!{SUBMODULE_NAME}/)\.github/scripts/migrate_labels\.py", f"{SUBMODULE_NAME}/.github/scripts/migrate_labels.py"),
    # Bare ".claude/agents/..." -> "ai-coding-standards2/.claude/agents/..."
    (rf"(?<!{SUBMODULE_NAME}/)\.claude/agents/", f"{SUBMODULE_NAME}/.claude/agents/"),
    # Bare "pipeline/..." -> "ai-coding-standards2/pipeline/..."
    # Negative lookbehind prevents double-prefixing already-submodule-qualified paths.
    (rf"(?<!{SUBMODULE_NAME}/)pipeline/", f"{SUBMODULE_NAME}/pipeline/"),
    # Bare ".claude/agent-todo-standard.md" was retired (see 13-todos.md);
    # rewrite any lingering reference to point at the new doc.
    (
        r"\.claude/agent-todo-standard\.md",
        f"{SUBMODULE_NAME}/docs/product/agile/13-todos.md",
    ),
]


def find_consuming_repo_root() -> Path:
    """Return the consuming repo's root, or exit with a clear error.

    Uses `git rev-parse --show-superproject-working-tree` from inside
    the submodule. That command returns the path to the parent (super)
    repo when run inside a submodule, or empty when not.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-superproject-working-tree"],
            cwd=SUBMODULE_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        sys.exit(
            f"Could not run git from {SUBMODULE_ROOT}: {exc}\n"
            f"Is git installed and is this a git working tree?"
        )

    super_path = result.stdout.strip()
    if not super_path:
        sys.exit(
            f"This repo does not appear to be installed as a submodule.\n"
            f"  Run from inside a consuming repo where this repo is at\n"
            f"  <consuming-repo>/{SUBMODULE_NAME}/.\n"
            f"  Standalone (non-submodule) usage does not need get_started.py."
        )

    return Path(super_path).resolve()


def write_file(
    path: Path,
    content: str,
    force: bool,
    dry_run: bool,
) -> bool:
    """Create a file, honouring --force and --dry-run. Returns True if
    a change was (or would be) made."""
    if path.exists() and not force:
        print(f"  SKIP   {path}  (exists; pass --force to overwrite)")
        return False
    if dry_run:
        print(f"  WOULD  {path}  ({len(content)} bytes)")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  WROTE  {path}")
    return True


def rewrite_paths(text: str) -> str:
    """Apply PATH_REWRITES to slash-command body text."""
    out = text
    for pattern, replacement in PATH_REWRITES:
        out = re.sub(pattern, replacement, out)
    return out


def install_standards(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Copy standards/*.json from the submodule into the consuming repo.

    Seeds the consuming repo's standards/ folder with the pipeline's base
    standards. The consuming repo can add project-specific standards as
    additional files (e.g. standards/myapp.json) -- the sync never deletes
    files it didn't create.

    Convention: do not modify the base files directly; add new files for
    custom standards so the daily sync can safely overwrite the base set
    without destroying local additions.

    Special case -- adrs.json: the consuming repo owns its adrs.json as the
    place to record project ADRs. The sync never overwrites it so that project
    ADRs are not lost. On first install (file absent), a minimal project-owned
    adrs.json is created. Org ADRs are a separate concern; the submodule's
    adrs.json is the canonical source for those.

    Skips *.schema.json (pipeline infrastructure, not agent-loadable).
    Returns the number of files written.
    """
    src_dir = SUBMODULE_ROOT / "standards"
    dst_dir = consuming_root / "standards"

    if not src_dir.is_dir():
        print(f"  SKIP   standards  ({src_dir} missing)")
        return 0

    print(f"  Standards: {src_dir} -> {dst_dir}")
    written = 0
    for src in sorted(src_dir.glob("*.json")):
        if src.name.endswith(".schema.json"):
            continue

        dst = dst_dir / src.name

        if src.name == "adrs.json":
            # adrs.json is project-owned: only seed it when it does not yet
            # exist. Never overwrite -- project ADRs would be lost on every
            # daily sync.
            if dst.exists():
                print(f"  KEEP   {dst}  (project-owned; not overwritten by sync)")
                continue
            # First install: create a project-scoped empty ADRs file.
            project_adrs = (
                '{\n'
                f'  "$schema": "../{SUBMODULE_NAME}/pipeline/schemas/standards.schema.json",\n'
                '  "version": "1.0",\n'
                '  "scope": "project",\n'
                '  "description": "Approved project-level Architecture Decision Records.",\n'
                '  "adrs": []\n'
                '}\n'
            )
            if write_file(dst, project_adrs, force, dry_run):
                written += 1
            continue

        content = src.read_text(encoding="utf-8").replace(
            '"../pipeline/schemas/standards.schema.json"',
            f'"../{SUBMODULE_NAME}/pipeline/schemas/standards.schema.json"',
        )
        if write_file(dst, content, force, dry_run):
            written += 1
    return written


def install_agents(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Wire .claude/agents/ from the submodule into the consuming repo.

    On Linux/macOS: creates a directory symlink dst -> src so the agents
    directory is always in sync with the submodule without copying files.

    On Windows: falls back to verbatim file copies (directory symlinks
    require elevated privileges on Windows).

    IMPORTANT: The orchestrator ALWAYS reads agent prompts from the
    submodule (SUBMODULE_ROOT/.claude/agents/), never from these copies.
    The symlink / copies are provided solely for interactive Claude Code
    sessions (developers using /agents or viewing agent files locally).
    Editing the copies has no effect on pipeline execution. To customise
    an agent for the pipeline, pin the submodule to a fork or raise a PR
    upstream.

    Returns 1 (symlink created/updated) or the number of files written.
    """
    src_dir = SUBMODULE_ROOT / ".claude" / "agents"
    dst_dir = consuming_root / ".claude" / "agents"

    if not src_dir.is_dir():
        print(f"  SKIP   agents  ({src_dir} missing)")
        return 0

    print(f"  Agents: {src_dir} -> {dst_dir}")

    if sys.platform != "win32":
        return _install_agents_symlink(src_dir, dst_dir, force, dry_run)
    return _install_agents_copy(src_dir, dst_dir, force, dry_run)


def _install_agents_symlink(
    src_dir: Path,
    dst_dir: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Create a relative directory symlink dst_dir -> src_dir.

    Returns 1 if a symlink was (or would be) created/updated, 0 if skipped.
    """
    rel_target = os.path.relpath(src_dir, dst_dir.parent)

    if dst_dir.is_symlink():
        resolved = (dst_dir.parent / os.readlink(dst_dir)).resolve()
        if resolved == src_dir.resolve():
            print(f"  SKIP   {dst_dir}  (symlink already correct)")
            return 0
        if not force:
            print(f"  SKIP   {dst_dir}  (symlink exists pointing elsewhere; pass --force to update)")
            return 0
        if dry_run:
            print(f"  WOULD  {dst_dir} -> {rel_target}  (replace symlink)")
            return 1
        dst_dir.unlink()
    elif dst_dir.is_dir():
        if not force:
            print(f"  SKIP   {dst_dir}  (directory exists; pass --force to replace with symlink)")
            return 0
        if dry_run:
            print(f"  WOULD  {dst_dir} -> {rel_target}  (replace directory with symlink; contents will be removed)")
            return 1
        print(f"  WARNING  replacing {dst_dir} with symlink -- any files not in the submodule will be removed")
        shutil.rmtree(dst_dir)
    elif dst_dir.exists():
        print(f"  SKIP   {dst_dir}  (exists but is not a directory or symlink; skipping)")
        return 0
    elif dry_run:
        print(f"  WOULD  {dst_dir} -> {rel_target}")
        return 1

    dst_dir.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(rel_target, dst_dir)
    print(f"  LINKED {dst_dir} -> {rel_target}")
    return 1


def _install_agents_copy(
    src_dir: Path,
    dst_dir: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Verbatim-copy agent files from src_dir into dst_dir.

    Used on Windows where directory symlinks require elevated privileges.
    Returns the number of files written.
    """
    written = 0
    for src in sorted(src_dir.rglob("*.md")):
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        if write_file(dst, src.read_text(encoding="utf-8"), force, dry_run):
            written += 1

    # Remove stale agents that are no longer in the submodule.
    if dst_dir.is_dir():
        for dst in sorted(dst_dir.rglob("*.md")):
            rel = dst.relative_to(dst_dir)
            if not (src_dir / rel).exists():
                if dry_run:
                    print(f"  WOULD REMOVE {dst}  (no longer in submodule)")
                else:
                    dst.unlink()
                    print(f"  REMOVED {dst}  (no longer in submodule)")

    return written


def install_slash_commands(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Copy .claude/commands/ into the consuming repo with paths rewritten.
    Returns the number of files written."""
    src_dir = SUBMODULE_ROOT / ".claude" / "commands"
    dst_dir = consuming_root / ".claude" / "commands"

    if not src_dir.is_dir():
        print(f"  SKIP   slash commands  ({src_dir} missing)")
        return 0

    print(f"  Slash commands: {src_dir} -> {dst_dir}")
    written = 0
    for src in sorted(src_dir.glob("*.md")):
        dst = dst_dir / src.name
        original = src.read_text(encoding="utf-8")
        rewritten = rewrite_paths(original)
        if rewritten != original:
            print(f"    (rewriting paths in {src.name})")
        if write_file(dst, rewritten, force, dry_run):
            written += 1

    # Remove stale commands that are no longer in the submodule.
    if dst_dir.is_dir():
        for dst in sorted(dst_dir.glob("*.md")):
            if not (src_dir / dst.name).exists():
                if dry_run:
                    print(f"  WOULD REMOVE {dst}  (no longer in submodule)")
                else:
                    dst.unlink()
                    print(f"  REMOVED {dst}  (no longer in submodule)")

    return written


def _add_submodules_to_checkout(content: str) -> str:
    """Insert 'submodules: true' into every bare actions/checkout step.

    The standalone orchestrator workflows omit submodules: true because
    this repo IS the submodule. Consuming repos need it to check out the
    ai-coding-standards2 submodule at workflow runtime.

    Handles both named form ('- name: Checkout\\n  uses: ...') and
    shorthand form ('- uses: actions/checkout@...') in YAML steps.
    Already-expanded steps (with: block present) are left untouched --
    callers that add their own with: options (e.g. fetch-depth) must
    include submodules: true themselves.
    """
    # Named form: the uses: line sits one level deeper than the name: line.
    # Capture the indent of the uses: line to align with: correctly.
    content = re.sub(
        r"(- name: Checkout\n([ \t]+)uses: actions/checkout@[^\n]+\n)"
        r"(?![ \t]+with:)",
        r"\1\2with:\n\2  submodules: true\n",
        content,
    )
    # Shorthand form: "- uses: actions/checkout@..." with no name: line.
    # Capture the indent of the dash to derive the correct with: indent.
    content = re.sub(
        r"([ \t]+)(- uses: actions/checkout@[^\n]+\n)(?![ \t]+with:)",
        lambda m: (
            m.group(0)
            + m.group(1) + "  with:\n"
            + m.group(1) + "    submodules: true\n"
        ),
        content,
    )
    return content


def install_orchestrator_workflows(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Copy the orchestrator workflow into the consuming repo.

    A single workflow file (orchestrator.yml) evaluates every pipeline
    phase in one pass, with contents:write so the execute-phase agents
    (coder, create-pr, prd-docs-updater) can push to the issue branch.

    Returns the number of files written.
    """
    workflows = [
        "orchestrator.yml",
    ]
    written = 0
    for name in workflows:
        src = SUBMODULE_ROOT / ".github" / "workflows" / name
        dst = consuming_root / ".github" / "workflows" / name
        if not src.exists():
            print(f"  SKIP   {name}  ({src} missing)")
            continue
        print(f"  Orchestrator workflow ({name}): -> {dst}")
        content = _add_submodules_to_checkout(rewrite_paths(src.read_text(encoding="utf-8")))
        if write_file(dst, content, force, dry_run):
            written += 1
    return written


def install_bootstrap_labels_workflow(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> bool:
    """Copy bootstrap-labels.yml into the consuming repo with paths rewritten."""
    src = SUBMODULE_ROOT / ".github" / "workflows" / "bootstrap-labels.yml"
    dst = consuming_root / ".github" / "workflows" / "bootstrap-labels.yml"
    if not src.exists():
        print(f"  SKIP   bootstrap-labels workflow  ({src} missing)")
        return False
    print(f"  Bootstrap-labels workflow: -> {dst}")
    content = _add_submodules_to_checkout(rewrite_paths(src.read_text(encoding="utf-8")))
    return write_file(dst, content, force, dry_run)


def install_label_cleanup_workflow(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> bool:
    """Copy label-cleanup.yml into the consuming repo with paths rewritten."""
    src = SUBMODULE_ROOT / ".github" / "workflows" / "label-cleanup.yml"
    dst = consuming_root / ".github" / "workflows" / "label-cleanup.yml"
    if not src.exists():
        print(f"  SKIP   label-cleanup workflow  ({src} missing)")
        return False
    print(f"  Label-cleanup workflow: -> {dst}")
    content = _add_submodules_to_checkout(rewrite_paths(src.read_text(encoding="utf-8")))
    return write_file(dst, content, force, dry_run)


def install_sync_workflow(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> bool:
    """Copy sync-claude.yml into the consuming repo with paths rewritten."""
    src = SUBMODULE_ROOT / ".github" / "workflows" / "sync-claude.yml"
    dst = consuming_root / ".github" / "workflows" / "sync-claude.yml"
    if not src.exists():
        print(f"  SKIP   sync-claude workflow  ({src} missing)")
        return False
    print(f"  Sync-claude workflow: -> {dst}")
    content = _add_submodules_to_checkout(rewrite_paths(src.read_text(encoding="utf-8")))
    return write_file(dst, content, force, dry_run)


def install_local_settings(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> bool:
    """Write a .claude/settings.local.json with AI_AGILE_ROOT set so a
    developer running the orchestrator manually picks up the right
    paths. The .local.json file is per-developer and not committed."""
    dst = consuming_root / ".claude" / "settings.local.json"
    payload = {
        "env": {
            "AI_AGILE_ROOT": ".",
        },
        "_comment": (
            "Generated by ai-coding-standards2/get_started.py. "
            "AI_AGILE_ROOT points at the consuming repo root (.) so agents "
            "resolve standards/ and .claude/agents/ from here. The pipeline "
            "submodule locates its own files via __file__, not this var. "
            "Add to .gitignore if your project doesn't already "
            "ignore .claude/settings.local.json."
        ),
    }
    print(f"  Local settings: -> {dst}")
    return write_file(dst, json.dumps(payload, indent=2) + "\n", force, dry_run)


def install_requirements(
    consuming_root: Path,
    dry_run: bool,
) -> bool:
    """Seed requirements.txt in the consuming repo if it does not already exist.

    The orchestrator workflow does `pip install -r requirements.txt` on every
    run.  In this submodule's own CI that file lists the full test stack
    (pytest, pyyaml, etc.).  In consuming repos the orchestrator only needs
    `requests`; project teams extend the file via PR for anything their own
    coder agents need at runtime.

    This file is never overwritten once created -- project additions are
    preserved across syncs.  When the submodule gains new runtime orchestrator
    dependencies, check {SUBMODULE_NAME}/requirements.txt and mirror any
    additions to this file manually.
    """
    dst = consuming_root / "requirements.txt"
    if dst.exists():
        print(f"  SKIP   requirements.txt  (exists; add packages there directly)")
        return False
    src = SUBMODULE_ROOT / "requirements.txt"
    if src.exists():
        runtime_deps = "\n".join(
            ln for ln in src.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("pytest")
        ) + "\n"
    else:
        runtime_deps = "requests\n"
    content = (
        "# Runtime dependencies for the AI Agile pipeline orchestrator.\n"
        f"# Seeded from {SUBMODULE_NAME}/requirements.txt -- never overwritten by sync.\n"
        "# When the submodule adds new runtime deps, mirror them here manually.\n"
        "# Add project-specific packages below.\n"
        f"{runtime_deps}"
    )
    print(f"  Requirements: -> {dst}")
    return write_file(dst, content, force=False, dry_run=dry_run)


def _managed_standards_files() -> list[str]:
    """Return 'standards/<name>.json' for every submodule-managed base standard.

    Excludes adrs.json (project-owned, stays committed) and *.schema.json
    (pipeline infrastructure, not agent-loadable).
    """
    src = SUBMODULE_ROOT / "standards"
    if not src.is_dir():
        return []
    return [
        f"standards/{f.name}"
        for f in sorted(src.glob("*.json"))
        if not f.name.endswith(".schema.json") and f.name != "adrs.json"
    ]


def add_gitignore_entries(
    consuming_root: Path,
    dry_run: bool,
    include_standards: bool = True,
) -> int:
    """Append .gitignore entries for get_started-managed files.

    Covers directories/files that get_started creates but that should not
    be committed to the consuming repo:
      - .claude/agents    -- symlink (Linux) or copied files (Windows)
      - .claude/commands/ -- always copied with path rewrites
      - .claude/settings.local.json -- developer-local settings
      - standards/<name>.json -- base standards copied from the submodule
        (project-owned adrs.json is intentionally excluded so it remains
         committed)

    ``include_standards`` should be False in --seed mode because
    install_standards() has not run yet; listing gitignore entries for
    files that do not exist yet confuses developers who try to manually
    place standards files before the setup workflow runs.

    Idempotent: patterns already present in .gitignore are not re-added.
    Returns the number of new entries written (or that would be written).
    """
    gitignore = consuming_root / ".gitignore"

    patterns: list[str] = [
        ".claude/agents",
        ".claude/commands/",
        ".claude/settings.local.json",
        *(_managed_standards_files() if include_standards else []),
    ]

    existing_lines = set(gitignore.read_text(encoding="utf-8").splitlines()) if gitignore.exists() else set()

    to_add = [p for p in patterns if p not in existing_lines]
    if not to_add:
        print(f"  SKIP   .gitignore  (all entries already present)")
        return 0

    header = "# Managed by get_started.py -- do not commit these paths manually; sync-claude.yml is the authoritative committer"
    needs_header = header not in existing_lines
    separator = "\n" if existing_lines else ""
    if needs_header:
        block = separator + header + "\n" + "\n".join(to_add) + "\n"
    else:
        block = separator + "\n".join(to_add) + "\n"

    if dry_run:
        print(f"  WOULD APPEND to {gitignore}:")
        for p in to_add:
            print(f"    {p}")
        return len(to_add)

    gitignore.parent.mkdir(parents=True, exist_ok=True)
    with open(gitignore, "a", encoding="utf-8") as fh:
        fh.write(block)

    plural = "entry" if len(to_add) == 1 else "entries"
    print(f"  Gitignore: added {len(to_add)} {plural} to {gitignore}")
    return len(to_add)


def untrack_managed_paths(consuming_root: Path, dry_run: bool) -> int:
    """Remove get_started-managed paths from git tracking (git rm --cached).

    Previous versions of get_started.py instructed users to commit
    .claude/agents/, .claude/commands/, and base standards files.
    This function removes those paths from the git index so they stop
    being tracked, without deleting the local copies.  Safe to call on
    repos that never tracked these paths (no-op when not tracked).

    Returns the number of paths removed from the index.
    """
    candidates = [
        ".claude/agents",
        ".claude/commands",
        ".claude/settings.local.json",
        *_managed_standards_files(),
    ]

    removed = 0
    for path in candidates:
        try:
            check = subprocess.run(
                ["git", "ls-files", "--", path],
                cwd=consuming_root,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            break  # git binary not found; skip all

        if check.returncode != 0:
            # Fatal git error (e.g. "not a git repository") -- no point continuing.
            # Transient per-path errors also return non-zero; bail once on first.
            if check.stderr.strip():
                break
            continue

        if not check.stdout.strip():
            continue  # not tracked

        if dry_run:
            print(f"  WOULD  git rm --cached -r {path}  (currently tracked; will be gitignored)")
            removed += 1
            continue

        result = subprocess.run(
            ["git", "rm", "--cached", "-r", "--", path],
            cwd=consuming_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"  UNTRACKED  {path}  (removed from git index; local files unchanged)")
            removed += 1
        else:
            print(f"  WARN  {path}  (git rm --cached failed: {result.stderr.strip()})")

    return removed


def print_followup_seed() -> None:
    print()
    print("Done. Two steps to finish:")
    print()
    print(f"  1. Commit and push the seed files:")
    print(f"     git add .gitmodules \\")
    print(f"             {SUBMODULE_NAME} \\")
    print(f"             .github/workflows/orchestrator.yml \\")
    print(f"             .gitignore")
    print(f"     git commit -m 'Add ai-coding-standards2 submodule'")
    print(f"     git push")
    print()
    print(f"  2. Add secrets, then run the setup workflow:")
    print(f"     Settings -> Secrets -> Actions:")
    print(f"       ANTHROPIC_API_KEY  -- your Anthropic API key")
    print(f"       AI_AGILE_BOT_TOKEN -- a GitHub PAT for the bot account")
    print()
    print(f"     Then: GitHub -> Actions -> 'Pipeline Orchestrator' -> Run workflow")
    print(f"     -> check 'First-time setup' -> Run.")
    print()
    print(f"     The workflow creates the .claude/agents symlink, copies slash")
    print(f"     commands and standards, drops sync-claude.yml and other workflows,")
    print(f"     and commits everything. After it completes, open a test issue.")
    print()
    print(f"For full design + roadmap see {SUBMODULE_NAME}/docs/product/orchestrator/.")


def print_followup(consuming_root: Path) -> None:
    print()
    print("Done. Next steps:")
    print()
    print(f"  1. Add secrets to your repo (Settings -> Secrets -> Actions):")
    print(f"       ANTHROPIC_API_KEY  -- your Anthropic API key")
    print(f"       AI_AGILE_BOT_TOKEN -- a GitHub PAT for the bot account")
    print()
    print(f"  2. Commit the seed files (workflows + .gitignore only).")
    print()
    print(f"     git add .gitmodules \\")
    print(f"             {SUBMODULE_NAME} \\")
    print(f"             .github/workflows/orchestrator.yml \\")
    print(f"             .github/workflows/bootstrap-labels.yml \\")
    print(f"             .github/workflows/label-cleanup.yml \\")
    print(f"             .github/workflows/sync-claude.yml \\")
    print(f"             .gitignore \\")
    print(f"             requirements.txt")
    print(f"     git commit -m 'Wire up ai-coding-standards2 orchestrator'")
    print(f"     git push")
    print()
    print(f"     If any managed paths were previously committed,")
    print(f"     get_started.py has already staged their removal via")
    print(f"     'git rm --cached' -- include those staged deletions in")
    print(f"     this commit too.")
    print()
    print(f"  3. Open a test issue with a problem statement and acceptance criteria.")
    print(f"     The orchestrator workflow fires on issue-opened; expect")
    print(f"     `01_product_docs/issue-classifier:wip` then `:complete` labels.")
    print()
    print(f"For full design + roadmap see {SUBMODULE_NAME}/docs/product/orchestrator/.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Wire ai-coding-standards2 into a consuming repo."
    )
    p.add_argument(
        "--seed",
        action="store_true",
        help=(
            "Minimal bootstrap: copy only orchestrator.yml + .gitignore. "
            "Commit those two files, push, then trigger the workflow with "
            "'First-time setup' to finish wiring on a Linux runner."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the consuming repo.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created/modified without writing.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    consuming_root = find_consuming_repo_root()
    print(f"Consuming repo root: {consuming_root}")
    print(f"Submodule root:      {SUBMODULE_ROOT}")
    if args.dry_run:
        print("(dry run -- no files will be written)")
    print()

    if args.seed:
        # Minimal bootstrap: drop only the orchestrator workflow so the
        # developer can commit and push a single file. The workflow's
        # built-in "First-time setup" mode handles everything else on a
        # Linux runner (symlinks, commands, standards, remaining workflows).
        # Skip standards gitignore entries -- install_standards() hasn't run
        # yet, so listing gitignore paths for non-existent files confuses
        # developers who try to place standards files manually before setup.
        install_orchestrator_workflows(consuming_root, args.force, args.dry_run)
        add_gitignore_entries(consuming_root, args.dry_run, include_standards=False)
        untrack_managed_paths(consuming_root, args.dry_run)
        print_followup_seed()
        return 0

    install_orchestrator_workflows(consuming_root, args.force, args.dry_run)
    install_bootstrap_labels_workflow(consuming_root, args.force, args.dry_run)
    install_label_cleanup_workflow(consuming_root, args.force, args.dry_run)
    install_sync_workflow(consuming_root, args.force, args.dry_run)
    install_standards(consuming_root, args.force, args.dry_run)
    install_agents(consuming_root, args.force, args.dry_run)
    install_slash_commands(consuming_root, args.force, args.dry_run)
    install_local_settings(consuming_root, args.force, args.dry_run)
    install_requirements(consuming_root, args.dry_run)
    add_gitignore_entries(consuming_root, args.dry_run)
    untrack_managed_paths(consuming_root, args.dry_run)

    print_followup(consuming_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
