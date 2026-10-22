#!/usr/bin/env python3
"""Release-note generator: PR/issue collation and Markdown rendering.

Accepts UTC start/end timestamp parameters, queries all merged PRs within the
window with full pagination, resolves the GitHub issues each PR closes, and
renders a grouped Markdown release-notes file plus a JSON diagnostics report.

Reopened-issue policy: issues that were closed by a merged PR in the window
but have since been reopened are included in the release notes and emitted as
diagnostic entries. They are never silently included as though still closed;
the release manager decides their disposition.

Usage:
    python3 scripts/release_note_generator.py \
        --repo owner/repo \
        --start 2026-10-01T00:00:00Z \
        --end   2026-10-08T00:00:00Z \
        --output release-notes.md \
        --diagnostics diagnostics.json \
        [--dry-run]
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLOSING_RE = re.compile(
    r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+'
    r'(?:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)|#(\d+))',
    re.IGNORECASE,
)

_RELEASE_NOTES_RE = re.compile(
    r'###\s+Release\s+Notes[ \t]*\n(.*?)(?=\n###|\Z)',
    re.DOTALL | re.IGNORECASE,
)

EXCLUDED_LABELS = frozenset({'dependencies', 'ignore-for-release'})

_CATEGORY_MAP = {
    'classification: security':    'Security',
    'classification: enhancement': 'Features',
    'classification: bug':         'Fixes',
    'classification: tech-debt':   'Maintenance',
}

CATEGORY_ORDER = ['Security', 'Features', 'Fixes', 'Maintenance', 'Other']


# ---------------------------------------------------------------------------
# GitHub REST client
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Parsing helpers (pure, no I/O -- testable without a client)
# ---------------------------------------------------------------------------

def parse_closing_refs(body, default_repo):
    """Return list of (repo, issue_number) from closing-keyword mentions in body.

    Same-repo references (#N) use default_repo.
    Cross-repo references (org/repo#N) keep their explicit repo.
    """
    refs = []
    for m in _CLOSING_RE.finditer(body or ''):
        cross_repo, cross_num, same_num = m.group(1), m.group(2), m.group(3)
        if cross_repo and cross_num:
            refs.append((cross_repo, int(cross_num)))
        else:
            refs.append((default_repo, int(same_num)))
    return refs


def extract_release_notes_section(body):
    """Return text under a '### Release Notes' heading, or None if absent/empty."""
    if not body:
        return None
    m = _RELEASE_NOTES_RE.search(body)
    if not m:
        return None
    text = m.group(1).strip()
    return text if text else None


def classify_issue(issue_labels, pr_labels):
    """Return category string.

    Falls back from issue classification labels to PR classification labels
    when the issue carries no classification label.
    """
    for lbl in issue_labels:
        cat = _CATEGORY_MAP.get(lbl)
        if cat:
            return cat
    for lbl in pr_labels:
        cat = _CATEGORY_MAP.get(lbl)
        if cat:
            return cat
    return 'Other'


# ---------------------------------------------------------------------------
# PR collation (requires I/O)
# ---------------------------------------------------------------------------

def _parse_dt(ts):
    return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))


def collect_merged_prs(client, repo, start, end):
    """Return all PRs merged in [start, end) from repo, with full pagination.

    Sorted by updated descending; stops early once the page's earliest
    updated_at is before start (merging a PR always updates updated_at).
    """
    results = []
    page = 1
    while True:
        prs = client.get(
            f'/repos/{repo}/pulls?state=closed&sort=updated'
            f'&direction=desc&per_page=100&page={page}'
        )
        if not prs:
            break
        earliest_updated = None
        for pr in prs:
            upd = pr.get('updated_at')
            if upd:
                upd_dt = _parse_dt(upd)
                if earliest_updated is None or upd_dt < earliest_updated:
                    earliest_updated = upd_dt
            merged_at = pr.get('merged_at')
            if not merged_at:
                continue
            merged_dt = _parse_dt(merged_at)
            if start <= merged_dt < end:
                results.append(pr)
        if earliest_updated and earliest_updated < start:
            break
        if len(prs) < 100:
            break
        page += 1
    return results


def collate(client, repo, start, end):
    """Collate issues closed by merged PRs in [start, end).

    Returns (entries, diagnostics, prs_count) where:
      entries     - list of dicts for render_markdown
      diagnostics - dict with cross_repo_refs, excluded, reopened, missing_release_notes
      prs_count   - total merged PRs found in the window
    """
    prs = collect_merged_prs(client, repo, start, end)

    # Map issue_number -> list of PR dicts (same-repo only, deduplicated)
    issue_to_prs = {}
    cross_repo_refs = []

    for pr in prs:
        body = pr.get('body') or ''
        refs = parse_closing_refs(body, repo)
        for ref_repo, issue_num in refs:
            if ref_repo != repo:
                cross_repo_refs.append({
                    'pr': pr['number'],
                    'ref': f'{ref_repo}#{issue_num}',
                })
                continue
            if issue_num not in issue_to_prs:
                issue_to_prs[issue_num] = []
            if pr not in issue_to_prs[issue_num]:
                issue_to_prs[issue_num].append(pr)

    diagnostics = {
        'cross_repo_refs': cross_repo_refs,
        'excluded': [],
        'reopened': [],
        'missing_release_notes': [],
    }
    entries = []

    for issue_num in sorted(issue_to_prs):
        closing_prs = issue_to_prs[issue_num]
        try:
            issue = client.get(f'/repos/{repo}/issues/{issue_num}')
        except urllib.error.HTTPError as exc:
            diagnostics['missing_release_notes'].append({
                'issue': issue_num,
                'reason': f'HTTP {exc.code} fetching issue',
            })
            continue

        issue_labels = [lbl['name'] for lbl in issue.get('labels', [])]

        excluded_present = EXCLUDED_LABELS & set(issue_labels)
        if excluded_present:
            diagnostics['excluded'].append({
                'issue': issue_num,
                'url': issue['html_url'],
                'reason': f'label: {", ".join(sorted(excluded_present))}',
            })
            continue

        reopened = issue.get('state') == 'open'
        if reopened:
            diagnostics['reopened'].append({
                'issue': issue_num,
                'url': issue['html_url'],
                'title': issue.get('title', ''),
            })

        pr_labels = [lbl['name'] for lbl in closing_prs[0].get('labels', [])]
        category = classify_issue(issue_labels, pr_labels)

        release_notes = extract_release_notes_section(issue.get('body') or '')
        pr_title = closing_prs[0].get('title', '')

        if release_notes is None:
            diagnostics['missing_release_notes'].append({
                'issue': issue_num,
                'url': issue['html_url'],
                'title': issue.get('title', ''),
                'fallback': pr_title,
            })

        entries.append({
            'issue_number': issue_num,
            'issue_title': issue.get('title', ''),
            'issue_url': issue['html_url'],
            'category': category,
            'release_notes': release_notes,
            'pr_title': pr_title,
            'pr_numbers': [pr['number'] for pr in closing_prs],
            'reopened': reopened,
        })

    return entries, diagnostics, len(prs)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_markdown(entries, start, end, repo):
    """Render issue-grouped Markdown release notes, categorised and sorted."""
    by_category = {cat: [] for cat in CATEGORY_ORDER}
    for entry in entries:
        cat = entry['category'] if entry['category'] in by_category else 'Other'
        by_category[cat].append(entry)

    start_str = start.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_str = end.strftime('%Y-%m-%dT%H:%M:%SZ')

    lines = [
        '# Release Notes',
        '',
        f'**Repository:** {repo}',
        f'**Period:** {start_str} to {end_str}',
        '',
    ]

    for cat in CATEGORY_ORDER:
        cat_entries = sorted(by_category[cat], key=lambda e: e['issue_number'])
        if not cat_entries:
            continue
        lines.append(f'## {cat}')
        lines.append('')
        for entry in cat_entries:
            prose = entry['release_notes'] if entry['release_notes'] is not None else entry['pr_title']
            suffix = ' *(reopened)*' if entry['reopened'] else ''
            lines.append(f'### [{entry["issue_title"]}]({entry["issue_url"]}){suffix}')
            lines.append('')
            lines.append(prose)
            lines.append('')

    return '\n'.join(lines)


def render_diagnostics(diagnostics, prs_count, entries_count):
    """Return pretty-printed JSON diagnostics report."""
    report = {
        'prs_in_window': prs_count,
        'issues_included': entries_count,
        **diagnostics,
    }
    return json.dumps(report, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_window_dt(ts):
    ts = ts.strip()
    if not (ts.endswith('Z') or '+' in ts[10:] or (ts.count('-') > 2 and ts[10:].count('-') > 0)):
        ts = ts + '+00:00'
    return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description='Generate release notes from merged PRs.')
    p.add_argument('--repo', required=True, help='owner/repo')
    p.add_argument('--start', required=True, help='UTC start timestamp (ISO-8601)')
    p.add_argument('--end', required=True, help='UTC end timestamp (ISO-8601)')
    p.add_argument('--output', default='release-notes.md', help='Output Markdown file path')
    p.add_argument('--diagnostics', default='diagnostics.json', help='Diagnostics JSON file path')
    p.add_argument('--dry-run', action='store_true', help='Print to stdout, do not write files')
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        print('Error: GH_TOKEN or GITHUB_TOKEN must be set', file=sys.stderr)
        sys.exit(1)

    start = _parse_window_dt(args.start)
    end = _parse_window_dt(args.end)

    client = GitHubClient(token)
    entries, diagnostics, prs_count = collate(client, args.repo, start, end)

    md = render_markdown(entries, start, end, args.repo)
    diag_json = render_diagnostics(diagnostics, prs_count, len(entries))

    if args.dry_run:
        print(md)
        print('--- diagnostics ---', file=sys.stderr)
        print(diag_json, file=sys.stderr)
        return

    Path(args.output).write_text(md)
    Path(args.diagnostics).write_text(diag_json)
    print(f'Wrote {args.output} and {args.diagnostics}')


if __name__ == '__main__':
    main()
