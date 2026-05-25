#!/usr/bin/env python3
"""
get_started.py — wire ai-coding-standards2 into a consuming repo.

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
  4. Drops the orchestrator workflow into the consuming repo's
     `.github/workflows/orchestrator.yml`. (GitHub Actions cannot pick
     up workflows from submodules; the consuming repo's own workflow
     dir is the only place they can run from.)
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
    --force      Overwrite existing files in the consuming repo
    --dry-run    Print what would be created/modified without writing
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


SUBMODULE_NAME = "ai-coding-standards2"
SUBMODULE_ROOT = Path(__file__).resolve().parent

# The orchestrator workflow content — kept inline so a fresh consumer
# repo gets a known-good copy without relying on a separate template
# file. Update this when the canonical workflow at
# .github/workflows/orchestrator.yml in this repo changes.
ORCHESTRATOR_WORKFLOW_TEMPLATE = """\
name: AI Agile orchestrator

on:
  issues:
    types: [opened, reopened, labeled, unlabeled]
  pull_request:
    types: [opened, reopened, synchronize, ready_for_review, labeled, unlabeled, closed]
  schedule:
    - cron: '*/15 6-20 * * 1-5'  # Every 15 min, 06:00–20:00 UTC, weekdays
  workflow_dispatch:
    inputs:
      issue_number:
        description: 'Process a single issue/PR number (leave blank for all)'
        required: false
      dry_run:
        description: 'Dry run — show what would trigger without executing'
        type: boolean
        default: false

permissions:
  contents: write
  issues: write
  pull-requests: write
  checks: read

concurrency:
  group: pipeline-orchestrator
  cancel-in-progress: false

