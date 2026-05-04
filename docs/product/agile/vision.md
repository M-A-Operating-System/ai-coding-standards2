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

1. **One issue, one trail.** Every artefact for a piece of work lives on or is
   linked from a single GitHub issue. Anyone can reconstruct what was decided,
   when, and by whom from that issue alone.
2. **Agents do the writing, humans do the deciding.** Agents draft. Humans
   approve at named gates by applying or removing a label. No work advances
   past a gate without an explicit human action.
3. **Status is a label.** The pipeline state is visible in the GitHub UI.
   There is no separate dashboard, no hidden state machine, no other system
   to learn.
4. **Standards are code.** Every architecture and product standard is
   declared in JSON conforming to a published schema, has a stable ID, and
   is referenced from code, PRs, and design docs by that ID.
5. **The system improves itself.** Retrospectives feed the standards-evolver,
   which proposes new or updated standards based on recurring violations.
   Humans approve the proposals. The next ticket benefits.
6. **Resumable by default.** Any agent can be re-run. No agent assumes the
   pipeline is in any particular state — it reads labels and acts on what it
   finds. A failed run is recovered by removing a label, not by editing
   internal state.
7. **Transparent over clever.** When in doubt the system prefers a comment on
   the issue, an explicit label, and a named status over inferred state or
   silent retries.

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
  this `docs/product/agile/` directory.

## What this is not

- Not a replacement for product management. Product managers still decide
  what to build, prioritise, and own the roadmap.
- Not a replacement for engineering judgement. Engineers still review
  designs, debate tradeoffs, write standards, and approve PRs.
- Not a black box. Every agent's output is a comment, a file, or a PR — all
  visible, all editable, all on GitHub.
