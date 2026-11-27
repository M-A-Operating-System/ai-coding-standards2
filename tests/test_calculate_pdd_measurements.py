"""Tests for pipeline/calculate_pdd_measurements.py (issue #759).

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
"""

import sys
import os
import json
import subprocess
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from calculate_pdd_measurements import (
    _extract_gherkin_section,
    _extract_user_stories_count,
    _parse_gherkin_section,
    _validate,
    METRIC_VERSION,
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
