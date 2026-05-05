# Human Gates

A **human gate** is a point in the pipeline where work cannot advance until a
named human has explicitly approved it. Gates are implemented as labels: the
agent applies a `:review` status, posts an artefact, and waits. A human reads
the artefact and either approves (applies the gate label) or requests
changes (removes the `:review` label after commenting; the agent re-runs).

When the human applies the gate label, the **orchestrator** does the
follow-through: it removes `{agent}:review`, applies `{agent}:complete`,
and emits the matching events to the audit log. Humans never directly
apply `{agent}:complete` — they apply the gate label, the orchestrator
promotes the agent. See
[`06-status-model.md`](06-status-model.md#gated-agents-the-review--complete-transition)
for the full lifecycle.

Gates exist for one reason: to make sure the deciding work — what to build,
how to design it, what "done" looks like, whether the code is right —
remains a human responsibility. Agents draft. Humans decide.

---

## The gates

The full, authoritative list of gates is generated from
[`ai-agile/pipeline/pipeline.json`](../../../ai-agile/pipeline/pipeline.json)
to [`generated/gates.md`](generated/gates.md). The summary below is for
orientation; the generated file is the source of truth (see
[P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated)).

| Gate label | Phase | Approver | What they are signing off |
|---|---|---|---|
| `prd:approved` | Product docs | Stakeholder | The PRD captures the right problem and acceptance criteria |
| `size:approved` | Product docs | Engineer | The ticket is the right size for one cycle, or has been broken up |
| `super-issue:approved` | Product docs | Engineer | The proposed grouping is correct; the super-issue becomes the shippable unit and the grouped children attach to it |
| `design:approved` | Technical docs | Engineer | The technical design is right and complete |
| `test-spec:approved` | Testing spec | Engineer | The Gherkin scenarios cover every acceptance criterion |
| `plan:approved` | Build plan | Engineer | The task breakdown and order are correct |
| `pr:approved` | Execute | Engineer | The implementation matches the design and resolves all `required` violations |
| `coverage:approved` | Test | Engineer | Tests pass and cover every required scenario |
| `standards-proposal:approved` | Evaluate (weekly) | Standards owner | The proposed change to the standards is sound |

---

## How a gate works in practice

1. The agent finishes its automated work.
2. The agent posts the artefact as an issue comment.
3. The agent calls `status.sh set-review`, which:
   - Applies `{agent}:review` to the issue.
   - Posts a comment naming the artefact and what action the human should
     take.
4. The pipeline halts for this issue. The orchestrator skips it on every
   subsequent run, except to watch for the gate label.
5. The human reads the artefact. They have three options:
   - **Approve as-is.** Apply the gate label (e.g., `prd:approved`). The
     orchestrator detects the gate, removes `{agent}:review`, applies
     `{agent}:complete`, emits `gate.approved` and `agent.complete` to
     the audit log, and re-evaluates downstream eligibility on its next
     tick.
   - **Approve with edits.** Edit the artefact comment in place. Apply
     the gate label. The orchestrator's promotion path is the same;
     edits to the comment are part of the audit trail.
   - **Request changes.** Comment with feedback. Remove the `:review`
     label *without* applying the gate label. The orchestrator
     re-evaluates eligibility, the agent re-runs, picks up the feedback
     comments, and produces a new draft.

There is never a "force push past a gate" path. The only way past is a
human applying the gate label, after which the orchestrator promotes
the agent to `:complete`.

---

## Gate-by-gate description

### `prd:approved`

**Approver.** The stakeholder who opened the issue, or whoever they delegate
to.

**Artefact.** A PRD comment from `prd-writer` covering: problem statement,
user stories, success metrics, out-of-scope items, acceptance criteria.

**What you are signing off.** That this is the right problem to solve and
that the acceptance criteria are complete and testable. Once approved, the
PRD is the source of truth for everything downstream.

**Cost of getting it wrong.** The most expensive gate to skim. The PRD
becomes the input for design, testing, and evaluation. Wrong PRD →
wrong everything.

### `size:approved`

**Approver.** The engineer who will own the work, or the tech lead.

**Artefact.** A sizing comment from `ticket-sizer` (`S`, `M`, `L`, `XL`)
with rationale.

**What you are signing off.** That the ticket fits a single development
cycle. If `XL`, you are committing to break the ticket into children before
proceeding.

**Cost of getting it wrong.** An XL ticket that slips past the gate produces
a sprawling design and a multi-week PR.

### `design:approved`

**Approver.** Engineer or tech lead.

**Artefact.** A technical design comment from `architect` covering data
model, API contracts, component boundaries, integration points, NFRs.

**What you are signing off.** That this is the right design, and that any
ADR-worthy decisions have been flagged.

**Cost of getting it wrong.** Code is written against this design. Discovering
a flaw at the PR stage means re-doing implementation work.

### `test-spec:approved`

**Approver.** Engineer.

**Artefact.** A Gherkin scenario list from `test-spec-writer`, plus a
coverage report from `test-coverage-auditor` confirming every PRD
acceptance criterion maps to at least one scenario.

**What you are signing off.** That these scenarios — and only these
scenarios — are what "done" means.

**Cost of getting it wrong.** Tests get written for the wrong things.

### `plan:approved`

**Approver.** Engineer.

**Artefact.** A build plan from `dependency-planner` showing the ordered
child task list and the critical path.

**What you are signing off.** That the decomposition is sensible and the
order is correct.

**Cost of getting it wrong.** Wasted work; merge conflicts; tasks that
discover the design has a hole.

### `pr:approved`

**Approver.** Engineer.

**Artefact.** A PR review from `pr-reviewer` checking scope, design
alignment, and resolution of `required` standards violations.

**What you are signing off.** That the code is right and ready to test.

**Cost of getting it wrong.** Bugs in production. Use this gate to look at
the actual diff, not just the agent's review summary.

### `coverage:approved`

**Approver.** Engineer.

**Artefact.** A coverage report from `coverage-enforcer` showing test
results, coverage delta, and any acceptance criterion without a passing
test.

**What you are signing off.** That tests pass, coverage hasn't regressed,
and every required scenario has a passing test.

**Cost of getting it wrong.** Untested code in production.

### `standards-proposal:approved`

**Approver.** Standards owner.

**Artefact.** An issue from `standards-evolver` proposing a new standard
or a change to an existing one, in JSON schema format.

**What you are signing off.** That the proposed standard is sound, the
rationale is real, and the agent guidance is unambiguous.

**Cost of getting it wrong.** A bad standard ripples into every future
ticket.

---

## What humans do *not* do

To keep gate cost low, humans should not:

- Edit code on behalf of agents. If the implementation is wrong, request
  changes and let the `coder` redo it.
- Manually advance past `:blocked` or `:failed` without resolving the
  underlying issue. Removing those labels signals "I have fixed the cause."
- Sign off without reading. The audit trail records who approved.
- Apply gate labels prematurely. Approving `prd:approved` before reading the
  PRD wastes the rest of the pipeline.

If the system is too noisy at any gate, that is a signal to refine the
upstream agent — not to lower the bar for sign-off.
