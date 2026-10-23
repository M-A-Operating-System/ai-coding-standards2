"""Tests for the release-note generator (issue #601).

Realises the Gherkin scenarios in
docs/features/release-note-generator-pr-issue-collation-and-markdown-rendering.md:

  Scenario: Query and paginate merged PRs within UTC date range
    -> TestCollectMergedPrs.test_pagination_*
    -> TestCollectMergedPrs.test_excludes_open_and_draft_prs
  Scenario: Deduplicate issues closed by multiple PRs
    -> TestCollate.test_deduplication_across_prs
  Scenario: Apply documented behavior for issues reopened after merge
    -> TestCollate.test_reopened_issue_emits_diagnostic
  Scenario: Include issue title, URL, and Release Notes prose in correct category
    -> TestRenderMarkdown.test_issue_in_correct_category
  Scenario: Exclude issues carrying excluded labels
    -> TestCollate.test_excluded_label_dependencies
    -> TestCollate.test_excluded_label_ignore_for_release
  Scenario: Fall back to PR classification when issue has no classification label
    -> TestClassifyIssue.test_falls_back_to_pr_label
  Scenario: Emit diagnostic and apply fallback for missing Release Notes section
    -> TestCollate.test_missing_release_notes_uses_pr_title_fallback
  Scenario: Dry-run produces reproducible output without publishing
    -> TestReproducibility.test_deterministic_ordering
"""

import datetime
import re
import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from release_note_generator import (
    CATEGORY_ORDER,
    EXCLUDED_LABELS,
    classify_issue,
    collate,
    collect_merged_prs,
    extract_release_notes_section,
    parse_closing_refs,
    render_diagnostics,
    render_markdown,
)

UTC = datetime.timezone.utc
_START = datetime.datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
_END = datetime.datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(ts):
    return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))


def _make_pr(number, merged_at=None, body='', labels=None, updated_at=None, title='PR title'):
    if updated_at is None:
        updated_at = merged_at or '2026-10-05T12:00:00Z'
    return {
        'number': number,
        'title': title,
        'body': body,
        'merged_at': merged_at,
        'updated_at': updated_at,
        'labels': [{'name': lbl} for lbl in (labels or [])],
        'html_url': f'https://github.com/owner/repo/pull/{number}',
    }


def _make_issue(number, title='Issue title', state='closed', labels=None, body='', url=None):
    return {
        'number': number,
        'title': title,
        'state': state,
        'html_url': url or f'https://github.com/owner/repo/issues/{number}',
        'labels': [{'name': lbl} for lbl in (labels or [])],
        'body': body,
    }


# ---------------------------------------------------------------------------
# parse_closing_refs
# ---------------------------------------------------------------------------

class TestParseClosingRefs:
    def test_closes_same_repo(self):
        refs = parse_closing_refs('Closes #42', 'owner/repo')
        assert refs == [('owner/repo', 42)]

    def test_fixes_same_repo(self):
        refs = parse_closing_refs('Fixes #7', 'owner/repo')
        assert refs == [('owner/repo', 7)]

    def test_resolves_same_repo(self):
        refs = parse_closing_refs('Resolves #100', 'owner/repo')
        assert refs == [('owner/repo', 100)]

    def test_cross_repo_reference(self):
        refs = parse_closing_refs('Closes other/repo#55', 'owner/repo')
        assert refs == [('other/repo', 55)]

    def test_multiple_refs(self):
        refs = parse_closing_refs('Fixes #1\nCloses #2', 'owner/repo')
        assert refs == [('owner/repo', 1), ('owner/repo', 2)]

    def test_case_insensitive(self):
        refs = parse_closing_refs('CLOSES #9', 'owner/repo')
        assert refs == [('owner/repo', 9)]

    def test_empty_body(self):
        assert parse_closing_refs('', 'owner/repo') == []
        assert parse_closing_refs(None, 'owner/repo') == []

    def test_fixed_variant(self):
        refs = parse_closing_refs('fixed #3', 'owner/repo')
        assert refs == [('owner/repo', 3)]

    def test_close_without_s_d(self):
        refs = parse_closing_refs('close #10', 'owner/repo')
        assert refs == [('owner/repo', 10)]


