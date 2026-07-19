#!/usr/bin/env python3
"""
get_started.py -- wire ai-coding-standards2 into a consuming repo.

Run from the consuming repo's root after `git submodule add ...` has
placed this repo at `<consuming-repo>/ai-coding-standards2/`:

    python ai-coding-standards2/get_started.py (--seed | --full) [--force] [--dry-run]

==============================================================================
TWO MODES -- this is the same script, run twice during onboarding.
==============================================================================

The script does very different amounts of work depending on the mode, so there
is NO DEFAULT: you must pick a run type explicitly. Running it with no mode
flag is an error (it refuses rather than guess, so a first-time local run can
neither clobber the consuming repo nor silently do the wrong amount of work).

  --seed             -> run_seed()  -> installs the two seed workflows
                                        (ai_orchestrator.yml + the emergency-stop
                                        kill switch) + .gitignore entries.
                                        Nothing else.

  --full             -> run_full()  -> installs the COMPLETE managed set:
                                        the whole-.claude symlink, the standards
                                        symlink, the local adrs/ folder,
                                        requirements, .gitignore. (The two
                                        pipeline workflows are committed during
                                        seed, not here.)

  --force is an overwrite modifier (not a mode): add it to --seed or --full to
  overwrite existing files. The Onboard job runs --full --force.

The two modes are two steps of ONE onboarding flow:

  Step 1 (local, by a developer):
      python get_started.py --seed
      -> writes the two seed workflows (ai_orchestrator.yml + the emergency-stop
         kill switch), so they can be committed and pushed. ai_orchestrator.yml is
         the minimum GitHub needs to run the Onboard job; the emergency stop
         ships alongside it so the operator has a kill switch from the start.

  Step 2 (on a Linux runner, by the Onboard job in ai_orchestrator.yml):
      python get_started.py --full --force
      -> writes EVERYTHING else and commits it.

So `--seed` deliberately copies almost nothing -- the whole-folder
symlink/full wiring happens in Step 2, on a Linux runner, via the Onboard
GitHub Action (which passes --full --force). A developer who genuinely wants
the full install locally passes --full (adding --force to overwrite). See
docs/product/orchestrator/16-onboarding.md for the full flow.

What run_full() installs, in order (each is one install_* function below):
    ai_orchestrator.yml, ai_emergency_stop.yml (already committed during seed;
    re-written locally but never pushed by the Onboard job),
    the standards/ symlink, the local adrs/ folder, the whole-.claude symlink,
    requirements.txt, .gitignore entries, and untracking of any
    previously-committed managed paths.

The consuming repo inherits its ENTIRE Claude Code setup from the submodule:
`.claude` and `standards` are whole-folder symlinks into it (copies on
Windows). The only thing the consuming repo owns is OUTSIDE those folders:
`adrs/` (project ADRs). Workflows still get submodule-relative path rewrites
applied on copy; agents and slash commands are read verbatim (commands already
try both standalone and submodule paths, so they need no rewriting).

Options (a run type is REQUIRED -- there is no default):
    --seed       SEED mode: copy the two seed workflows (ai_orchestrator.yml +
                 ai_emergency_stop.yml) + .gitignore, then stop. Commit
                 those, push, then trigger the "Onboard" job to finish wiring
                 on a Linux runner (which runs --full --force).
    --full       FULL mode: install the complete managed set locally. This is
                 what the Onboard job runs on a Linux runner.
    --force      Overwrite existing files. A modifier, not a mode -- combine it
                 with --seed or --full.
    --dry-run    Print what would be created/modified without writing.

Running with no run type (neither --seed nor --full) is an error.
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
        f"{SUBMODULE_NAME}/docs/product/orchestrator/13-todos.md",
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
    """Wire the whole `standards/` directory from the submodule into the consuming repo.

    Standards are defined centrally: the framework owns them and they are read
    verbatim, and no project-owned file lives inside `standards/` (ADRs live in
    the separate local `adrs/` folder -- see install_adrs). So `standards/` is a
    single directory symlink `<consuming>/standards -> submodule/standards` on
    Linux/macOS, and a verbatim copy on Windows (unprivileged symlinks
    unavailable).

    Returns 1 (symlink created/updated) or the number of files written.
    """
    src_dir = SUBMODULE_ROOT / "standards"
    dst_dir = consuming_root / "standards"

    if not src_dir.is_dir():
        print(f"  SKIP   standards  ({src_dir} missing)")
        return 0

    print(f"  Standards: {src_dir} -> {dst_dir}")

    if sys.platform != "win32":
        return _symlink_dir(src_dir, dst_dir, force, dry_run)
    return _copy_dir_tree(src_dir, dst_dir, force, dry_run)


def install_adrs(
    consuming_root: Path,
    dry_run: bool,
) -> bool:
    """Seed the local `adrs/` folder with a project-owned adrs.json.

    ADRs are the one standards-adjacent artifact a project owns locally. They
    live OUTSIDE the symlinked `standards/` folder precisely so `standards/` can
    be a whole-folder symlink. Seeded once and never overwritten, so project
    ADRs survive every sync.
    """
    dst = consuming_root / "adrs" / "adrs.json"
    if dst.exists():
        print(f"  KEEP   {dst}  (project-owned; not overwritten by sync)")
        return False
    project_adrs = (
        '{\n'
        f'  "$schema": "../{SUBMODULE_NAME}/pipeline/schemas/standards.schema.json",\n'
        '  "version": "1.0",\n'
        '  "scope": "project",\n'
        '  "description": "Approved project-level Architecture Decision Records.",\n'
        '  "adrs": []\n'
        '}\n'
    )
    print(f"  Project ADRs: -> {dst}")
    return write_file(dst, project_adrs, force=False, dry_run=dry_run)


def install_claude(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Wire the whole `.claude/` directory from the submodule into the consuming repo.

    The consuming repo inherits its ENTIRE Claude Code setup from the submodule:
    agents, slash commands, AGENTS.md, and settings.json. On Linux/macOS this is
    a single directory symlink `<consuming>/.claude -> submodule/.claude`, so it
    is always live and never drifts. On Windows (unprivileged directory symlinks
    unavailable) the tree is copied verbatim.

    Slash commands need no path rewriting: they are written to try both the
    standalone (`pipeline/...`) and submodule (`ai-coding-standards2/...`) paths,
    so they resolve correctly from a verbatim symlink. `AI_AGILE_ROOT` is carried
    by the inherited `.claude/settings.json`, so consumers get it for free.

    The consuming repo keeps no Claude config of its own -- to change an agent,
    command, or setting, change it here (PR the submodule) or pin a fork.

    Returns 1 (symlink created/updated) or the number of files written.
    """
    src_dir = SUBMODULE_ROOT / ".claude"
    dst_dir = consuming_root / ".claude"

    if not src_dir.is_dir():
        print(f"  SKIP   .claude  ({src_dir} missing)")
        return 0

    print(f"  Claude setup: {src_dir} -> {dst_dir}")

    if sys.platform != "win32":
        return _symlink_dir(src_dir, dst_dir, force, dry_run)
    return _copy_dir_tree(src_dir, dst_dir, force, dry_run)


