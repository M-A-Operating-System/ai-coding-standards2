#!/usr/bin/env python3
"""Gherkin section parser for PDD measurement collection (issue #759, part 1 of #507).

Reads an issue body, locates the '## Acceptance criteria (Gherkin)' section,
extracts scenarios and step lines, counts keywords by type, and produces a
validated raw measurement JSON object on stdout.

Usage:
    python pipeline/calculate_pdd_measurements.py --issue <N>

The issue must carry 'prd-writer:approved'. On success, prints JSON to stdout
and 'AI_AGILE_STATUS: complete'. On failure, prints a message to stderr and
'AI_AGILE_STATUS: blocked'.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import NoReturn

METRIC_VERSION = "pdd-measures-v1"

GHERKIN_SECTION_HEADING = "## Acceptance criteria (Gherkin)"
USER_STORIES_HEADING_RE = re.compile(r"^#{1,6}\s+User stories\s*$", re.IGNORECASE)

SCENARIO_RE = re.compile(r"^#{1,6}\s+Scenario:\s*(.+)$")
STEP_RE = re.compile(r"^\s*\*\*(Given|When|Then|And|But)\*\*")

SECTION_END_RE = re.compile(r"^(---+|#{1,2}\s)")


def _gh_env() -> dict:
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "GH_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


def _gh_api(path: str) -> dict:
    repo = os.environ.get("REPO", "")
    if not repo:
        raise RuntimeError("REPO environment variable is not set")
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{path}"],
        capture_output=True,
        text=True,
        check=True,
        env=_gh_env(),
    )
    return json.loads(result.stdout)


def _fetch_issue(issue_number: int) -> dict:
    return _gh_api(str(issue_number))


def _extract_gherkin_section(body: str) -> str | None:
    """Return the text of the '## Acceptance criteria (Gherkin)' section.

    Section ends at the first '---' horizontal rule or '##'-or-higher heading
    that follows the section heading.
    """
    lines = body.splitlines()
    in_section = False
    section_lines: list[str] = []

    for line in lines:
        if not in_section:
            if line.strip() == GHERKIN_SECTION_HEADING:
                in_section = True
            continue

        if SECTION_END_RE.match(line):
            break
        section_lines.append(line)

    if not in_section:
        return None
    return "\n".join(section_lines)


def _extract_user_stories_count(body: str) -> int | None:
    """Count 'As a'-starting bullets in '## User stories'. None if absent."""
    lines = body.splitlines()
    in_section = False
    count = 0
    found_section = False

    for line in lines:
        if not in_section:
            if USER_STORIES_HEADING_RE.match(line.strip()):
                in_section = True
                found_section = True
            continue

        if re.match(r"^(---+|#{1,6}\s)", line):
            break

        stripped = line.lstrip("- *").strip()
        if stripped.startswith("As a"):
            count += 1

    if not found_section:
        return None
    return count


def _parse_gherkin_section(section: str) -> dict:
    """Parse the Gherkin section text and return raw measurement fields.

    Raises SystemExit on malformed input (zero-step scenario, etc.).
    """
    lines = section.splitlines()
    scenarios: list[dict] = []
    keyword_counts: dict[str, int] = {
        "given": 0, "when": 0, "then": 0, "and": 0, "but": 0,
    }

    current_scenario: dict | None = None
    in_fence = False

    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        scenario_match = SCENARIO_RE.match(line)
        if scenario_match:
            if current_scenario is not None:
                if current_scenario["steps"] == 0:
                    _fail(
                        f"malformed input: scenario '{current_scenario['scenario_title']}' "
                        "has no recognized step lines"
                    )
                scenarios.append(current_scenario)
            title = scenario_match.group(1).strip()
            current_scenario = {
                "scenario_index": len(scenarios) + 1,
                "scenario_title": title,
                "steps": 0,
            }
            continue

        if current_scenario is not None:
            step_match = STEP_RE.match(line)
            if step_match:
                keyword = step_match.group(1).lower()
                keyword_counts[keyword] += 1
                current_scenario["steps"] += 1

    if current_scenario is not None:
        if current_scenario["steps"] == 0:
            _fail(
                f"malformed input: scenario '{current_scenario['scenario_title']}' "
                "has no recognized step lines"
            )
        scenarios.append(current_scenario)

    total_steps = sum(s["steps"] for s in scenarios)

    return {
        "scenarios": len(scenarios),
        "scenario_step_counts": scenarios,
        "total_steps": total_steps,
        "given_steps": keyword_counts["given"],
        "when_steps": keyword_counts["when"],
        "then_steps": keyword_counts["then"],
        "and_steps": keyword_counts["and"],
        "but_steps": keyword_counts["but"],
    }


def _validate(measurements: dict) -> None:
    """Check the three reconciliation invariants. Raises SystemExit on failure."""
    if measurements["scenarios"] != len(measurements["scenario_step_counts"]):
        _fail("reconciliation failed: scenarios != len(scenario_step_counts)")
    if measurements["total_steps"] != sum(
        s["steps"] for s in measurements["scenario_step_counts"]
    ):
        _fail("reconciliation failed: total_steps != sum of scenario_step_counts")
    keyword_total = (
        measurements["given_steps"]
        + measurements["when_steps"]
        + measurements["then_steps"]
        + measurements["and_steps"]
        + measurements["but_steps"]
    )
    if measurements["total_steps"] != keyword_total:
        _fail("reconciliation failed: total_steps != sum of keyword counts")


def _fail(message: str) -> NoReturn:
    print(f"ERROR: {message}", file=sys.stderr)
    print("AI_AGILE_STATUS: blocked", file=sys.stderr, flush=True)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Gherkin section from an issue and output PDD measurements."
    )
    parser.add_argument("--issue", type=int, required=True, help="GitHub issue number")
    args = parser.parse_args()

    try:
        issue = _fetch_issue(args.issue)
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        _fail(f"failed to fetch issue #{args.issue}: {exc}")

    labels = [lbl["name"] for lbl in issue.get("labels", [])]
    if "prd-writer:approved" not in labels:
        _fail(
            f"issue #{args.issue} does not carry 'prd-writer:approved' "
            f"(labels: {labels})"
        )

    body = issue.get("body") or ""

    gherkin_section = _extract_gherkin_section(body)
    if gherkin_section is None:
        _fail(
            f"issue #{args.issue} has no '## Acceptance criteria (Gherkin)' section"
        )

    measurements = _parse_gherkin_section(gherkin_section)
    _validate(measurements)

    user_stories = _extract_user_stories_count(body)
    measurements["user_stories"] = user_stories
    measurements["metric_version"] = METRIC_VERSION

    print(json.dumps(measurements, indent=2))
    print("AI_AGILE_STATUS: complete", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
