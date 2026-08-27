# Generated Documentation

**Do not hand-edit any file in this directory.**

Every file here is produced by a generator from a single machine-readable
source. Editing the generated file directly will be overwritten on the
next regeneration and rejected by CI.

This directory implements [P-2](../02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated):
human-readable views are generated from machine-readable sources.

---

## Sources and generators

| Generated file | Source | Generator |
|---|---|---|
| `agents.md` | `pipeline/pipeline.json` | `pipeline/generators/generate_docs.py` |
| `pipeline-steps.md` | `pipeline/pipeline.json` | `pipeline/generators/generate_docs.py` |
| `statuses.md` | `pipeline/statuses.json` | `pipeline/generators/generate_docs.py` |
| `pipeline.mmd` | `pipeline/pipeline.json` | `pipeline/generators/generate_phase_mermaid.py` |
| `pipeline_phases.mmd` | `pipeline/pipeline.json` | `pipeline/generators/generate_phase_mermaid.py` |
| `phases/{phase}.mmd` (one per phase) | `pipeline/pipeline.json` | `pipeline/generators/generate_phase_mermaid.py` |
| `pipeline-schema-reference.md` | `docs/product/orchestrator/schema/pipeline.schema.json` | `pipeline/generators/generate_schema_reference.py` |

The last row is a different kind of source. Every other row describes
`pipeline/pipeline.json` as it exists today; `pipeline-schema-reference.md`
describes the **target** shape (issue #393) -- what `pipeline.json` is meant
to become, not what it currently is. See
[`gap_analysis.md`](../gap_analysis.md) for the distance between them.

---

## Regenerating

From the repo root:

```bash
python3 pipeline/generators/generate_docs.py
python3 pipeline/generators/generate_phase_mermaid.py
python3 pipeline/generators/generate_schema_reference.py
```

Generators are idempotent -- running them twice produces byte-identical
output. To verify without writing:

```bash
python3 pipeline/generators/generate_docs.py --check
```

CI regenerates these files on every push to `main` that touches the sources
and commits the result (`.github/workflows/generate-pipeline-diagrams.yml`).
It does not fail a PR whose committed output is stale -- it repairs it after
merge. Run `--check` locally if you want the stricter behaviour before
pushing.

---

## Canonical source

The machine-readable sources are `pipeline/pipeline.json` (process,
sequence, dependencies, entitled activities) and `pipeline/statuses.json`
(the label model).

`pipeline.json` is authoritative for the pipeline definition -- see **AS-1**
in [`../PRODUCT.md`](../PRODUCT.md). Nothing in this directory adds a fact
that is not in one of those two files; if a fact is missing here, it is
missing at source.
