"""Deterministic audit verdicts for issue-obsolescence-audit (issue #743).

Pure functions -- evidence items in, verdict out -- with no GitHub client, no
orchestrator types, and no I/O of any kind. The issue-obsolescence-audit agent
reports structured evidence; this module, not the model, decides the verdict
from those items. Mirrors review_outcome.derive_review_verdict (issue #512
Part 2): the model's own stated conclusion is never trusted directly.
"""
import re

OBSOLETE = "OBSOLETE"
STILL_VALID = "STILL-VALID"
NEEDS_HUMAN_REVIEW = "NEEDS-HUMAN-REVIEW"

CLOSING_THRESHOLD = 0.85

CLOSING_TYPES = frozenset({"code-removed", "code-changed", "merged-fix"})


def _superseded_verdict(citation: str) -> str:
    """Format SUPERSEDED-BY-#N from a citation that holds the issue number."""
    m = re.search(r"(\d+)", str(citation))
    if not m:
        raise ValueError(
            f"superseding-issue citation contains no issue number: {citation!r}"
        )
    return f"SUPERSEDED-BY-#{m.group(1)}"


def derive_audit_verdict(evidence: list) -> str:
    """Compute the verdict from a list of evidence items (issue #741 rule set).

    Rule priority (first match wins):
    1. OBSOLETE -- a code-removed/code-changed/merged-fix item reaches 0.85 AND
       no contradicted item reaches 0.85.
    2. SUPERSEDED-BY-#N -- a superseding-issue item reaches 0.85 AND no
       contradicted item reaches 0.85.
    3. STILL-VALID -- a contradicted item reaches 0.85 AND no closing or
       superseding item reaches 0.85.
    4. NEEDS-HUMAN-REVIEW -- otherwise, including: conflicting high-confidence
       items (closing/superseding AND contradicted both above threshold), every
       item below 0.85, and unverifiable items with no competing signal.
    """
    has_closing = any(
        item.get("type") in CLOSING_TYPES
        and item.get("confidence", 0) >= CLOSING_THRESHOLD
        for item in evidence
    )
    superseding_item = next(
        (
            item for item in evidence
            if item.get("type") == "superseding-issue"
            and item.get("confidence", 0) >= CLOSING_THRESHOLD
        ),
        None,
    )
    has_contradicted = any(
        item.get("type") == "contradicted"
        and item.get("confidence", 0) >= CLOSING_THRESHOLD
        for item in evidence
    )

    if has_contradicted and (has_closing or superseding_item):
        return NEEDS_HUMAN_REVIEW

    if has_closing:
        return OBSOLETE

    if superseding_item:
        return _superseded_verdict(superseding_item.get("citation", ""))

    if has_contradicted:
        return STILL_VALID

    return NEEDS_HUMAN_REVIEW


def select_top_evidence(evidence: list, types: frozenset, min_confidence: float = CLOSING_THRESHOLD) -> dict:
    """Return the highest-confidence item of the given type(s) at or above
    min_confidence (issue #745's OBSOLETE/SUPERSEDED-BY-#N auto-close actions
    use this to pick which evidence item's citation/excerpt to cite in the
    closing comment). Raises ValueError, naming the expected types, if none
    qualifies -- this should never happen when called on evidence that
    already produced the corresponding verdict from derive_audit_verdict, so
    a raise here means the two have gone out of sync, not a normal outcome.
    """
    items = [
        item for item in evidence
        if item.get("type") in types and item.get("confidence", 0) >= min_confidence
    ]
    if not items:
        raise ValueError(f"no evidence item of type {sorted(types)} at or above {min_confidence}")
    return max(items, key=lambda i: i.get("confidence", 0))


def batch_sort_key(issue: dict) -> str:
    """Single sort key for open-issue batch selection.

    Returns the date from the current issue-obsolescence-audit:reviewed-YYYY-MM-DD
    label when the issue has one, otherwise the issue's created_at. Never-reviewed
    issues sort by their own age, not ahead of or behind all reviewed issues
    regardless of creation date -- there is no two-tier bucketing (issue #741).
    """
    for label in (issue.get("labels") or []):
        name = label if isinstance(label, str) else label.get("name", "")
        m = re.match(r"issue-obsolescence-audit:reviewed-(\d{4}-\d{2}-\d{2})$", name)
        if m:
            return m.group(1)
    return issue.get("created_at", "")


def select_batch(issues: list, limit: int = 10) -> list:
    """Select up to limit open issues sorted by single age key ascending."""
    return sorted(issues, key=batch_sort_key)[:limit]
