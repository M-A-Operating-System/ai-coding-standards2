# Contributing to AI Agile

Contributions are welcome — bug reports, design feedback, agent improvements,
and code. This guide covers how to get set up and what to expect.

## Questions and feedback

Use [GitHub Discussions](https://github.com/M-A-Operating-System/ai-coding-standards2/discussions)
to ask questions, share feedback, or propose ideas before opening an issue or PR.

---

## Start here

Read [docs/product/orchestrator/README.md](docs/product/orchestrator/README.md) first.
It explains the system, the document map, and the recommended reading order. Everything
you need to understand the pipeline before making changes is in that folder.

---

## What happens when you open an issue

This repo runs the AI Agile pipeline on itself. When you open an issue, an
agent will classify it (bug / feature / enhancement / spike / toil) within a
few minutes, and if it progresses, the `prd-writer` agent may restructure the
issue body into PRD format (user stories and Gherkin acceptance criteria).
This is expected behaviour, not vandalism — your original intent is preserved
and you can comment or edit at any time.

To give your issue the best start, include a **problem statement** and
**acceptance criteria**. Issues missing required fields get a corrective
comment from the classifier explaining what to add.

---

## Local setup

```bash
git clone git@github.com:M-A-Operating-System/ai-coding-standards2.git
cd ai-coding-standards2
pip install -r requirements.txt
```

## Running tests

```bash
pytest
python pipeline/validate.py
```

The full test suite must pass before a PR is merged.

---

## Submitting a change

1. Open an issue describing what you want to change and why (or discuss it
   first in Discussions).
2. Branch from `main` and make your change.
3. Run `pytest` and `python pipeline/validate.py`.
4. Open a draft PR. The pipeline will review it automatically.
5. Address any Critical, High, or Medium findings from `pr-reviewer` before
   requesting human review.

---

## Code standards

See [CLAUDE.md](CLAUDE.md) for the project-wide rules (ASCII-safe output, UTF-8
encoding). See `standards/process.json` for the GitHub Actions naming standard
(STD-PROC-028).

---

## A note on security

Contributing to this repo is open. **Installing** the pipeline is a different
matter: the `coder` agent runs with broad shell access and processes issue
bodies, so the pipeline must only be installed on private repos with trusted
contributors — never on a public repo where untrusted users can open issues.
See the security notice in the [README](README.md#using-this-repo).
