"""Tests for pipeline/calculate_pdd_measurements.py (issue #759 / #760).

Realises the Gherkin scenarios in
docs/features/gherkin-parser-section-extraction-and-step-counting.md:

  Scenario: Parser produces validated measurement object for well-formed input
    -> TestWellFormedInput.test_nine_fields_present
    -> TestWellFormedInput.test_reconciliation_checks_pass
    -> TestWellFormedInput.test_metric_version

  Scenario: Keyword counts include step lines with leading whitespace
    -> TestKeywordCounting.test_leading_whitespace_counted

  Scenario: Content after a horizontal rule boundary is not parsed
    -> TestSectionBoundary.test_stops_at_horizontal_rule

  Scenario: Content after a heading-level boundary is not parsed
    -> TestSectionBoundary.test_stops_at_heading

  Scenario: Step-like lines inside fenced code blocks are not counted
    -> TestFencedCodeBlocks.test_fenced_steps_excluded

  Scenario: Script exits non-zero for a scenario with no step lines
    -> TestMalformedInput.test_zero_step_scenario_fails

  Scenario: User stories counted when User stories section is present
    -> TestUserStories.test_user_stories_counted

  Scenario: User stories is null when User stories section is absent
    -> TestUserStories.test_user_stories_null_when_absent

  Scenario: Output contains no score, index, band, threshold, or coefficient fields
    -> TestWellFormedInput.test_no_forbidden_fields

docs/features/pdd-measurement-pipeline-integration-and-schema-extension.md:

  Scenario: Script skips execution when approval label is absent
    -> TestPipelineIntegration.test_absent_label_exits_cleanly

  Scenario: Script writes complete record and emits success status for approved issue with valid Gherkin
    -> TestPipelineIntegration.test_approved_writes_record_and_emits_complete

  Scenario: Record includes hierarchy fields for a sub-issue
    -> TestPipelineIntegration.test_sub_issue_hierarchy_fields_non_null

  Scenario: Script emits blocked status on malformed or missing Gherkin
    -> TestMainErrors.test_missing_gherkin_section_exits_nonzero

  Scenario: Any reconciliation inconsistency in parsed step counts blocks the step
    -> TestMalformedInput.test_zero_step_scenario_fails
"""

import sys
import os
import json
import subprocess
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from calculate_pdd_measurements import (
    _extract_gherkin_section,
    _extract_user_stories_count,
    _parse_gherkin_section,
    _validate,
    _extract_classification,
    _extract_parent_issue_number,
    _compute_hierarchy,
    main,
    METRIC_VERSION,
    AGENT_ID,
)


BODY_TWO_SCENARIOS = """
## Acceptance criteria (Gherkin)

#### Scenario: First scenario
**Given** some precondition
**When** an action is taken
**Then** a result is observed

#### Scenario: Second scenario
**Given** another precondition
**When** another action
**Then** another result
**And** an additional check
"""

BODY_WITH_USER_STORIES = """
## User stories

- As a developer I want to run the parser
- As an operator I want to get measurements
- As a user I want correct output
- Not matching bullet

## Acceptance criteria (Gherkin)

#### Scenario: One step scenario
**Given** a precondition
"""

BODY_NO_USER_STORIES = """
## Acceptance criteria (Gherkin)

#### Scenario: One step scenario
**Given** a precondition
"""

BODY_AFTER_HORIZONTAL_RULE = """
## Acceptance criteria (Gherkin)

#### Scenario: Before boundary
**Given** counted step

---

#### Scenario: After boundary
**Given** not counted
"""

BODY_AFTER_HEADING = """
## Acceptance criteria (Gherkin)

#### Scenario: Before boundary
**Given** counted step

## Another Section

#### Scenario: After boundary
**Given** not counted
"""

BODY_FENCED_CODE = """
## Acceptance criteria (Gherkin)

#### Scenario: Real steps only
**Given** real step
```
**When** inside fence - not counted
**Then** also not counted
```
**Then** real step after fence
"""

BODY_ZERO_STEP_SCENARIO = """
## Acceptance criteria (Gherkin)

#### Scenario: Empty scenario

#### Scenario: Valid scenario
**Given** a step
"""

BODY_LEADING_WHITESPACE = """
## Acceptance criteria (Gherkin)

#### Scenario: Whitespace scenario
  **Given** step with leading spaces
\t**When** step with leading tab
**Then** step without leading whitespace
"""


def _parse_body(body: str) -> dict:
    section = _extract_gherkin_section(body)
    assert section is not None
    result = _parse_gherkin_section(section)
    _validate(result)
    return result


