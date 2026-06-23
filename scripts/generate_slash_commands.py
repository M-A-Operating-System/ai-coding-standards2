#!/usr/bin/env python3
"""Generate .claude/commands/maos-*.md slash commands from pipeline.json.

One command file per non-script agent. Creates missing files, updates
changed files, and deletes stale maos-*.md files for removed agents.

Usage:
    python3 scripts/generate_slash_commands.py
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PIPELINE_JSON = REPO_ROOT / "pipeline" / "pipeline.json"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"

COMMAND_TEMPLATE = """\
# {title}

{description}

## Input

`$ARGUMENTS` — GitHub issue or PR number (e.g. `42`)

## Instructions

Follow the `run-agent` command with pre-filled arguments:
`run-agent {agent} $ARGUMENTS`
"""


def _short_name(agent_path: str) -> str:
    """'03_execute/pr-reviewer' → 'pr-reviewer'"""
    return agent_path.split("/")[-1]


def _first_sentence(text: str) -> str:
    """Return the first sentence of a description string."""
    sentence = re.split(r"\.\ ", text.strip())[0].rstrip(".")
    # Hard-wrap at 90 chars so the heading stays readable
    if len(sentence) > 90:
        sentence = sentence[:87] + "…"
    return sentence


def _render(entry: dict) -> str:
    agent = entry["agent"]
    short = _short_name(agent)
    raw_desc = entry.get("description", "")
    first = _first_sentence(raw_desc)
    title = f"maos-{short}"
    description = f"Run the `{agent}` pipeline agent. {first}."
    return COMMAND_TEMPLATE.format(
        title=title,
        description=description,
        agent=agent,
    )


def main() -> int:
    pipeline = json.loads(PIPELINE_JSON.read_text())

    # Agent-type entries only — script-type steps (create-pr, ci-gate) are
    # not interactively invokable and get no slash command.
    agents = [
        e for e in pipeline["pipeline"]
        if e.get("type", "agent") == "agent"
    ]

    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

    # Expected filename → pipeline entry
    expected: dict[str, dict] = {
        f"maos-{_short_name(e['agent'])}.md": e
        for e in agents
    }

    created, updated, deleted = [], [], []

    for fname, entry in expected.items():
        content = _render(entry)
        dest = COMMANDS_DIR / fname
        if not dest.exists():
            dest.write_text(content)
            created.append(fname)
        elif dest.read_text() != content:
            dest.write_text(content)
            updated.append(fname)

    # Remove stale maos-*.md files for agents no longer in pipeline.json
    for existing in sorted(COMMANDS_DIR.glob("maos-*.md")):
        if existing.name not in expected:
            existing.unlink()
            deleted.append(existing.name)

    if created:
        print(f"Created:  {', '.join(sorted(created))}")
    if updated:
        print(f"Updated:  {', '.join(sorted(updated))}")
    if deleted:
        print(f"Deleted:  {', '.join(sorted(deleted))}")
    if not created and not updated and not deleted:
        print("Slash commands already up-to-date.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
