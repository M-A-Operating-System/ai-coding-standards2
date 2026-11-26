#!/usr/bin/env python3
"""Select the next batch of open issues for 00_ondemand/issue-obsolescence-audit.

Implements the single-key rotation rule from issue #741: each open issue's
sort key is the date on its current `issue-obsolescence-audit:reviewed-*`
label if it has one, otherwise the issue's own creation date. A never-
reviewed issue therefore sorts by its own age, not ahead of every reviewed
issue regardless of age. Sorting all open issues by this key ascending and
taking the first N always picks the oldest items overall, whether "oldest"
means longest since last reviewed or longest never reviewed.

Usage:
    python3 scripts/select_issues_for_audit.py --repo owner/repo [--batch-size 10]
"""

import argparse
import datetime
import json
import re
import sys
import urllib.error
import urllib.request

REVIEWED_LABEL_RE = re.compile(r'^issue-obsolescence-audit:reviewed-(\d{4}-\d{2}-\d{2})$')


class GitHubClient:
    def __init__(self, token):
        self._token = token

    def get(self, path):
        url = f'https://api.github.com{path}'
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {self._token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        })
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())


def list_open_issues(client, repo):
    """Return every open issue (never a PR) with its number, labels, created_at."""
    issues = []
    page = 1
    while True:
        batch = client.get(f'/repos/{repo}/issues?state=open&per_page=100&page={page}')
        if not batch:
            break
        issues.extend(item for item in batch if 'pull_request' not in item)
        page += 1
    return issues


def sort_key(issue):
    """Return the date (as a `datetime.date`) this issue sorts by.

    The reviewed-label date if present, else the issue's own creation date --
    pure and testable without any network access.
    """
    for label in issue.get('labels', []):
        m = REVIEWED_LABEL_RE.match(label['name'])
        if m:
            return datetime.date.fromisoformat(m.group(1))
    created = issue['created_at']
    return datetime.datetime.fromisoformat(created.replace('Z', '+00:00')).date()


def select_batch(issues, batch_size):
    """Return the `batch_size` issues with the oldest sort_key, oldest first."""
    return sorted(issues, key=sort_key)[:batch_size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, help='owner/repo')
    parser.add_argument('--batch-size', type=int, default=10)
    parser.add_argument('--token-env', default='GITHUB_TOKEN',
                         help='Environment variable holding the GitHub token')
    args = parser.parse_args()

    import os
    token = os.environ.get(args.token_env)
    if not token:
        print(f'select_issues_for_audit: ERROR: {args.token_env} is not set', file=sys.stderr)
        return 1

    client = GitHubClient(token)
    try:
        issues = list_open_issues(client, args.repo)
    except urllib.error.HTTPError as exc:
        print(f'select_issues_for_audit: ERROR: {exc}', file=sys.stderr)
        return 1

    batch = select_batch(issues, args.batch_size)
    for issue in batch:
        print(json.dumps({
            'number': issue['number'],
            'title': issue['title'],
            'sort_key': sort_key(issue).isoformat(),
        }))
    return 0


if __name__ == '__main__':
    sys.exit(main())
