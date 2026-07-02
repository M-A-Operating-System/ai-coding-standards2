# Contributing to ai-coding-standards2

## Questions and feedback

Use [GitHub Discussions](../../discussions) to ask questions, share feedback, or
propose ideas before opening an issue or PR.

---

## Start here

Read [docs/product/orchestrator/README.md](docs/product/orchestrator/README.md) first.
It explains the system, the document map, and the recommended reading order. Everything
you need to understand the pipeline before making changes is in that folder.

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

All 526 tests must pass before a PR is merged.

---

## Submitting a change

1. Open an issue describing what you want to change and why.
2. Branch from `main` and make your change.
3. Run `pytest` and `python pipeline/validate.py`.
4. Open a draft PR. The pipeline will classify and review it automatically.
5. Address any Critical, High, or Medium findings from `pr-reviewer` before requesting
   human review.

---

## Code standards

See [CLAUDE.md](CLAUDE.md) for the project-wide rules (ASCII-safe output, UTF-8
encoding). See `standards/process.json` for the GitHub Actions naming standard
(STD-PROC-028).

---

## Security notice

This is a private repo for trusted contributors only. The `coder` agent runs with
broad shell access and has `ANTHROPIC_API_KEY` and `GITHUB_TOKEN` in its environment.
Do not install this pipeline on a public repository where untrusted users can open
issues.