# ---------------------------------------------------------------------------
# extract_release_notes_section
# ---------------------------------------------------------------------------

class TestExtractReleaseNotesSection:
    def test_extracts_prose(self):
        body = '## Summary\n\nSome text.\n\n### Release Notes\n\nNew feature added.\n'
        assert extract_release_notes_section(body) == 'New feature added.'

    def test_returns_none_when_absent(self):
        body = '## Summary\n\nSome text.'
        assert extract_release_notes_section(body) is None

    def test_returns_none_for_empty_body(self):
        assert extract_release_notes_section('') is None
        assert extract_release_notes_section(None) is None

    def test_returns_none_for_empty_section(self):
        body = '### Release Notes\n\n### Other Section\n'
        assert extract_release_notes_section(body) is None

    def test_stops_at_next_heading(self):
        body = '### Release Notes\n\nLine one.\n\n### Other\n\nLine two.'
        result = extract_release_notes_section(body)
        assert 'Line one.' in result
        assert 'Line two.' not in result

    def test_case_insensitive_heading(self):
        body = '### release notes\n\nsome prose\n'
        assert extract_release_notes_section(body) == 'some prose'


# ---------------------------------------------------------------------------
# classify_issue
# ---------------------------------------------------------------------------

class TestClassifyIssue:
    def test_enhancement_to_features(self):
        assert classify_issue(['classification: enhancement'], []) == 'Features'

    def test_bug_to_fixes(self):
        assert classify_issue(['classification: bug'], []) == 'Fixes'

    def test_tech_debt_to_maintenance(self):
        assert classify_issue(['classification: tech-debt'], []) == 'Maintenance'

    def test_security_to_security(self):
        assert classify_issue(['classification: security'], []) == 'Security'

    def test_no_classification_returns_other(self):
        assert classify_issue([], []) == 'Other'

    def test_falls_back_to_pr_label(self):
        assert classify_issue([], ['classification: enhancement']) == 'Features'

    def test_issue_label_takes_priority_over_pr(self):
        result = classify_issue(
            ['classification: bug'],
            ['classification: enhancement'],
        )
        assert result == 'Fixes'

    def test_unrecognised_labels_return_other(self):
        assert classify_issue(['unrelated'], ['also-unrelated']) == 'Other'


# ---------------------------------------------------------------------------
# collect_merged_prs -- pagination scenarios
# ---------------------------------------------------------------------------

