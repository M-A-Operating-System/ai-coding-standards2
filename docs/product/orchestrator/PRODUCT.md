# The Orchestrator Product

The single description of what the orchestrator is and what it promises.

This document states the target design as fact. Closing the gap to the
current implementation is tracked as a sequenced build plan on
[issue #393](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/393),
against the
[`feature/393-orchestrator-target-design`](https://github.com/M-A-Operating-System/ai-coding-standards2/tree/feature/393-orchestrator-target-design)
integration branch.

---

## Vision

Software teams spend a disproportionate share of their time on the
connective tissue around code: writing PRDs, translating them into
designs, deciding what to test, decomposing work into tasks, reviewing
for standards. That work is repetitive, done under time pressure, and
where most quality issues originate — a missing acceptance criterion, an
unrecorded architectural decision, a forgotten test case.

AI Agile is a product development lifecycle in which specialised AI
agents own each repetitive activity, run from a single source of truth —
a GitHub issue — and produce a complete trail of artefacts. Humans
approve at well-defined gates rather than performing the work. The
orchestrator runs that lifecycle. It does not replace product or
engineering judgement, only the repetitive work around it.

---

## Personas

Six people, and one automated role, use AI Agile, each at a different
point in the pipeline:

- **Stakeholder** — opens the issue that starts a piece of work, and
  approves the PRD that comes back.
- **Engineer** — owns the design and the code; approves the build plan
  before any of it is written.
- **Reviewer** — approves at the gates a Stakeholder or Engineer does
  not: sizing, design, test spec, PR.
- **Standards Owner** — owns the standards the pipeline enforces, and
  approves proposed changes to them.
- **Security Owner** — approves any change flagged as touching a
  security-sensitive surface.
- **Data Owner** — approves any change that includes a data migration.
- **System actor** — the role a capability is written against when its
  primary actor is genuinely automation (a scheduled job, an audit
  logger), not a person, so automated capabilities go through the same
  product-led pipeline as everything else.

This is a closed vocabulary: `prd-writer` validates every `As the
{persona} ...` story against it, the same way `coder` validates a diff
against a standards category. The machine-readable source is
[`standards/personas.json`](../../../standards/personas.json); the
System actor's qualifying test lives there as data, not prose duplicated
in a prompt (see
[`14-standards.md`](../standards/14-standards.md#personas-not-a-category-a-closed-vocabulary)).

---

## Contents

**The work-item taxonomy**
- [Type ranks five reasons an issue exists](#type-ranks-five-reasons-an-issue-exists)
- [Size measures how much work there is](#size-measures-how-much-work-there-is)
- [Priority orders pickup among eligible work](#priority-orders-pickup-among-eligible-work)
- [Blocking declares an ordering dependency between issues](#blocking-declares-an-ordering-dependency-between-issues)

**The state machine**
- [Labels are state; a step is a transition](#labels-are-state-a-step-is-a-transition)
- [Eligibility and order decide which item runs next](#eligibility-and-order-decide-which-item-runs-next)
- [A component label lets unrelated work run at once](#a-component-label-lets-unrelated-work-run-at-once)
- [Every step has the same four parts](#every-step-has-the-same-four-parts)

**Flows**
- [The pipeline defines flows, not a flow](#the-pipeline-defines-flows-not-a-flow)
- [A flow takes one of three shapes](#a-flow-takes-one-of-three-shapes)
- [Coordinating work needs a trigger that can look outward](#coordinating-work-needs-a-trigger-that-can-look-outward)
- [A flow is not the only thing that can watch an object](#a-flow-is-not-the-only-thing-that-can-watch-an-object)
- [A step can finish its own work in pieces](#a-step-can-finish-its-own-work-in-pieces)
- [A scheduled flow derives its own due-ness from the record](#a-scheduled-flow-derives-its-own-due-ness-from-the-record)
- [The orchestrator stamps what it creates](#the-orchestrator-stamps-what-it-creates)

**Steps**
- [A step learns its situation only from what it's told](#a-step-learns-its-situation-only-from-what-its-told)
- [Headless and interactive ask two different questions](#headless-and-interactive-ask-two-different-questions)
- [The orchestrator decides; agents only produce](#the-orchestrator-decides-agents-only-produce)
- [An agent's activity lives in one prompt file](#an-agents-activity-lives-in-one-prompt-file)
- [Every step, agent or script, is bound by the same contract](#every-step-agent-or-script-is-bound-by-the-same-contract)

**The promises**
- [The promises](#the-promises)

**Modes**
- [Headless and interactive](#headless-and-interactive)
- [What is allowed to differ](#what-is-allowed-to-differ)

---

## The work-item taxonomy

Four independent label dimensions describe a work item. None chooses
what a step *does* — the same `coder` runs identically regardless of any
of them. `type` and `size` choose which flow and which steps apply;
`priority` and blocking change only how the orchestrator schedules
eligible work. A fifth label, `component:`, is a different kind of
thing entirely: not a classification of the work but a concurrency
claim on the part of the system it touches (see [A component label lets
unrelated work run at
once](#a-component-label-lets-unrelated-work-run-at-once)).

Which agent applies each of the four, and the exact flow each
combination produces, is process — see
[lifecycle.md](lifecycle.md), starting with [Issue classification
taxonomy](lifecycle.md#issue-classification-taxonomy).

### Type ranks five reasons an issue exists

Product docs are the target state; code is the current state.
`docs/product/` describes what should exist, and the gap between that
and what has shipped is the issue backlog. No code change ships unless
it is already described in `docs/product/` first.

Every issue carries a `type:` label, exactly one of five. Four split on
one axis: does the work move the product forward, or not. `enhancement`
is the baseline unit that does. `security`, `bug`, and `tech-debt` are
the same scale and complexity but exist without moving the product
forward — they close an exposure, correct a drift from the documented
target, or remediate and maintain. `spike` is the one type not measured
against the baseline at all: it ships no increment, only knowledge. The
split makes a ratio like `enhancement : (tech-debt + bug + security)` a
real signal read off the label alone.

| Priority | Type | Definition | Qualifying criterion |
|---|---|---|---|
| 1 | `security` | A concrete security vulnerability with a clear exploit path — injection, authn/authz bypass or privilege escalation, secret/credential exposure, SSRF, path traversal, insecure deserialization, missing/incorrect access control, or a known-vulnerable dependency with an exploit path. | Classified conservatively: the impact must be clear and concrete, not "might be a security concern" (that stays `bug`). Carries the heaviest review bar of all five. |
| 2 | `bug` | Broken behaviour — something that used to work and no longer does, or behaviour that violates the target state in the product docs. | By definition the code has drifted from the product-docs target; the fix is to correct the code, not the docs. |
| 3 | `enhancement` | A change to the product's capability, new or existing, sized to ship end-to-end in one sequence. | Moves the target state forward. Scale alone does not change the type, only its size. |
| 4 | `tech-debt` | Enhancement-scale work that does not move the product forward: routine operational/maintenance upkeep and remediation of a previously made structural or architectural choice now recognised as costly. | Tied to a non-functional requirement in the product docs, not a user-facing feature. |
| 5 | `spike` | Research or investigation whose primary output is knowledge — a recommendation, an ADR, or a prototype — not shipped code. | Time-boxed; the result feeds a later issue that ships the actual change. |

The Priority column is a total order: when more than one type is
plausible, `issue-classifier` picks the one that ranks highest.
`security` beats everything, but only when the impact is clear and
concrete — an ambiguous case stays `bug`. `bug` beats `enhancement` and
everything below it: a drift from the documented target is the story,
whatever capability it sits inside. `enhancement` beats `tech-debt`: a
user-observable change is product work, even if it also pays something
down. `tech-debt` beats `spike`: real remediation work outranks "let's
go find out." `spike` is last on purpose — it is a claim of not knowing
enough to build yet, and if enough is already known to name the work as
anything else on this list, it is not a spike.

### Size measures how much work there is

A second, independent dimension: `size:` answers how much work there is,
never why it exists. Every issue carries exactly one, alongside its
`type:`.

| Size | Meaning |
|---|---|
| `S` | Small enough on its own that shipping it alone wastes review overhead — a candidate for grouping with other small work |
| `M` | Fits the enhancement baseline as itself |
| `L` | Too big for one item — a candidate for splitting into independently-sized children |

Only `M` ever ships code. `S` and `L` are routing sizes, not build
sizes: neither the small issue that gets grouped nor the large issue
that gets split is itself what gets implemented. Each routes to a fresh
work item — a super-issue for `S`, children for `L` — sized on its own
merits, and the recursion bottoms out at `M` before any code-producing
step runs. `size:` applies uniformly across every `type:`: there is no
type that is big by definition; bigness is `size: L`, for anything.

### Priority orders pickup among eligible work

A third, independent dimension: `priority: high`, `priority: medium`, or
`priority: low`. Priority never changes which steps run or what a step
does — unlike `type:` and `size:`, it only decides which of several
eligible issues the orchestrator works on first (see [Eligibility and
order decide which item runs
next](#eligibility-and-order-decide-which-item-runs-next)).

A human applies `priority:` today, since it reflects business urgency
that a step reading one issue in isolation cannot weigh. That is a fact
about today's mechanism, not a permanent rule: a future scheduled
mechanism reading signals across the whole backlog — the same shape as
the continuous loops in lifecycle.md — could propose or set it instead.
No such mechanism is designed here. Unprioritised work stays eligible;
it just sorts behind anything carrying a `priority:` label.

### Blocking declares an ordering dependency between issues

A separate mechanism from `type:`/`size:`/`priority:`, for an ordering
dependency between two issues that has nothing to do with either one's
classification. `blocks: {N}` on one issue and `blockedby: {N}` on the
other declare it symmetrically, so the relationship reads off either
issue's own label list.

A human applies them directly today, or delegates the applying to a
request-triggered step. That is not a permanent rule either: a future
scheduled mechanism could detect and declare the dependency on its own,
the same way a scheduled mechanism could set `priority:`. No such
mechanism is designed here. Either way the labels are the whole of the
fact — there is no second record of the dependency anywhere else.

An issue carrying `blockedby: {N}` while `N` is still open is not
eligible to start at all. This gates only the entry step, never a step
mid-flow — once a flow has started, further changes to
`blocks:`/`blockedby:` have no effect on it. Clearing works two ways: a
human removes either label directly at any time, identically in either
mode, the same way clearing `review` or `blocked` already resumes a
halted step; or, once `N` closes on its own, both labels come off
automatically. Either way, nothing about who or what removed the label
changes what it meant while it was there.

---

## Labels are state; a step is a transition

The labels on a work item are the state. A step is a transition. The
orchestrator reads the labels, selects the one step whose conditions
are met, runs it, and writes the outcome back as a label.

Because state lives on the work item, there is nothing to recover and
no position that exists only in memory. Any orchestrator process reading
settled labels reaches the same conclusion.

A headless run is started by a GitHub event, automatically. A label
write is not visible instantly, so a run's own `:wip` write can fire an
event that starts a second run inside that unsettled window, which reads
stale state and repeats a decision the first run already acted on. So
headless needs one thing synchronised: at most one headless orchestrator
run at a time, enforced by the GitHub Actions concurrency group the
workflow runs under. Once runs are serialised this way, the `:wip` check
becomes a fast skip rather than a guard against a race — the run keeps
its own settled copy current for as long as it runs, updating it the
instant it writes a label itself.

One headless run works through as many eligible items as it has room
for, bounded by a per-tick cap and its own wall-clock ceiling, rather
than handling one and exiting. That cap exists because a burst of
eligible work — a hundred issues, a backlog import — needs a bound on
how much a single pass takes on; it is a budget declared in
`pipeline.json`, not fixed in code.

Interactive mode does not have this race, because it is not this shape.
A person typing `/maos-{agent}` starts an orchestrator instance
directly — no webhook, no automatic respawn. Nothing stops two people,
or one person in two sessions, from doing this at once; nothing should,
since waiting on someone else's chat session defeats the point of
working interactively. Interactive concurrency is addressed on its own
terms (see [A component label lets unrelated work run at
once](#a-component-label-lets-unrelated-work-run-at-once)), not folded
into headless's guarantee.

### Eligibility and order decide which item runs next

Two questions, not one, and both are core orchestration logistics — not
one of [AS-1's seven
concerns](#as-1----one-file-tells-you-what-the-pipeline-does), but a
sibling to that promise under the same governing rule.

**Eligibility: is this item allowed to start at all.** An item halted
mid-flow — any step of it sitting in `review` or `blocked` — has no
eligible next step until a human clears the gate, so it drops out of
contention on its own. An item that has not yet started is additionally
ineligible while it carries `blockedby: {N}` and `N` is still open. Both
kinds of halt clear the same way: a human removes the label, in either
mode, and the item is eligible again on the next check. A third,
unrelated reason an item may wait: it cannot claim every `component:` it
names right now, because another item in flight already holds one — not
a halt, and not something a human clears; it resolves itself the moment
the holding item finishes.

**Order: among what's eligible, which goes first.** `priority:` orders
the rest — `high` before `medium` before `low` before unprioritised —
and within a tier, the item raised earliest goes first.

Priority tiering is already declared config today:
`pipeline/statuses.json`'s `priority_ordering` list, external to
orchestrator code, the same principle AS-1 states for `pipeline.json`.
Blocking eligibility has no equivalent yet — nothing declares
`blockedby:` as a condition anywhere machine-readable. Giving it a
declared home is unfinished target-state work.

### A component label lets unrelated work run at once

From an issue's perspective, at most one issue per component is in
flight at a time, headless and interactive combined. Labels only ever
keep two runs off the same *item*; two issues that change the same
module have nothing else keeping them apart, and the collision surfaces
as a merge conflict at best. So the unit that has to be exclusive is not
the issue, it is the part of the system the work touches.

An issue carries a `component:` label for each part of the system it
affects, and may carry several. Before starting an item, an orchestrator
instance — headless or interactive — claims every component the item
names, and starts only if it can claim them all at once: an item never
holds part of what it needs while waiting for the rest, which is what
keeps this from deadlocking. An untagged item claims everything, so it
runs exactly as sequentially as the pipeline does today. There is no
register of valid components anywhere; the orchestrator reads whatever
`component:` labels exist and compares them for equality.

That correctness is never checked against evidence. A mistagged item —
claiming fewer components than it actually touches — produces no signal
until the collision it causes is the evidence, and a near-miss name
(`component:auth` vs. `component:authentication`) reads as no overlap
at all. This is a deliberate trade: inspecting what an issue really
touches is unreliable enough that a visible, person-correctable label
beats it.

The same claim holds under both concurrency shapes. Headless is one
process, so it answers "is this component free?" from the settled copy
it already holds. Interactive is genuinely several processes — each
`/maos-{agent}` invocation is its own, unserialised — so an interactive
instance reads GitHub's labels fresh for the same check.

Claiming decides who may proceed together; it does not isolate them.
Two cleared items still need separate working trees — a shared checkout
means the second disturbs the first regardless of what either touches.
The label is the decision; the working tree is what makes the decision
mean something.

### Every step has the same four parts

| Part | Declared in `pipeline.json` as | What it is | Determinism |
|---|---|---|---|
| Allowed commands | `extra_allowedTools` | Everything this activity may do. Anything else is refused | Data |
| Pre-actions | `defaults.agent_lifecycle.before` | Work performed before the activity — checking out the branch, preparing the scratch directory | Code |
| The activity | `type` with `agent` or `script` | The work the step exists to do: an AI agent, or a script | Deterministic when a script; not deterministic when an agent |
| Post-actions | `post_steps`, `git_ops`, `defaults.agent_lifecycle.after` | Work performed after — committing, pushing, labelling, posting the artefact | Code |

Three of the four parts are always code or data. The fourth is code
too, unless the step uses an agent — so uncertainty enters the system
at exactly one place, and only for the steps that need judgement.

`post_steps` and `agent_lifecycle.after` run in different shapes for
different jobs. `post_steps` is an ordered list of scripts specific to
one step, firing only when that step signals `complete`, and a
non-zero exit aborts the rest of the list and fails the step.
`agent_lifecycle.after` wraps every agent step regardless of outcome —
`complete`, `review`, `blocked`, a crash, or retries exhausted — and its
own failure is logged and swallowed rather than failing the run. Use
`post_steps` for an action specific to one step's success; use
`agent_lifecycle` for work every agent needs done around it, win or
lose.

`agent_lifecycle.before` must be idempotent because it runs again on
every retry, including one following a kill mid-run — there is no
signal handler that can save it, since the kill that ends a background
tick is uncatchable. `before` removes its scratch directory before
creating it, rather than assuming it is absent, so a tick killed
mid-run leaves debris the next run simply clears before it starts.

Commands every step needs are declared once in
`defaults.extra_allowedTools` rather than repeated on each step. A
step's effective permission is exactly the global set plus its own
`extra_allowedTools`, and nothing else. Budgets follow the same shape:
declared once in `pipeline.json`'s top-level `budgets`, overridable per
step where a step genuinely differs, one wall independent of the other.
A wrong number is not silently wrong — it surfaces as `exhausted`,
naming the wall a step hit, and gets revised like any other value in the
file.

Permission is decided before the activity runs and cannot be widened by
it. Setup and consequences run as pre- and post-actions on either side
of the agent, on the orchestrator's schedule. What the agent actually
influences is the work product and one status value — nothing else in
the system depends on the agent having behaved reasonably.

---

## The pipeline defines flows, not a flow

The orchestrator runs work. It does not know what kinds of work exist.

A **flow** is one kind of work, declared in `pipeline.json`: what it
applies to, what starts it, which steps run in what order, and what its
branches and pull requests are called. The orchestrator knows how to run
a flow; the file says which flows there are. A system that knows about
one kind of work has that kind written into it, and every new kind of
work becomes a change to the component every other kind depends on.

### A flow takes one of three shapes

These are not the flows themselves. They are the shapes a flow can
have, and all three must be expressible without touching the
orchestrator.

| Shape | Started by | Example |
|---|---|---|
| Work that produces change | A work item appearing, or a label on it | An issue, taken from description to shipped code |
| Work that coordinates other work | A work item whose children are the real work | An epic, which decomposes into issues and closes when its review step confirms the whole, not merely when the parts are closed |
| Work with no work item behind it | A schedule | A periodic loop over the codebase, the backlog or the record, which produces work items rather than consuming one |

### Coordinating work needs a trigger that can look outward

A flow that coordinates other work has a stage where it is waiting: the
parts are running and the parent has nothing to do until they finish.
Waiting is not a step — it is a later step whose conditions are not yet
met, so the orchestrator finds the item ineligible and moves on,
advancing once the condition holds.

A trigger must be able to say more than "a label on this item." "Every
child of this item is closed" is a condition about other work items;
without it, the waiting has to be written in code, which is how
coordination ends up inside the orchestrator rather than in the file
that describes it.

### A flow is not the only thing that can watch an object

Nothing requires exactly one flow per object kind. The orchestrator
routes on a step's own trigger and dependencies, not which flow declared
it, so a second flow may match an object kind a first already covers, as
long as their steps' conditions never make two eligible on the same item
at once.

That is what makes "closes when the whole is sound" real: an epic's
children closing is not the soundness check, it is what makes a review
step eligible, and that step — declared like any other, with its own
allowed commands and expected effect — is what the epic's closing
depends on. What the review judges is a decision for whoever declares
that step.

### A step can finish its own work in pieces

An epic waits *while* its children are open. A step can use the
identical capability the other way round: stay eligible *while its own*
children are open, so finishing the item takes several invocations
instead of one. Lifecycle.md's super-issue, where several grouped small
issues become one shippable unit, is the shape this fits — though
lifecycle.md does not yet say whether its build step actually uses this
capability, one grouped issue per invocation, or covers all of them in a
single pass.

A step's turn and wall-clock budgets bound one invocation, and a
sub-issue-heavy issue can need more of either than any single invocation
should be given, even though no one sub-issue does. Without this, a step
that runs out partway through loses everything back to the last commit.

The unit of work shrinks; the contract does not. `complete` still means
the step finished what it was given, because what it was given is now
smaller. The orchestrator commits after each invocation, so a step that
later runs out on sub-issue four leaves the first three committed. The
step just needs one more thing on the channel every step is already
told: which piece this invocation is for.

A flow's primary branch is created from the default branch unless the
flow says otherwise, declared the same way the branch name itself is, a
token pattern in `naming`, never computed in code. This is what makes a
shared integration branch expressible for a coordinating-work flow:
today's large-item flow (lifecycle.md, [The ticket is too
big](lifecycle.md#the-ticket-is-too-big)) uses exactly this — every
child of a decomposed `L` ticket is cut from, and merges into, the
parent's own `feature-{parent_N}` integration branch instead of the
default branch, so the aggregate lands somewhere reviewable as a whole
before any of it reaches `main`. If a flow's declared base does not
exist, it falls back to the default branch.

### A scheduled flow derives its own due-ness from the record

A scheduled flow has no work item, so it has nowhere to carry a label —
and labels are the state. Where "this last ran on Tuesday" is kept is
not kept anywhere new: every completed step appends a timestamped entry
to the log and metrics branches, so when a flow last ran is a read of
the record, and a flow that has never run has no entry, which is the
same answer as overdue. The alternative — a last-run table, or a cadence
in a workflow file — is exactly the hidden state the label model exists
to avoid. The cadence is declared with the flow; whether it is due is
derived from what already happened.

A scheduled flow also needs a claim of its own, because the `:wip`
mutex is a label on a work item and there is no work item to label — two
runners must not start the same sweep.

A scheduled step is a step: what it may do is its allowed commands and
its expected effect, declared in `pipeline.json`, never inferred from
the fact that a schedule started it. A step that only looks is granted
no commands that write and an expected effect of no change; a step that
acts is granted the commands to act. A step declaring no change that
produces a commit disagrees with itself, and MI-6 surfaces the
disagreement, the same as for every other step.

### The orchestrator stamps what it creates

A step returns what it produced and the orchestrator writes it (the
step contract); when what it produced is a new work item, the
orchestrator also records which step and which flow produced it. That
provenance is what lets a flow find its own earlier output and raise
only what is new since, rather than repeating the same findings every
run.

---

## A step learns its situation only from what it's told

A step — agent or script, pre-action or post-action — is a separate
process that knows nothing when it starts. Everything it needs arrives
as environment variables the orchestrator sets when it invokes the step.
A step never works out its own context: it does not search for the
repository root, guess the issue number, decide where to put working
files, or probe whether a human is present. If the orchestrator does not
tell it, the step does not need it. That rule is what makes a step
testable in isolation and portable between the two modes.

| Variable | What it says |
|---|---|
| `AI_AGILE_ROOT` | Where the repository is |
| `AI_AGILE_CONTEXT` | Where the shared agent protocol is |
| `AI_AGILE_EXECUTION_MODE` | Whether *this step* has a human attached |
| `REPO` | Which GitHub repository to act on |
| `WORK_ITEM_KIND`, `WORK_ITEM_NUMBER` | What it is working on |
| `ISSUE_NUMBER` or `PR_NUMBER` | The same, in the form the step expects |
| `SUB_ITEM_NUMBER` (when applicable) | Which piece of the item this invocation covers, for a step invoked once per sub-issue |
| `SESSION_ID`, `SESSION_SCOPE` | Which run this is, and how far it persists |
| `AI_AGILE_SCRATCH` | Where working files go |

`SESSION_ID` is derived from a token pattern declared on the step
(`session.id_pattern`); the available tokens and retry-suffix behaviour
are specified in
[`schema/pipeline.schema.json`](schema/pipeline.schema.json). Credentials
are supplied the same way and deliberately not part of this list: a
step receives what it needs to authenticate and nothing about how that
was arranged.

### Headless and interactive ask two different questions

"Headless or interactive" means two different things depending on what
is being asked, and conflating them causes real defects.

| | Question | Who knows |
|---|---|---|
| How the tick was started | Did a person run this, or did GitHub Actions? | The orchestrator |
| How this step runs | Does *this activity* have a human attached to it? | The step, via `AI_AGILE_EXECUTION_MODE` |

They are not the same, and the second is not derived from the first.
When a person drives a run interactively, the orchestrator is
interactive — but the agents it spawns are still subprocesses with
nobody watching them. `AI_AGILE_EXECUTION_MODE` answers the second
question and describes the activity, not the run: every activity the
orchestrator spawns as a subprocess is `headless`, whichever way the
tick began. The only activity that is `interactive` is one a person is
working through themselves, not a spawned agent at all. A step whose
behaviour genuinely depends on the first question — how to treat an
emergency stop, whether a human can be prompted right now — must be told
separately and explicitly; a step that infers one from the other, or
probes to find out, is deciding something the orchestrator owns (AS-2).

---

## The orchestrator decides; agents only produce

The orchestrator is deterministic. The agents it invokes are not: they
are language models, and the same prompt over the same input can
produce different work on different runs. The whole design follows from
keeping those two things apart.

Routing, state, sequencing and permission are computed by code from
`pipeline.json` and the labels. Nothing an agent says influences what
runs next, beyond the single terminal status it returns from a fixed
set. Each agent is a black box: the orchestrator supplies a defined
input, waits, and reads a defined output, without inspecting how the
agent reached it. This is what makes agents replaceable — a step can be
re-prompted, re-modelled, or reimplemented as a script without anything
else changing.

Because an agent's only influence on control flow is one status value, a
bad run costs one step and is visible on the issue. It cannot corrupt
the state machine, skip a gate, or change what happens next. That
containment is only real if the boundary is precise, which is what the
step contract states.

### An agent's activity lives in one prompt file

An agent step's activity lives in exactly one file: a prompt at
`.claude/agents/{phase}/{short-name}.md`. Declaring the step in
`pipeline.json` is necessary but not sufficient — the orchestrator will
not invoke an agent with no matching file, and CI rejects a file whose
shape does not conform.

An agent's name is `{phase}/{short-name}`, and the name is not
cosmetic: the orchestrator computes the file's path by treating the `/`
as a directory separator, so the name, the file location and the
`pipeline.json` `agent` field are three spellings of one fact.

| Per-ticket | Continuous | On-demand |
|---|---|---|
| `01_product_docs` | `05_continuous` | `00_ondemand` |
| `02_design` | | |
| `03_execute` | | |
| `04_evaluate` | | |

The phase directory uses `NN_snake_case` so it matches the phase enum
in `pipeline.json` and sorts in lifecycle order; the short-name uses
`kebab-case` because it appears in GitHub labels, audit-log entries and
status markers, where hyphens are the standard separator. `_templates/`
holds copy-paste starting points and is never referenced in
`pipeline.json`; `00_ondemand/` holds human-triggered agents that sit
outside the per-ticket and continuous phases. A phase change is a
rename: a new `pipeline.json` entry replaces the old one, and closed
work keeps the old name in its audit trail.

The file opens with a YAML block CI validates:

| Field | Type | Constraints |
|---|---|---|
| `name` | string | `{phase}/{short-name}`; matches the file's path under `.claude/agents/`; matches `pipeline.json`'s `agent` field |
| `description` | string | One paragraph, plain language, states what the agent does and when it runs |

That is the whole of it. What the step may do and which model it runs
on are not frontmatter fields — both are declared in `pipeline.json`
alone (`extra_allowedTools`; the model named on the step's own entry)
and nowhere else, including here.

`extra_allowedTools` names commands from a fixed vocabulary:

| Tool | What it does |
|---|---|
| `Bash` | Runs shell commands |
| `Read` | Reads files |
| `Glob` | Pattern-based file lookup |
| `Grep` | Content search |
| `Edit` | In-place file edits |
| `Write` | Creates files |
| `WebFetch` | Fetches URLs — forbidden by default |
| `WebSearch` | Web search — forbidden by default |

The rule for granting them is the smallest set that lets the step do
its job: `Edit` and `Write` go to a step that writes files, not to a
reviewer that only reads. `WebFetch` and `WebSearch` are forbidden by
default because fetched content can carry text that steers the agent
(prompt injection), and issue or PR content can be encoded into an
outbound URL (data exfiltration). A step that genuinely needs external
content requests it through a controlled endpoint, as a documented
exception.

The body is seven required sections, in order:

| # | Section | Purpose |
|---|---|---|
| 1 | Role statement | What the agent owns, in plain English |
| 2 | Opening announcement | Posts the start `announcement` comment before any work begins |
| 3 | Read-input steps | Gathers context from the work item, comments and files — fresh every run, never assumed from a prior one |
| 4 | Work steps | The agent's actual job, one step per logical action |
| 5 | Closing announcement | Posts the end `announcement` comment naming what was produced |
| 6 | Terminal status step | Returns exactly one outcome, as the step contract requires |
| 7 | Behaviour rules | A short, specific, testable list of hard constraints |

A prompt file does not restate the shared protocol every agent already
reads (the marker formats, the status contract, what a step must never
do). What belongs in a prompt is only what is specific to that agent:
its inputs, its work, its artefact, and the rules that apply to it
alone.

---

## Every step, agent or script, is bound by the same contract

A step that does not meet this contract is not a different kind of
step — it is a defect. Most of it exists because an agent is not
deterministic, and a script meets those clauses by construction: it
cannot replay a previous answer or improvise past a refusal. The clauses
still apply to it — a script must return one status, keep its files
where they belong, and report honestly when it did nothing.

### What the orchestrator provides

| Provided | Guarantee |
|---|---|
| One work item | Exactly one issue or PR. The agent never chooses its own subject |
| Its allowed commands | Everything the step may do, complete and enforced. An action outside the set is refused. Where the environment refuses something the set permits, the step is told before it starts |
| A scratch directory | An existing, writable path for working files, prepared before the agent starts and removed after |
| Two budgets | A bounded number of turns and a bounded wall-clock time, each known to be enough for the work the step declares |
| Its instructions | A prompt whose every instruction is executable under the commands allowed |
| A model | Which model this step runs on, chosen when the step was declared, never chosen by the step itself |

The model is the smallest one that does the job, chosen deliberately: a
more expensive model than the step needs wastes budget; a cheaper one
produces an artefact that fails review and gets re-run anyway, which
costs more than the model it saved. Sonnet is the default.

### What a step must return

A step returns a value the way any process returns a value: it writes
one result to a path the orchestrator gave it, and the orchestrator
reads it. It does not announce its outcome in prose that something else
has to parse back out.

| Returned | Requirement |
|---|---|
| An outcome | Exactly one, from the set below. Never absent, never two, never invented |
| A summary of what it did | Its own account, in plain words, including when it did nothing |
| What it expected to change | The effect the step believes it had, so the orchestrator can compare it against what actually changed (MI-6) |
| What it did not do | Present and empty when the step finished everything |
| Its output | Whatever the step produces — a review, a classification, a plan. Returned, not posted |
| Its files, in the repository or scratch | Real work in the tree, working files in scratch. Nothing anywhere else |
| Label changes it's requesting, if any | Which labels to add or remove, and on which issue — defaults to the item itself when the issue is omitted. Never applied directly; the orchestrator checks each request against the step's declared `allowed_labels` and applies only what clears, silently dropping the rest |

No result is a failure. A step that returns nothing has not returned a
value, and nothing is inferred from a clean exit. The orchestrator
writes the summary and the output to the issue as structured comments;
the step does not.

The same rule covers changing what is already there, not only adding a
comment. `prd-writer` rewriting an issue body into a PRD and `coder`
ticking off one entry in a todos-block subsection are the same case: the
step's job is to decide what the new content should be, not to apply
it. It returns that content as its output, and the orchestrator writes
it — a full-body replace for a rewrite, a section-scoped patch for a
partial update. Reading the current body, applying the change, and
retrying if another write landed first is post-action plumbing, the
same class of work as staging and pushing a commit.

### What lands on the issue

"Structured comment" is a specific thing, not a style. Every comment the
system writes opens with a marker on its own line, and the
machine-readable content follows in a fenced block.

| Marker | What it carries |
|---|---|
| `announcement` | A step started, or finished, and what it did |
| `artefact` | Something produced for a person to read — a review, a PRD, a plan |
| `session` | Which run this was, for the pair of work item and step |
| `claim` | A step taking the mutex on this item, so a concurrent runner can see it |
| `snapshot` | Human-authored content preserved verbatim before a step rewrote it |

Every marker carries the acting step's name, since every step posts
under the same account — the marker is the only place a step's identity
appears in the timeline. `snapshot` is a safety property, not
bookkeeping: some steps rewrite content a person wrote, an issue body
becoming a specification is the standard case, and the original has to
survive the rewrite so nobody loses track of what changed.

A checklist that needs to survive many runs — a build plan, acceptance
criteria, a standards remediation list, test scenarios — lives in the
body of the issue or PR it belongs to, below any human-authored prose,
under an `## AI Agile -- Tasks` heading, wrapped in an outer marker
pair: an open/close delimiter, distinct from the single-line comment
markers above, since a region inside a shared body needs its end
marked. Each subsection sits inside its own marker pair nested within
it, so the step that owns one subsection can rewrite it without
touching what another step owns. This is also how a step is re-invoked
across many runs without redoing what it already finished: `coder`
invoked a second time reads which entries are already checked, does the
rest, and ticks them off in turn.

| Subsection | On issue | On PR | Owner |
|---|---|---|---|
| Build plan | yes | yes, mirrored | the step that turns the issue into a plan (issue); `coder`, ticking an item off as its commit lands (PR) |
| Acceptance criteria | yes | no | `prd-writer` |
| Standards remediations | no | yes | the step that reviews standards compliance |
| Test scenarios | no | yes | the step that writes the scenarios (populates); the step that runs them (ticks off) |

A checkbox is `- [ ]` (pending) or `- [x]` (done). Every state change
carries a timestamp and the actor that made it. A step touches only the
subsection it owns, and never removes a checked item.

### The environment can refuse more than the pipeline denies

A step's allowed commands are what the design permits. The environment
it runs in has limits of its own — a credential can be refused write
access to somewhere the allowlist permits, and no declaration on our
side changes that. A step must learn such a limit before it starts, not
when it hits it: discovering the refusal mid-task leaves only bad
options, while knowing in advance lets the step produce the change
somewhere the limit does not apply and say plainly that a person must
carry it the last step.

### A step returns exactly one of five outcomes

| Outcome | Set by | Means |
|---|---|---|
| `complete` | the step | It did the whole thing |
| `review` | the step | It did its work, and names what a person must act on before the next step |
| `blocked` | the step | It cannot proceed, and says what it needs |
| `failed` | the orchestrator | The step broke: it crashed, returned nothing, or returned something malformed |
| `exhausted` | the orchestrator | The step ran out of one of its budgets before returning. The record says which |

`review` carries the same obligation `blocked` does: it names what a
person must act on, the same way `blocked` names what would unblock it.
A step with no declared gate has no legitimate use of `review`. A step
never sets the last two itself — one that broke is in no position to
report it, and one that hit the turn wall never got to write anything.

`exhausted` is separate from `failed` because they ask for different
things: a failure means read the logs and fix something; exhaustion
means a budget does not fit the step, so raise it or make the step
smaller. Two walls exist because they fail separately — a step can burn
its turns in a minute, or spend an hour inside a single one — but one
outcome covers both, and the record names the wall that was hit. The
orchestrator retries `failed` and never retries `exhausted`, because the
budget itself does not change between runs: an identical retry against
an identical wall is waste.

Not every invocation reaches an outcome. Sometimes an upstream limit is
hit before the work could begin, and the step never got a fair run. A
withdrawn invocation produces no outcome: the step returns to the state
it was in before, its lock is released, and a later tick invokes it
again. Recording it as `failed` would be a lie about a run that never
happened. The attempt is still recorded — time passed and budget may
have been spent — so a person reading the trail finds evidence, not
silence.

Three more states exist because a person put them there directly, not
because a run produced them:

| Status | Set by | Means |
|---|---|---|
| `requested` | a person | Run this step on this item now, whatever its normal trigger would say |
| `approved` | a person | The gate is crossed. This is the record of a human decision (MI-7) |
| `skipped` | a person | This step does not apply to this item, and I am accountable for that |

`skipped` is terminal and counts as `complete` when the orchestrator
resolves what may run next, releasing everything downstream without
pretending work was done.

Together with `:wip`, these are the nine states a step can be in: five
are the machine's account of a run, three are a person's instruction to
the machine, and `:wip` is the mutex, present only while a step is
actually running.

Two of the four return-obligations below are enforced structurally —
`exhausted` exists as its own outcome, and the result format requires
what was left undone to be stated. The other two are caught only by
observation: MI-6 compares a step's declared effect against what
actually changed, and a step that improvised past a refusal, or
replayed a stale answer, is caught there, not by any format. No return
format can stop a step reporting success after improvising — a step
that hits the turn wall never writes a result at all, so "what it did
not do" only ever captures work a step deliberately left; being cut off
mid-task is caught by `exhausted` and the diff.

### What a step must never do

- **Write to the issue or PR.** No comments, no edits, no labels. A
  step returns what it produced and the orchestrator records it.
- **Decide what runs next.** Routing belongs to the orchestrator.
- **Apply its own lifecycle labels.** `:wip`, `:complete`, `:review`,
  `:blocked`, `:failed` and `:exhausted` are the orchestrator's record
  of the step, not the step's own claim.
- **Approve a gate.** Agents draft, humans decide (P-10). No
  exceptions, in either mode.
- **Act outside its allowed commands**, or route around a refusal.
- **Request a label outside its declared `allowed_labels`.** The
  orchestrator checks every requested add/remove against it and applies
  only what clears.
- **Rewrite or delete history.** No step's allowed commands may include
  `git reset`, `git push --force`, `git branch -D`, or any other command
  that rewrites or deletes history. These are operator-only actions
  taken outside the pipeline.
- **Depend on state from outside its own (object, agent) session.**
  Sessions never cross-pollinate (P-7). A re-invocation of the same
  agent on the same object resumes its own prior conversation, but that
  memory is never a substitute for the work item and git as the source
  of truth.

### What a step must do when it cannot comply

- **Blocked means say so, and say what would unblock it.** A step that
  cannot perform an instruction reports that, stops, and states what it
  needs, rather than substituting a different approach and reporting
  success. No spawned step can ask a question and wait for an answer, so
  the halt is the question — a person answers by fixing the cause and
  clearing the label.
- **A re-run does the work again.** Re-invoking an agent performs the
  work afresh. Returning a previous run's result is a failure, however
  plausible the answer. "Afresh" means the effect, not the record: a
  re-run must not open a second PR, create a second branch, or
  double-apply a label, but its artefact comment is a new one, headed
  `(Re-run)`, never an edit to the previous comment in place.
- **Out of budget is its own outcome.** Exhausting the turn budget is
  reported as exhausting the turn budget, never as the work failing.
- **Partial work is declared.** An agent that completed some of its
  task says which part. Silence is read as completion.

---

## The promises

Eleven promises in two families. **AS — architectural separation**:
where a fact, or a piece of work, is allowed to live. Three promises
about structure. **MI — mode invariant**: what must hold identically
however the work was started. Eight promises, each with a both-modes
clause.

Each promise states what it means, exactly what is claimed, and how it
is tested.

---

### AS-1 -- One file tells you what the pipeline does

> **You can read one file and know what will happen: which steps run, in
> what order, what has to finish first, what each step is allowed to
> touch, and what each is supposed to change. Nothing behaves in a way
> that file does not describe.**

`pipeline.json` is the authoritative definition of seven concerns, and
nothing else defines any of them:

| Concern | Declared as | What it covers |
|---|---|---|
| Process | step entries | Which steps exist, what each one is — including which model an agent step runs on — and which phase it belongs to |
| Sequence | `trigger` | What triggers a step and what it emits |
| Dependencies | `dependencies` | What must have completed before a step is eligible |
| Entitled activities | `defaults.extra_allowedTools`, `extra_allowedTools`, `allowed_labels` | Everything a step may do, globally and per step, plus lifecycle actions, post-steps, and which labels it may ask the orchestrator to add or remove |
| Expected effect | `expected_effect` | What the step is supposed to change — commits, files, labels, comments — or nothing, declared explicitly |
| Flows | flow entries | Which kinds of work exist, what each applies to, what starts it, and what its branches and pull requests are called |
| Budgets | `max_turns` and `max_wall_seconds`, declared once globally and overridable per step; a per-tick cap on work started, global only | What may be consumed: how much a step may attempt, how long it may hold the pipeline, and how much work a single tick takes on |

"In what order" in the headline promise means step sequence within a
flow — Sequence and Dependencies above — not which of several eligible
work items the orchestrator picks up first. That is a sibling concern,
governed by the same rule this promise rests on (P-2: one
machine-readable source per concern) but declared in its own file
rather than folded into `pipeline.json` (see [Eligibility and order
decide which item runs
next](#eligibility-and-order-decide-which-item-runs-next)).

The exact shape of each concern, and which are required, is a JSON
Schema: [`schema/pipeline.schema.json`](schema/pipeline.schema.json).
The written reference
([`generated/pipeline-schema-reference.md`](generated/pipeline-schema-reference.md))
is generated from it, never restated by hand, so the two cannot drift
apart. JSON is the format because it has a published schema language
with broad tooling and is what the orchestrator reads directly, with no
translation step; its verbosity is a low cost since the file is
generated-from for human reading, never hand-read raw. A helper script
maintains `pipeline.json` directly — adding a step or changing a
setting goes through it, validating against the schema as it writes,
never a hand-edit.

This is P-2 — one machine-readable source per concern, human views
generated — applied to the pipeline itself. It matters most for allowed
commands: a permission defined in two places is a security property
that holds in one reading and not the other.

A work item's `type:` and `size:` labels do not change what a step
does — the same `coder` runs the same way regardless of either. What
they change is which flow a work item enters and which steps within
that flow are eligible, declared as a `type` and/or `labels`
restriction on a flow's or a step's own trigger. A flow's trigger
restricts which items enter it (`type` for the type dimension
specifically, since a work item carries exactly one; `labels`, a
general AND-combination, for everything else); a step's trigger
restricts which of a flow's items make it eligible the same way.
`type: enhancement` and `size: M` together is what a step's trigger
checks to run only on a medium enhancement — the same `labels` array
with two entries, not a special case. Selection is positive: a trigger
states what it matches, so keeping `spike` out of the default flow
means the default flow's `type` list omits it, not a rule kept in sync
elsewhere. `priority:` and `blocks:`/`blockedby:` are deliberately never
a selection criterion, at either level — they answer a different
question (see [Eligibility and order decide which item runs
next](#eligibility-and-order-decide-which-item-runs-next)).

A repository may replace the shipped pipeline definition with one of
its own, in full — a complete replacement validating against the
identical schema, not a set of changes layered over the shipped one.
There is no partial override and nothing to merge: presence means the
repository's file decides everything, absence means the shipped default
decides everything. The local file lives at `pipeline/pipeline.json`,
mirroring the path it overrides; most repositories will not have one,
and onboarding creates no copy. Where it does exist it is never
overwritten by a sync. A repository that goes local stops tracking the
shipped default entirely, the same trade a fork makes.

**Precisely.** Process, sequence, dependencies, entitled activities,
expected effect, flows and budgets are defined in the pipeline
definition and nowhere else — no constant in the orchestrator, no agent
frontmatter field, no settings file. No name is computed in code: a
branch or pull-request name built inside the orchestrator is a
definition living outside the file that should hold it.

**Test.** The resolved command set for every step is derivable from
`pipeline.json` alone; the same for triggers, dependencies, and
expected effect. Flows and budgets are tested the same way: a work item
entering a flow whose trigger it does not match, or a step running
under an allowance the file does not declare, is a failure — the same
class as a label the orchestrator applies on a step's request that its
`allowed_labels` does not cover. Both the shipped `pipeline.json` and a
repository's own validate against `schema/pipeline.schema.json`; a
definition the schema rejects is a file that does not parse, not a test
failure to discover later.

The orchestrator always runs its own code, `pipeline.json` and the
agent prompts from `main`, never from the ref a triggering event points
at — otherwise a PR editing `pipeline.json` could alter the run
reviewing it. The PR's own content is still reviewed, over the API, not
by checking out its ref.

---

### AS-2 -- The orchestrator only coordinates

> **Changing how the process works means changing configuration and
> scripts, not the orchestrator. Nothing that produces or changes an
> artefact lives inside it.**

The orchestrator's job is to read the state, select the one step whose
conditions are met, run it, and record the outcome. Every other kind of
work — writing a file, committing, cleaning up, posting a record,
computing a number — belongs in a step, a pre-action or a post-action,
all of which are scripts or agents. This is what keeps the process
malleable: when value-add work accumulates inside the coordinator,
every change to it risks breaking work unrelated to that change.

**Precisely.** The orchestrator performs only: reading state, selecting
the next step, claiming and releasing the mutex, invoking the step, and
recording the outcome as a label and an audit entry. Everything else is
a script or an agent named in `pipeline.json`.

**Test.** Adding a step, removing a step, reordering steps, or changing
what a step may do requires no change to `pipeline_orchestrator.py`.

---

### AS-3 -- A command names something; it does not do something

> **Every `/maos-*` command is a thin wrapper. It says what to run and
> passes along what you typed. Nothing else.**

A slash command is an entry point, not a program. It names a step, a
script or an agent, and hands over the arguments. A command describing
a procedure — first do this, then check that — is logic that
`pipeline.json` does not describe and no script contains: it cannot be
tested, cannot be reused by the headless path, and drifts silently,
since nothing reads a command file except a person typing it.

**Precisely.** Every command either is generated from `pipeline.json`,
or names a single script or agent and passes its arguments through. No
command contains conditional logic, a loop, or a sequence of steps.

**Test.** Every command file resolves to a generated wrapper or a
single named target. A command containing a numbered procedure, a
conditional, or a retry loop is a test failure.

---

### MI-1 -- An issue means the same thing to everyone

> **The labels on an issue tell you where the work has got to, and they
> mean the same thing whether a person or the headless runner put them
> there.**

Labels are the only state, so their meaning must not depend on their
origin — otherwise the same label on two issues means two different
things according to history nobody can see.

**Precisely.** No label is specific to one mode, and no step interprets
a label differently depending on which actor applied it.

**Test.** Every label in `statuses.json` has exactly one documented
meaning, and no step's behaviour branches on who applied it.

---

### MI-2 -- The same situation always produces the same next step

> **Two people looking at the same issue get the same answer about what
> happens next. So does the headless runner.**

This is what makes the pipeline explainable: two implementations of
routing drift invisibly until they disagree on a specific issue.

**Precisely.** Given identical state, both modes select the same next
step. Routing is computed in exactly one place. A driver may read the
pipeline definition to explain what will happen, never to decide it.

**Test.** Run the resolver and the real dispatch path over the same
issue state and assert identical selection, for every step.

---

### MI-3 -- An agent can only ever do what you allowed

> **The limits on what an agent can touch are the same limits however
> the work was started. There is no looser path.**

A re-implementation of enforcement must be kept in step with the
original forever, and it will not be — every divergence is a security
property that holds in one mode and silently not in the other.

**Precisely.** Whatever enforces a step's allowed commands — and
whatever checks a step's requested label changes against its
`allowed_labels` — is the same mechanism in both modes, not an
equivalent one.

**Test.** Exactly one component decides whether an action is
permitted, and both modes route through it. A second implementation is
a test failure.

AS-1 and MI-3 are two halves of one property: AS-1 says permissions are
written down in one place, MI-3 says they are enforced by one mechanism.

---

### MI-4 -- Nothing gets stuck with no way out

> **Every state the work can reach has a way forward that you can
> actually perform — in a chat session or on the runner.**

A halt with no exit is not a pause, it is a loss: recovering means
editing state by hand outside the system, unseen and unrecorded.

**Precisely.** Any state a run can enter has a documented exit
performable in both modes. A state reachable in one mode and escapable
only in the other is a defect.

Clearing a halt is a claim, not a click: removing the `blocked` or
`failed` label means *I have dealt with the cause*, and the next tick
takes that literally. A label cleared just to make a red thing go away
sends the step straight back into whatever stopped it, and the trail
records a guess as a fix. So the orchestrator, not the step, posts the
recovery guidance: on every `review`, `blocked`, or `failed`
transition, its own closing `announcement` names what the halt means
and what clears it, independent of how well the step's own report was
worded.

A step can also just stop existing — the machine running it is lost,
the process is killed outright. Nothing is returned, and the `:wip` it
held stays where it is, blocking the pipeline. Catching a termination
signal is not enough: a process killed outright runs no handler, and a
lost machine cannot clear anything. So the reclaim is something a
*later* tick does, by looking at the label rather than the run: a
`:wip` older than that step's wall-clock budget cannot still be
legitimately running, so the orchestrator takes the lock back, records
the step as `failed`, and says why. A reclaim counts as an attempt, the
same as a crash, and draws from the one retry budget — a step that
hangs the same way every time still exhausts its retries and lands on a
`failed` a person must clear, rather than reclaiming and hanging
indefinitely.

**Test.** Every status in `statuses.json` where `blocks_pipeline` is
true names a `cleared_by`, that exit is reachable from the step's own
configuration, and it is performable in both modes.

---

### MI-5 -- The result does not depend on who was watching

> **A step does the same thing whether you watched it or not. The trail
> on the issue records the work, not who was present.**

If effects vary by mode, the artefact trail stops being evidence, since
two issues cannot be compared if they were produced under different
conditions.

**Precisely.** A step's pre-actions, activity and post-actions produce
the same effects in both modes, in the same order. A mode may differ in
who triggers a step, never in what the step does.

**Test.** Run the same step in both modes against equivalent state and
diff the resulting issue timeline, ignoring timestamps and actor.

---

### MI-6 -- You can believe what the system tells you

> **Every step says what it did, including when it did nothing — and
> the orchestrator separately records what actually changed. Where the
> two disagree, you are told.**

Nobody watches a headless run: you read the issue afterwards and
believe it. A step that reports success while doing nothing makes
everything after it meaningless. Asking a step to announce its own
silence is not enough, since a step that does nothing usually does not
know it did nothing — so the system records two things and compares
them.

| | What it is | Who produces it |
|---|---|---|
| The account | What the step says it did, in its own words | The step |
| The evidence | What actually changed — commits, files, labels, comments | The orchestrator, by observation |

Each step also declares, as `expected_effect`, what it is supposed to
change — `coder` produces commits, `pr-reviewer` produces none and says
so. A step that should change something and did not is as wrong as one
that changed something it had no business touching.

**Precisely.** Every step returns a summary of what it did, and doing
nothing is a result reported as one. The orchestrator observes the
actual change independently, compares it against the declared expected
effect, and records both. A disagreement is surfaced, not buried.

**Test.** Every step returns a summary on the path where it acted and
the path where it did not, and declares its expected effect. The
orchestrator records the observed change and flags any disagreement.
After a run in either mode, both branches carry one appended record per
completed step, indistinguishable in what they wrote.

The account, the evidence and the measurements are written to two
protected orphan branches — `ai-agile/log` for what happened,
`ai-agile/metrics` for what it cost — appended once per completed step
by a git push, which works identically regardless of what started the
run. Each appended entry is one JSON object:

```json
{
  "ts": "2026-05-04T14:23:11Z",
  "event": "agent.complete",
  "agent": "01_product_docs/prd-writer",
  "issue": 42,
  "status": "complete"
}
```

Required on every entry: `ts`, `event` (from the table below), `agent`
(the `pipeline.json` name, or null for a system-level event), `issue`
(the work item number, or null for a PR or global event), and `status`.
Nullable alongside them: `detail`, `session_id`, `object`
(`{"kind": "issue"|"pr", "id": number, "repo": "owner/repo"}`), `actor`
(who triggered the run — `{"kind": "orchestrator", "id":
"github-actions", "human": null}` for unattended, `{"kind":
"orchestrator", "id": <actor-id>, "human": true}` for human-initiated),
and `duration_ms`.

| Event | Emitted when |
|---|---|
| `agent.invoked` | The orchestrator launched the step |
| `agent.complete` | The step returned `complete`, or a gate promotion completed |
| `agent.review` | The step returned `review` |
| `agent.blocked` | The step returned `blocked` |
| `agent.failed` | The step crashed, timed out, or exited without a sentinel |
| `gate.approved` | A human applied the gate label; gate promotion ran |
| `lock.reclaimed` | A stale `:wip` was force-reclaimed |
| `system.emergency_stop` | The stop marker was detected — headless, the orchestrator exits without invoking anything; interactive, it is logged and the run proceeds |

---

### MI-7 -- Only a person approves

> **An approval needs a human decision, recorded the same way every
> time. The system cannot approve itself, and cannot be tricked into it
> by timing.**

**Precisely.** The decision is always a person's, in both modes. The
record is always the same gate label, readable by either. A gate is
crossed only by a person's own label (headless) or by the orchestrator
recording a confirmation the driver relayed (interactive) — never by an
agent, and never by a driver writing the label itself. An approval the
orchestrator cannot establish a person stood behind is refused.

**Test.** In headless mode, a gate label applied by any non-human actor
is rejected. In interactive mode, an approval recorded by the
orchestrator on a relayed human confirmation is honoured. No agent can
cause either. An inconclusive check refuses rather than admits.

A gate label and its promotion appear together, or not at all: a
downstream step's dependency check reads `{agent}:complete` and
`{gate}:approved` as a pair, and the orchestrator guarantees both are
present or neither is.

The obvious rule — "no bot may apply a gate label" — does not work,
because in interactive mode the chat-AI writing the label on the
person's instruction is the supported path: transcribing a decision,
not making one. Transcription and origination look identical at the
point of writing, so no amount of actor-checking separates them. The
design instead makes origination unreachable: the orchestrator is the
only component that is neither an agent nor a credential-holder, and it
knows first-hand how it was invoked. An agent's entire output surface is
one status value from a fixed set, so there is no message an agent can
send that means "approve this."

| Mode | How a gate can be crossed |
|---|---|
| Headless | Only by a label a person applied, asynchronously, from their own account. The pipeline itself can never cross a gate, because no human is present during the tick |
| Interactive | The orchestrator records the approval, having been told by the driver that the person confirmed. The driver never writes the gate label itself |

Everything the system does on GitHub acts as a dedicated identity of
its own, never a person's account or the generic identity a CI run gets
by default — the default is the trap, since it makes system actions
indistinguishable from unrelated CI. A dedicated identity buys
decidability ("a person applied this label" is a fact, not a guess),
least privilege, legibility, and isolation from a contributor's API
quota; MI-7 needs the first. Every step acts under the same identity,
which is why the marker on each comment carries the step's name.

One assumption is asserted rather than trusted: that a non-headless
invocation genuinely has a person present. There is no independent
check — it holds because the interactive path exists nowhere except
inside a chat session. If anything ever invokes the orchestrator
non-headlessly without a human, this guarantee disappears silently,
because nothing exists to catch that case.

---

### MI-8 -- Any difference is written down

> **There is a short list of things that differ between headless and
> interactive mode. Anything not on that list is a bug.**

Without an enumerated list the two modes drift apart one reasonable
accommodation at a time, until they are different products.

**Precisely.** Anything that legitimately differs is listed in
[What is allowed to differ](#what-is-allowed-to-differ) with a reason.
An unlisted difference is a defect, not a feature.

**Test.** Every mode-conditional branch in the orchestrator, the
scripts and the agent prompts maps to a listed difference.

---

## Headless and interactive

**Headless** is a continuous background process on GitHub Actions. It
starts when an issue or pull request changes, or on a timer, and nobody
is watching; approvals wait for whoever next looks at the issue. This
is the primary mode.

**Interactive** is a chat session in Claude Code. You run `/maos-run
{N}` and drive one issue forward a step at a time, watching each agent
work and answering approvals as they arrive. This is how work gets
unblocked, debugged, and pushed when someone is at the keyboard.

You must be able to start an issue in one mode, walk away, and have the
other finish it, with no difference in the result — that is what the
eleven promises above are for.

Interactive mode offers three things, and two of them run the pipeline:

| Command | What it invokes | Activity performed by | Mode |
|---|---|---|---|
| `/maos-run {N}` | The orchestrator, repeatedly — one step per invocation, each picking the next eligible step | a spawned agent or script | `headless` |
| `/maos-{agent} {N}` | The orchestrator, naming one step, which it spawns as a subprocess exactly as the headless path does | a spawned agent or script | `headless` |
| `/maos-{agent}-i {N}` | The orchestrator in resolve-only mode; you then work through the step's instructions | you and the chat-AI | `interactive` |

All three advance state, and none of them advances it by hand: the
orchestrator performs every label transition, artefact comment,
post-action and commit, in interactive mode exactly as in headless. A
driver command never applies a lifecycle label, posts an artefact, or
performs a step's work itself — hand-mirroring any of that is how a run
ends up with misplaced artefacts and orphaned branches. Two exceptions
exist, both narrow, both the driver relaying something only a person
can supply: applying the `{agent}:approved` gate label on a confirmation
you gave (MI-7), and marking a pull request ready when a restricted
session — one running under the driver's own, more narrowly scoped
login rather than the repository's service credentials — blocks the
operation the orchestrator would otherwise use.

The distinction between the two shapes is load-bearing, not cosmetic.
`/maos-{agent}` is the pipeline: same prompt, same allowed commands,
same enforcement, so what you see is what the headless runner would do.
`/maos-{agent}-i` is not the pipeline, and does not pretend to be — you
and the chat-AI work through the agent's instructions together, in your
session, with your permissions, because no agent is running; a person
is, with an assistant. It still advances the pipeline, and the record
says how: the step returns its result the way every step does, and the
orchestrator records that a person performed the activity rather than a
spawned agent. That provenance keeps an in-the-loop run legitimate
without letting it stand in for evidence of what the pipeline would do
unattended, and resolves an apparent conflict with MI-3 — enforcement
is still one mechanism, the platform's own on the spawn path, and the
in-the-loop command needs no second one because it is not an agent
invocation to enforce.

In headless mode, GitHub is the only channel — labels and comments on
the issue. In interactive mode you can also talk to the chat-AI in your
own words, and it writes the labels and comments that carry your
intent, a scribe rather than a decision-maker (MI-7). The record is
identical either way.

---

## What is allowed to differ

The complete list. Anything not here is a defect. Headless and
Interactive here mean how the tick was started — a GitHub event versus
any of the three interactive commands — never `AI_AGILE_EXECUTION_MODE`,
which answers a different question about a single activity; a driver
command spawns steps that are themselves `headless` regardless.

| Difference | Headless | Interactive | Why this is legitimate |
|---|---|---|---|
| Who starts a step | A GitHub event or a timer | A person running `/maos-run` | This is the whole point of having two modes |
| Where you watch it | Issue and pull-request activity | The same, plus live agent output | What you see is not what happened; the trail is identical |
| Which credentials are used | Repository secrets | The session's own login | The environments genuinely differ; the *authority* those credentials carry must not |
| How long an approval waits | Until someone next looks | Immediately | A person being present is the difference |
| How you address the pipeline | Labels and comments on the issue | The same, or in your own words to the chat-AI, which writes them for you | Only the channel differs; what lands on the issue is identical |
| Who writes a gate label | Only the person, from their own account | The orchestrator, on a confirmation the driver relays | The decision is the person's either way; only the evidence available to show it differs (MI-7) |
| Whether the emergency stop applies | Halts the run before any step | Logged, and the run proceeds | A person driving one issue by hand is not unattended, and stopping them too would remove the means of investigating whatever caused the stop |
| How many items advance at once | Several, where their components do not overlap — one run working through them in turn | Several, where their components do not overlap — one instance per item, each started by a person | The invariant is identical; only the shape differs |

Everything else is governed by the promises above and must be
identical. Two things are often mistaken for legitimate differences and
are not: how permissions are enforced (MI-3 — whether a mode can use the
platform's own enforcement is a consequence of how it starts agents, a
choice, not a constraint), and which errors can be recovered from (a
refused query and a refused repository are different failures, but which
one you get must never depend on how the work was started).
