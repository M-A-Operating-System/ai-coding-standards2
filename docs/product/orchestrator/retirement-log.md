# Legacy document retirement log

Where each numbered document from the pre-[`PRODUCT.md`](PRODUCT.md) era
ended up: which of its content was durable and migrated into the target
design, which was current-only and dropped, and why. This is a historical
record of the consolidation, not part of the design itself -- `PRODUCT.md`
states what the product is; this states where that statement's pieces came
from.

| Topic | Authoritative source now | Note |
|---|---|---|
| Core requirements | `PRODUCT.md` | draft |
| The state machine and activity shape | `PRODUCT.md` | draft |
| How a step is told where it is | `PRODUCT.md` | draft |
| How it uses agents, the agent prompt file, and the step contract | `PRODUCT.md` | draft -- `12-agent-spec.md` retired; durable design content migrated (naming, frontmatter schema, tool vocabulary, model-selection rationale, required body structure); its current-only content (the stdout-sentinel status mechanism, the CI-validation checklist, the add-a-new-agent checklist) not preserved, since the step contract's written-result model (`PRODUCT.md#what-a-step-must-return`) replaces the first and the rest is operational detail with no target-design analog |
| The promises (AS-1 to AS-3, MI-1 to MI-8) | `PRODUCT.md` | draft |
| Headless and interactive | `PRODUCT.md` | draft -- `17-operating-modes.md` retired |
| Conformance and traceability | [`gap_analysis.md`](gap_analysis.md) | current |
| Vision and problem | `PRODUCT.md` | draft |
| Personas -- who AI Agile serves, in brief | `PRODUCT.md` | draft |
| Personas -- the enforced vocabulary and the System actor's qualifying test | [`standards/personas.json`](../../../standards/personas.json) | current -- `03-personas.md` retired; its prose ("wants" / "how AI Agile serves them" per persona) not preserved, since it restated agent-catalogue detail already covered by `04-lifecycle.md`; the one genuinely durable piece (the System actor's 3-part validity test) migrated into the new standards file instead |
| Promises (formerly principles P-1 to P-16) | `PRODUCT.md` and `04-lifecycle.md` | draft |
| Pipeline configuration, target shape | [`schema/pipeline.schema.json`](schema/pipeline.schema.json) | current |
| Pipeline configuration, as it exists today | `pipeline.json` itself (AS-1); `pipeline/schemas/pipeline.schema.json`'s own field descriptions are the current reference -- `05-pipeline-config.md` retired | durable content migrated; current-only content (script-step sentinel mechanics, `git_ops.commit_after` as a per-step opt-in, `orchestrator_checks`) not preserved, since the target design replaces each |
| The process itself -- which flows exist, their phases and forks | [`04-lifecycle.md`](04-lifecycle.md) | **stays there by design.** `PRODUCT.md` says the orchestrator can run whatever flows `pipeline.json` declares; which flows those are, and why, is process |
| Status model | `PRODUCT.md` | draft -- `06-status-model.md` retired |
| Human gates, mechanism | `PRODUCT.md` (MI-7) | draft |
| Human gates, which ones exist today | [`04-lifecycle.md`](04-lifecycle.md#human-gates) | current -- `07-human-gates.md` retired |
| Orchestrator responsibilities | `PRODUCT.md` (target-design promises); `pipeline_orchestrator.py` itself (current implementation) | draft -- `11-orchestrator.md` retired; durable trust-boundary content migrated (AS-1); current-only implementation detail (function names, JSON marker formats, CLI flags, retry constants) not preserved, since it has no target-design analog |
| Standards model | [`docs/product/standards/14-standards.md`](../standards/14-standards.md) | stays there by design -- standards enforcement is agent behaviour (`coder`, `pr-reviewer` reading `standards/*.json`), not orchestrator mechanism, so `PRODUCT.md` was never going to absorb it |
| Audit log, mechanism and record shape | `PRODUCT.md` (MI-6) | draft -- `08-audit-log.md` retired; its stdout/GitHub-Actions-run-log mechanism was already stale in that document's own text (superseded by the `ai-agile/log` orphan branch); the event schema and event-type table, still live (cited by `pipeline_orchestrator.py`), migrated in |
| Human interaction -- markers, gates, agent identity | `PRODUCT.md` (the step contract's marker table, MI-7) | draft -- `09-human-interaction.md` retired; nothing migrated. Agent identity duplicated MI-7's existing 'How a non-human actor is recognised'; agent announcements restated the step contract's existing return/marker requirements at a level of detail nothing needs; Question Cards were never carried into the target design (see `gap_analysis.md`, 'The record format') -- headless steps have `blocked`, interactive sessions are a conversation, neither needs a bespoke Q&A protocol |
| Todo-list format -- markers, subsections, checkbox and timestamp grammar | `PRODUCT.md` (the step contract's 'Todo lists in issue and PR bodies') | draft -- `13-todos.md` retired. The target-design mechanism migrated in, described by role rather than by the specific owner agents `13-todos.md` named, since four of those six (`task-decomposer`, `standards-compliance-reviewer`, `test-spec-writer`, `test-runner`) never existed in `pipeline.json`. Its write-protocol content -- agents PATCHing GitHub directly via a shared script -- was not migrated: the script it named does not exist in this repo, and the mechanism itself contradicts the step contract's write-ownership rule, which `PRODUCT.md` already generalizes to cover body edits. `.claude/AGENTS.md`'s own todo-lists section still describes this mechanism as current agent behaviour, which no agent prompt actually implements (zero references to `ai-agile/todos/` anywhere in `.claude/agents/`) -- not yet reconciled with this |
| Delivery sequencing and staging plan | n/a -- not part of the target design | `10-roadmap.md` retired; nothing migrated. It was a point-in-time staging document by its own stated purpose, not a durable description of the system; `pipeline/pipeline.json` is the authoritative dependency graph (AS-1) |