class TestCollectMergedPrs:
    def _make_client(self, pages):
        """pages: list of lists of PR dicts returned per page call."""
        client = MagicMock()
        client.get.side_effect = pages + [[]]
        return client

    def test_returns_prs_merged_in_window(self):
        pr = _make_pr(1, merged_at='2026-10-04T10:00:00Z')
        client = self._make_client([[pr]])
        in_window, outside = collect_merged_prs(client, 'owner/repo', _START, _END)
        assert len(in_window) == 1
        assert in_window[0]['number'] == 1

    def test_excludes_prs_outside_window(self):
        pr_before = _make_pr(1, merged_at='2026-09-30T23:59:59Z',
                              updated_at='2026-09-30T23:59:59Z')
        pr_after = _make_pr(2, merged_at='2026-10-08T00:00:00Z',
                             updated_at='2026-10-08T00:00:00Z')
        pr_in = _make_pr(3, merged_at='2026-10-04T12:00:00Z',
                          updated_at='2026-10-04T12:00:00Z')
        client = self._make_client([[pr_after, pr_in, pr_before]])
        in_window, outside = collect_merged_prs(client, 'owner/repo', _START, _END)
        assert [r['number'] for r in in_window] == [3]
        assert set(outside) == {1, 2}

    def test_excludes_unmerged_prs(self):
        pr_open = _make_pr(1, merged_at=None, updated_at='2026-10-05T00:00:00Z')
        pr_closed = _make_pr(2, merged_at=None, updated_at='2026-10-05T00:00:00Z')
        client = self._make_client([[pr_open, pr_closed]])
        in_window, outside = collect_merged_prs(client, 'owner/repo', _START, _END)
        assert in_window == []
        assert outside == []

    def test_pagination_collects_all_pages(self):
        page1 = [_make_pr(i, merged_at='2026-10-04T10:00:00Z',
                           updated_at='2026-10-04T10:00:00Z')
                 for i in range(1, 101)]
        page2 = [_make_pr(101, merged_at='2026-10-03T10:00:00Z',
                           updated_at='2026-10-03T10:00:00Z')]
        client = self._make_client([page1, page2])
        in_window, outside = collect_merged_prs(client, 'owner/repo', _START, _END)
        assert len(in_window) == 101

    def test_stops_when_earliest_updated_before_start(self):
        pr_in = _make_pr(1, merged_at='2026-10-04T10:00:00Z',
                          updated_at='2026-10-04T10:00:00Z')
        pr_before = _make_pr(2, merged_at='2026-09-15T10:00:00Z',
                              updated_at='2026-09-15T10:00:00Z')
        client = self._make_client([[pr_in, pr_before]])
        in_window, outside = collect_merged_prs(client, 'owner/repo', _START, _END)
        # Should stop after page 1 (earliest updated before start)
        assert client.get.call_count == 1
        assert len(in_window) == 1
        assert 2 in outside

    def test_window_boundary_start_inclusive_end_exclusive(self):
        pr_at_start = _make_pr(1, merged_at='2026-10-01T00:00:00Z',
                                updated_at='2026-10-01T00:00:00Z')
        pr_at_end = _make_pr(2, merged_at='2026-10-08T00:00:00Z',
                              updated_at='2026-10-08T00:00:00Z')
        client = self._make_client([[pr_at_start, pr_at_end]])
        in_window, outside = collect_merged_prs(client, 'owner/repo', _START, _END)
        assert [r['number'] for r in in_window] == [1]
        assert 2 in outside

    def test_outside_window_prs_tracked(self):
        pr_before = _make_pr(5, merged_at='2026-09-25T10:00:00Z',
                              updated_at='2026-10-02T10:00:00Z')
        pr_in = _make_pr(6, merged_at='2026-10-04T10:00:00Z',
                          updated_at='2026-10-04T10:00:00Z')
        client = self._make_client([[pr_before, pr_in]])
        in_window, outside = collect_merged_prs(client, 'owner/repo', _START, _END)
        assert [r['number'] for r in in_window] == [6]
        assert 5 in outside


# ---------------------------------------------------------------------------
# collate
# ---------------------------------------------------------------------------

