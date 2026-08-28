#!/usr/bin/env python3
"""
next_taxonomy_id.py - report the next free node identifier for a level.

Usage:
    python pipeline/next_taxonomy_id.py <level> [count] [--taxonomy-dir PATH]

    python pipeline/next_taxonomy_id.py subclass       -> SUB000264
    python pipeline/next_taxonomy_id.py class 3        -> CLS000152
                                                          CLS000153
                                                          CLS000154

Node identifiers are opaque and sequential within a level, assigned once and
retired only by deprecation. The counter therefore has to advance past every
number ever issued, not past every number currently active - which is why the
next value is derived from the highest identifier present in the tree,
deprecated nodes included, rather than from a count of live nodes.

This reads the taxonomy; it does not reserve anything. Two branches run
concurrently will be handed the same number, and that collision surfaces when
the second one merges and validate_taxonomy.py reports the identifier as
reused. Detecting it late is the accepted cost here; issuing numbers centrally
would need a reservation scheme, which is a larger decision than this script.

Exits 0 on success, 1 if the taxonomy cannot be read, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from validate_taxonomy import (
    DEFAULT_TAXONOMY_DIR,
    DOMAINS,
    LEVEL_PREFIX,
    collect_nodes,
)

# Must stay in step with ID_PATTERN in validate_taxonomy.py, which is what
# rejects a badly formed identifier once it has been written into a file.
ID_WIDTH = 6


def next_ids(taxonomy_dir: Path, level: str, count: int = 1) -> list[str]:
    """
    The next `count` free identifiers for `level`, lowest first.

    Raises ValueError for an unknown level or a non-positive count, and
    FileNotFoundError if the taxonomy has no domain files to read.
    """
    prefix = LEVEL_PREFIX.get(level)
    if prefix is None:
        raise ValueError(
            f"unknown level {level!r}; expected one of {', '.join(sorted(LEVEL_PREFIX))}"
        )
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")

    loaded: dict[str, dict] = {}
    for domain in DOMAINS:
        path = taxonomy_dir / domain / f"{domain}.json"
        if path.is_file():
            loaded[f"{domain}/{domain}.json"] = json.loads(path.read_text())
    if not loaded:
        raise FileNotFoundError(f"no domain files found in {taxonomy_dir}")

    # Ignore the traversal's errors: a malformed tree is validate_taxonomy.py's
    # to report, and refusing to allocate would leave an author unable to write
    # the very node that fixes it.
    by_id, _, _ = collect_nodes(loaded)

    highest = 0
    for node_id in by_id:
        if node_id.startswith(prefix):
            digits = node_id[len(prefix):]
            if digits.isdigit():
                highest = max(highest, int(digits))

    return [f"{prefix}{n:0{ID_WIDTH}d}" for n in range(highest + 1, highest + 1 + count)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report the next free taxonomy node identifier for a level."
    )
    parser.add_argument(
        "level",
        help=f"one of: {', '.join(sorted(LEVEL_PREFIX))}",
    )
    parser.add_argument(
        "count",
        nargs="?",
        type=int,
        default=1,
        help="how many consecutive identifiers to report (default 1)",
    )
    parser.add_argument(
        "--taxonomy-dir",
        type=Path,
        default=DEFAULT_TAXONOMY_DIR,
        help=f"path to the taxonomy folder (default {DEFAULT_TAXONOMY_DIR})",
    )
    args = parser.parse_args()

    try:
        ids = next_ids(args.taxonomy_dir, args.level, args.count)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("\n".join(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
