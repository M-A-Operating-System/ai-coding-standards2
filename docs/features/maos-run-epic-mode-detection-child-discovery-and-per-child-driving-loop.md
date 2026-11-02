# Feature: Maos-Run Epic Mode Detection Child Discovery And Per-Child Driving Loop

## Scenario: maos-run drives each child of an epic issue in sub-issue order

**Given** an issue N carries the `epic` and `blocked` labels and has a non-empty native sub-issue list
**When** an operator runs `/maos-run N`
**Then** each child issue is driven through its own pipeline via `drive-item.sh` in the order returned by the sub-issues API, with each child's human gate surfaced individually rather than batched

## Scenario: maos-run on a non-epic issue follows the existing single-issue path

**Given** an issue N does not carry the `epic` label, or carries `epic` but has an empty native sub-issue list
**When** an operator runs `/maos-run N`
**Then** `drive-item.sh` is invoked directly on issue N with no child-discovery logic applied

## Scenario: epic-driving loop stops at the first child that halts for a human gate

**Given** an issue N carries the `epic` and `blocked` labels with a non-empty sub-issue list, and child issue C (not the last child) halts at a human gate during its pipeline run
**When** an operator runs `/maos-run N`
**Then** the command stops after reporting C's human gate message and does not invoke `drive-item.sh` on any subsequent child issues