class TestCollate:
    def _make_client(self, prs, issues):
        """issues: dict of issue_number -> issue dict."""
        client = MagicMock()

        def get_side_effect(path):
            if '/pulls?' in path:
                m = re.search(r'[?&]page=(\d+)', path)
                page = int(m.group(1)) if m else 1
                if page == 1:
                    return prs
                return []
            for num, issue in issues.items():
                if f'/issues/{num}' in path:
                    return issue
            raise ValueError(f'Unexpected path: {path}')

        client.get.side_effect = get_side_effect
        return client

    def test_deduplication_across_prs(self):
        pr1 = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        pr2 = _make_pr(11, merged_at='2026-10-03T10:00:00Z', body='Fixes #5')
        issue5 = _make_issue(5, title='Dup issue', labels=['classification: bug'],
                              body='### Release Notes\n\nFixed the bug.')
        client = self._make_client([pr1, pr2], {5: issue5})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        issue_nums = [e['issue_number'] for e in entries]
        assert issue_nums.count(5) == 1

    def test_multiple_prs_per_issue_records_all_pr_numbers(self):
        pr1 = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        pr2 = _make_pr(11, merged_at='2026-10-03T10:00:00Z', body='Fixes #5')
        issue5 = _make_issue(5, labels=['classification: bug'],
                              body='### Release Notes\n\nFixed.')
        client = self._make_client([pr1, pr2], {5: issue5})
        entries, _, _ = collate(client, 'owner/repo', _START, _END)
        entry = next(e for e in entries if e['issue_number'] == 5)
        assert set(entry['pr_numbers']) == {10, 11}

    def test_excluded_label_dependencies(self):
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        issue5 = _make_issue(5, labels=['dependencies'])
        client = self._make_client([pr], {5: issue5})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        assert entries == []
        assert any(e['issue'] == 5 for e in diag['excluded'])

    def test_excluded_label_ignore_for_release(self):
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        issue5 = _make_issue(5, labels=['ignore-for-release'])
        client = self._make_client([pr], {5: issue5})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        assert entries == []
        assert any(e['issue'] == 5 for e in diag['excluded'])

    def test_excluded_label_on_closing_pr_filters_issue_without_the_label(self):
        """A PR carrying ignore-for-release excludes the issue it closes even
        when the issue itself has no exclusion label (RV-001)."""
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5',
                      labels=['ignore-for-release'])
        issue5 = _make_issue(5, labels=['classification: bug'])
        client = self._make_client([pr], {5: issue5})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        assert entries == []
        assert any(e['issue'] == 5 for e in diag['excluded'])

    def test_reopened_issue_emits_diagnostic(self):
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        issue5 = _make_issue(5, state='open', labels=['classification: bug'],
                              body='### Release Notes\n\nFixed.')
        client = self._make_client([pr], {5: issue5})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        assert len(entries) == 1
        assert entries[0]['reopened'] is True
        assert any(e['issue'] == 5 for e in diag['reopened'])

    def test_reopened_issue_is_not_silently_included(self):
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        issue5 = _make_issue(5, state='open', labels=['classification: bug'],
                              body='### Release Notes\n\nFixed.')
        client = self._make_client([pr], {5: issue5})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        entry = entries[0]
        assert entry['reopened'] is True, 'reopened flag must be set'
        assert any(e['issue'] == 5 for e in diag['reopened']), 'diagnostic must be emitted'

    def test_missing_release_notes_uses_pr_title_fallback(self):
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z',
                      body='Closes #5', title='My PR title')
        issue5 = _make_issue(5, labels=['classification: bug'],
                              body='## Summary\n\nNo release notes section.')
        client = self._make_client([pr], {5: issue5})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        entry = entries[0]
        assert entry['release_notes'] is None
        assert entry['pr_title'] == 'My PR title'
        assert any(e['issue'] == 5 for e in diag['missing_release_notes'])
        assert diag['missing_release_notes'][0]['fallback'] == 'My PR title'

    def test_cross_repo_ref_emits_diagnostic_and_is_excluded(self):
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z',
                      body='Closes other/repo#99')
        client = self._make_client([pr], {})
        entries, diag, _ = collate(client, 'owner/repo', _START, _END)
        assert entries == []
        assert any(d['ref'] == 'other/repo#99' for d in diag['cross_repo_refs'])

    def test_classification_fallback_to_pr_label(self):
        pr = _make_pr(10, merged_at='2026-10-02T10:00:00Z',
                      body='Closes #5',
                      labels=['classification: enhancement'])
        issue5 = _make_issue(5, labels=[],
                              body='### Release Notes\n\nNew feature.')
        client = self._make_client([pr], {5: issue5})
        entries, _, _ = collate(client, 'owner/repo', _START, _END)
        assert entries[0]['category'] == 'Features'

    def test_prs_count_returned_correctly(self):
        pr1 = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        pr2 = _make_pr(11, merged_at='2026-10-03T10:00:00Z', body='Closes #6')
        issue5 = _make_issue(5, labels=['classification: bug'],
                              body='### Release Notes\n\nFix 1.')
        issue6 = _make_issue(6, labels=['classification: bug'],
                              body='### Release Notes\n\nFix 2.')
        client = self._make_client([pr1, pr2], {5: issue5, 6: issue6})
        _, _, prs_count = collate(client, 'owner/repo', _START, _END)
        assert prs_count == 2

    def test_prs_covered_in_diagnostics(self):
        pr1 = _make_pr(10, merged_at='2026-10-02T10:00:00Z', body='Closes #5')
        pr2 = _make_pr(11, merged_at='2026-10-03T10:00:00Z', body='Closes #6')
        issue5 = _make_issue(5, labels=['classification: bug'],
                              body='### Release Notes\n\nFix 1.')
        issue6 = _make_issue(6, labels=['classification: bug'],
                              body='### Release Notes\n\nFix 2.')
        client = self._make_client([pr1, pr2], {5: issue5, 6: issue6})
        _, diag, _ = collate(client, 'owner/repo', _START, _END)
        assert sorted(diag['prs_covered']) == [10, 11]

    def test_prs_outside_window_in_diagnostics(self):
        pr_in = _make_pr(10, merged_at='2026-10-02T10:00:00Z',
                          updated_at='2026-10-02T10:00:00Z', body='Closes #5')
        pr_before = _make_pr(9, merged_at='2026-09-20T10:00:00Z',
                               updated_at='2026-10-02T09:00:00Z', body='')
        issue5 = _make_issue(5, labels=['classification: bug'],
                              body='### Release Notes\n\nFix.')
        client = self._make_client([pr_in, pr_before], {5: issue5})
        _, diag, _ = collate(client, 'owner/repo', _START, _END)
        assert 9 in diag['prs_outside_window']
        assert 10 not in diag['prs_outside_window']


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

