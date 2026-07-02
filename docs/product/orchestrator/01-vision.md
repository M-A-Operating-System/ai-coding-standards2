# Vision

## Problem

Software teams spend a disproportionate share of their time on the connective
tissue around code: writing PRDs, translating them into designs, deciding what
to test, decomposing work into tasks, reviewing for standards, and writing
release notes. These activities are valuable but repetitive. They are also
where most quality issues originate — a missing acceptance criterion, an
unrecorded architectural decision, a forgotten test case — because they are
done under time pressure and inconsistently from one ticket to the next.

The result is a familiar pattern:

- Tickets ship without traceable acceptance criteria.
- Designs are decided in chat and never written down.
- Tests are added late, only for the happy path.
- Standards drift because there is no closed loop between what we ship and
  what we say we should be shipping.

## Vision

AI Agile is a product development lifecycle in which specialised AI agents
own each repetitive activity, run from a single source of truth (a GitHub
issue), and produce a complete trail of artefacts — PRD, design, ADRs, test
spec, build plan, code, tests, changelog, retrospective — with humans
approving at well-defined gates rather than performing the work.

The intent is not to remove humans from product development. It is to free
them to do the parts only they can do: deciding what to build, judging
tradeoffs, and signing off that the work is right.

## Principles

The rules AI Agile is built on are documented as a numbered, referenced
list in [`02-principles.md`](02-principles.md). Every principle has a
stable ID (`P-1`, `P-2`, …) referenced from code, agent prompts, and
design docs.

In summary: Git is authoritative; every fact has one machine-readable
source; every event is appended to an immutable log; agents draft and
humans decide; the system is resumable, transparent, and built so swarms
can scale without a separate coordination layer.

## What success looks like

- Every shipped feature has a PRD, a design, ADRs where relevant, a test
  spec, an implementation, tests linked to the spec, and a retrospective —
  all reachable from the originating issue.
- Architecture standards are referenced by ID in code, in PRs, in design
  docs, and in violation reports. Violations decline over time.
- Humans spend their time approving, not authoring. A typical reviewer
  workflow is: read the artefact in the issue, comment if needed, remove the
  gate label.
- A new contributor can pick up the system in a single afternoon by reading
  this `docs/product/orchestrator/` directory.

## What this is not

- Not a replacement for product management. Product managers still decide
  what to build, prioritise, and own the roadmap.
- Not a replacement for engineering judgement. Engineers still review
  designs, debate tradeoffs, write standards, and approve PRs.
- Not a black box. Every agent's output is a comment, a file, or a PR — all
  visible, all editable, all on GitHub.
