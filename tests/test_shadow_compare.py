"""Tests for shadow_compare.py (issue #603).

Realises the Gherkin scenario in
docs/features/github-actions-workflow-integration-replace-auto-generated-release-notes.md:

  Scenario: Shadow-run comparison confirms full coverage before production cutover
    -> TestCompare.test_full_coverage_passes
    -> TestCompare.test_missing_pr_reported
    -> TestCompare.test_extra_in_generator_not_a_failure
  Scenario: PRs outside selected window excluded with diagnostics in CI log
    -> (covered via prs_outside_window in test_release_note_generator.py)
"""

import datetime
import re
import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from shadow_compare import compare, extract_pr_numbers, get_prior_release

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# extract_pr_numbers
# ---------------------------------------------------------------------------

class TestExtractPrNumbers:
    def test_pr_url(self):
        body = 'Fix something by @user in https://github.com/org/repo/pull/42'
        assert 42 in extract_pr_numbers(body)

    def test_short_ref(self):
        body = 'Added feature (#123)'
        assert 123 in extract_pr_numbers(body)

    def test_multiple_prs(self):
        body = 'https://github.com/org/repo/pull/10\n(#20)'
        nums = extract_pr_numbers(body)
        assert nums == {10, 20}

    def test_empty_body(self):
        assert extract_pr_numbers('') == set()
        assert extract_pr_numbers(None) == set()

    def test_no_duplicates(self):
        body = '/pull/5 /pull/5 (#5)'
        assert extract_pr_numbers(body) == {5}


# ---------------------------------------------------------------------------
# get_prior_release
# ---------------------------------------------------------------------------

class TestGetPriorRelease:
    def _make_release(self, tag, published_at):
        return {'tag_name': tag, 'published_at': published_at, 'body': ''}

    def test_returns_most_recent_before_cutoff(self):
        releases = [
            self._make_release('v2.5.0', '2026-10-15T10:00:00Z'),
            self._make_release('v2.4.0', '2026-10-08T10:00:00Z'),
            self._make_release('v2.3.0', '2026-10-01T10:00:00Z'),
        ]
        client = MagicMock()
        client.get.return_value = releases
        result = get_prior_release(client, 'owner/repo', '2026-10-15T10:00:00Z')
        assert result['tag_name'] == 'v2.4.0'

    def test_returns_none_when_no_prior(self):
        releases = [
            self._make_release('v2.5.0', '2026-10-15T10:00:00Z'),
        ]
        client = MagicMock()
        client.get.return_value = releases
        result = get_prior_release(client, 'owner/repo', '2026-10-15T10:00:00Z')
        assert result is None

    def test_returns_none_for_empty_list(self):
        client = MagicMock()
        client.get.return_value = []
        result = get_prior_release(client, 'owner/repo', '2026-10-15T10:00:00Z')
        assert result is None

    def test_returns_max_published_at_not_first_in_api_order(self):
        # API returns by created_at desc; a draft published retroactively may appear
        # later in the list than its published_at implies. The function must return
        # the release with the largest published_at that is still before the cutoff.
        releases = [
            self._make_release('v2.5.0', '2026-10-15T10:00:00Z'),
            # v2.3.0 was created first but published later than v2.4.0
            self._make_release('v2.3.0', '2026-10-09T12:00:00Z'),
            self._make_release('v2.4.0', '2026-10-08T10:00:00Z'),
        ]
        client = MagicMock()
        client.get.return_value = releases
        result = get_prior_release(client, 'owner/repo', '2026-10-15T10:00:00Z')
        assert result['tag_name'] == 'v2.3.0'


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

def _make_pr(number, merged_at, body='', labels=None, updated_at=None, title='PR title'):
    if updated_at is None:
        updated_at = merged_at
    return {
        'number': number,
        'title': title,
        'body': body,
        'merged_at': merged_at,
        'updated_at': updated_at,
        'labels': [{'name': lbl} for lbl in (labels or [])],
        'html_url': f'https://github.com/owner/repo/pull/{number}',
    }


def _make_issue(number, title='Issue', state='closed', labels=None, body=''):
    return {
        'number': number,
        'title': title,
        'state': state,
        'html_url': f'https://github.com/owner/repo/issues/{number}',
        'labels': [{'name': lbl} for lbl in (labels or [])],
        'body': body,
    }