def _symlink_dir(
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


def _copy_dir_tree(
    src_dir: Path,
    dst_dir: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Verbatim-copy every file under src_dir into dst_dir (recursive).

    Used on Windows where directory symlinks require elevated privileges. Copies
    all files (not just *.md) so settings.json and AGENTS.md come along too.
    Removes stale files no longer present in the submodule. Returns the number
    of files written.
    """
    written = 0
    for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        if write_file(dst, src.read_text(encoding="utf-8"), force, dry_run):
            written += 1

    # Remove stale files that are no longer in the submodule.
    if dst_dir.is_dir():
        for dst in sorted(p for p in dst_dir.rglob("*") if p.is_file()):
            rel = dst.relative_to(dst_dir)
            if not (src_dir / rel).exists():
                if dry_run:
                    print(f"  WOULD REMOVE {dst}  (no longer in submodule)")
                else:
                    dst.unlink()
                    print(f"  REMOVED {dst}  (no longer in submodule)")

    return written


def install_claude_md(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> bool:
    """Make CLAUDE.md discoverable at the consuming repo's root.

    Claude Code's project-memory auto-load and coder.md's own
    `[ -f CLAUDE.md ]` check both look at the repo root, not inside `.claude/`
    -- so the baseline content at `.claude/CLAUDE.md` (which ships as part of
    the whole-folder `.claude` install) needs a root-level presence to ever
    actually be read.

    Called from both run_seed() and run_full(): --seed is a local step that
    may run on Windows (unlike --full, always a Linux runner during Onboard),
    so a developer who onboards via --seed gets the link immediately; calling
    it again from run_full() covers a developer who runs --full directly,
    without ever running --seed first. Two different mechanisms depending on
    platform:
      - Non-Windows: a relative symlink `CLAUDE.md -> .claude/CLAUDE.md`.
        Its target doesn't need to exist yet -- when called from run_seed(),
        `.claude/` itself is only wired up later by --full/Onboard -- the
        symlink just starts resolving the moment that happens.
      - Windows (no unprivileged symlinks): copy the file's actual bytes
        from the submodule now. There is no later auto-resolution to rely
        on here, since `.claude/` is also a plain copy on Windows, not a
        symlink -- so the content has to land for real at call time.
    """
    dst = consuming_root / "CLAUDE.md"

    if sys.platform == "win32":
        src = SUBMODULE_ROOT / ".claude" / "CLAUDE.md"
        if not src.is_file():
            print(f"  SKIP   CLAUDE.md  ({src} missing)")
            return False
        print(f"  CLAUDE.md: {src} -> {dst}")
        return write_file(dst, src.read_text(encoding="utf-8"), force, dry_run)

    rel_target = ".claude/CLAUDE.md"
    if dst.is_symlink():
        if os.readlink(dst) == rel_target:
            print(f"  SKIP   {dst}  (symlink already correct)")
            return False
        if not force:
            print(f"  SKIP   {dst}  (symlink exists pointing elsewhere; pass --force to update)")
            return False
        if dry_run:
            print(f"  WOULD  {dst} -> {rel_target}  (replace symlink)")
            return True
        dst.unlink()
    elif dst.exists():
        if not force:
            print(f"  SKIP   {dst}  (exists; pass --force to overwrite)")
            return False
        if dry_run:
            print(f"  WOULD  {dst} -> {rel_target}  (replace file with symlink)")
            return True
        dst.unlink()
    elif dry_run:
        print(f"  WOULD  {dst} -> {rel_target}")
        return True

    dst.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(rel_target, dst)
    print(f"  LINKED {dst} -> {rel_target}")
    return True


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

    A single workflow file (ai_orchestrator.yml) evaluates every pipeline
    phase in one pass, with contents:write so the execute-phase agents
    (coder, create-pr, prd-docs-updater) can push to the issue branch.

    Returns the number of files written.
    """
    workflows = [
        "ai_orchestrator.yml",
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


def _install_workflow(
    name: str,
    consuming_root: Path,
    force: bool,
    dry_run: bool,
    *,
    inject_submodules: bool = True,
) -> bool:
    """Copy a single workflow file from the submodule into the consuming repo.

    Path rewrites (submodule-relative paths) are always applied. ``submodules:
    true`` is injected into checkout steps unless ``inject_submodules`` is
    False -- pass False for workflows that read nothing from the submodule so
    they never depend on a submodule fetch (which can fail for a private
    submodule checked out without an elevated token).

    Returns True if the file was (or would be) written, False if the source
    was missing or the destination was skipped.
    """
    src = SUBMODULE_ROOT / ".github" / "workflows" / name
    dst = consuming_root / ".github" / "workflows" / name
    if not src.exists():
        print(f"  SKIP   {name}  ({src} missing)")
        return False
    print(f"  Workflow ({name}): -> {dst}")
    content = rewrite_paths(src.read_text(encoding="utf-8"))
    if inject_submodules:
        content = _add_submodules_to_checkout(content)
    return write_file(dst, content, force, dry_run)


def install_emergency_stop_workflow(consuming_root: Path, force: bool, dry_run: bool) -> bool:
    """Copy ai_emergency_stop.yml into the consuming repo.

    The operator's kill switch: writes the .pipeline-stop marker (at the repo
    root, where the orchestrator looks for it) and cancels in-flight runs.
    inject_submodules=False -- it reads nothing from the submodule, so it must
    not depend on a submodule fetch to run when the pipeline needs stopping.
    """
    return _install_workflow(
        "ai_emergency_stop.yml", consuming_root, force, dry_run, inject_submodules=False
    )


def _requirement_name(line: str) -> str:
    """Extract the package name from a requirements.txt line, ignoring any
    version specifier, extras, or environment marker (e.g. 'requests==2.33.1'
    and 'requests[socks]>=2 ; python_version>"3.8"' both -> 'requests')."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    name = re.split(r"[<>=!~;\[\s]", stripped, maxsplit=1)[0]
    return name.strip().lower()


#: Exact package names in this submodule's own requirements.txt that exist
#: only for this submodule's own test suite, not for pipeline_orchestrator.py's
#: runtime -- never merged into a consuming repo's requirements.txt. Matched
#: via _requirement_name(), not a raw prefix, so e.g. a future 'pytest-cov'
#: entry wouldn't be excluded just for sharing the 'pytest' prefix.
_TEST_ONLY_DEP_NAMES = frozenset({"pytest", "pyyaml"})


def _orchestrator_runtime_deps() -> list[str]:
    """Return this submodule's own requirements.txt lines, minus its
    test-only entries (pytest, pyyaml -- see _TEST_ONLY_DEP_NAMES), as the
    set of deps the orchestrator itself needs at runtime in any consuming
    repo."""
    src = SUBMODULE_ROOT / "requirements.txt"
    if not src.exists():
        return ["requests"]
    return [
        ln.strip() for ln in src.read_text(encoding="utf-8").splitlines()
        if ln.strip() and _requirement_name(ln) not in _TEST_ONLY_DEP_NAMES
    ]


def install_requirements(
    consuming_root: Path,
    dry_run: bool,
) -> bool:
    """Ensure the orchestrator's runtime dependencies are present in the
    consuming repo's requirements.txt -- creating the file if it doesn't
    exist, or merging any missing entries into it if it does.

    The orchestrator workflow does `pip install -r requirements.txt` on every
    run, so if a consuming repo already tracks its own requirements.txt (its
    own app dependencies, unrelated to this pipeline), our runtime deps must
    still land in it or CI never gets off the ground.  Merging is idempotent
    and additive only: it appends whichever of our runtime deps aren't
    already present (matched by package name, ignoring version pins), and
    never removes, reorders, or rewrites anything the project already has.
    Once an entry is present, later onboarding runs leave it alone -- this
    only ever adds what's missing, so it converges to a no-op.
    """
    dst = consuming_root / "requirements.txt"
    runtime_deps = _orchestrator_runtime_deps()

    if not dst.exists():
        content = (
            "# Runtime dependencies for the AI Agile pipeline orchestrator.\n"
            f"# Seeded from {SUBMODULE_NAME}/requirements.txt.\n"
            "# Add project-specific packages below.\n"
            + "\n".join(runtime_deps) + "\n"
        )
        print(f"  Requirements: -> {dst}")
        return write_file(dst, content, force=False, dry_run=dry_run)

    existing_text = dst.read_text(encoding="utf-8")
    existing_names = {
        _requirement_name(ln) for ln in existing_text.splitlines()
    }
    missing = [
        dep for dep in runtime_deps
        if _requirement_name(dep) not in existing_names
    ]
    if not missing:
        print(f"  SKIP   requirements.txt  (orchestrator runtime deps already present)")
        return False

    if dry_run:
        print(f"  WOULD  {dst}  (append {len(missing)} missing orchestrator dep(s): {', '.join(missing)})")
        return True

    needs_leading_newline = existing_text != "" and not existing_text.endswith("\n")
    addition = (
        ("\n" if needs_leading_newline else "")
        + "\n# Runtime dependencies required by the AI Agile pipeline orchestrator\n"
        + f"# (added by onboarding from {SUBMODULE_NAME}/requirements.txt).\n"
        + "\n".join(missing) + "\n"
    )
    with dst.open("a", encoding="utf-8") as f:
        f.write(addition)
    print(f"  APPEND {dst}  ({len(missing)} orchestrator dep(s): {', '.join(missing)})")
    return True


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
    be committed to the consuming repo as normal files (they are symlinks
    into the submodule, force-committed by the Onboard job):
      - .claude     -- whole-folder symlink into the submodule
      - standards   -- whole-folder symlink into the submodule
      - CLAUDE.md   -- symlink (or, on Windows, a copy) to .claude/CLAUDE.md

    The project-owned adrs/ folder is intentionally NOT gitignored so it stays
    committed.

    ``include_standards`` should be False in --seed mode because the standards
    symlink has not been created yet; listing it before it exists confuses
    developers who try to place files there before the setup workflow runs.
    CLAUDE.md is unconditional (like .claude) since install_claude_md() runs
    in --seed itself, not --full.

    Idempotent: patterns already present in .gitignore are not re-added.
    Returns the number of new entries written (or that would be written).
    """
    gitignore = consuming_root / ".gitignore"

    patterns: list[str] = [
        ".claude",
        "CLAUDE.md",
        *(["standards"] if include_standards else []),
    ]

    existing_lines = set(gitignore.read_text(encoding="utf-8").splitlines()) if gitignore.exists() else set()

    to_add = [p for p in patterns if p not in existing_lines]
    if not to_add:
        print(f"  SKIP   .gitignore  (all entries already present)")
        return 0

    header = "# Managed by get_started.py -- do not commit these paths manually; the Onboard job in ai_orchestrator.yml is the authoritative committer"
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

    Earlier installs committed .claude subpaths and per-file standards, or the
    now-retired .claude/settings.local.json. This removes them (and the whole
    .claude / standards paths) from the git index so they stop being tracked as
    normal files, without deleting the local copies. Safe to call on repos that
    never tracked these paths (no-op when not tracked).

    Returns the number of paths removed from the index.
    """
    candidates = [
        ".claude",
        ".claude/settings.local.json",
        "standards",
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
    print(f"  Step 1 -- Commit and push the seed files:")
    print(f"     git add .gitmodules \\")
    print(f"             {SUBMODULE_NAME} \\")
    print(f"             .github/workflows/ai_orchestrator.yml \\")
    print(f"             .github/workflows/ai_emergency_stop.yml \\")
    print(f"             .gitignore")
    print(f"     git add -f CLAUDE.md   # gitignored like .claude/ -- force-add it")
    print(f"     git commit -m 'Add ai-coding-standards2 submodule'")
    print(f"     git push")
    print()
    print(f"  Step 2 -- Add secrets, then run the Onboard job:")
    print(f"     Settings -> Secrets -> Actions:")
    print(f"       ANTHROPIC_API_KEY  -- your Anthropic API key")
    print(f"       AI_AGILE_BOT_TOKEN -- a GitHub PAT for the bot account")
    print()
    print(f"     Then: GitHub -> Actions -> 'AI - Orchestrator' -> Run workflow")
    print(f"     -> check 'Onboard' -> Run.")
    print()
    print(f"     The Onboard job runs on a Linux runner. It creates the")
    print(f"     .claude/standards symlinks, seeds adrs/ and requirements,")
    print(f"     bootstraps the pipeline labels, and commits everything EXCEPT")
    print(f"     workflow files (those were committed in the seed step, so the")
    print(f"     Onboard token needs no workflow scope).")
    print(f"     After it completes, open a test issue to confirm the pipeline is live.")
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
    print(f"             .github/workflows/ai_orchestrator.yml \\")
    print(f"             .github/workflows/ai_emergency_stop.yml \\")
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
            "SEED mode (one of --seed/--full is required; there is no default): "
            "copy the two seed workflows (ai_orchestrator.yml + "
            "ai_emergency_stop.yml) + .gitignore. Commit those, push, then "
            "trigger the 'Onboard' workflow to finish wiring on a Linux runner."
        ),
    )
    p.add_argument(
        "--full",
        action="store_true",
        help=(
            "FULL mode (one of --seed/--full is required): lay down every "
            "workflow, the whole-.claude and standards symlinks, adrs/, and "
            "requirements locally. This is what the Onboard job and "
            "the Onboard job on a Linux runner (it adds --force)."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite existing files. A modifier, not a mode: use it with "
            "--seed or --full."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created/modified without writing.",
    )
    return p.parse_args()


def run_seed(consuming_root: Path, force: bool, dry_run: bool) -> None:
    """SEED mode (--seed): install the two seed workflows + .gitignore, then stop.

    This is the minimal local bootstrap. It installs exactly two workflow files:
      - ai_orchestrator.yml         -- all GitHub needs to run the "Onboard" job,
                                     which re-runs this script in full mode
                                     (--full --force) on a Linux runner to
                                     install everything else.
      - ai_emergency_stop.yml -- the operator's kill switch. It reads
                                     nothing from the submodule, so it works
                                     from the first commit; shipping it in the
                                     seed means the operator can halt a runaway
                                     pipeline before the full wiring exists.
    The developer commits these two workflows (plus .gitignore) and pushes.
    Deliberately copies almost nothing else; see run_full() for the real wiring.

    include_standards=False because install_standards() does not run in seed
    mode -- listing gitignore entries for standards files that do not exist yet
    confuses developers who try to place them manually before the Onboard job.

    Also links/copies CLAUDE.md at the repo root (see install_claude_md()) --
    this step is local and may run on the developer's own machine, so it is
    the one place that needs the Windows-vs-symlink platform branch, unlike
    install_claude() which only ever runs on a Linux runner during --full.
    """
    install_orchestrator_workflows(consuming_root, force, dry_run)
    install_emergency_stop_workflow(consuming_root, force, dry_run)
    install_claude_md(consuming_root, force, dry_run)
    add_gitignore_entries(consuming_root, dry_run, include_standards=False)
    untrack_managed_paths(consuming_root, dry_run)
    print_followup_seed()


def _guard_existing_claude(consuming_root: Path) -> None:
    """Refuse to clobber a consuming repo's own `.claude` directory.

    The framework installs `.claude` as a whole-folder symlink into the
    submodule, so the consuming repo keeps no Claude config of its own -- and
    the symlink install would `rmtree` a real `.claude` that got in the way.
    Most repos that use Claude Code already have a `.claude/` (settings, hooks,
    commands), so deleting it silently would lose the developer's files.

    Fail the run (exit non-zero, which fails the Onboard/sync job) if a real,
    non-symlink `.claude` exists and was not created by a prior get_started run
    (a prior managed install leaves a `.claude/agents` symlink). Set
    `AI_AGILE_REPLACE_CLAUDE=1` to replace it deliberately.
    """
    dst = consuming_root / ".claude"
    if not dst.is_dir() or dst.is_symlink():
        return  # missing, or already the framework's symlink -- nothing to guard
    if (dst / "agents").is_symlink():
        return  # a prior get_started-managed install -- safe to convert
    if os.environ.get("AI_AGILE_REPLACE_CLAUDE") == "1":
        print("  WARNING  replacing existing .claude (AI_AGILE_REPLACE_CLAUDE=1 set)")
        return
    sys.exit(
        f"ERROR: {dst} already exists as a real directory in the consuming repo.\n"
        "  AI Agile installs .claude as a whole-folder symlink into the\n"
        "  ai-coding-standards2 submodule, so the consuming repo keeps no Claude\n"
        "  config of its own. Refusing to delete your existing .claude.\n"
        "  Back up or remove it and re-run, or set AI_AGILE_REPLACE_CLAUDE=1 to\n"
        "  replace it deliberately."
    )


def run_full(consuming_root: Path, force: bool, dry_run: bool) -> None:
    """Full mode (--full): install the COMPLETE managed file set.

    This is what the Onboard job in ai_orchestrator.yml runs (get_started.py
    --full --force). It lays down the whole `.claude` symlink, the `standards`
    symlink, the local `adrs/` folder, requirements, and the root-level
    CLAUDE.md link -- everything a consuming repo needs to run the pipeline.
    The two pipeline workflows (ai_orchestrator, ai_emergency_stop) are
    committed during the seed step, not here, so the Onboard job never has to
    push `.github/workflows/*` (which would require a workflow-scoped token);
    the Onboard job commits only non-workflow files. Each step is one
    install_* function; the order is stable so the printed log reads
    top-to-bottom.

    install_claude_md() also runs here (not just in run_seed()) so a developer
    who runs --full directly, without ever running --seed first, still gets
    the root-level CLAUDE.md link.
    """
    # Pre-flight: refuse to clobber a consuming repo's own .claude. Runs before
    # any writes so a rejected onboard leaves no partial state.
    _guard_existing_claude(consuming_root)

    install_orchestrator_workflows(consuming_root, force, dry_run)
    install_emergency_stop_workflow(consuming_root, force, dry_run)
    install_standards(consuming_root, force, dry_run)
    install_adrs(consuming_root, dry_run)
    install_claude(consuming_root, force, dry_run)
    install_claude_md(consuming_root, force, dry_run)
    install_requirements(consuming_root, dry_run)
    add_gitignore_entries(consuming_root, dry_run)
    untrack_managed_paths(consuming_root, dry_run)
    print_followup(consuming_root)


def main() -> int:
    args = parse_args()

    # Mode resolution -- there is NO DEFAULT. Exactly one run type is required:
    # --seed (minimal) or --full (complete wiring). --force is an overwrite
    # modifier usable with either, never a mode of its own. Refuse an ambiguous
    # invocation before touching the consuming repo.
    if args.seed and args.full:
        sys.exit("ERROR: pass either --seed or --full, not both.")
    if not args.seed and not args.full:
        sys.exit(
            "ERROR: no run type specified -- get_started.py has no default mode.\n"
            "  Choose one:\n"
            "    --seed    minimal local bootstrap (the two seed workflows + .gitignore),\n"
            "              then commit, push, and run the Onboard job to finish.\n"
            "    --full    complete wiring locally -- what the Onboard job and\n"
            "              the Onboard job on a Linux runner (it adds --force).\n"
            "  Add --force to overwrite existing files, --dry-run to preview."
        )
    full_mode = args.full

    consuming_root = find_consuming_repo_root()
    print(f"Consuming repo root: {consuming_root}")
    print(f"Submodule root:      {SUBMODULE_ROOT}")
    print(f"Mode:                {'full (complete wiring)' if full_mode else 'seed (orchestrator + emergency-stop)'}")
    if args.dry_run:
        print("(dry run -- no files will be written)")
    print()

    # One script, two modes -- see the module docstring. run_seed() is the
    # minimal local bootstrap; run_full() does the real wiring and is what the
    # Onboard job runs on a Linux runner.
    if full_mode:
        run_full(consuming_root, args.force, args.dry_run)
    else:
        run_seed(consuming_root, args.force, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