class TestWellFormedInput:
    def test_nine_fields_present(self):
        result = _parse_body(BODY_TWO_SCENARIOS)
        result["user_stories"] = None
        result["metric_version"] = METRIC_VERSION
        expected_fields = {
            "scenarios", "scenario_step_counts", "total_steps",
            "given_steps", "when_steps", "then_steps",
            "and_steps", "but_steps", "user_stories", "metric_version",
        }
        assert set(result.keys()) == expected_fields

    def test_scenario_count(self):
        result = _parse_body(BODY_TWO_SCENARIOS)
        assert result["scenarios"] == 2

    def test_scenario_step_counts_shape(self):
        result = _parse_body(BODY_TWO_SCENARIOS)
        counts = result["scenario_step_counts"]
        assert len(counts) == 2
        assert counts[0]["scenario_index"] == 1
        assert counts[0]["scenario_title"] == "First scenario"
        assert counts[0]["steps"] == 3
        assert counts[1]["scenario_index"] == 2
        assert counts[1]["scenario_title"] == "Second scenario"
        assert counts[1]["steps"] == 4

    def test_total_steps(self):
        result = _parse_body(BODY_TWO_SCENARIOS)
        assert result["total_steps"] == 7

    def test_keyword_counts(self):
        result = _parse_body(BODY_TWO_SCENARIOS)
        assert result["given_steps"] == 2
        assert result["when_steps"] == 2
        assert result["then_steps"] == 2
        assert result["and_steps"] == 1
        assert result["but_steps"] == 0

    def test_reconciliation_checks_pass(self):
        result = _parse_body(BODY_TWO_SCENARIOS)
        assert result["scenarios"] == len(result["scenario_step_counts"])
        assert result["total_steps"] == sum(
            s["steps"] for s in result["scenario_step_counts"]
        )
        keyword_sum = (
            result["given_steps"] + result["when_steps"] + result["then_steps"]
            + result["and_steps"] + result["but_steps"]
        )
        assert result["total_steps"] == keyword_sum

    def test_metric_version(self):
        assert METRIC_VERSION == "pdd-measures-v1"

    def test_no_forbidden_fields(self):
        result = _parse_body(BODY_TWO_SCENARIOS)
        result["user_stories"] = None
        result["metric_version"] = METRIC_VERSION
        forbidden = {"score", "index", "band", "threshold", "coefficient"}
        assert not forbidden.intersection(result.keys())


class TestKeywordCounting:
    def test_leading_whitespace_counted(self):
        result = _parse_body(BODY_LEADING_WHITESPACE)
        assert result["total_steps"] == 3
        assert result["given_steps"] == 1
        assert result["when_steps"] == 1
        assert result["then_steps"] == 1

    def test_each_line_counted_once(self):
        result = _parse_body(BODY_LEADING_WHITESPACE)
        keyword_sum = (
            result["given_steps"] + result["when_steps"] + result["then_steps"]
            + result["and_steps"] + result["but_steps"]
        )
        assert result["total_steps"] == keyword_sum


class TestSectionBoundary:
    def test_stops_at_horizontal_rule(self):
        result = _parse_body(BODY_AFTER_HORIZONTAL_RULE)
        assert result["scenarios"] == 1
        assert result["scenario_step_counts"][0]["scenario_title"] == "Before boundary"
        assert result["total_steps"] == 1

    def test_stops_at_heading(self):
        result = _parse_body(BODY_AFTER_HEADING)
        assert result["scenarios"] == 1
        assert result["scenario_step_counts"][0]["scenario_title"] == "Before boundary"
        assert result["total_steps"] == 1

    def test_no_section_returns_none(self):
        body = "## Some Other Section\n\n#### Scenario: Foo\n**Given** bar\n"
        assert _extract_gherkin_section(body) is None


class TestFencedCodeBlocks:
    def test_fenced_steps_excluded(self):
        result = _parse_body(BODY_FENCED_CODE)
        assert result["total_steps"] == 2
        assert result["given_steps"] == 1
        assert result["when_steps"] == 0
        assert result["then_steps"] == 1

    def test_fenced_steps_not_in_counts(self):
        section = _extract_gherkin_section(BODY_FENCED_CODE)
        result = _parse_gherkin_section(section)
        assert result["total_steps"] == 2


class TestMalformedInput:
    def test_zero_step_scenario_fails(self):
        section = _extract_gherkin_section(BODY_ZERO_STEP_SCENARIO)
        assert section is not None
        with pytest.raises(SystemExit) as exc_info:
            _parse_gherkin_section(section)
        assert exc_info.value.code != 0