class TestCompare:
    def _make_client(self, releases, prs, issues):
        """Build a mock GitHubClient that serves releases, PRs, and issues."""
        client = MagicMock()

        def get_side_effect(path):
            # Release by tag
            if '/releases/tags/' in path:
                tag = path.split('/releases/tags/')[-1]
                for r in releases:
                    if r['tag_name'] == tag:
                        return r
                import urllib.error
                raise urllib.error.HTTPError(path, 404, 'Not Found', {}, None)

            # Release list (for get_prior_release)
            if '/releases?' in path:
                return releases

            # PRs list
            if '/pulls?' in path:
                m = re.search(r'[?&]page=(\d+)', path)
                page = int(m.group(1)) if m else 1
                if page == 1:
                    return prs
                return []

            # Issue by number
            for num, issue in issues.items():
                if f'/issues/{num}' in path:
                    return issue

            raise ValueError(f'Unexpected path: {path}')

        client.get.side_effect = get_side_effect
        return client

    def test_full_coverage_passes(self):
        target = {
            'tag_name': 'v2.5.0',
            'published_at': '2026-10-15T10:00:00Z',
            'body': 'https://github.com/owner/repo/pull/20',
        }
        prior = {
            'tag_name': 'v2.4.0',
            'published_at': '2026-10-08T10:00:00Z',
            'body': '',
        }
        pr = _make_pr(20, merged_at='2026-10-12T10:00:00Z',
                      updated_at='2026-10-12T10:00:00Z', body='Closes #5')
        issue = _make_issue(5, labels=['classification: enhancement'],
                            body='### Release Notes\n\nNew feature.')
        client = self._make_client([target, prior], [pr], {5: issue})
        result = compare(client, 'owner/repo', 'v2.5.0')
        assert result['coverage_ok'] is True
        assert result['missing_from_generator'] == []

    def test_missing_pr_reported(self):
        target = {
            'tag_name': 'v2.5.0',
            'published_at': '2026-10-15T10:00:00Z',
            'body': '/pull/20\n/pull/21',
        }
        prior = {
            'tag_name': 'v2.4.0',
            'published_at': '2026-10-08T10:00:00Z',
            'body': '',
        }
        # Only PR 20 closes an issue; PR 21 does not.
        pr20 = _make_pr(20, merged_at='2026-10-12T10:00:00Z',
                        updated_at='2026-10-12T10:00:00Z', body='Closes #5')
        pr21 = _make_pr(21, merged_at='2026-10-13T10:00:00Z',
                        updated_at='2026-10-13T10:00:00Z', body='No closing ref')
        issue = _make_issue(5, labels=['classification: enhancement'],
                            body='### Release Notes\n\nNew feature.')
        client = self._make_client([target, prior], [pr20, pr21], {5: issue})
        result = compare(client, 'owner/repo', 'v2.5.0')
        # PR 21 is in GitHub notes but not covered by the generator (no issue)
        assert result['coverage_ok'] is False
        assert 21 in result['missing_from_generator']

    def test_extra_in_generator_not_a_failure(self):
        target = {
            'tag_name': 'v2.5.0',
            'published_at': '2026-10-15T10:00:00Z',
            'body': '/pull/20',
        }
        prior = {
            'tag_name': 'v2.4.0',
            'published_at': '2026-10-08T10:00:00Z',
            'body': '',
        }
        # PR 20 and PR 22 both close issues; only PR 20 is in GitHub notes.
        pr20 = _make_pr(20, merged_at='2026-10-12T10:00:00Z',
                        updated_at='2026-10-12T10:00:00Z', body='Closes #5')
        pr22 = _make_pr(22, merged_at='2026-10-12T10:00:00Z',
                        updated_at='2026-10-12T10:00:00Z', body='Closes #6')
        issue5 = _make_issue(5, labels=['classification: enhancement'],
                             body='### Release Notes\n\nA.')
        issue6 = _make_issue(6, labels=['classification: enhancement'],
                             body='### Release Notes\n\nB.')
        client = self._make_client([target, prior], [pr20, pr22], {5: issue5, 6: issue6})
        result = compare(client, 'owner/repo', 'v2.5.0')
        assert result['coverage_ok'] is True
        assert 22 in result['extra_in_generator']

    def test_release_not_found_returns_error(self):
        client = self._make_client([], [], {})
        result = compare(client, 'owner/repo', 'v9.9.9')
        assert 'error' in result

    def test_no_prior_release_uses_epoch(self):
        target = {
            'tag_name': 'v1.0.0',
            'published_at': '2026-10-15T10:00:00Z',
            'body': '',
        }
        client = self._make_client([target], [], {})
        result = compare(client, 'owner/repo', 'v1.0.0')
        assert result['window_start'].startswith('1970')
        assert result['coverage_ok'] is True
