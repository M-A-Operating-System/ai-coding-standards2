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
| `agents.md` | `ai-agile/pipeline/pipeline.json` | `ai-agile/pipeline/generators/generate_docs.py` |
| `phases.md` | `ai-agile/pipeline/pipeline.json` | `ai-agile/pipeline/generators/generate_docs.py` |
| `gates.md` | `ai-agile/pipeline/pipeline.json` | `ai-agile/pipeline/generators/generate_docs.py` |
| `pipeline.mmd` | `ai-agile/pipeline/pipeline.json` | `ai-agile/pipeline/generators/generate_pipeline_mermaid.py` |
| `pipeline-issue.mmd` | `ai-agile/pipeline/pipeline.json` | `ai-agile/pipeline/generators/generate_pipeline_mermaid.py` |
| `pipeline-pr.mmd` | `ai-agile/pipeline/pipeline.json` | `ai-agile/pipeline/generators/generate_pipeline_mermaid.py` |

---

## Regenerating

From the repo root:

```bash
python ai-agile/pipeline/generators/generate_docs.py
python ai-agile/pipeline/generators/generate_pipeline_mermaid.py
```

Generators are idempotent — running them twice produces byte-identical
output. CI runs both and fails the PR if any committed file differs from
the regenerated version.

---

## Status

Generators are not yet implemented. Files in this directory will be
populated as part of the build-out described in
[`05-pipeline-config.md`](../05-pipeline-config.md). Until then the
canonical source is `ai-agile/pipeline/pipeline.json` (currently at
`.claude/pipeline.json`, pending move).