class TestRenderMarkdown:
    def _entry(self, number, category, title, url, release_notes, pr_title='',
               reopened=False):
        return {
            'issue_number': number,
            'issue_title': title,
            'issue_url': url,
            'category': category,
            'release_notes': release_notes,
            'pr_title': pr_title,
            'pr_numbers': [100],
            'reopened': reopened,
        }

    def test_issue_in_correct_category(self):
        entry = self._entry(1, 'Features', 'My feature', 'http://x', 'Adds X.')
        md = render_markdown([entry], _START, _END, 'owner/repo')
        assert '## Features' in md
        assert 'My feature' in md
        assert 'Adds X.' in md

    def test_each_issue_appears_exactly_once(self):
        entry = self._entry(1, 'Fixes', 'A fix', 'http://x', 'Fixed it.')
        md = render_markdown([entry], _START, _END, 'owner/repo')
        assert md.count('A fix') == 1

    def test_uses_pr_title_when_release_notes_absent(self):
        entry = self._entry(1, 'Fixes', 'A fix', 'http://x',
                            release_notes=None, pr_title='PR: Fix the thing')
        md = render_markdown([entry], _START, _END, 'owner/repo')
        assert 'PR: Fix the thing' in md

    def test_reopened_flag_shown(self):
        entry = self._entry(1, 'Fixes', 'A fix', 'http://x', 'Fixed.',
                            reopened=True)
        md = render_markdown([entry], _START, _END, 'owner/repo')
        assert 'reopened' in md

    def test_categories_in_correct_order(self):
        entries = [
            self._entry(1, 'Other',       'O', 'u1', 'x'),
            self._entry(2, 'Maintenance', 'M', 'u2', 'x'),
            self._entry(3, 'Fixes',       'F', 'u3', 'x'),
            self._entry(4, 'Features',    'E', 'u4', 'x'),
            self._entry(5, 'Security',    'S', 'u5', 'x'),
        ]
        md = render_markdown(entries, _START, _END, 'owner/repo')
        positions = {cat: md.index(f'## {cat}') for cat in CATEGORY_ORDER
                     if f'## {cat}' in md}
        ordered = sorted(positions, key=lambda c: positions[c])
        assert ordered == CATEGORY_ORDER

    def test_issues_sorted_by_number_within_category(self):
        entries = [
            self._entry(30, 'Fixes', 'Z issue', 'u1', 'x'),
            self._entry(5,  'Fixes', 'A issue', 'u2', 'x'),
            self._entry(15, 'Fixes', 'M issue', 'u3', 'x'),
        ]
        md = render_markdown(entries, _START, _END, 'owner/repo')
        pos5 = md.index('A issue')
        pos15 = md.index('M issue')
        pos30 = md.index('Z issue')
        assert pos5 < pos15 < pos30

    def test_empty_categories_omitted(self):
        entry = self._entry(1, 'Security', 'S issue', 'u', 'x')
        md = render_markdown([entry], _START, _END, 'owner/repo')
        assert '## Features' not in md
        assert '## Security' in md

    def test_includes_repo_and_period(self):
        md = render_markdown([], _START, _END, 'owner/repo')
        assert 'owner/repo' in md
        assert '2026-10-01' in md
        assert '2026-10-08' in md


