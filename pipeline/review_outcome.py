"""Code-computed review verdicts (issue #512 Part 2, STD-ARCH-035).

Pure functions -- findings in, verdict out -- with no GitHub client, no
orchestrator types (AgentDef/WorkItem), and no I/O of any kind. A reviewing
step (pr-reviewer) reports findings; this module, not the model, decides
whether they add up to APPROVE or REQUEST CHANGES (P-14: deterministic
orchestrator decides, the step only supplies facts).

Moved out of pipeline_orchestrator.py for the same reason todos_patch.py
was (issue #495): the algorithm is decoupled from the orchestrator's
dispatch/coordination code, importable and testable on its own, and adding
it does not grow the one file ADR-001 already tracks as over its own
line budget.
"""
import json
from typing import Optional

APPROVE = "APPROVE"
REQUEST_CHANGES = "REQUEST CHANGES"

_NON_BLOCKING_CONFIDENCE_THRESHOLD = 0.8


def adr_exception_index(adr_records: list[dict], standards_by_id: dict[str, dict]) -> dict[str, set[str]]:
    """Build {adr_id: {standard_id, ...}} from adrs.json's own records --
    only ADRs that actually list a standard in authorises_exception_to grant
    an exception for it (adrs.json's own rule, restated in CLAUDE.md and in
    pr-reviewer.md's own "ADR coverage" instruction). A plain decision record
    with no authorises_exception_to contributes no entries. A record whose
    own status is not "accepted" (proposed, deprecated, superseded) grants
    no exception either -- a withdrawn or not-yet-approved decision cannot
    still be waiving a standard.

    A standard is only included if standards_by_id (standards/*.json's own
    records, keyed by id) says its own adr_overridable is True -- verified
    the same way the ADR citation itself is, never trusted from the ADR's
    own listing alone (docs/product/standards/14-standards.md: "adr_overridable:
    false -- always blocks; no exception is possible"). A standard missing
    from standards_by_id is treated as non-overridable.
    """
    index: dict[str, set[str]] = {}
    for record in adr_records:
        if record.get("status") != "accepted":
            continue
        adr_id = record.get("id")
        standards = [
            std_id for std_id in (record.get("authorises_exception_to") or [])
            if standards_by_id.get(std_id, {}).get("adr_overridable") is True
        ]
        if adr_id and standards:
            index[adr_id] = set(standards)
    return index


def finding_blocks(finding: dict, adr_index: dict[str, set[str]]) -> bool:
    """A finding blocks APPROVE unless one of these holds (issue #506):

    - its category is "improvement" -- improvements are unconditionally
      non-blocking; the schema (pr-review.schema.json) forbids an
      improvement from carrying a severity at all, so there is no
      "Critical improvement" to defend against here;
    - its severity is "Low" or "Informational" -- the defect-blocking
      policy's own default table (issue #506): Critical/High/Medium block,
      Low/Informational do not;
    - it cites an ADR whose authorises_exception_to actually lists the
      finding's standard, verified against adrs.json rather than trusted
      from the finding's own claim;
    - it is not Critical and its confidence is below 0.8.

    Critical findings are handled explicitly (checked before the confidence
    gate applies) so a low confidence value can never silently make one
    non-blocking.
    """
    if finding.get("category") == "improvement":
        return False

    severity = finding.get("severity")

    if severity in ("Low", "Informational"):
        return False

    adr_id = finding.get("adr")
    standard = finding.get("standard")
    if adr_id and standard and standard in adr_index.get(adr_id, ()):
        return False

    confidence = finding.get("confidence", 1.0)
    if severity != "Critical" and confidence < _NON_BLOCKING_CONFIDENCE_THRESHOLD:
        return False

    return True


_IMPROVEMENT_DISPOSITIONS = {
    "simple": "fix-if-coder-cycle",
    "medium": "ask-human",
    "complex": "defer",
}


