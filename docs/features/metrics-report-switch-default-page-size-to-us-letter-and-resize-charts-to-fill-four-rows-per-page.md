# Feature: Metrics Report Switch Default Page Size To Us Letter And Resize Charts To Fill Four Rows Per Page

## Scenario: Generated report uses US Letter page size
**Given** a metrics report is generated
**When** the report is rendered to PDF
**Then** each page is US Letter size (8.5in x 11in / 215.9mm x 279.4mm)

## Scenario: Four chart rows fit on one page after chart resize
**Given** a metrics report is generated with multiple weekly data points
**When** the report is rendered to PDF
**Then** four chart rows appear on a single page and the page-break grouping logic is unchanged

## Scenario: Resized charts fill the US Letter page height
**Given** a metrics report is rendered to PDF
**When** a page is inspected
**Then** the four chart rows visibly occupy most of the US Letter page height with no large blank area beneath them

## Scenario: No chart row overflows the page boundary
**Given** a metrics report is rendered to PDF
**When** a page containing four chart rows is inspected
**Then** no chart row extends past the page boundary or is cut off

## Scenario: Both line-chart and bar-chart rows use the same updated figure dimensions
**Given** a metrics report containing both dual line-chart rows and by-agent bar-chart rows is rendered
**When** the rendered output is inspected
**Then** both chart types reflect the same updated aspect ratio

## Scenario: No A4 page-size references remain in code, tests, or docs
**Given** the updated codebase
**When** all source files, test files, and documentation are inspected
**Then** no reference to A4 page size remains in any file

## Scenario: Test suite passes after page size and chart dimension updates
**Given** the metrics report test suite
**When** the tests are run with the updated page size and chart dimensions
**Then** all tests pass, including any tests updated to reflect the new figsize or US Letter page size values
