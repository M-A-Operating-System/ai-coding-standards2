"""Resolves entitlement_groups catalog references (issue #523).

Single source of truth for one operation -- "what does this allow_groups/
deny_groups entry mean" -- so pipeline_orchestrator.py's loader and
generate_docs.py's doc generator cannot silently disagree on it. Pure data
transform, no orchestrator or GitHub coupling (same reasoning as
todos_patch.py: importable from a plain script without pulling in the
orchestrator's heavier dependencies).
"""


def _coerce_pattern_list(val: object, context: str) -> list[str]:
    """Coerce a `patterns` value to a list of strings.

    Mirrors pipeline_orchestrator._coerce_tools' contract exactly (accepts a
    JSON array, a comma-separated string, or None/missing) so this module's
    behavior matches the orchestrator's own coercion without importing it.
    """
    if val is None or val == []:
        return []
    if isinstance(val, str):
        return [t.strip() for t in val.split(",") if t.strip()]
    if isinstance(val, list):
        for t in val:
            if not isinstance(t, str):
                raise TypeError(
                    f"{context} patterns list elements must be strings, got {type(t).__name__}: {t!r}"
                )
        return [t.strip() for t in val if t.strip()]
    raise TypeError(f"{context} patterns must be a list or comma-separated string, got {type(val).__name__}")


def resolve_group(group: object, entitlement_groups: dict, field_name: str = "group") -> dict:
    """Resolve one allow_groups/deny_groups entry to {name, purpose, patterns}.

    `group` is either a string naming a top-level entitlement_groups catalog
    entry, or a legacy inline {name, purpose, patterns} object -- both forms
    resolve to the same shape. Raises ValueError for a string naming an
    unknown catalog entry, TypeError for anything else.
    """
    if isinstance(group, str):
        definition = (entitlement_groups or {}).get(group)
        if definition is None:
            raise ValueError(f"unknown entitlement group {group!r}")
        return {
            "name": group,
            "purpose": definition.get("purpose", ""),
            "patterns": _coerce_pattern_list(definition.get("patterns"), group),
        }
    if isinstance(group, dict):
        if "patterns" not in group:
            raise ValueError(
                f"inline entitlement group {group.get('name', '<unnamed>')!r} is missing 'patterns' "
                "-- an inline group with no patterns key contributes nothing, which is very likely a typo"
            )
        return {
            "name": group.get("name", ""),
            "purpose": group.get("purpose", ""),
            "patterns": _coerce_pattern_list(group.get("patterns"), group.get("name") or "<inline>"),
        }
    raise TypeError(f"{field_name} entries must be entitlement-group names or inline objects")


def resolve_pattern_groups(groups: list, entitlement_groups: dict, field_name: str = "group") -> list[str]:
    """Flatten a list of group entries into a deduplicated pattern list.

    First-occurrence order preserved: a duplicate pattern, whether repeated
    across groups or already present in a literal list a caller merges this
    into, must not change effective behavior (issue #523).
    """
    patterns: list[str] = []
    for group in groups or []:
        patterns.extend(resolve_group(group, entitlement_groups, field_name).get("patterns", []))
    return list(dict.fromkeys(patterns))