class TestUserStories:
    def test_user_stories_counted(self):
        count = _extract_user_stories_count(BODY_WITH_USER_STORIES)
        assert count == 3

    def test_user_stories_null_when_absent(self):
        count = _extract_user_stories_count(BODY_NO_USER_STORIES)
        assert count is None

    def test_non_matching_bullets_not_counted(self):
        body = """
## User stories

- Not matching
- Also not matching
"""
        count = _extract_user_stories_count(body)
        assert count == 0

    def test_stops_at_horizontal_rule(self):
        body = """
## User stories

- As a user I want something

---

- As a user I want something else (after boundary, not counted)
"""
        count = _extract_user_stories_count(body)
        assert count == 1


def _make_issue_response(body: str, labels: list[str] | None = None) -> MagicMock:
    mock = MagicMock()
    mock.stdout = json.dumps({
        "body": body,
        "labels": [{"name": lbl} for lbl in (labels or ["prd-writer:approved"])],
    })
    mock.returncode = 0
    return mock


_VALID_BODY = """
## Acceptance criteria (Gherkin)

#### Scenario: One step scenario
**Given** a precondition
"""


class TestMainErrors:
    def test_called_process_error_exits_nonzero(self):
        with patch(
            "calculate_pdd_measurements.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "gh", stderr="network error"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                sys.argv = ["calculate_pdd_measurements.py", "--issue", "1"]
                main()
        assert exc_info.value.code != 0

    def test_missing_gherkin_section_exits_nonzero(self):
        body_no_gherkin = "## Some other section\n\nContent without Gherkin.\n"
        mock_resp = _make_issue_response(body_no_gherkin)
        with patch("calculate_pdd_measurements.subprocess.run", return_value=mock_resp):
            with pytest.raises(SystemExit) as exc_info:
                sys.argv = ["calculate_pdd_measurements.py", "--issue", "1"]
                main()
        assert exc_info.value.code != 0

    def test_missing_repo_env_exits_nonzero(self, monkeypatch):
        monkeypatch.delenv("REPO", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            sys.argv = ["calculate_pdd_measurements.py", "--issue", "1"]
            main()
        assert exc_info.value.code != 0


class TestHierarchy:
    def test_extract_classification_found(self):
        labels = ["classification: enhancement", "prd-writer:approved"]
        assert _extract_classification(labels) == "enhancement"

    def test_extract_classification_missing(self):
        labels = ["prd-writer:approved", "sub-issue"]
        assert _extract_classification(labels) is None

    def test_extract_parent_issue_number_found(self):
        labels = ["parent-issue:507", "sub-issue"]
        assert _extract_parent_issue_number(labels) == 507

    def test_extract_parent_issue_number_missing(self):
        labels = ["prd-writer:approved", "classification: enhancement"]
        assert _extract_parent_issue_number(labels) is None

    def test_compute_hierarchy_root_issue(self):
        parent, root, depth = _compute_hierarchy(["prd-writer:approved"])
        assert parent is None
        assert root is None
        assert depth is None

    def test_compute_hierarchy_sub_issue(self, monkeypatch):
        monkeypatch.setenv("REPO", "owner/repo")
        parent_issue_resp = MagicMock()
        parent_issue_resp.stdout = json.dumps({
            "body": "",
            "labels": [{"name": "classification: enhancement"}],
        })
        parent_issue_resp.returncode = 0
        with patch("calculate_pdd_measurements.subprocess.run", return_value=parent_issue_resp):
            parent, root, depth = _compute_hierarchy(["parent-issue:507", "sub-issue"])
        assert parent == 507
        assert root == 507
        assert depth == 1

    def test_compute_hierarchy_nested_sub_issue(self, monkeypatch):
        monkeypatch.setenv("REPO", "owner/repo")
        grandparent_resp = MagicMock()
        grandparent_resp.stdout = json.dumps({
            "body": "",
            "labels": [{"name": "parent-issue:100"}],
        })
        grandparent_resp.returncode = 0
        root_resp = MagicMock()
        root_resp.stdout = json.dumps({
            "body": "",
            "labels": [{"name": "classification: enhancement"}],
        })
        root_resp.returncode = 0
        with patch(
            "calculate_pdd_measurements.subprocess.run",
            side_effect=[grandparent_resp, root_resp],
        ):
            parent, root, depth = _compute_hierarchy(["parent-issue:507"])
        assert parent == 507
        assert root == 100
        assert depth == 2


class TestPipelineIntegration:
    """Realises scenarios in pdd-measurement-pipeline-integration-and-schema-extension.md."""

    def test_absent_label_exits_cleanly(self, monkeypatch):
        """Scenario: Script skips execution when approval label is absent."""
        monkeypatch.setenv("REPO", "owner/repo")
        mock_resp = _make_issue_response(_VALID_BODY, labels=["some-other-label"])
        with patch("calculate_pdd_measurements.subprocess.run", return_value=mock_resp):
            with pytest.raises(SystemExit) as exc_info:
                sys.argv = ["calculate_pdd_measurements.py", "--issue", "1"]
                main()
        assert exc_info.value.code == 0

    def test_approved_writes_record_and_emits_complete(self, capsys, monkeypatch):
        """Scenario: Script writes complete record for approved issue with valid Gherkin."""
        monkeypatch.setenv("REPO", "owner/repo")

        fetch_resp = _make_issue_response(
            _VALID_BODY,
            labels=["prd-writer:approved", "classification: enhancement"],
        )

        append_ok = MagicMock()
        append_ok.returncode = 0
        append_ok.stdout = "appended"
        append_ok.stderr = ""

        call_responses = [fetch_resp, append_ok]

        with patch(
            "calculate_pdd_measurements.subprocess.run",
            side_effect=call_responses,
        ):
            with patch("os.path.isfile", return_value=True):
                sys.argv = ["calculate_pdd_measurements.py", "--issue", "1"]
                main()

        captured = capsys.readouterr()
        record_out = json.loads(captured.out)
        assert "scenarios" in record_out
        assert "total_steps" in record_out
        assert "metric_version" in record_out

    def test_sub_issue_hierarchy_fields_non_null(self, monkeypatch):
        """Scenario: Record includes hierarchy fields for a sub-issue."""
        monkeypatch.setenv("REPO", "owner/repo")

        fetch_resp = _make_issue_response(
            _VALID_BODY,
            labels=["prd-writer:approved", "parent-issue:507", "classification: enhancement"],
        )
        parent_resp = MagicMock()
        parent_resp.stdout = json.dumps({
            "body": "",
            "labels": [{"name": "classification: enhancement"}],
        })
        parent_resp.returncode = 0

        append_ok = MagicMock()
        append_ok.returncode = 0
        append_ok.stdout = "appended"
        append_ok.stderr = ""

        written_records: list[dict] = []
        orig_run = subprocess.run
        fetch_calls: list = []

        def side_effect_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[:2] == ["gh", "api"]:
                fetch_calls.append(cmd)
                if len(fetch_calls) == 1:
                    return fetch_resp
                return parent_resp
            if isinstance(cmd, list) and "append-metrics-record.sh" in str(cmd):
                record_path = cmd[-1]
                with open(record_path) as f:
                    written_records.append(json.loads(f.read().strip()))
                return append_ok
            return orig_run(cmd, **kwargs)

        with patch("calculate_pdd_measurements.subprocess.run", side_effect=side_effect_run):
            with patch("os.path.isfile", return_value=True):
                sys.argv = ["calculate_pdd_measurements.py", "--issue", "1"]
                main()

        assert len(written_records) == 1
        rec = written_records[0]
        assert rec["parent_issue_number"] is not None
        assert rec["root_issue_number"] is not None
        assert rec["decomposition_depth"] is not None

    def test_record_contains_required_fields(self, monkeypatch):
        """Record has all required metrics fields."""
        monkeypatch.setenv("REPO", "owner/repo")

        fetch_resp = _make_issue_response(
            _VALID_BODY,
            labels=["prd-writer:approved", "classification: enhancement"],
        )
        append_ok = MagicMock()
        append_ok.returncode = 0
        append_ok.stdout = "appended"
        append_ok.stderr = ""

        written_records: list[dict] = []

        def side_effect_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[:2] == ["gh", "api"]:
                return fetch_resp
            if isinstance(cmd, list) and "append-metrics-record.sh" in str(cmd):
                record_path = cmd[-1]
                with open(record_path) as f:
                    written_records.append(json.loads(f.read().strip()))
                return append_ok
            return MagicMock(returncode=0)

        with patch("calculate_pdd_measurements.subprocess.run", side_effect=side_effect_run):
            with patch("os.path.isfile", return_value=True):
                sys.argv = ["calculate_pdd_measurements.py", "--issue", "42"]
                main()

        assert len(written_records) == 1
        rec = written_records[0]
        required = {
            "record_type", "github_issue_number", "timestamp_start", "timestamp_end",
            "agent_id", "cycle_id", "duration_ms", "input_tokens", "output_tokens",
            "retry_count", "retry_errors",
        }
        assert required.issubset(rec.keys())
        assert rec["record_type"] == "pdd_measurements"
        assert rec["github_issue_number"] == 42
        assert rec["agent_id"] == AGENT_ID
        assert rec["input_tokens"] == 0
        assert rec["output_tokens"] == 0
        assert rec["retry_count"] == 0
        assert rec["retry_errors"] == []