def improvement_disposition(finding: dict) -> Optional[str]:
    """Map an improvement's effort to how it gets actioned (issue #506):

    - "simple" -> "fix-if-coder-cycle": eligible for an already-required
      coder pass; does not by itself trigger one (a coder pass only ever
      runs on a REQUEST CHANGES verdict, and finding_blocks never returns
      True for an improvement, so this can never be the sole reason a pass
      exists).
    - "medium" -> "ask-human": flagged for a human's own decision on
      whether to do it at all, never auto-blocked.
    - "complex" -> "defer": recorded as future work via
      build_deferred_findings_issue, never fixed inline and never blocking.

    None for a non-improvement finding, or for an improvement whose effort
    is missing or unrecognised (the schema requires a valid effort on every
    improvement, so this should not occur in practice)."""
    if finding.get("category") != "improvement":
        return None
    return _IMPROVEMENT_DISPOSITIONS.get(finding.get("effort"))


def build_deferred_findings_issue(findings: list[dict], pr_number: Optional[int] = None) -> dict:
    """Bundle every "defer" disposition improvement (effort: complex) from
    one review round into a single creates_issue request (issue #506).
    AGENTS.md's result.json contract has one creates_issue slot per step
    run, not a list, so multiple deferred improvements become sections of
    one issue rather than one issue each. {} (no request) when nothing is
    deferred -- most runs have nothing to defer, and the orchestrator's own
    MI-6 consistency check already logs (not fails) an empty request
    against a step that declares expected_effect.creates_issues, the same
    way 00_ondemand/sizer's own conditional issue creation does."""
    deferred = [f for f in findings if improvement_disposition(f) == "defer"]
    if not deferred:
        return {}
    title = (
        f"Deferred review findings from PR #{pr_number}" if pr_number is not None
        else "Deferred review findings"
    )
    body_lines = [
        "The following optional improvements were raised during review but are "
        "too large to implement inline -- deferred here as future work rather "
        "than blocking the PR.",
        "",
    ]
    for f in deferred:
        body_lines.append(f"## {f.get('id', '')} -- {f.get('title', '')}")
        if f.get("path"):
            location = f"{f['path']}:{f['line']}" if f.get("line") else f["path"]
            body_lines.append(f"**File:** `{location}`")
        body_lines.append(f"**Evidence:** {f.get('evidence', '')}")
        body_lines.append(f"**Suggested fix:** {f.get('fix', '')}")
        body_lines.append("")
    return {"title": title, "body": "\n".join(body_lines), "labels": ["classification: tech-debt"]}


def derive_review_verdict(
    findings: list[dict],
    human_blockers: list,
    adr_records: list[dict],
    standards_by_id: Optional[dict] = None,
) -> str:
    """The verdict is REQUEST_CHANGES if any finding blocks or any human
    blocker exists; otherwise APPROVE. Code decides; the model's own
    outcome/verdict fields are advisory only (issue #512 Part 2).

    standards_by_id feeds adr_exception_index's own adr_overridable check;
    omitting it means no ADR exception is ever granted (fail closed), never
    a silent bypass of a standard that cannot be waived.
    """
    if human_blockers:
        return REQUEST_CHANGES
    adr_index = adr_exception_index(adr_records, standards_by_id or {})
    if any(finding_blocks(f, adr_index) for f in findings):
        return REQUEST_CHANGES
    return APPROVE


