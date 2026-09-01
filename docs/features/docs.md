# Feature: Docs

## Scenario: A new consumer can identify which mode to use

**Given** a consumer reading the updated docs
**When** they want to run the pipeline for the first time
**Then** they can find a Quick Start that gets a first run working in either mode within a few minutes, with prerequisites listed, and points to `PRODUCT.md`'s "Headless and interactive" section for the concept and comparison

## Scenario: A session checking standards content is warned about the symlink trap

**Given** `.claude/CLAUDE.md` after this change
**When** a session is about to check `standards/*.json` (or any path under `.claude/`) for content
**Then** the doc instructs using `Grep` or a symlink-following `find` invocation instead of `Glob`, and explains that `Glob` can silently return an empty result through a symlinked directory

## Scenario: The guidance specifies a correct invocation, not just a tool name

**Given** the same doc
**When** a reader looks for the recommended alternative
**Then** it names a concrete, verified-correct invocation (`Grep`, or `find -L` / a trailing-slash `find`) rather than just "use find," which would not by itself avoid the same trap

## Scenario: The affected paths are named explicitly

**Given** the same doc
**When** a reader wants to know which paths this actually affects
**Then** `standards/` and `.claude/` are named as the whole-folder symlinks every consuming repo installs, per `16-onboarding.md`

## Scenario: An interactively-run agent is scoped to its declared tool allowlist

**Given** `/run-agent` invoked on an agent whose frontmatter declares `tools: [Bash, Read, Grep]` (no `Glob`)
**When** the interactive session follows that agent's instructions
**Then** it is constrained to (or explicitly warned before stepping outside) the same tool set the real orchestrator-spawned subprocess would have -- `Glob` is not silently available just because the ambient session happens to have it

## Scenario: Sections 1-4 are preserved verbatim

**Given** the restructured `.claude/CLAUDE.md`
**When** its Part 1 content is compared against the current live sections 1-4
**Then** the wording is byte-for-byte identical, only regrouped under a "Part 1 — For every session" heading

## Scenario: Coding-AI guidance is scoped, not universal

**Given** the restructured file
**When** a session in a non-code (assessment/policy) repo reads Part 2
**Then** it is explicitly scoped ("Applies when the repo is a codebase... and the task is a code change") so it does not misapply to non-code work

## Scenario: The issue-first gap is closed for coding repos

**Given** the restructured file's Part 2
**When** an interactive session in a codebase repo is about to implement a code change
**Then** it is instructed to confirm a GitHub issue exists (creating one if not) and to drive the work through the orchestrator, rather than committing directly in the session

## Scenario: Content-AI guidance is scoped, not universal

**Given** the restructured file
**When** a session in a codebase repo reads Part 3
**Then** it is explicitly scoped to non-code deliverables so it does not misapply to code work
