#!/usr/bin/env python3
"""
migrate_labels.py

Renames non-conforming pipeline labels to their canonical {agent}:{status}
equivalents across both the repo label registry and every open issue.

Reads the migration map from pipeline.json (comparing old hard-coded names
against current trigger/gate label values) and applies the changes via the
GitHub REST API using GITHUB_TOKEN.

Run via bootstrap-labels.yml or manually:
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
# Labels that existed before the {agent}:{status} convention was enforced.
# Map: old_label -> new_label
# ---------------------------------------------------------------------------
LABEL_MIGRATIONS = {
    "prd:approved":           "01_product_docs/prd-writer:approved",
    "pr:approved":            "05_execute/pr-reviewer:approved",
    "build:requested":        "05_execute/coder:requested",
    "pr-review:requested":    "05_execute/pr-reviewer:requested",
    "codebase-review:requested": "09_gap_assessment/codebase-reviewer:requested",
}

# Colours and descriptions for labels that need to be created.
# Derived from statuses.json; kept here so the script is self-contained.
LABEL_SPECS = {
    "01_product_docs/prd-writer:approved":        ("0075CA", "Approve 01_product_docs/prd-writer output to advance pipeline"),
    "05_execute/pr-reviewer:approved":            ("0075CA", "Approve 05_execute/pr-reviewer output to advance pipeline"),
    "05_execute/coder:requested":                 ("FBCA04", "Invoke 05_execute/coder"),
    "05_execute/pr-reviewer:requested":           ("FBCA04", "Invoke 05_execute/pr-reviewer"),
    "09_gap_assessment/codebase-reviewer:requested": ("FBCA04", "Invoke 09_gap_assessment/codebase-reviewer"),
}


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
        print(f"  HTTP {exc.code} {method} {path}: {body_text}", file=sys.stderr)
        return None


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
    issues = []
    page = 1
    encoded = urllib.parse.quote(label, safe="")
    while True:
        batch = _api("GET", f"/repos/{repo}/issues?labels={encoded}&state=open&per_page=100&page={page}")
        if not batch:
            break
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return issues


def replace_label_on_issue(repo, issue_number, old_label, new_label, all_issue_labels):
    updated = [lbl for lbl in all_issue_labels if lbl != old_label] + [new_label]
    result = _api("PATCH", f"/repos/{repo}/issues/{issue_number}", {"labels": updated})
    if result is not None:
        print(f"  issue #{issue_number}: {old_label!r} → {new_label!r}")


def main():
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print("ERROR: GITHUB_REPOSITORY not set", file=sys.stderr)
        sys.exit(1)

    print(f"Migrating labels in {repo}")

    existing_labels = list_labels(repo)

    # Step 1 — create new conforming labels if absent
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

    # Step 2 — migrate open issues
    print("\nMigrating open issues...")
    for old_label, new_label in LABEL_MIGRATIONS.items():
        if old_label not in existing_labels:
            continue
        issues = issues_with_label(repo, old_label)
        if not issues:
            print(f"  no issues carry {old_label!r}")
            continue
        for issue in issues:
            current_labels = [lbl["name"] for lbl in issue["labels"]]
            replace_label_on_issue(
                repo,
                issue["number"],
                old_label,
                new_label,
                current_labels,
            )
            time.sleep(0.2)  # stay under secondary rate limit

    # Step 3 — delete old labels from repo
    print("\nDeleting old non-conforming labels...")
    for old_label in LABEL_MIGRATIONS:
        if old_label in existing_labels:
            _api("DELETE", f"/repos/{repo}/labels/{urllib.parse.quote(old_label, safe='')}")
            print(f"  deleted  {old_label}")

    print("\nLabel migration complete.")


if __name__ == "__main__":
    main()
