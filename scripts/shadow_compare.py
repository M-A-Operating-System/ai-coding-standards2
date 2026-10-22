#!/usr/bin/env python3
"""Shadow-run comparison: validate Python generator coverage against GitHub-generated notes.

Fetches the GitHub-generated release notes body for a given release tag, runs
the Python generator for the same window (from the prior published release to
the target release), and reports which PRs in the GitHub notes are not present
in the generator output and vice versa.

A non-zero exit code means coverage gaps were found.

Usage:
    python3 scripts/shadow_compare.py \
        --repo owner/repo \
        --release-tag v2.5.0 \
        [--output comparison.json]
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from release_note_generator import GitHubClient, collate, _parse_dt

_PR_URL_RE = re.compile(r'/pull/(\d+)')
_PR_REF_RE = re.compile(r'\(#(\d+)\)')


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def extract_pr_numbers(text):
    """Extract PR numbers from GitHub-generated release notes text.

    Handles both full PR URLs (.../pull/N) and short references (#N).
    """
    nums = set()
    for m in _PR_URL_RE.finditer(text or ''):
        nums.add(int(m.group(1)))
    for m in _PR_REF_RE.finditer(text or ''):
        nums.add(int(m.group(1)))
    return nums


# ---------------------------------------------------------------------------
# Release lookup helpers
# ---------------------------------------------------------------------------

def get_release_by_tag(client, repo, tag):
    """Return the release dict for the given tag, or None if not found."""
    try:
        return client.get(f'/repos/{repo}/releases/tags/{tag}')
    except urllib.error.HTTPError:
        return None


def get_prior_release(client, repo, before_published_at):
    """Return the most recently published release with published_at < before_published_at."""
    cutoff = _parse_dt(before_published_at)
    page = 1
    while True:
        releases = client.get(
            f'/repos/{repo}/releases?per_page=100&page={page}'
        )
        if not releases:
            break
        for r in releases:
            pub = r.get('published_at')
            if pub and _parse_dt(pub) < cutoff:
                return r
        if len(releases) < 100:
            break
        page += 1
    return None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare(client, repo, release_tag):
    """Compare Python generator output against GitHub-generated notes.

    Returns a dict describing the comparison:
      release_tag          -- the tag compared
      window_start         -- ISO-8601 window start used
      window_end           -- ISO-8601 window end (target release published_at)
      prs_in_github_notes  -- sorted list of PR numbers found in GitHub notes
      prs_in_generator     -- sorted list of PR numbers covered by the generator
      missing_from_generator -- PRs in GitHub notes not covered by generator
      extra_in_generator   -- PRs in generator not referenced in GitHub notes
      coverage_ok          -- True when missing_from_generator is empty
    """
    release = get_release_by_tag(client, repo, release_tag)
    if release is None:
        return {'error': f'release {release_tag} not found in {repo}'}

    gh_notes_body = release.get('body') or ''
    gh_prs = extract_pr_numbers(gh_notes_body)

    window_end = _parse_dt(release['published_at'])
    prior = get_prior_release(client, repo, release['published_at'])
    if prior:
        window_start = _parse_dt(prior['published_at'])
    else:
        window_start = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

    entries, diagnostics, _ = collate(client, repo, window_start, window_end)
    gen_prs = set(diagnostics.get('prs_covered', []))

    missing = sorted(gh_prs - gen_prs)
    extra = sorted(gen_prs - gh_prs)

    return {
        'release_tag': release_tag,
        'window_start': window_start.isoformat(),
        'window_end': window_end.isoformat(),
        'prs_in_github_notes': sorted(gh_prs),
        'prs_in_generator': sorted(gen_prs),
        'missing_from_generator': missing,
        'extra_in_generator': extra,
        'coverage_ok': len(missing) == 0,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description='Compare Python generator coverage against GitHub-generated notes.'
    )
    p.add_argument('--repo', required=True, help='owner/repo')
    p.add_argument('--release-tag', required=True, help='Release tag to compare against')
    p.add_argument('--output', default='-',
                   help='Output JSON file path, or - for stdout (default: -)')
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        print('Error: GH_TOKEN or GITHUB_TOKEN must be set', file=sys.stderr)
        sys.exit(1)

    client = GitHubClient(token)
    result = compare(client, args.repo, args.release_tag)

    output = json.dumps(result, indent=2)
    if args.output == '-':
        print(output)
    else:
        Path(args.output).write_text(output)
        print(f'Wrote {args.output}', file=sys.stderr)

    if 'error' in result:
        print(f'Error: {result["error"]}', file=sys.stderr)
        sys.exit(1)

    missing = result.get('missing_from_generator', [])
    if missing:
        print(
            f'Coverage FAILED: {len(missing)} PR(s) in GitHub notes not in generator output: '
            + ', '.join(f'#{n}' for n in missing),
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f'Coverage OK: {len(result["prs_in_github_notes"])} PR(s) in GitHub notes, '
        f'{len(result["prs_in_generator"])} PR(s) in generator output.',
        file=sys.stderr,
    )


if __name__ == '__main__':
    main()
