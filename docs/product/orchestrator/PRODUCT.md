# The Orchestrator Product

The single description of what the orchestrator is and what it guarantees.

This document is being authored from first principles as the target design
(issue #393). It supersedes the numbered documents `01-vision.md` through
`17-operating-modes.md` section by section as it is written; until a section
exists here, the numbered document remains authoritative for that topic. The
[status table](#status-of-this-document) records which is which.

Every guarantee in this document states how it is tested and whether the
implementation conforms today. A guarantee with no test is not a guarantee, and
is marked as such.

---

## Contents

- [What the orchestrator is](#what-the-orchestrator-is)
- [Authoritative sources](#authoritative-sources) -- AS-1
- [The two operating modes](#the-two-operating-modes)
- [Mode invariants](#mode-invariants) -- MI-1 to MI-8
- [Legitimate differences](#legitimate-differences)
- [Conformance summary](#conformance-summary)
- [Status of this document](#status-of-this-document)

---

## What the orchestrator is

A deterministic process that advances GitHub issues through a defined sequence
of steps. Each step invokes an AI agent or a script, records what happened on
the issue, and moves the issue to its next state. Humans decide at named gates;
the orchestrator never decides on their behalf.

State lives in GitHub labels. There is no database, no queue, and no state file:
the labels on an issue *are* its position in the pipeline, and any orchestrator
process reading them reaches the same conclusion about what runs next.

---

## Authoritative sources

### AS-1 -- `pipeline.json` defines the process

**Statement.** `pipeline.json` is the authoritative definition of four things,
and nothing else defines any of them:

| Concern | What it covers |
|---|---|
| **Process** | Which steps exist, what each one is, and which phase it belongs to |
| **Sequence** | What triggers a step and what it emits |
| **Dependencies** | What must have completed before a step is eligible |
| **Entitled activities** | What each step is permitted to do -- tools, commands, environment |

**Why.** This is P-2 ("one machine-readable source per concern") applied to the
pipeline itself. A second definition of any of these does not supplement the
first, it competes with it: the two drift, and the drift is invisible until a
specific step behaves in a way neither source predicts.

Entitlement is the concern where this matters most, because an entitlement
defined in two places is a security property that holds in one reading and not
the other. It is also the concern where a second source is easiest to add
without noticing -- a constant in the orchestrator, a line in an agent's
frontmatter, a grant in a settings file -- each individually reasonable.

**Test.** Assert that the resolved entitlement set for every step is derivable
from `pipeline.json` alone. Any entitlement that cannot be traced to it is a
test failure. The same for triggers and dependencies.

**Conformance:** `VIOLATED` for entitlements; `CONFORMS` for process, sequence
and dependencies.

Entitlements currently come from four sources:

| Source | Size | Kind |
|---|---|---|
| `BASE_AGENT_TOOLS`, `pipeline_orchestrator.py:2712` | 28 entries | Python constant |
| Agent frontmatter `tools:` | 14 agent files | Prompt metadata |
| `pipeline.json` `defaults.extra_allowedTools` + per-step | 2 + 8 steps | Configuration |
| `.claude/settings.json` `permissions.allow` | 1 entry | Session config |

The largest block is a hardcoded constant, not configuration. Three defects
trace directly to this split: **#326** was a defect *in* `BASE_AGENT_TOOLS`
(patterns failed to match quoted URLs, blocking agents outright in headless
mode); **#362** is a defect in the `settings.json` path (the grant is silently
dropped when the workspace is untrusted); **#356** was drift between sources
during resolution (24 tools returned where 93 are passed).

**Relationship to MI-3.** These are two halves of one property and both are
required. AS-1 says entitlement is **defined** in one place. MI-3 says it is
**enforced** by one mechanism. Satisfying AS-1 alone still permits two enforcers
reading the same definition and disagreeing; satisfying MI-3 alone still permits
one enforcer reading four definitions.

**Existing work.** #357 already proposes exactly this ("pipeline.json should be
the authoritative source for allowed env vars and commands, globally and per
step"). It is open and predates this document.

---

## The two operating modes

The orchestrator runs in two modes, and both exist for good reasons.

**Scheduled (headless).** GitHub Actions triggers the orchestrator on issue and
pull-request events, or on a timer. Nobody is watching. Work progresses while
the team sleeps, and gates wait for whoever next looks at the issue. This is the
primary mode.

**In-session (interactive).** A person runs `/maos-run {N}` inside a Claude Code
session and drives one issue forward step by step, watching each agent work and
answering gates immediately. This is how work gets unblocked, debugged, and
pushed when someone is at the keyboard.

Both modes are the same product. A person must be able to start an issue in one
mode, walk away, and have the other finish it, with no observable difference in
the result.

---

## Mode invariants

These are the properties that must hold **identically** in both modes. They are
not aspirational: an unlisted difference between modes is a defect, and each
invariant below states how to test it.

They exist because mode divergence is the single largest source of defects in
this system. Of the 27 defects filed between 15 and 25 August 2026, **11 are
mode divergence** -- more than any other cause. The duplicated tool-scope
enforcement layer alone produced five of them, including the only one
classified `[SECURITY]`.

There was no invariant list when in-session mode was built, so nothing existed
to check it against.

---

### MI-1 -- One state, one meaning

**Statement.** The labels on an issue mean exactly the same thing regardless of
which mode wrote them. No label is mode-specific, and no label is interpreted
differently depending on who applied it.

**Why.** State is the only thing shared between modes. If a label's meaning
depends on its origin, the two modes are not operating on the same machine and
an issue cannot be handed between them.

**Test.** For every label in `statuses.json`, assert exactly one documented
meaning, and assert no step's behaviour branches on which mode applied it.

**Conformance:** `PARTIAL, UNTESTED`. Labels are shared and no mode-specific
label exists. But no test enforces this, and #380 shows a case where a label's
practical meaning depends on step configuration rather than on the label:
`:review` means "awaiting a named gate" for most steps and "halted with no exit"
for a step that declares no `human_gate_label`.

---

### MI-2 -- One routing decision

**Statement.** Given identical state, both modes select the same next step.
Routing is computed in exactly one place. A driver may read the pipeline
definition to explain what will happen, but never to decide it.

**Why.** Two implementations of routing drift, and the drift is invisible until
they disagree on a specific issue.

**Test.** Run the resolver and the real dispatch path over the same issue state
and assert identical selection, for every step in `pipeline.json`.

**Conformance:** `VIOLATED`. `/maos-run` correctly delegates routing to the
orchestrator, but `/run-agent` resolves invocation parameters through a separate
`--print-prompt` path. #356 is exactly this drift realised: resolve-only mode
returned 24 tools where the real spawn passes 93. It was fixed, but the
duplicated path remains and nothing tests the two against each other.

---

### MI-3 -- One authority mechanism

**Statement.** Whatever constrains what an agent may do is the **same
mechanism** in both modes, not an equivalent one. No mode re-implements another
mode's enforcement.

**Why.** This is the most expensive invariant in the list. A re-implementation
must be kept in step with the original forever, and it will not be. Every
divergence is a security property that holds in one mode and not the other,
silently.

**Test.** Assert that exactly one component decides whether a tool call is
permitted, and that both modes route through it. A second implementation is a
test failure, not a design choice.

**Conformance:** `VIOLATED`. Headless mode uses Claude Code's native
`--allowedTools` when it spawns an agent subprocess. In-session mode cannot,
because `/run-agent` executes agent instructions inside the caller's session, so
it re-implements enforcement in bash: a resolved allowlist written to a scope
file, a `PreToolUse` hook, and a shell-command splitter. `run-agent.md` says so
in its own words -- the hook applies *"the same restriction the real
orchestrator applies via `--allowedTools`"*.

That emulation has produced five defects: #335 (denied every call), #356
(dropped grants), #374 (concurrent runs clobbered each other -- `[SECURITY]`),
#383 (refuses 31% of all agent shell blocks), #388 (the key may never match, so
enforcement may be inert entirely).

**The cheapest route to conformance is deletion, not repair**: if `/run-agent`
spawns a subprocess as the orchestrator already does, native enforcement applies
and the hook, splitter, scope file and resolve-only grant plumbing can be
removed. What is lost is in-session visibility of the agent's work. That
trade-off has not yet been evaluated; it is a question for #393.

---

### MI-4 -- Every halt has an exit in both modes

**Statement.** Any state a run can enter must have a documented exit that is
performable in both modes. A state reachable in one mode and escapable only in
the other is a defect.

**Why.** A halt with no exit is not a pause, it is a loss. Recovering from one
requires editing state out of band, which is exactly the un-auditable
intervention the label model exists to prevent.

**Test.** For every terminal and halt status, assert a documented exit action,
and assert that action is performable by both an unattended runner and an
in-session driver.

**Conformance:** `VIOLATED`, three ways.

- **#380** -- a step emitting `:review` without declaring a `human_gate_label`
  strands the issue: no label exists that clears it. Recovery required deleting
  a label out of band, twice, on 25 August.
- **#377** -- `/maos-run` is documented to apply the `{agent}:approved` gate
  label itself, but the self-approval guard rejects any gate label applied by a
  bot. The documented procedure cannot work in-session.
- **#314** -- `.pipeline-stop` has no defined interactive behaviour and no
  staleness alerting.

---

### MI-5 -- One set of effects, in one order

**Statement.** The side effects of a step -- labels applied, comments posted,
commits made, artefacts written -- are identical in both modes and occur in the
same order. A mode may differ in **who triggers** a step. It may never differ in
**what the step does**.

**Why.** If effects vary by mode, the artefact trail is not a record of what
happened; it is a record of who happened to be watching.

**Test.** Run the same step in both modes against equivalent state and diff the
resulting issue timeline -- labels, comments and commits -- ignoring
timestamps and actor.

**Conformance:** `UNTESTED`. No known violation, and no test. This invariant is
listed because its absence would be invisible until it mattered: nothing today
would detect a step that behaves differently under a runner than under a driver.

---

### MI-6 -- Observability does not vary by mode

**Statement.** Every control reports whether it engaged and what it decided, in
both modes, in the same form. No control is silent in one mode and loud in the
other, and no control is silent in both.

**Why.** This is the invariant whose absence caused the most damage. When a
control fails by reporting success, every downstream signal -- green CI, a clean
review, a `:complete` label -- becomes evidence of nothing.

**Test.** For every control, assert it emits a decision line on both the engaged
and the skipped path, and assert the two modes produce the same line.

**Conformance:** `VIOLATED`, and this is the widest failure in the list. Nine of
the 27 defects in the review window report success while doing nothing: #308,
#315, #343, #346, #358, #362, #378, #387, #388. Several are additionally
mode-specific: #346 false-negatives only in an interactive session, #326 blocked
agents only in headless mode, #334 failed only in restricted sessions.

---

### MI-7 -- Human authority does not vary by mode

**Statement.** A gate requires a human decision in both modes, recorded through
the same mechanism. Neither mode may self-approve, and neither may record
approval in a way the other cannot read.

**Why.** P-10 -- agents draft, humans decide -- is a load-bearing commitment. A
mode in which it is enforced differently is a mode in which it is not enforced.

**Test.** Assert that a gate label applied by a non-human actor is rejected in
both modes, and that a gate label applied by a human is honoured in both.

**Conformance:** `VIOLATED`. The self-approval guard correctly rejects bot-applied
gate labels -- but in-session mode has no other way to record a decision, so a
driver cannot cross a gate at all (#377). The guard is also **fail-open**: when
the timeline API has not yet surfaced the `labeled` event, it logs
`no 'labeled' event found ... allowing (fail-open)` and admits the gate. Timeline
reads are eventually consistent, so a bot-applied gate passes under lag. Both
were observed on 25 August.

---

### MI-8 -- Differences are enumerated and justified

**Statement.** Anything that legitimately differs between modes is listed in
[Legitimate differences](#legitimate-differences) with a reason. A difference
that is not listed is a defect, not a feature.

**Why.** Without this, divergence accumulates as a series of individually
reasonable accommodations, each invisible, until the modes are different
products. That is what happened.

**Test.** Assert that every mode-conditional branch in the orchestrator, the
scripts and the agent prompts maps to a listed difference.

**Conformance:** `PARTIAL`. `17-operating-modes.md` documents differences, but as
a comparison table plus a list of *current limitations* -- things that happen to
be true today, not differences argued to be permanent. Nothing distinguishes an
intended difference from an unrepaired defect, and no test maps code branches to
either.

---

## Legitimate differences

The complete list of what may differ between modes. Anything not here is a
defect.

| Difference | Scheduled | In-session | Why this is legitimate |
|---|---|---|---|
| Who triggers a step | GitHub Actions event or cron | A person running `/maos-run` | The whole point of having two modes |
| Where output is displayed | GitHub issue and PR activity | The same, plus live agent output in the session | Display is not state; the artefact trail is identical either way |
| Credential source | Repository secrets | The session's own login | The environments genuinely differ; the *authority* those credentials carry must not |
| Latency to a gate decision | Until a human next looks | Immediate | A human being present is the difference between the modes |

Everything else -- state, routing, authority, exits, effects, observability --
is governed by MI-1 to MI-7 and must be identical.

Two things are frequently mistaken for legitimate differences and are not:

- **Enforcement mechanism** (MI-3). That in-session mode *cannot* use
  `--allowedTools` today is a consequence of how `/run-agent` executes, which is
  a choice, not a constraint.
- **Which errors are recoverable.** A GraphQL refusal and a repository-access
  refusal are different failures with different remedies, but which one you get
  must not depend on the mode.

---

## Conformance summary

| Invariant | Status | Defects |
|---|---|---|
| AS-1 `pipeline.json` defines the process | VIOLATED (entitlements) | #326, #356, #362 |
| MI-1 One state, one meaning | PARTIAL, UNTESTED | #380 |
| MI-2 One routing decision | VIOLATED | #356 |
| MI-3 One authority mechanism | VIOLATED | #335, #356, #374, #383, #388 |
| MI-4 Every halt has an exit | VIOLATED | #377, #380, #314 |
| MI-5 One set of effects | UNTESTED | none known |
| MI-6 Observability | VIOLATED | #308, #315, #326, #334, #343, #346, #358, #362, #378, #387, #388 |
| MI-7 Human authority | VIOLATED | #377 |
| MI-8 Differences enumerated | PARTIAL | -- |

Seven of nine invariants are violated or unverified. **No invariant currently
has a test.** That is the first thing to change: until each has one, conformance
is an assertion in a document rather than a property of the system.

---

## Status of this document

| Topic | Authoritative source | State |
|---|---|---|
| What the orchestrator is | this document | draft |
| Authoritative sources (AS-1) | this document | draft |
| Operating modes and invariants | this document | draft -- supersedes `17-operating-modes.md` |
| Pipeline configuration | `pipeline.json` itself (AS-1); `05-pipeline-config.md` documents its schema | not yet superseded |
| Vision and problem | `01-vision.md` | not yet superseded |
| Principles P-1 to P-16 | `02-principles.md` | not yet superseded; three known contradictions with the implementation |
| Lifecycle, status model, gates | `04`, `06`, `07` | not yet superseded |
| Orchestrator responsibilities | `11-orchestrator.md` | not yet superseded |
| Agent specification | `12-agent-spec.md` | not yet superseded |
| Standards model | `14-standards.md` | not yet superseded |

**Known contradictions carried forward**, to be resolved as sections are
written:

- P-16 names `coder` a Mode 1 (agent-driven commit) agent; `pipeline.json`
  configures it `commit_after: true`, which is Mode 2; and `coder.md` instructs
  it never to run `git commit` or `git push`. Three sources, three positions.
- P-16 states agent allowlists must name specific git subcommands, "never the
  bare `Bash(git *)` glob". `coder`'s only git grant is `Bash(git *)`, which
  admits `git reset --hard`, `git push --force` and `git branch -D` -- the three
  commands P-16 separately forbids for all actors in both modes.
- P-9 mandates unconstrained cross-issue parallelism and names
  `impact-assessor` and `dependency-resolver` as the agents that make it safe.
  Neither exists, and the orchestrator has no `blocked-by` handling (#135).
