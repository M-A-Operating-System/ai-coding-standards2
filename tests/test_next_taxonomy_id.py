"""Tests for pipeline/next_taxonomy_id.py."""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import pytest
from pathlib import Path
from next_taxonomy_id import next_ids
from validate_taxonomy import DOMAINS, LEVEL_PREFIX, collect_nodes

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
REAL_TAXONOMY_DIR = REPO_ROOT / "taxonomy"
SCRIPT = REPO_ROOT / "pipeline" / "next_taxonomy_id.py"


@pytest.fixture()
def taxonomy(tmp_path) -> Path:
    """A writable copy of the real taxonomy, so nodes can be injected."""
    dest = tmp_path / "taxonomy"
    shutil.copytree(REAL_TAXONOMY_DIR, dest)
    return dest


def _ids_in_use() -> set[str]:
    loaded = {f"{d}/{d}.json": json.loads((REAL_TAXONOMY_DIR / d / f"{d}.json").read_text())
              for d in DOMAINS}
    by_id, _, _ = collect_nodes(loaded)
    return set(by_id)


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


# ---------------------------------------------------------------------------
# The allocated identifier is free, and formed correctly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", sorted(LEVEL_PREFIX))
def test_next_identifier_is_not_in_use(level):
    in_use = _ids_in_use()
    assert next_ids(REAL_TAXONOMY_DIR, level)[0] not in in_use


@pytest.mark.parametrize("level,prefix", sorted(LEVEL_PREFIX.items()))
def test_next_identifier_carries_the_level_code(level, prefix):
    allocated = next_ids(REAL_TAXONOMY_DIR, level)[0]
    assert allocated.startswith(prefix)
    assert allocated[len(prefix):].isdigit()
    assert len(allocated[len(prefix):]) == 6


@pytest.mark.parametrize("level", sorted(LEVEL_PREFIX))
def test_next_identifier_follows_the_highest_in_use(level):
    """The counter advances past the highest number issued, not the node count."""
    prefix = LEVEL_PREFIX[level]
    highest = max(int(i[len(prefix):]) for i in _ids_in_use() if i.startswith(prefix))
    assert next_ids(REAL_TAXONOMY_DIR, level) == [f"{prefix}{highest + 1:06d}"]


def test_count_returns_consecutive_identifiers():
    allocated = next_ids(REAL_TAXONOMY_DIR, "subclass", 4)
    assert len(allocated) == 4
    assert len(set(allocated)) == 4
    numbers = [int(i[3:]) for i in allocated]
    assert numbers == list(range(numbers[0], numbers[0] + 4))
    assert not set(allocated) & _ids_in_use()


# ---------------------------------------------------------------------------
# A retired number is never handed out again
# ---------------------------------------------------------------------------

def test_deprecated_node_still_consumes_its_number(taxonomy):
    """Identifiers retire by deprecation, so the counter must clear them too."""
    doc = json.loads((taxonomy / "code" / "code.json").read_text())
    family = next(iter(doc["families"].values()))
    klass = next(iter(family["classes"].values()))
    retired = dict(next(iter(klass["subclasses"].values())))
    retired.update({
        "id": "SUB009000",
        "path": f"{retired['path']}-retired",
        "name": "Retired",
        "status": "deprecated",
        "replaced_by": "SUB000001",
    })
    klass["subclasses"]["retired"] = retired
    (taxonomy / "code" / "code.json").write_text(json.dumps(doc, indent=2))

    assert next_ids(taxonomy, "subclass") == ["SUB009001"]


def test_allocating_past_a_gap_does_not_backfill(taxonomy):
    """Counters never rewind, so a hole left by a rename is not reissued."""
    doc = json.loads((taxonomy / "patterns" / "patterns.json").read_text())
    family = next(iter(doc["families"].values()))
    klass = next(iter(family["classes"].values()))
    sub = next(iter(klass["subclasses"].values()))
    sub["id"] = "SUB800000"
    (taxonomy / "patterns" / "patterns.json").write_text(json.dumps(doc, indent=2))

    assert next_ids(taxonomy, "subclass") == ["SUB800001"]


# ---------------------------------------------------------------------------
# Usage errors
# ---------------------------------------------------------------------------

def test_unknown_level_is_rejected():
    with pytest.raises(ValueError, match="unknown level"):
        next_ids(REAL_TAXONOMY_DIR, "domain")


def test_level_is_not_guessed_from_a_prefix():
    """'SUB' is the code, not the level name; only the three level names work."""
    with pytest.raises(ValueError, match="unknown level"):
        next_ids(REAL_TAXONOMY_DIR, "SUB")


def test_non_positive_count_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        next_ids(REAL_TAXONOMY_DIR, "subclass", 0)


def test_empty_taxonomy_dir_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        next_ids(tmp_path, "subclass")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def test_cli_prints_one_identifier_per_line():
    result = _run("class", "2")
    assert result.returncode == 0
    lines = result.stdout.split()
    assert len(lines) == 2
    assert all(line.startswith("CLS") for line in lines)


def test_cli_rejects_an_unknown_level():
    result = _run("domain")
    assert result.returncode == 2
    assert "unknown level" in result.stderr


def test_cli_reports_a_missing_taxonomy(tmp_path):
    result = _run("subclass", "--taxonomy-dir", str(tmp_path))
    assert result.returncode == 1
    assert "no domain files found" in result.stderr