def find_duplicate_finding_ids(findings: list[dict]) -> list[str]:
    """Return the ids that appear more than once, in first-seen order --
    the shape of malformed review data (Scenario: Invalid review object)
    that JSON Schema's per-item validation alone cannot catch."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for finding in findings:
        finding_id = finding.get("id")
        if finding_id is None:
            continue
        if finding_id in seen and finding_id not in duplicates:
            duplicates.append(finding_id)
        seen.add(finding_id)
    return duplicates


_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Informational": 4}


def sort_findings(findings: list[dict]) -> list[dict]:
    """Critical -> High -> Medium -> Low -> Informational, stable within a
    severity (preserves the order the step reported them in). Improvements
    carry no severity and sort after every defect, stable among themselves."""
    return sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.get("severity"), len(_SEVERITY_ORDER)))


def render_review_comment(
    verdict: str,
    head_sha: str,
    findings: list[dict],
    adr_records: list[dict],
    *,
    standards_by_id: Optional[dict] = None,
    human_blockers: Optional[list] = None,
    prior_rerun: bool = False,
) -> str:
    """Render the artefact body the orchestrator posts on APPROVE would-be
    review comments -- verdict line, reviewed SHA, sorted findings, and the
    fenced JSON block coder.md Mode B (Step 9) parses back out. The step
    never renders its own comment (PRODUCT.md, "What a step must return");
    this is that render, done once, in the one place that also computes
    the verdict it describes.

    Each finding in the JSON block carries a "blocking" field -- the same
    review_outcome.finding_blocks computation the verdict itself used, so
    coder.md's Mode B never has to re-derive which findings block from
    severity/confidence/ADR data on its own (issue #512, "Coder reads the
    rendered findings").

    human_blockers (raw GitHub review objects, unresolved REQUEST_CHANGES)
    take priority over every finding in derive_review_verdict; the render
    must say so too, or a REQUEST CHANGES verdict with zero findings reads
    as unexplained -- and gives coder's Mode B nothing to act on.
    """
    human_blockers = human_blockers or []
    adr_index = adr_exception_index(adr_records, standards_by_id or {})
    ordered = sort_findings(findings)
    counts: dict[str, int] = {}
    for f in ordered:
        sev = "Improvement" if f.get("category") == "improvement" else f.get("severity", "Informational")
        counts[sev] = counts.get(sev, 0) + 1
    summary = " * ".join(
        f"{counts.get(sev, 0)} {sev}" for sev in list(_SEVERITY_ORDER) + ["Improvement"]
    )

    lines = [f"## PR Review{' (Re-run)' if prior_rerun else ''}", ""]
    lines.append(f"**Verdict: {verdict}**")
    lines.append(f"**Reviewed SHA:** `{head_sha}`")
    if human_blockers:
        reviewers = ", ".join(
            f"@{b.get('user', {}).get('login', '?')}" for b in human_blockers
        )
        lines.append(
            f"**Unresolved human REQUEST_CHANGES:** {reviewers} -- takes priority "
            "over automated findings; each reviewer must APPROVE or have their "
            "review dismissed to clear the block."
        )
    lines.append(f"**Summary:** {summary}")
    lines.append("")

    annotated: list[dict] = []
    if not ordered:
        lines.append("No findings.")
    for f in ordered:
        blocking = finding_blocks(f, adr_index)
        disposition = improvement_disposition(f)
        annotated.append({**f, "blocking": blocking})

        title = f.get("title", "")
        fid = f.get("id", "")
        severity = f.get("severity")
        category = f.get("category", "")
        path = f.get("path")
        line_no = f.get("line")
        if blocking:
            tag = "BLOCKING"
        elif disposition == "ask-human":
            tag = "FLAGGED FOR HUMAN DECISION"
        elif disposition == "defer":
            tag = "DEFERRED to a new issue"
        elif disposition == "fix-if-coder-cycle":
            tag = "eligible for the next required coder pass"
        else:
            tag = "non-blocking"
        sev_bracket = f" [{severity}]" if severity else ""
        lines.append(f"### {fid} -- {title}{sev_bracket} [{tag}]")
        lines.append("")
        if path:
            lines.append(f"**File:** `{path}:{line_no}`" if line_no else f"**File:** `{path}`")
        if category == "defect" and f.get("type"):
            lines.append(f"**Category:** defect ({f['type']})")
        elif category == "improvement" and f.get("effort"):
            lines.append(f"**Category:** improvement (effort: {f['effort']})")
        else:
            lines.append(f"**Category:** {category}")
        if f.get("standard"):
            adr_note = f" [ADR: {f['adr']}]" if f.get("adr") else ""
            lines.append(f"**Standard:** {f['standard']}{adr_note}")
        lines.append("")
        lines.append(f"**Evidence:** {f.get('evidence', '')}")
        lines.append("")
        lines.append(f"**Fix:** {f.get('fix', '')}")
        lines.append("")

    lines.append("---")
    lines.append("_On APPROVE: PR is marked ready for human review. On REQUEST CHANGES: "
                  "the orchestrator will automatically re-invoke the coder (up to 3 cycles). "
                  "After 3 cycles without agreement, human sign-off is required._")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps({"head_sha": head_sha, "findings": annotated}, indent=2))
    lines.append("```")

    return "\n".join(lines)
