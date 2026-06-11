# Generated Documentation

**Do not hand-edit any file in this directory.**

Every file here is produced by a generator from a single machine-readable
source. Editing the generated file directly will be overwritten on the
next regeneration and rejected by CI.

This directory implements [P-2](../02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated):
human-readable views are generated from machine-readable sources.

---

## Sources and generators

| Generated file | Source | Generator | Status |
|---|---|---|---|
| `phases/{phase}.mmd` (one per phase) | `pipeline/pipeline.json` | `pipeline/generators/generate_phase_mermaid.py` | Implemented |
| `agents.md` | `pipeline/pipeline.json` | `pipeline/generators/generate_docs.py` | Planned |
| `phases.md` | `pipeline/pipeline.json` | `pipeline/generators/generate_docs.py` | Planned |
| `gates.md` | `pipeline/pipeline.json` | `pipeline/generators/generate_docs.py` | Planned |
| `pipeline.mmd` | `pipeline/pipeline.json` | `pipeline/generators/generate_pipeline_mermaid.py` | Planned |
| `pipeline-issue.mmd` | `pipeline/pipeline.json` | `pipeline/generators/generate_pipeline_mermaid.py` | Planned |
| `pipeline-pr.mmd` | `pipeline/pipeline.json` | `pipeline/generators/generate_pipeline_mermaid.py` | Planned |

---

## Regenerating

From the repo root:

```bash
python pipeline/generators/generate_phase_mermaid.py
```

Generators are idempotent — running them twice produces byte-identical
output. CI runs the generator and fails the PR if any committed file
differs from the regenerated version.

---

## Canonical source

The machine-readable source is `pipeline/pipeline.json`.
See [`05-pipeline-config.md`](../05-pipeline-config.md) for the
schema, change process, and generator invocation details.
