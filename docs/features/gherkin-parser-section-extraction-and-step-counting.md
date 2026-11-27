# Feature: Gherkin Parser Section Extraction And Step Counting

## Scenario: Parser produces validated measurement object for well-formed input
**Given** an issue body containing a `## Acceptance criteria (Gherkin)` section with two named scenarios each having multiple step lines
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** the JSON output contains exactly the nine fields with correct types, `metric_version` equals `pdd-measures-v1`, `scenarios` equals `len(scenario_step_counts)`, `total_steps` equals the sum of `scenario_step_counts`, and `total_steps` equals `given_steps + when_steps + then_steps + and_steps + but_steps`

## Scenario: Keyword counts include step lines with leading whitespace
**Given** an issue body whose Gherkin section contains step lines with leading whitespace before the `**Given**`, `**When**`, `**Then**`, `**And**`, or `**But**` keyword
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** each such line is counted exactly once toward its keyword counter and the per-scenario and aggregate counts are consistent

## Scenario: Content after a horizontal rule boundary is not parsed
**Given** an issue body whose Gherkin section is followed by a `---` separator and then additional scenario-like content
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** only step lines before the `---` boundary are counted and the post-boundary content does not affect any output field

## Scenario: Content after a heading-level boundary is not parsed
**Given** an issue body whose Gherkin section is followed by a `##`-level heading and then additional scenario-like content
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** only step lines before the `##` heading are counted and the post-heading content does not affect any output field

## Scenario: Step-like lines inside fenced code blocks are not counted
**Given** an issue body whose Gherkin section contains a fenced code block with lines starting with `**Given**` or `**When**`
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** those lines are not counted as steps and do not appear in any keyword counter

## Scenario: Script exits non-zero for a scenario with no step lines
**Given** an issue body containing a named scenario heading with no recognised step lines before the next scenario heading or section boundary
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** the script exits with a non-zero exit code

## Scenario: User stories counted when User stories section is present
**Given** an issue body containing a `## User stories` section with three `As a`-starting bullets
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** `user_stories` in the output equals `3`

## Scenario: User stories is null when User stories section is absent
**Given** an issue body with no `## User stories` section
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** `user_stories` in the output is `null`

## Scenario: Output contains no score, index, band, threshold, or coefficient fields
**Given** an issue body with a well-formed Gherkin section
**When** `python pipeline/calculate_pdd_measurements.py --issue <N>` is called
**Then** the JSON output contains no field named `score`, `index`, `band`, `threshold`, or `coefficient`
