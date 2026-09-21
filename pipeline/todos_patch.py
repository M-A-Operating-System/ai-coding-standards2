"""Todos-block markdown patching (issue #495, STD-ARCH-035).

Pure string-transformation functions -- body in, new body out -- with no
GitHub client, no orchestrator types (AgentDef/WorkItem), and no I/O of any
kind. Moved out of pipeline_orchestrator.py so the patching algorithm is
decoupled from the orchestrator's dispatch/coordination code, importable and
testable on its own.

Imported directly rather than invoked as a subprocess: unlike the git/
filesystem extractions (issue #445/#493's salvage-exhausted-worktree.sh,
this issue's ensure-gh-cli.sh), this has no OS-level work to isolate into a
process boundary, and the caller (_apply_body_write's read-compute-write-
verify retry loop) calls it inline against a body it already holds in
memory -- a subprocess-per-attempt would add latency to that retry loop for
no isolation benefit.
"""
import re
from typing import Optional

TODOS_HEADING = "## AI Agile -- Tasks"
TODOS_OUTER_START = "<!-- ai-agile/todos/v1 START -->"
TODOS_OUTER_END = "<!-- ai-agile/todos/v1 END -->"

_CHECKED_ITEM_RE = re.compile(r"^[ \t]*-\s*\[x\]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def todos_subsection_markers(subsection: str) -> tuple[str, str]:
    return (
        f"<!-- ai-agile/todos/{subsection}/v1 START -->",
        f"<!-- ai-agile/todos/{subsection}/v1 END -->",
    )


def checked_items_would_be_lost(old_content: str, new_content: str) -> str:
    """Return a non-empty refusal reason if any `- [x]` line in old_content
    is missing, or no longer checked, in new_content -- comparing by the
    checkbox's own text, so a step that only appends new entries or ticks
    more boxes never trips this. A checked item's text is terminal (AGENTS.md:
    a `done`/`blocked`/`skipped` event is appended once and it never changes
    again), so an exact-text comparison is the whole check.
    """
    old_checked = set(_CHECKED_ITEM_RE.findall(old_content))
    if not old_checked:
        return ""
    lost = old_checked - set(_CHECKED_ITEM_RE.findall(new_content))
    if not lost:
        return ""
    shown = sorted(lost)[:3]
    return (
        f"patch would un-check or drop {len(lost)} previously checked item(s): "
        + "; ".join(shown) + ("; ..." if len(lost) > len(shown) else "")
    )


def apply_todos_patch(body: str, subsection: str, content: str) -> tuple[Optional[str], str]:
    """Compute a new body with `subsection`'s todos-block content replaced by
    `content`, creating the outer/subsection marker blocks if either is
    absent yet (PRODUCT.md, "What lands on the issue"). Returns (new_body,
    "") on success, or (None, reason) when the patch would silently drop a
    previously checked item -- the caller keeps the old body unchanged.

    Touches only the named subsection; every other subsection's content,
    and everything outside the outer block, passes through byte-for-byte.
    """
    sub_start, sub_end = todos_subsection_markers(subsection)

    outer_start_idx = body.find(TODOS_OUTER_START)
    if outer_start_idx == -1:
        # No todos block at all yet -- create it, with just this subsection.
        block = (
            f"\n\n{TODOS_HEADING}\n\n{TODOS_OUTER_START}\n"
            f"{sub_start}\n{content}\n{sub_end}\n"
            f"{TODOS_OUTER_END}\n"
        )
        return body.rstrip("\n") + block, ""

    outer_end_idx = body.find(TODOS_OUTER_END, outer_start_idx)
    if outer_end_idx == -1:
        return None, "found an unterminated todos block (START with no matching END)"

    outer_inner_start = outer_start_idx + len(TODOS_OUTER_START)
    outer_content = body[outer_inner_start:outer_end_idx]

    sub_start_idx = outer_content.find(sub_start)
    if sub_start_idx == -1:
        # Subsection doesn't exist yet within the outer block -- append it,
        # leaving every existing subsection untouched.
        new_outer_content = outer_content.rstrip("\n") + f"\n{sub_start}\n{content}\n{sub_end}\n"
        return body[:outer_inner_start] + new_outer_content + body[outer_end_idx:], ""

    sub_end_idx = outer_content.find(sub_end, sub_start_idx)
    if sub_end_idx == -1:
        return None, f"found an unterminated {subsection} subsection (START with no matching END)"

    sub_inner_start = sub_start_idx + len(sub_start)
    old_content = outer_content[sub_inner_start:sub_end_idx]

    refusal = checked_items_would_be_lost(old_content, content)
    if refusal:
        return None, refusal

    # Same "\n{content}\n" wrapping as the create-from-scratch and
    # new-subsection paths above, so a subsection's on-disk shape doesn't
    # depend on whether this is its first patch or a later one.
    new_outer_content = outer_content[:sub_inner_start] + f"\n{content}\n" + outer_content[sub_end_idx:]
    return body[:outer_inner_start] + new_outer_content + body[outer_end_idx:], ""
