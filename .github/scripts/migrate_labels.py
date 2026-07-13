#!/usr/bin/env python3
"""
migrate_labels.py

Renames pipeline labels from the old {phase}/{agent}:{status} format to
the short {agent}:{status} format across both the repo label registry and
every open issue and PR.

Run by the Onboard job's label-bootstrap step, or manually:
    python .github/scripts/migrate_labels.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

# ---------------------------------------------------------------------------
# Full migration map — old_label -> new_label.
# Covers: phase-prefixed status labels (8 agents × 6 statuses),
#         phase-prefixed trigger/gate labels,
#         and legacy pre-convention labels from earlier versions.
# ---------------------------------------------------------------------------

_AGENTS = [
    "01_product_docs/issue-classifier",
    "01_product_docs/prd-writer",
    "01_product_docs/create-pr",
    "01_product_docs/prd-docs-updater",
    "05_execute/coder",
    "05_execute/ci-gate",
    "05_execute/pr-reviewer",
    "09_gap_assessment/codebase-reviewer",
]

_STATUSES = ["wip", "complete", "review", "blocked", "failed", "skipped"]

# Build status-label migrations for every agent × status combination.
LABEL_MIGRATIONS: dict[str, str] = {}
for _agent in _AGENTS:
    _short = _agent.rsplit("/", 1)[-1]
    for _status in _STATUSES:
        LABEL_MIGRATIONS[f"{_agent}:{_status}"] = f"{_short}:{_status}"

# Special trigger and gate labels (phase-prefixed).
LABEL_MIGRATIONS.update({
    "01_product_docs/prd-writer:approved":           "prd-writer:approved",
    "01_product_docs/prd-docs-updater:approved":     "prd-docs-updater:approved",
    "05_execute/pr-reviewer:approved":               "pr-reviewer:approved",
    "05_execute/coder:requested":                    "coder:requested",
    "05_execute/pr-reviewer:requested":              "pr-reviewer:requested",
    "09_gap_assessment/codebase-reviewer:requested": "codebase-reviewer:requested",
})

# Legacy pre-convention labels (from before phase-prefixed naming).
LABEL_MIGRATIONS.update({
    "prd:approved":              "prd-writer:approved",
    "pr:approved":               "pr-reviewer:approved",
    "build:requested":           "coder:requested",
    "pr-review:requested":       "pr-reviewer:requested",
    "codebase-review:requested": "codebase-reviewer:requested",
})

# ---------------------------------------------------------------------------
# Label colours and descriptions for every new-format label that may need
# creating. Derived from statuses.json; kept here so the script is
# self-contained.
# ---------------------------------------------------------------------------

_STATUS_COLOURS = {
    "wip":       "E4E669",
    "complete":  "0E8A16",
    "review":    "D4C5F9",
    "blocked":   "E99695",
    "failed":    "B60205",
    "skipped":   "BFD4F2",
    "approved":  "0075CA",
    "requested": "FBCA04",
}

LABEL_SPECS: dict[str, tuple[str, str]] = {}
_seen_specs: set[str] = set()
for _old, _new in LABEL_MIGRATIONS.items():
    if _new in _seen_specs:
        continue
    _seen_specs.add(_new)
    _suffix = _new.rsplit(":", 1)[-1]
    _colour = _STATUS_COLOURS.get(_suffix, "FBCA04")
    _agent_short = _new.rsplit(":", 1)[0]
    LABEL_SPECS[_new] = (_colour, f"Pipeline label for {_agent_short}")


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _api(method, path, body=None):
    token = os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read()) if resp.status not in (204,) else None
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode()
        if exc.code in (404, 422):
            return None
        raise RuntimeError(
            f"GitHub API error {exc.code} {method} {path}: {body_text}"
        ) from exc


def list_labels(repo):
    labels = []
    page = 1
    while True:
        batch = _api("GET", f"/repos/{repo}/labels?per_page=100&page={page}")
        if not batch:
            break
        labels.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return {lbl["name"] for lbl in labels}


def issues_with_label(repo, label):
    items = []
    page = 1
    encoded = urllib.parse.quote(label, safe="")
    while True:
        batch = _api("GET", f"/repos/{repo}/issues?labels={encoded}&state=open&per_page=100&page={page}")
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items


def replace_label_on_issue(repo, issue_number, old_label, new_label, all_issue_labels):
    updated = [lbl for lbl in all_issue_labels if lbl != old_label] + [new_label]
    result = _api("PATCH", f"/repos/{repo}/issues/{issue_number}", {"labels": updated})
    if result is not None:
        print(f"  #{issue_number}: {old_label!r} → {new_label!r}")


def main():
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("ERROR: GITHUB_REPOSITORY not set", file=sys.stderr)
        sys.exit(1)

    print(f"Migrating labels in {repo}")

    existing_labels = list_labels(repo)

    # Step 1 — create new short-format labels if absent
    print("\nEnsuring new labels exist...")
    for name, (colour, description) in LABEL_SPECS.items():
        if name not in existing_labels:
            result = _api("POST", f"/repos/{repo}/labels", {
                "name": name,
                "color": colour,
                "description": description,
            })
            if result:
                print(f"  created  {name}")
        else:
            print(f"  exists   {name}")

    # Step 2 — migrate open issues and PRs
    print("\nMigrating open issues and PRs...")
    for old_label, new_label in LABEL_MIGRATIONS.items():
        if old_label == new_label:
            continue
        if old_label not in existing_labels:
            continue
        items = issues_with_label(repo, old_label)
        if not items:
            print(f"  no open items carry {old_label!r}")
            continue
        for item in items:
            current_labels = [lbl["name"] for lbl in item["labels"]]
            replace_label_on_issue(
                repo,
                item["number"],
                old_label,
                new_label,
                current_labels,
            )
            time.sleep(0.2)  # stay under secondary rate limit

    # Step 3 — delete old labels from repo
    print("\nDeleting old labels...")
    for old_label, new_label in LABEL_MIGRATIONS.items():
        if old_label == new_label:
            continue
        if old_label in existing_labels:
            _api("DELETE", f"/repos/{repo}/labels/{urllib.parse.quote(old_label, safe='')}")
            print(f"  deleted  {old_label}")

    print("\nLabel migration complete.")


if __name__ == "__main__":
    main()
