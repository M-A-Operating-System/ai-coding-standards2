"""One-shot script to remove temp artefact files left by prd-writer agent."""
from pathlib import Path
for name in [".tmp_announcement.md", ".tmp_closing.md", ".tmp_new_body.md", ".tmp_snapshot.md"]:
    p = Path(name)
    if p.exists():
        p.unlink()
