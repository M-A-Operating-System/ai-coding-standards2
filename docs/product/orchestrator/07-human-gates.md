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

The authoritative source for the gate list is
[`pipeline/pipeline.json`](../../../pipeline/pipeline.json), rendered as a
generated catalogue per
[P-2](02-principles.md#p-2--one-machine-readable-source-per-concern-human-views-are-generated).
This document describes what each gate means for the human approving it.

Each row gives the gate's approver, the artefact the human reads, what
approval signs off, and the cost of getting it wrong.

| Gate label | Phase | Approver | Artefact | What you're signing off | Cost if wrong |
|---|---|---|---|---|---|
| `01_product_docs/prd-writer:approved` | Product docs | Stakeholder who opened the issue, or their delegate | The **issue body itself**, after `01_product_docs/prd-writer` rewrites it into the canonical PRD format (see [PRD format](#prd-format-and-the-prd-writer-gate) below) and rewrites the title | The problem and goal are correct; each user story names a real persona (including the System actor, [`03-personas.md`](03-personas.md) §7) and `As a developer` stories are suspect; each Gherkin scenario is falsifiable; "Out of scope" actually rules things out; success metrics are externally observable; the new title categorises the work correctly and names a real bounded context. Once approved, the PRD is the source of truth for everything downstream | The most expensive gate to skim — wrong PRD → wrong everything downstream (design, testing, evaluation) |
| `size:approved` | Product docs | Engineer who will own the work, or the tech lead | A sizing comment from `ticket-sizer` (`S`, `M`, `L`, `XL`) with rationale | That the ticket fits a single development cycle. If `XL`, you are committing to break it into children before proceeding | An XL ticket past the gate produces a sprawling design and a multi-week PR |
| `super-issue:approved` | Product docs | Engineer | The proposed grouping | The proposed grouping is correct; the super-issue becomes the shippable unit and the grouped children attach to it | — |
| `design:approved` | Technical docs | Engineer or tech lead | A technical design comment from `architect` covering data model, API contracts, component boundaries, integration points, NFRs | That this is the right design and that any ADR-worthy decisions have been flagged | Code is written against this design; a flaw found at PR stage means re-doing implementation |
| `test-spec:approved` | Testing spec | Engineer | A Gherkin scenario list from `test-spec-writer`, plus a coverage report from `test-coverage-auditor` confirming every PRD acceptance criterion maps to at least one scenario | That these scenarios — and only these — are what "done" means | Tests get written for the wrong things |
| `plan:approved` | Build plan | Engineer | A build plan showing the ordered child task list and the critical path, produced by `dependency-planner` | That the decomposition is sensible and the order is correct | Wasted work; merge conflicts; tasks that discover the design has a hole |
| `pr:approved` | Execute | Engineer | A PR review from `pr-reviewer` checking scope, design alignment, and resolution of `required` standards violations | That the code is right and ready to test | Bugs in production. Use this gate to look at the actual diff, not just the agent's review summary |
| `coverage:approved` | Test | Engineer | A coverage report showing test results, coverage delta, and any acceptance criterion without a passing test, produced by `coverage-enforcer` | That tests pass, coverage hasn't regressed, and every required scenario has a passing test | Untested code in production |
| `standards-proposal:approved` | Evaluate (weekly) | Standards owner | An issue from `standards-evolver` proposing a new or changed standard, in JSON schema format | That the proposed standard is sound, the rationale is real, and the agent guidance is unambiguous | A bad standard ripples into every subsequent ticket |
| `security-review:approved` | Execute | Security owner | The PR diff and the `impact-assessor` security-flag comment listing the sensitive surfaces touched (auth flows, RLS policies, IAM definitions, secrets, PII fields) | That the change is safe from an authentication, authorisation, and data-exposure perspective. Not a full pentest — a focused review of the flagged surface | Security vulnerabilities in production. Only required on PRs flagged by `impact-assessor`; non-flagged PRs skip this gate automatically |
| `data-migration:approved` | Execute | Data owner | The migration file(s) and the `migration-validator` report confirming or flagging forward-only, idempotent, and RLS compliance | That the migration is safe to run against production data and that the data lifecycle implications (retention, PII, rollback) are understood and accepted | Data loss or corruption in production. Only required on PRs that include `**/*.sql` files |
| `merge-conflict:approved` | Execute | Engineer | A prioritised list of conflict resolution recommendations from the `merge-conflict` agent, posted as a PR comment; each identifies the affected file, the conflict scope, and the suggested resolution approach | That the proposed resolution for each conflicting file is correct, safe, and consistent with both sides of the merge. Binary and generated files (lock files, compiled assets) may be flagged but require manual handling | Applying the wrong resolution silently drops or corrupts intentional changes. Review each conflicting hunk against the PR's stated intent. Only required on PRs that contain merge conflict markers when marked Ready for Review; clean PRs skip this gate automatically |
| `gap-report:approved` | Gap assessment | Stakeholder + Standards owner (dual approval) | The rolled-up gap report from `gap-curator` listing candidate gap-issues grouped by severity | That the identified gaps are real (not stale requirements the product has intentionally moved away from) and worth filing as tickets | Filing phantom issues wastes the per-ticket pipeline on work no one wants |
| `debt-report:approved` | Tech debt | Engineer (or tech lead) + Standards owner (dual approval) | The rolled-up debt report from `debt-curator` listing candidate debt-issues with structural evidence (metrics, ADR age, hot-spot trends) | That the identified debt is real and worth prioritising against the feature backlog | Remediating false debt distracts from delivering value |
| `pipeline-change:approved` | Learn | Standards owner | A PR against `pipeline.json` from `pipeline-tuner`, with evidence from the metrics report | That the proposed pipeline change — adjusted schedule, added dependency, changed gate — is sound and will not degrade pipeline health | A bad pipeline change affects every subsequent ticket |
| `prompt-change:approved` | Learn | The agent's designated owner (responsible for that agent's quality) | A PR against `.claude/agents/{agent}.md` from `prompt-tuner`, with rejection-rate evidence and diff | That the proposed prompt edit improves agent quality and does not introduce regression | A regressed prompt silently degrades every run of that agent |
| `process-review:approved` | Learn | Standards owner + a principal stakeholder (dual approval required) | A coordinated change proposal from `process-reviewer` spanning the pipeline graph, agent prompts, standards, and docs | That the system-level diagnosis is correct, the proposed coordinated changes are coherent, and the dual approvers together represent both the technical and product perspectives | A bad coordinated change is harder to unwind than a single-component change; the dual approval bar reflects the blast radius |

Two gates carry additional refusal/guard behaviour worth noting:

- **`size:approved`** — `ticket-sizer`'s `XL` verdict is itself the trigger
  to decompose; approving an `XL` commits you to breaking the ticket into
  children first.
- **`01_product_docs/prd-writer:approved`** — `prd-writer` will refuse to
  draft an oversized PRD. If the issue describes multiple distinct user
  outcomes or spans multiple bounded contexts, the agent set-blocks with a
  decomposition recommendation rather than producing a sprawling PRD.
  Decomposing early is cheaper than reviewing a too-big PRD.

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
   - **Approve as-is.** Apply the gate label (e.g., `01_product_docs/prd-writer:approved`). The
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

## PRD format and the `prd-writer` gate

The artefact for `01_product_docs/prd-writer:approved` is the rewritten
issue body. Its required structure — the six sections (Problem, Goal,
User stories, Acceptance criteria, Out of scope, Success metrics), the
user-story and Gherkin formats, and the `[CATEGORY] - {module} - {Title}`
title format — is defined in the `prd-writer` / product-docs
documentation, not duplicated here. Two facts about that artefact matter
at the gate:

- **Gherkin flows downstream.** Each Gherkin scenario in an approved PRD
  becomes a numbered test scenario in Phase 3
  (`testing-spec/test-spec-writer`), tying every test back to a
  stakeholder-approved acceptance condition.
- **The original is preserved.** The stakeholder's original title and body
  — before `prd-writer` rewrote them — are kept as a one-off, immutable
  snapshot comment marked
  `<!-- ai-agile/snapshot/v1 by 01_product_docs/prd-writer -->`. It stays
  as first captured even if the PRD is rewritten after rejection,
  preserving the audit trail under the
  [P-10](02-principles.md#p-10--agents-draft-humans-decide) carve-out that
  lets `prd-writer` edit issue title and body.

---

## What humans do *not* do

To keep gate cost low, humans should not:

- Edit code on behalf of agents. If the implementation is wrong, request
  changes and let the `coder` redo it.
- Manually advance past `:blocked` or `:failed` without resolving the
  underlying issue. Removing those labels signals "I have fixed the cause."
- Sign off without reading. The audit trail records who approved.
- Apply gate labels prematurely. Approving `01_product_docs/prd-writer:approved` before reading the
  PRD wastes the rest of the pipeline.

If the system is too noisy at any gate, that is a signal to refine the
upstream agent — not to lower the bar for sign-off.
