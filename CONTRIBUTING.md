# Contributing to ai-coding-standards2

Welcome. This repo is the AI Agile pipeline — a deterministic Python orchestrator plus
a catalogue of agent prompts that moves GitHub issues through to merged PRs with human
approval at well-defined gates. If you are new here, read
[docs/product/orchestrator/README.md](docs/product/orchestrator/README.md) before
making changes.

---

## Contents

- [Before you start](#before-you-start)
- [Local setup](#local-setup)
- [Running tests](#running-tests)
- [Code standards](#code-standards)
- [Submitting a change](#submitting-a-change)
- [Adding or changing an agent](#adding-or-changing-an-agent)
- [Changing pipeline.json](#changing-pipelinejson)
- [Changing the standards files](#changing-the-standards-files)
- [Changing get_started.py](#changing-get_startedpy)
- [Documentation](#documentation)

---

## Before you start

This is a **private repo for trusted contributors only.** The orchestrator runs the
`coder` agent with broad shell access and has `ANTHROPIC_API_KEY` and
`GITHUB_TOKEN` in its environment. Do not install this pipeline on a public
repository where untrusted users can open issues.

If you are evaluating a change that touches the orchestrator workflow or any agent
prompt, test it against this repo first (it runs the pipeline against itself) before
shipping to consuming repos.

---

## Local setup

```bash
git clone git@github.com:M-A-Operating-System/ai-coding-standards2.git
cd ai-coding-standards2
pip install -r requirements.txt
```

No further setup is needed to run tests or validate the pipeline. You do not need to
add this repo as a submodule of another repo just to work on it.

---

## Running tests

```bash
pytest
```

526 tests cover `get_started.py`, `pipeline_orchestrator.py`, `validate.py`,
`validate_standards.py`, and the pipeline schema. All must pass before a PR is merged.

To run a single suite:

```bash
pytest tests/test_get_started.py
pytest tests/test_validate_standards.py
```

To validate the pipeline graph independently:

```bash
python pipeline/validate.py
```

---

## Code standards

### ASCII-safe output

Never write emoji or non-ASCII characters inside code, configuration, or workflow files.
This includes Python source files, shell scripts, GitHub Actions YAML files, and JSON
files. Use plain English words instead:

- Em dash `--` not `--`
- Arrow `->` not `->`
- Checkmark `OK:` not a tick symbol

Markdown documentation files (`.md`) may use Unicode freely.

### File encoding

All file reads and writes must specify `encoding="utf-8"` explicitly. Python defaults
to the platform codec (cp1252 on Windows) which cannot round-trip UTF-8 content.

```python
path.read_text(encoding="utf-8")
path.write_text(content, encoding="utf-8")
open(path, "a", encoding="utf-8")
```

### No comments explaining what code does

Comments are for non-obvious *why*, not for *what*. Well-named identifiers carry the
what. Do not add docstrings that restate the function signature or describe each
argument unless the behaviour is genuinely surprising.

### GitHub Actions naming (STD-PROC-028)

Workflow file `name:` fields follow `{TYPE} - {Description}` where TYPE is uppercase
and the description is an active sentence. For deploy workflows, include the target
platform: `DEPLOY - Supabase`, `DEPLOY - Azure`. See `standards/process.json` for the
full vocabulary and examples.

---

## Submitting a change

1. **Open an issue** describing what you want to change and why. For small fixes
   (typo, one-line bug) a PR without a prior issue is fine.

2. **Branch from main:**

   ```bash
   git checkout -b your-name/short-description
   ```

3. **Make your change, run tests:**

   ```bash
   pytest
   python pipeline/validate.py
   ```

4. **Push and open a draft PR.** Include:
   - What changed and why (not just what the diff says)
   - How to test it

5. The pipeline will classify and review your PR automatically. Wait for the
   `pr-reviewer` label to reach `:complete` before requesting human review.

6. Address `pr-reviewer` findings marked Critical, High, or Medium before the PR
   can be merged.

---

## Adding or changing an agent

Agent prompt files live under `.claude/agents/{phase}/{agent-name}.md`. The file
format is specified in [docs/product/orchestrator/12-agent-spec.md](docs/product/orchestrator/12-agent-spec.md).

Every new agent also needs an entry in `pipeline/pipeline.json`. Run the validator
after any change to that file:

```bash
python pipeline/validate.py
```

The `00_ondemand/new-agent` agent can scaffold a new agent from an issue description
if you apply the `new-agent:requested` label.

Key rules for agent prompts:

- No non-ASCII characters (see code standards above)
- State all tool permissions in the `tools:` frontmatter list
- Reference paths via `$AI_AGILE_ROOT` or `$STATUS_SH`, never hardcoded absolute paths
- Test the agent in this repo (which runs the pipeline against itself) before shipping

---

## Changing pipeline.json

`pipeline/pipeline.json` is the single source of truth for the agent dependency graph.
Human-readable views (Mermaid diagrams, agent catalogues) are generated from it and
must not be hand-edited.

After changing `pipeline.json`:

1. Run the validator: `python pipeline/validate.py`
2. Regenerate the Mermaid diagram:

   ```bash
   python pipeline/generators/generate_phase_mermaid.py
   ```

3. Commit both files in the same PR.

---

## Changing the standards files

Standards live in `standards/*.json` and are validated against
`pipeline/schemas/standards.schema.json`. After a change:

```bash
pytest tests/test_validate_standards.py
```

The `standards-migrator` agent can help convert existing knowledge documents into
machine-readable standards format. Apply the `standards-migrator:requested` label to
an issue to invoke it.

---

## Changing get_started.py

`get_started.py` runs on the developer's local machine (Windows, macOS, or Linux)
during the two-step onboarding flow:

- **Step 1 (local, cross-platform):** `python ai-coding-standards2/get_started.py --seed`
  copies only `orchestrator.yml` to `.github/workflows/` and adds `.gitignore` entries.
- **Step 2 (GitHub Actions, Linux only):** trigger the **Onboard** job in the
  Pipeline Orchestrator workflow. It calls `get_started.py --force` on a Linux runner
  to create symlinks, copy slash commands, install standards, and commit everything.

Because Step 1 runs on Windows, the script must:

- Contain no non-ASCII characters anywhere in the source file
- Specify `encoding="utf-8"` on every file read and write

Tests for `get_started.py` are in `tests/test_get_started.py`.

---

## Documentation

Product documentation is in `docs/product/orchestrator/`. The reading order and a
full document map are in that directory's [README](docs/product/orchestrator/README.md).

When a code change affects documented behaviour, update the relevant doc in the same
PR. Do not open a separate "docs PR" for a change that should have been in the
code PR.

Generated files under `docs/product/orchestrator/generated/` are produced by scripts
in `pipeline/generators/`. Update the generator, not the output file directly.