jobs:
  orchestrate:
    name: Evaluate pipeline state
    runs-on: ubuntu-latest
    timeout-minutes: 120

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          submodules: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install requests

      - name: Install Claude Code CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Build orchestrator args
        id: args
        env:
          ISSUE_INPUT: ${{ github.event.inputs.issue_number }}
        run: |
          ARGS=""

          [[ "$ISSUE_INPUT" =~ ^[0-9]*$ ]] || {{ echo "ERROR: issue_number must be a positive integer" >&2; exit 1; }}

          if [ -n "$ISSUE_INPUT" ]; then
            ARGS="$ARGS --issue $ISSUE_INPUT"
          elif [ "${{ github.event_name }}" = "issues" ]; then
            ARGS="$ARGS --issue ${{ github.event.issue.number }} --kind issue"
          elif [ "${{ github.event_name }}" = "pull_request" ]; then
            ARGS="$ARGS --issue ${{ github.event.pull_request.number }} --kind pr"
          fi

          if [ "${{ github.event.inputs.dry_run }}" = "true" ]; then
            ARGS="$ARGS --dry-run"
          fi

          echo "args=$ARGS" >> "$GITHUB_OUTPUT"

      - name: Run orchestrator
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          AI_AGILE_BOT_TOKEN: ${{ secrets.AI_AGILE_BOT_TOKEN }}
          GIT_TRACE: "1"
          AI_AGILE_ROOT: ${{ github.workspace }}/ai-coding-standards2
          # ci-gate uses this to exclude orchestrator check runs from its poll.
          CI_GATE_EXCLUDE_JOB_NAMES: "Evaluate pipeline state"
        run: |
          python ai-coding-standards2/pipeline/pipeline_orchestrator.py \\
            --repo "$GITHUB_REPOSITORY" \\
            --verbose \\
            ${{ steps.args.outputs.args }}

  bootstrap-labels:
    name: Bootstrap pipeline labels
    runs-on: ubuntu-latest
    if: github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: true

      - name: Bootstrap labels
        env:
          GITHUB_TOKEN: ${{ secrets.AI_AGILE_BOT_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
        run: |
          bash ai-coding-standards2/.github/scripts/status.sh bootstrap-all \\
            ai-coding-standards2/pipeline/pipeline.json
"""


# Path-rewrite rules applied to slash command markdown when copying
# from the submodule into the consuming repo's .claude/. Each rule is
# (pattern, replacement) in regex. The submodule paths get rewritten
# to the submodule-relative form so they resolve when a developer runs
# them from the consuming repo's root.
PATH_REWRITES = [
    # Bare ".github/scripts/status.sh" → "ai-coding-standards2/.github/scripts/status.sh"
    # Negative lookbehind prevents double-prefixing already-submodule-qualified paths.
    (rf"(?<!{SUBMODULE_NAME}/)\.github/scripts/status\.sh", f"{SUBMODULE_NAME}/.github/scripts/status.sh"),
    # Bare ".claude/agents/..." → "ai-coding-standards2/.claude/agents/..."
    (rf"(?<!{SUBMODULE_NAME}/)\.claude/agents/", f"{SUBMODULE_NAME}/.claude/agents/"),
    # Bare "pipeline/..." → "ai-coding-standards2/pipeline/..."
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
    path.write_text(content)
    print(f"  WROTE  {path}")
    return True


def rewrite_paths(text: str) -> str:
    """Apply PATH_REWRITES to slash-command body text."""
    out = text
    for pattern, replacement in PATH_REWRITES:
        out = re.sub(pattern, replacement, out)
    return out


def install_agents(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> int:
    """Copy .claude/agents/ from the submodule into the consuming repo.

    Preserves the full subdirectory structure (01_product_docs/,
    05_execute/, etc.). Agent files reference all paths via $AI_AGILE_ROOT
    so no path rewriting is needed — they are copied verbatim.

    Returns the number of files written.
    """
    src_dir = SUBMODULE_ROOT / ".claude" / "agents"
    dst_dir = consuming_root / ".claude" / "agents"

    if not src_dir.is_dir():
        print(f"  SKIP   agents  ({src_dir} missing)")
        return 0

    print(f"  Agents: {src_dir} → {dst_dir}")
    written = 0
    for src in sorted(src_dir.rglob("*.md")):
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        if write_file(dst, src.read_text(), force, dry_run):
            written += 1
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

    print(f"  Slash commands: {src_dir} → {dst_dir}")
    written = 0
    for src in sorted(src_dir.glob("*.md")):
        dst = dst_dir / src.name
        original = src.read_text()
        rewritten = rewrite_paths(original)
        if rewritten != original:
            print(f"    (rewriting paths in {src.name})")
        if write_file(dst, rewritten, force, dry_run):
            written += 1
    return written


def install_orchestrator_workflow(
    consuming_root: Path,
    force: bool,
    dry_run: bool,
) -> bool:
    """Drop the orchestrator workflow into the consuming repo."""
    dst = consuming_root / ".github" / "workflows" / "orchestrator.yml"
    print(f"  Orchestrator workflow: → {dst}")
    return write_file(dst, ORCHESTRATOR_WORKFLOW_TEMPLATE, force, dry_run)


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
    print(f"  Label-cleanup workflow: → {dst}")
    content = rewrite_paths(src.read_text())
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
    print(f"  Sync-claude workflow: → {dst}")
    content = rewrite_paths(src.read_text())
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
            "AI_AGILE_ROOT": SUBMODULE_NAME,
        },
        "_comment": (
            "Generated by ai-coding-standards2/get_started.py. "
            "AI_AGILE_ROOT tells the orchestrator where to find pipeline.json, "
            "status.sh, and the agent prompts when running from the consuming "
            "repo's root. Add to .gitignore if your project doesn't already "
            "ignore .claude/settings.local.json."
        ),
    }
    print(f"  Local settings: → {dst}")
    return write_file(dst, json.dumps(payload, indent=2) + "\n", force, dry_run)


def print_followup(consuming_root: Path) -> None:
    print()
    print("Done. Next steps:")
    print()
    print(f"  1. Add secrets to your repo (Settings → Secrets → Actions):")
    print(f"       ANTHROPIC_API_KEY  — your Anthropic API key")
    print(f"       AI_AGILE_BOT_TOKEN — a GitHub PAT for the bot account")
    print()
    print(f"  2. Commit the new files:")
    print(f"     git add .github/workflows/orchestrator.yml \\")
    print(f"             .github/workflows/label-cleanup.yml \\")
    print(f"             .github/workflows/sync-claude.yml \\")
    print(f"             .claude/agents/ \\")
    print(f"             .claude/commands/")
    print(f"     git commit -m 'Wire up ai-coding-standards2 orchestrator'")
    print()
    print(f"     NOTE: do NOT commit .claude/settings.local.json — it is")
    print(f"     developer-local. Add it to your .gitignore if not already.")
    print(f"     The sync-claude.yml workflow re-syncs agents and commands")
    print(f"     automatically every day; re-run get_started.py --force after")
    print(f"     updating the submodule to pick up changes immediately.")
    print()
    print(f"  3. Bootstrap the {{agent}}:{{status}} labels:")
    print(f"     Trigger the orchestrator workflow manually once from")
    print(f"     Actions → AI Agile orchestrator → Run workflow.")
    print(f"     The bootstrap-labels job runs automatically on workflow_dispatch")
    print(f"     and creates all required labels in one step.")
    print()
    print(f"     (Or run locally: bash {SUBMODULE_NAME}/.github/scripts/status.sh")
    print(f"      bootstrap-all {SUBMODULE_NAME}/pipeline/pipeline.json)")
    print()
    print(f"  4. Open a test issue with a problem statement and acceptance criteria.")
    print(f"     The orchestrator workflow fires on issue-opened; expect")
    print(f"     `01_product_docs/issue-classifier:wip` then `:complete` labels.")
    print()
    print(f"For full design + roadmap see {SUBMODULE_NAME}/docs/product/agile/.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Wire ai-coding-standards2 into a consuming repo."
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
        print("(dry run — no files will be written)")
    print()

    install_orchestrator_workflow(consuming_root, args.force, args.dry_run)
    install_label_cleanup_workflow(consuming_root, args.force, args.dry_run)
    install_sync_workflow(consuming_root, args.force, args.dry_run)
    install_agents(consuming_root, args.force, args.dry_run)
    install_slash_commands(consuming_root, args.force, args.dry_run)
    install_local_settings(consuming_root, args.force, args.dry_run)

    print_followup(consuming_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
