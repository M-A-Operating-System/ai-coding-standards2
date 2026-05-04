# Personas

AI Agile serves four primary personas. Every feature, gate, and artefact is
designed against at least one of them.

---

## 1. The Stakeholder

**Role.** Product manager, designer, founder, or business stakeholder who
opens an issue describing a desired change.

**Wants.**

- A frictionless way to describe a problem without writing a full spec.
- Confidence that the request will be turned into a clear PRD they can review.
- Visibility into where the work is in the pipeline at any time.
- Notification when something needs their input — not when it doesn't.

**How AI Agile serves them.**

- They open a GitHub issue with a title and a short description. The
  `issue-classifier` rejects malformed issues with a corrective comment.
- The `prd-writer` produces a structured PRD as an issue comment within
  minutes.
- They review and approve the PRD by removing the `prd:approved` gate label.
- After that, the system runs without their involvement until the work is
  released. Status labels show progress at a glance.

---

## 2. The Engineer

**Role.** Software engineer responsible for the design, the code, and the
quality of the change.

**Wants.**

- A complete and unambiguous design before code is written.
- A test spec that maps to acceptance criteria, not invented from scratch.
- An implementation plan they can review and override.
- Standards that are enforceable, not aspirational.
- Time spent on novel problems, not on writing the same boilerplate.

**How AI Agile serves them.**

- The `architect` produces a technical design covering data model, API
  contracts, component boundaries, and non-functional requirements.
- The `test-spec-writer` generates Gherkin scenarios from PRD acceptance
  criteria. The `test-coverage-auditor` blocks if any criterion lacks a
  scenario.
- The `task-decomposer` and `dependency-planner` propose an ordered build
  plan. The engineer approves it before any code is written.
- The `coder` opens one PR per task. The `standards-compliance-reviewer`
  flags violations with proposed diffs. The `pr-reviewer` checks scope and
  alignment with the design.
- Standards are loaded from `ai-agile/standards/*.json` and referenced by
  STD ID in code comments and PR descriptions.

---

## 3. The Reviewer

**Role.** Tech lead, staff engineer, or peer who approves at one or more of
the human gates: PRD, ticket sizing, design, test spec, build plan, PR,
coverage, or proposed standards changes.

**Wants.**

- A single artefact to read at each gate, not scattered context.
- Clear instructions on what they are signing off and what to do next.
- The ability to reject and re-run an agent without manual recovery.
- Confidence that approving a gate is a meaningful act, not a rubber stamp.

**How AI Agile serves them.**

- Every gate posts an explicit comment naming the artefact, the action
  required, and the label to remove or apply.
- Every artefact is self-contained: the PRD is one comment, the design is
  one comment, the build plan is one comment.
- Removing a gate label allows the agent to re-run with feedback from the
  reviewer's comments — there is no "rerun the build" button to find.
- The pipeline halts entirely when a gate label is held; nothing advances
  silently.

---

## 4. The Standards Owner

**Role.** Architect, platform team, or technical lead who owns the
architecture and product standards that govern the codebase.

**Wants.**

- Standards that are referenced and applied, not ignored.
- A way to evolve standards based on what is actually happening in the
  codebase.
- A record of exceptions and the ADRs that authorised them.
- Confidence that proposed standards changes have been thought through, not
  reactive.

**How AI Agile serves them.**

- Every standard has a stable STD ID, a layer, a severity, an enforcement
  method, and machine-readable acceptance criteria.
- The `standards-compliance-reviewer` runs daily and on every PR, raising
  issues for violations with the offending STD ID and proposed fix.
- The `standards-evolver` runs weekly, reviews recent retrospectives and
  recurring violations, and drafts standards proposals as issues for human
  approval.
- Exceptions to a standard require an ADR. The schema enforces this —
  `exceptions[].adr_ref` is a required field.

---

## Cross-cutting needs

All four personas share three needs the system must serve:

1. **Auditability.** Every action is on GitHub: a comment, a label, a commit,
   a PR. Nothing happens in a side channel.
2. **Resumability.** Any agent can be retried by removing a label. No
   recovery scripts.
3. **No surprises.** The system never silently advances past a gate, never
   rewrites human-authored content, and never decides on behalf of a
   reviewer.
