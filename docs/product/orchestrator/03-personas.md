# Personas

AI Agile serves seven personas — six human and one System actor for
capabilities whose primary actor is automation. Every feature, gate,
and artefact is
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
- They review and approve the PRD by **applying** the `01_product_docs/prd-writer:approved`
  gate label. To request changes, they comment with feedback and
  remove the `prd-writer:review` label — the agent re-runs.
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
- The `coder` produces the code PR for each shippable-unit issue (the
  design docs merge in a separate design PR first; see
  [`04-lifecycle.md`](04-lifecycle.md#two-phase-design-to-build-delivery)) with one
  commit per child task from the build plan. The
  `standards-compliance-reviewer` flags violations with proposed
  diffs. The `pr-reviewer` checks scope and alignment with the
  design.
- Standards are loaded from `standards/*.json` and referenced by
  STD ID in code comments and PR descriptions.

---

## 3. The Reviewer

**Role.** Tech lead, staff engineer, or peer who approves at one or more of
the human gates: PRD, ticket sizing, design, test spec, build plan, PR,
coverage, or proposed standards changes.

**Wants.**

- A single artefact to read at each gate, not scattered context.
- Clear instructions on what they are signing off and what to do next.
- Confidence that approving a gate is a meaningful act, not a rubber stamp.

**How AI Agile serves them.**

- Every gate posts an explicit comment naming the artefact, the action
  required, and the label to remove or apply.
- Every artefact is self-contained: the PRD is one comment, the design is
  one comment, the build plan is one comment.

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

- Every standard has a stable STD ID, a scope (`org` or `project`), a
  category, an `adr_overridable` flag, and machine-readable acceptance
  criteria and anti-patterns. See [14-standards.md](14-standards.md) for
  the full field reference and category taxonomy.
- Standards exist at two tiers: org-wide rules in the `ai-coding-standards2`
  submodule (read-only in consuming projects) and project-specific rules in
  the consuming repo. Both tiers are enforced on every diff.
- The `standards-compliance-reviewer` runs daily and on every PR, raising
  issues for violations with the offending STD ID and proposed fix.
- The `standards-evolver` runs weekly, reviews recent retrospectives and
  recurring violations, and drafts standards proposals as issues for human
  approval.
- Exceptions to a standard require an ADR citing the STD ID via
  `authorises_exception_to`. Standards marked `adr_overridable: false`
  cannot be waived by any ADR and always block merge.

---

## 5. The Security Owner

**Role.** Security engineer, AppSec lead, or compliance officer
responsible for the security posture of the codebase: authentication,
authorisation, RLS, secret handling, PII, and regulatory compliance.

**Wants.**

- Confidence that security-layer standards are enforced in code, not
  aspirational in documents.
- Visibility into every change that touches a security-sensitive
  surface (auth flows, RLS policies, IAM, secrets, PII fields).
- Approval rights on PRs whose blast radius includes those surfaces.
- An auditable trail of who approved what, suitable for compliance
  evidence (SOC 2, ISO 27001, HIPAA — whichever applies).
- Early signal on risk, not late surprises at PR review.

**How AI Agile serves them.**

- The standards schema has a dedicated `security` category. Security
  standards are declared with `adr_overridable: false` by default,
  meaning they always block merge and cannot be waived by any ADR.
- The `impact-assessor` flags any change whose touched files or schema
  intersect with security-sensitive paths (a configurable allowlist
  including `auth/**`, RLS policies, `secrets/**`, IAM definitions).
  When flagged, the issue gets a `security-review-required` label.
- A dedicated **`security-review:approved`** gate blocks merge on
  security-flagged PRs until the security owner approves.
- The `standards-compliance-reviewer` raises violations against
  `security`-layer standards as issues, with the STD ID and proposed
  fix.
- The orchestrator emits structured JSON audit events to stdout; the GitHub Actions run log provides timestamped evidence of
  every security-related approval and change for compliance purposes.
- `migration-validator` blocks SQL migrations that disable RLS,
  expose PII columns, or weaken existing access controls.

---

## 6. The Data Owner

**Role.** Owns the content, schema, and lifecycle of one or more data
domains. Responsible for migrations, retention, deletion, GDPR/data
residency, and the integrity of production data.

**Wants.**

- Every data migration is forward-only, idempotent, reversible by
  policy (or explicitly flagged as not-reversible), and reviewed
  before merge.
- Schema changes that affect data shape or semantics are documented
  as ADRs.
- Data lifecycle rules (retention windows, soft-delete vs hard-delete,
  PII redaction, export formats) are enforced as standards, not
  guidelines.
- Visibility into what data is being created, modified, or deleted by
  any feature shipping into production.
- A clear path to roll back or quarantine a migration that
  misbehaves.

**How AI Agile serves them.**

- Database-layer standards govern naming (snake_case plural), FK
  conventions, RLS, and type rules. The `migration-validator` blocks
  merge on violations.
- Migrations live in a known location and are required to be
  forward-only and idempotent — checked by the `migration-validator`
  agent.
- The `architect` is required to flag any data model change as an
  ADR candidate; the `adr-proposer` then drafts the ADR.
- A dedicated **`data-migration:approved`** gate blocks merge on
  PRs that include migrations until the data owner approves.
- The `impact-assessor` reports the data domains touched by a change,
  so the right data owner is auto-tagged for review.
- Every user-initiated write produces an activity log entry
  (per the existing `STD000000007` product standard), giving the
  data owner a complete change-of-record trail.

---

## 7. The System actor

**Role.** An automated component that initiates work without a human
in the loop: a scheduled job, a webhook handler, an autoscaler, an
audit logger, an integration that reacts to upstream events. Used as
the user-story subject when the **primary actor of a capability is
genuinely automation**, not a person.

**Why this persona exists.** Some capabilities the product needs are
not user-triggered: a nightly metrics aggregator, a webhook that
ingests upstream changes, a token rotator that runs every 24 hours.
The user-story format still applies — "as the X, I want to … so that
…" — but the X is a system role, not a human one. Treating these as
first-class personas keeps automated capabilities inside the
product-led pipeline (PRD with Gherkin AC), instead of being
smuggled into technical design as "implementation detail".

**Example of a valid System actor user story.**

- *As the **scheduled metrics aggregator**, I want to compute pipeline
  cycle times nightly, so that the standards owner sees current
  performance on the dashboard without manual queries.*

**The valid-vs-invalid test.** A System actor story must:

1. Have a **real human stakeholder benefitting** from the outcome —
   even indirectly. The "so that" clause names that benefit. If you
   cannot name the human who cares, it is technical preference, not
   product.
2. Be expressible as **Gherkin acceptance criteria** with an
   observable Then-clause (a row appears in a table; an alert fires;
   a number increases on a dashboard). If the only observable
   outcome is "the code is structured a certain way", it is technical
   design, not product.
3. Name a **stable automated role**, not an implementation choice.
   "As the audit log writer" is fine. "As the database" is not — that
   is implementation. "As a developer" is also not — developers are
   tool users, not product personas.

**What this persona does NOT serve.** Technical-intermediate work
(refactors, library upgrades, internal API rewrites) and code-only
acceptance criteria are not System actor stories — see the
product-led target-state rule and the toil classification in
[04-lifecycle.md](04-lifecycle.md#issue-classification-taxonomy).

**How AI Agile serves them.**

- `prd-writer` accepts `As the {automated-role}` user stories on the
  same terms as human personas, gated by the valid-vs-invalid test
  above. The Gherkin acceptance criteria still apply.
- Downstream agents (`architect`, `task-decomposer`, `coder`) treat
  System-actor PRDs identically to human-actor PRDs — they implement
  to the acceptance criteria, regardless of who the primary actor is.
- The **audit log writer**, **scheduled metrics aggregator**, and
  similar AI-Agile-internal automated components are themselves
  modelled as System actors: their capabilities ship through the
  same pipeline as feature work.

---

## Cross-cutting needs

All seven personas share three needs the system must serve:

1. **Auditability.** Every action is on GitHub: a comment, a label, a commit,
   a PR. Nothing happens in a side channel.
2. **Resumability.** Any agent can be retried by removing a label. No
   recovery scripts.
3. **No surprises.** The system never silently advances past a gate, never
   rewrites human-authored content, and never decides on behalf of a
   reviewer.
