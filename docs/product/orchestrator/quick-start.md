# Quick Start

The fastest path to a first successful pipeline run, in either operating
mode. For the concept and comparison, see
[Headless and interactive](PRODUCT.md#headless-and-interactive) in `PRODUCT.md`.

---

## Mode 1 — Scheduled (background)

**Prerequisites:**
- Submodule added and `get_started.py` run (see [16-onboarding.md](16-onboarding.md))
- `ANTHROPIC_API_KEY` and `AI_AGILE_BOT_TOKEN` secrets set on the repo
- At least one issue open with a problem statement and acceptance criteria

**Steps:**
1. Open a GitHub issue with a problem statement and acceptance criteria.
2. The `ai_orchestrator.yml` workflow fires automatically on `issues.opened`.
3. Watch for `issue-classifier:wip` then `issue-classifier:complete` labels and a classification comment within a few minutes.
4. The pipeline advances automatically until it reaches a human gate (a `{agent}:review` label).
5. Read the artefact in the issue comments, then apply `{agent}:approved` to advance.

**"It worked":** the issue has `issue-classifier:complete` and a classification comment within a few minutes of opening.

---

## Mode 2 — In-session (live)

**Prerequisites:**
- A local checkout with the submodule initialised (`git submodule update --init`)
- Claude Code open at the repo root
- `gh` CLI on PATH and authenticated (`gh auth status`)
- Claude CLI on PATH (`claude --version`)
- GitHub auth the orchestrator can use: `GITHUB_TOKEN` or `GH_TOKEN` in the environment, or `gh auth` (the session's own Claude subscription/OAuth works for agent steps)

**Steps:**
1. Open a GitHub issue (or use an existing one).
2. In the Claude Code session, run: `/maos-run {issue_number}`
3. Claude drives each orchestrator step live and streams output to the session.
4. When a human gate is reached, Claude pauses and prompts you to approve or request changes.
5. Apply the `{agent}:approved` label (or ask Claude to apply it) and Claude continues.

**"It worked":** Claude reports the first agent step completing, shows the resulting label, and links to the artefact comment on GitHub.

---

## See also

- **Concept and comparison:** [Headless and interactive](PRODUCT.md#headless-and-interactive) in `PRODUCT.md`
- **Mechanism** (how `/maos-run` drives the orchestrator step by step): [`.claude/commands/maos-run.md`](../../../.claude/commands/maos-run.md)
- **Scheduled mode setup** (secrets, bootstrap, platform behaviour): [16-onboarding.md](16-onboarding.md) and [README.md](../../../README.md)
