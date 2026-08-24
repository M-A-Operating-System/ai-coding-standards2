# CLAUDE.md

Behavioral guidelines for AI sessions across this repo family — used both in
repos that ship code and in repos that produce assessments, policies, and
other non-code deliverables. Merge with project-specific instructions as
needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial
tasks, use judgment.

**Never edit `CLAUDE.md`** — it is framework-managed and symlinked from the
submodule in consuming repos; keep local hints, knowledge, and patterns in
`CLAUDE.local.md` instead.

## Part 1 — For every session

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.
- A tool/API failure in one context (one repo, one call, one session) is not
  evidence of a platform-wide restriction. Verify with a different call or
  repo before generalizing a capability as categorically unavailable —
  especially for GitHub access: a `gh`/API 403 on one repo usually means that
  repo lacks token/App access, not that direct API access is disabled
  entirely. Read the actual error body, not just the status code, and don't
  mistake a system-prompt policy line ("use MCP tools") for a technical fact
  about what the environment can or cannot do — test it.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Part 2 — Additional, when working as a coding AI

Applies when the repo is a codebase (`pipeline/pipeline_orchestrator.py`
present) and the task is a code change.

### 5. Finding Your Way Around

This project runs on the AI Agile pipeline:

- **Agents** (`.claude/agents/`) — automated pipeline steps (classify, plan, build, review). They follow the protocol in `.claude/AGENTS.md` — you don't need to read that unless you're changing an agent.
- **Commands** (`.claude/commands/`) — slash commands to run, retry, or unblock a pipeline agent by hand.
- **Standards** (`standards/*.json`) — enforceable coding rules, checked on every diff. Check the relevant category before writing code in an unfamiliar area.
- **ADRs** (`adrs/adrs.json`) — either exception records (list a standard they waive in `authorises_exception_to`) or plain decision records (no standard override). Check here before assuming a standard was violated by mistake; only ADRs that list the standard in `authorises_exception_to` downgrade a finding.

When checking for content under `standards/` or `.claude/`, use `Grep` or a
symlink-following `find` invocation — see Section 6 below. `Glob` silently
returns nothing through these paths in every consuming repo.

### 6. Symlink trap: reading standards and .claude files

**`Glob` returns nothing through a symlinked directory -- use `Grep` or `find -L` instead.**

Every consuming repo installs `standards/` and `.claude/` as whole-folder
symlinks pointing into the submodule (see `16-onboarding.md`). `Glob` does not
follow a symlinked directory and returns an empty result silently, with no error
to signal the miss. A naive `find standards -name "*.json"` (no flags, no
trailing slash) has the same trap for the same reason.

When reading content under `standards/` or `.claude/`:
- Use **`Grep`** -- it follows symlinked directories correctly.
- Or use **`find -L standards -name "*.json"`** (the `-L` flag follows symlinks).
- Or use **`find standards/ -name "*.json"`** (trailing slash also works).

Do **not** use `Glob("standards/*.json")` or `find standards -name "*.json"`
(no `-L`, no trailing slash) -- both silently return nothing through a symlink.

### 7. Code deliverables go through the orchestrator

**If the deliverable is code, drive it through the pipeline — don't implement ad hoc.**

- Before implementing, confirm a GitHub issue describes the change. If none
  exists, create one — don't start editing files ad hoc.
- Drive the work through the orchestrator (`/maos-run`, or let the scheduled
  pipeline pick it up) instead of committing code directly in the session.
  Agents follow the protocol in `.claude/AGENTS.md`; don't reimplement it
  by hand.
- Pure exploration, debugging, or a throwaway prototype is fine ad hoc — say
  so explicitly, and keep it out of version control until it becomes real
  work.

## Part 3 — Additional, when working as a content AI (assessments, policy, non-code deliverables)

Applies when the repo's deliverable is a document — an assessment, a
policy, a report — rather than code.

### 8. Evidence over assertion

**State evidence, not just conclusions.**

Every claim or judgment should be traceable to a source, a citation, or a
stated assumption — a reader should be able to tell "the data shows X" apart
from "I inferred X." Don't present an inference with the same confidence as
a sourced fact.

### 9. Preserve structure and voice

**The same "surgical changes" discipline as code, applied to prose.**

Match the existing document's section structure, tone, and terminology
unless the request specifically asks to change them. Don't restructure a
document, rewrite its voice, or "improve" unrelated sections while making a
scoped edit.

### 10. Define the rubric before writing

**State the standard you're judging against before producing the judgment.**

For an assessment or review, name the criteria first, so the standard is
visible and auditable in the deliverable itself — not implicit in the
author's head.

### 11. Flag gaps, don't fill them

**An unanswered question is safer than a confidently wrong answer.**

If information needed for a complete assessment or policy is missing, say so
explicitly rather than producing plausible-sounding text to cover the gap.

---

**These guidelines are working if:** fewer unnecessary changes in diffs,
fewer rewrites due to overcomplication, and clarifying questions come before
implementation rather than after mistakes.
