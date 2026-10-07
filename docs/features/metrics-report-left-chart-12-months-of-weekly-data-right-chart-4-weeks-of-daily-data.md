# Feature: Metrics Report Left Chart 12 Months Of Weekly Data Right Chart 4 Weeks Of Daily Data

## Scenario: Daily aggregation covers the previous complete calendar day
**Given** the metrics aggregator is invoked with --period day
**When** the aggregation runs on any given day
**Then** the output contains exactly one new row with period="day" covering the previous calendar day, 00:00:00.000000 UTC through 23:59:59.999999 UTC

## Scenario: Daily aggregation script appends rows in one atomic commit
**Given** aggregate-metrics.sh is run with --period day against a git repository containing metric data
**When** the script completes successfully
**Then** exactly one new commit is appended to records.jsonl containing period="day" rows, with no partial or duplicate writes

## Scenario: --dry-run mode reports daily rows without writing
**Given** aggregate-metrics.sh is run with --dry-run --period day
**When** the command completes
**Then** it reports which rows would be appended without modifying records.jsonl and exits with a zero exit code

## Scenario: Daily pipeline step runs once a day, independent of the weekly schedule
**Given** the metrics pipeline is deployed with both weekly and daily aggregation steps configured
**When** a calendar day completes
**Then** the daily aggregation runs for that day and the weekly aggregation continues running each week on its separate schedule, independently

## Scenario: Left-hand chart sources weekly aggregate rows over 12 months with correct title
**Given** the weekly metrics report is generated with at least 12 months of period="week" rows available
**When** a user views any paired-metric chart (line or bar) in the PDF report
**Then** the left-hand chart displays weekly data points for the most recent 12 months and its title states "12 months"

## Scenario: Right-hand chart sources daily rows over a 4-week window with correct title
**Given** the weekly metrics report is generated with at least 4 weeks of period="day" rows available
**When** a user views any paired-metric chart (line or bar) in the PDF report
**Then** the right-hand chart displays data from period="day" rows for the most recent 4 weeks and its title states "4 weeks" with no reference to "2 months", "2mo", or "12 weeks"

## Scenario: Charts render available data when the full window is not yet populated
**Given** the available period="week" rows span fewer than 12 months or the available period="day" rows span fewer than 4 weeks
**When** the weekly metrics report is generated
**Then** each chart renders the available data range without raising an error