# ---------------------------------------------------------------------------
# render_diagnostics
# ---------------------------------------------------------------------------

class TestRenderDiagnostics:
    def test_json_parseable(self):
        diag = {
            'cross_repo_refs': [],
            'excluded': [],
            'reopened': [],
            'missing_release_notes': [],
        }
        result = json_parse(render_diagnostics(diag, 10, 5))
        assert result['prs_in_window'] == 10
        assert result['issues_included'] == 5

    def test_all_diagnostic_keys_present(self):
        diag = {
            'cross_repo_refs': [{'pr': 1, 'ref': 'x/y#2'}],
            'excluded': [{'issue': 3, 'url': 'u', 'reason': 'label: dependencies'}],
            'reopened': [{'issue': 4, 'url': 'u', 'title': 'T'}],
            'missing_release_notes': [{'issue': 5, 'url': 'u', 'title': 'T', 'fallback': 'P'}],
        }
        result = json_parse(render_diagnostics(diag, 2, 1))
        assert len(result['cross_repo_refs']) == 1
        assert len(result['excluded']) == 1
        assert len(result['reopened']) == 1
        assert len(result['missing_release_notes']) == 1


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_deterministic_ordering(self):
        entries = [
            {
                'issue_number': i,
                'issue_title': f'Issue {i}',
                'issue_url': f'https://github.com/owner/repo/issues/{i}',
                'category': 'Fixes',
                'release_notes': f'Fix {i}.',
                'pr_title': '',
                'pr_numbers': [i + 100],
                'reopened': False,
            }
            for i in [5, 3, 1, 4, 2]
        ]
        md1 = render_markdown(entries, _START, _END, 'owner/repo')
        md2 = render_markdown(entries, _START, _END, 'owner/repo')
        assert md1 == md2

    def test_same_inputs_same_output(self):
        entry = {
            'issue_number': 42,
            'issue_title': 'Stable issue',
            'issue_url': 'https://github.com/owner/repo/issues/42',
            'category': 'Features',
            'release_notes': 'Added stable feature.',
            'pr_title': 'PR title',
            'pr_numbers': [142],
            'reopened': False,
        }
        md1 = render_markdown([entry], _START, _END, 'owner/repo')
        md2 = render_markdown([entry], _START, _END, 'owner/repo')
        assert md1 == md2


# ---------------------------------------------------------------------------
# Weekly boundary / timezone
# ---------------------------------------------------------------------------

class TestTimezone:
    def test_utc_boundary_start_inclusive(self):
        start = datetime.datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime.datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)
        pr = _make_pr(1, merged_at='2026-10-01T00:00:00Z',
                      updated_at='2026-10-01T00:00:00Z')
        client = MagicMock()
        client.get.side_effect = [[pr], []]
        in_window, _ = collect_merged_prs(client, 'owner/repo', start, end)
        assert any(r['number'] == 1 for r in in_window)

    def test_utc_boundary_end_exclusive(self):
        start = datetime.datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime.datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)
        pr = _make_pr(1, merged_at='2026-10-08T00:00:00Z',
                      updated_at='2026-10-08T00:00:00Z')
        client = MagicMock()
        client.get.side_effect = [[pr], []]
        in_window, outside = collect_merged_prs(client, 'owner/repo', start, end)
        assert in_window == []
        assert 1 in outside

    def test_timezone_aware_comparison(self):
        start = datetime.datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime.datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)
        pr = _make_pr(1, merged_at='2026-10-04T23:00:00+00:00',
                      updated_at='2026-10-04T23:00:00+00:00')
        client = MagicMock()
        client.get.side_effect = [[pr], []]
        in_window, _ = collect_merged_prs(client, 'owner/repo', start, end)
        assert any(r['number'] == 1 for r in in_window)


# ---------------------------------------------------------------------------
# Importability check
# ---------------------------------------------------------------------------

def test_module_importable():
    import release_note_generator  # noqa: F401 -- verifies importability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import json as _json


def json_parse(s):
    return _json.loads(s)
