# The Orchestrator Product

The single description of what the orchestrator is and what it promises.

This document describes the target design. It states what the product does,
not what the implementation currently manages -- closing that gap is tracked
as a sequenced build plan on [issue #393](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/393),
against the [`feature/393-orchestrator-target-design`](https://github.com/M-A-Operating-System/ai-coding-standards2/tree/feature/393-orchestrator-target-design)
integration branch.

---

## Vision

Software teams spend a disproportionate share of their time on the connective
tissue around code -- writing PRDs, translating them into designs, deciding
what to test, decomposing work into tasks, reviewing for standards -- work
that is repetitive, done under time pressure, and where most quality issues
originate: a missing acceptance criterion, an unrecorded architectural
decision, a forgotten test case.

AI Agile is a product development lifecycle in which specialised AI agents own
each repetitive activity, run from a single source of truth -- a GitHub issue
-- and produce a complete trail of artefacts, with humans approving at
well-defined gates rather than performing the work. The orchestrator is what
makes that lifecycle run: it is not a replacement for product or engineering
judgement, only for the repetitive work around it.

---

## Personas

Six kinds of person, and one automated role, rely on AI Agile, each meeting it
at a different point in the pipeline:

- **Stakeholder** -- opens the issue that starts a piece of work, and approves
  the PRD that comes back.
- **Engineer** -- owns the design and the code; approves the build plan before
  any of it is written.
- **Reviewer** -- approves at the gates a Stakeholder or Engineer does not:
  sizing, design, test spec, PR.
- **Standards Owner** -- owns the standards the pipeline enforces, and
  approves proposed changes to them.
- **Security Owner** -- approves any change flagged as touching a
  security-sensitive surface.
- **Data Owner** -- approves any change that includes a data migration.
- **System actor** -- the role a capability is written against when its
  primary actor is genuinely automation (a scheduled job, an audit logger),
  not a person, so automated capabilities go through the same product-led
  pipeline as everything else.

This is not just a description -- it is the closed vocabulary a PRD user story
must draw from. `prd-writer` validates every `As the {persona} ...` story
against it, the same way `coder` validates a diff against a standards
category: [`standards/personas.json`](../../../standards/personas.json) is
the machine-readable source (one file, P-2), and the System actor's
qualifying test lives there as data, not as prose duplicated in a prompt --
see [`14-standards.md`](../standards/14-standards.md#personas-not-a-category-a-closed-vocabulary).

---

## Core requirements

Read these together. They describe what the product is; [the
promises](#the-promises) state what it guarantees and how each is tested.

**Work is a GitHub issue, and the issue is the record.** You describe a piece of
work as an issue. The orchestrator walks it through the steps that turn an issue
into shipped code, and everything it does is written back to that issue. There
is no dashboard, no database, no hidden state. If you can read the issue, you
know exactly where the work has got to.

**The orchestrator is a state machine.** The labels on the issue are the state.
Steps are the transitions between states. The machine is deterministic: given
the same labels it always chooses the same next step, and that choice is
computed by code, never by a model.

**Every step has the same four parts.** A step declares the commands it is
allowed to run, the deterministic work that happens before it, the activity
itself, and the deterministic work that happens after. The activity is either an
AI agent or a script; everything around it is always scripts. So uncertainty
enters the system at exactly one place, and only in the steps that need
judgement.

**A step is told everything it needs to know.** Each step runs as a separate
process and learns its situation entirely from environment variables the
orchestrator sets: where the repository is, what it is working on, where to put
working files, and whether a human is attached to it. A step never works its own
context out, and never probes to find out.

**The orchestrator coordinates; steps do the work.** It reads the state, picks
the next step, runs it, and records what happened. Everything that produces or
changes an artefact is a step, a pre-action or a post-action. Changing the
process means changing `pipeline.json` and the scripts it names rather than the
orchestrator (AS-2), and a `/maos-*` command names what to run rather than
describing how to do it (AS-3).

**One file defines the process.** `pipeline.json` says which steps exist, what
starts each one, what must finish first, and what each is permitted to do.
Nothing behaves in a way that file does not describe (AS-1).

**Agents produce; they never decide.** An agent is a black box that receives a
work item and returns a result. It cannot choose what runs next, set its own
state, approve anything, or act outside the commands it was allowed. Its only
influence on the machine is one status value from a fixed set -- which is what
contains the fact that the same prompt can produce different work on different
runs.

**An agent that cannot comply says so.** Being blocked, running out of budget,
and finishing only part of the work are distinct outcomes, and each is reported
as itself. An agent never substitutes a different approach and reports success,
because a silent workaround is an unrecorded change to the process.

**Steps produce output; the orchestrator posts it.** Every step returns what it
produced and a summary of what it did, including when it did nothing. The
orchestrator writes those to the issue and separately records what actually
changed, so exactly one thing writes to GitHub and a disagreement between the
account and the evidence surfaces rather than hides (MI-6).

**Only a person approves.** Named gates require a human decision, recorded the
same way every time. The system cannot approve itself, and an approval check
that cannot reach a conclusion refuses rather than admits (MI-7).

**People speak to the pipeline through GitHub, or through the chat.** In
headless mode the issue is the only channel: you add labels and write comments,
and that is the whole of the interface. In interactive mode you can also talk to
the chat-AI in your own words, and it writes the labels and comments for you.
The record is identical either way -- the difference is whether you write it
yourself or dictate it.

**Nothing gets stuck.** Every state the work can reach has a way forward that
someone can actually perform. A halt is a pause, never a loss (MI-4).

**Closed is terminal.** Once an issue closes, the orchestrator drops every
event on it, permanently. There is no reopening it back into the pipeline --
a bug found later in what it shipped is a new issue, not a resumption of the
old one.

**It will not run in a repository that has not been onboarded.** The
orchestrator depends on what onboarding puts in place: the standards and agent
definitions it reads, the labels that are its state, and the project's own ADR
file. Onboarding records that it completed and the orchestrator checks that
record before doing anything else, so a repository that was never set up fails
immediately and legibly rather than part-way through its first piece of work.

**It runs two ways, and they behave identically.** Headless as a continuous
background process on GitHub Actions, or interactive inside a chat session in
Claude Code. You can start work in one, walk away, and let the other finish it.
The short list of things that legitimately differ is written down; anything else
that differs is a bug (MI-1 to MI-8).

---

## Contents

- [Vision](#vision)
- [Personas](#personas)
- [Core requirements](#core-requirements)
- [The state machine](#the-state-machine)
- [The pipeline defines flows, not a flow](#the-pipeline-defines-flows-not-a-flow)
- [How the orchestrator tells a step where it is](#how-the-orchestrator-tells-a-step-where-it-is)
- [How it uses agents](#how-it-uses-agents)
- [The agent prompt file](#the-agent-prompt-file)
- [The step contract](#the-step-contract)
- [The promises](#the-promises)
- [Headless and interactive](#headless-and-interactive)
- [What is allowed to differ](#what-is-allowed-to-differ)

---

## The state machine

The labels on a work item are the state. A step is a transition. The orchestrator
reads the labels, selects the one step whose conditions are met, runs it, and
writes the outcome back as a label.

Because state lives on the work item, there is nothing to recover and no
position that exists only in memory. Any orchestrator process reading settled
labels reaches the same conclusion.

**Settled is the load-bearing word, and this is specifically headless mode's
problem.** A headless run is started by a GitHub event, automatically. A
label write is not visible instantly, so a run's own `:wip` write can fire an
event that starts a second, automatic run inside that unsettled window, and
that second run reads stale state and reaches the same, wrong conclusion the
first one already acted on. The window is only wide enough to matter for
steps that run long, which is what makes it a sporadic, hard-to-reproduce
duplicate rather than a permanent fault -- but it is a real one, because
nothing about a webhook firing waits for a person to notice.

So headless needs one thing synchronised: **at most one headless orchestrator
run at a time**, enforced by the GitHub Actions concurrency group the
workflow runs under. Once runs are serialised this way, every run begins with
settled labels and the `:wip` check becomes a fast skip rather than a guard
against a race. That settled read is not a snapshot a run discards after
using it once, either: it keeps its own copy current for the rest of the run,
updating it the instant it writes a label itself -- the same thing that makes
the `:wip` check a fast skip rather than a round trip back to GitHub. For as
long as it is the only headless run alive, that in-memory copy is as good as
GitHub's, for every item it looks at, not only the one it is currently acting
on.

One headless run, then, works through as many eligible items as it has room
for -- bounded by the per-tick cap below and by the run's own wall-clock
ceiling -- rather than handling one and exiting. Nothing about that reopens
the race: it is still the one process, still reading its one settled copy,
for as long as it runs.

One limit is still needed, and it is not about concurrency. When a burst of work
becomes eligible at once -- a hundred issues, a backlog import -- something has
to bound how much a single pass takes on, or one run tries to do all of it. That
is a cap on how much work a run *starts*, and it belongs with the other budgets
rather than fixed in code: one number chosen once for every situation is a
number nobody can tune for the case in front of them.

### Which eligible item runs next

Two questions, not one, and both are core orchestration logistics --
part of the target design, not an implementation detail of how a tick
happens to iterate.

**Eligibility: is this item allowed to start at all.** An item halted
mid-flow -- any step of it sitting in `review` or `blocked` -- has no
eligible next step until a human clears the gate, so it drops out of
contention on its own; nothing extra checks for this. An item that
has not yet started is additionally ineligible while it carries
`blockedby: {N}` and `N` is still open -- a second, independent kind
of block, declared by a human (or on their behalf, on request) rather
than raised by a step's own outcome. `blocks:` and `blockedby:` are
ordinary labels: a human clears either one directly, the same way
clearing `review` or `blocked` already resumes a halted step, in
either mode -- there is no special interactive path, because label
removal already works identically regardless of who is watching (see
[lifecycle.md, Blocking between
issues](lifecycle.md#blocking-between-issues)).

**Order: among what's eligible, which goes first.** `priority:` orders
the rest -- `high` before `medium` before `low` before unprioritised --
and within a tier, the item raised earliest goes first (see
[lifecycle.md, Priority](lifecycle.md#priority)). Priority never
touches eligibility; an unprioritised item is still eligible, only
last in line.

**AS-1's declared-not-hidden principle applies to this the same as
everything else.** Priority tiering is already there today:
`pipeline/statuses.json`'s `priority_ordering` list is exactly this,
externalized rather than a constant in `pipeline_orchestrator.py` --
this document simply had not said so until now. Blocking eligibility
has no equivalent yet: nothing declares `blockedby:` as a condition
anywhere machine-readable; it exists only as this section's prose and
lifecycle.md's. Giving it a declared home, the way priority already
has one, is unfinished target-state work, not a decision made here.

**Interactive mode is not this problem, because it is not this shape.** A
person typing `/maos-{agent}` starts an orchestrator instance directly --
there is no webhook, no automatic respawn, and therefore no version of the
race above to serialise against. Nothing stops two people, or one person in
two sessions, from doing this at the same time; nothing should, since a
person waiting on someone else's chat session defeats the point of working
interactively. Interactive concurrency is addressed on its own terms below,
not folded into headless's guarantee.

### Working on several things at once

**From an issue's perspective, at most one issue per component is in flight
at a time -- headless and interactive combined.** Labels only ever keep two
runs off the same *item*; two issues that change the same module have nothing
else keeping them apart, and the collision surfaces as a merge conflict at
best. So the unit that has to be exclusive is not the issue, it is **the part
of the system the work touches**.

**How it works.** An issue carries a `component:` label for each part of the
system it affects, and may carry several. Before starting an item, an
orchestrator instance -- headless or interactive -- claims every component
the item names, and starts only if it can claim them **all** at once: an item
never holds part of what it needs while waiting for the rest, which is what
keeps this from deadlocking. An untagged item claims everything, so it runs
exactly as sequentially as the pipeline does today. There is no register of
valid components anywhere; the orchestrator just reads whatever `component:`
labels exist and compares them for equality, which is what keeps it
coordinating rather than needing to know about the system it is building.

**Unlike almost everything else this document promises, that correctness is
never checked against evidence (MI-6).** A mistagged item -- claiming fewer
components than it actually touches -- produces no signal until the collision
it causes is the evidence, and a near-miss name (`component:auth` vs.
`component:authentication`) reads as no overlap at all. This is a deliberate
trade, not an oversight: inspecting what an issue really touches is unreliable
enough that a visible, person-correctable label beats it, but the label is
still the whole of the guarantee.

**The same claim holds under two concurrency shapes.** Headless is one
process (the state machine above), so it answers "is this component free?"
from the settled copy it already holds. Interactive is genuinely several
processes -- each `/maos-{agent}` invocation is its own, unserialised, since
waiting on someone else's chat session would defeat the point -- so an
interactive instance reads GitHub's labels fresh for the same check. That is
the same settled-labels reasoning the `:wip` check already relies on, just
triggered by a person instead of a webhook, which makes the collision window
far narrower in practice.

**Claiming decides who may proceed together; it does not isolate them.** Two
cleared items still need separate working trees -- a shared checkout means
the second disturbs the first regardless of what either touches. The label is
the decision; the working tree is what makes the decision mean something.

### Every step has the same four parts

| Part | Declared in `pipeline.json` as | What it is | Determinism |
|---|---|---|---|
| Allowed commands | `extra_allowedTools` | Everything this activity may do. Anything else is refused | Data |
| Pre-actions | `defaults.agent_lifecycle.before` | Work performed before the activity -- checking out the branch, preparing the scratch directory | Code |
| The activity | `type` with `agent` or `script` | The work the step exists to do: an AI agent, or a script | Deterministic when a script; **not deterministic when an agent** |
| Post-actions | `post_steps`, `git_ops`, `defaults.agent_lifecycle.after` | Work performed after -- committing, pushing, labelling, posting the artefact | Code |

Three of the four parts are always code or data. The fourth is code too, unless
the step uses an agent -- so uncertainty enters the system at exactly one place,
and only for the steps that need judgement. A step whose activity is a script is
deterministic from end to end.

**Post-actions run in two different shapes, for two different jobs.**
`post_steps` is an ordered list of scripts specific to one step, firing only
when that step signals `complete` -- never on `review`, `blocked`, or
`failed` -- and a non-zero exit aborts whatever is left in the list and fails
the step. `defaults.agent_lifecycle.after` is different in kind: declared
once, it wraps every agent step regardless of outcome (`complete`, `review`,
`blocked`, a crash, or retries exhausted), and its own failure is logged and
swallowed rather than failing the run. Use `post_steps` for an action
specific to one step's success; use `agent_lifecycle` for work every agent
needs done around it, win or lose.

**Why `agent_lifecycle.before` must be idempotent.** It runs again on every
retry, including one following a kill mid-run -- and that is what makes the
lifecycle self-healing without a signal handler. A `SIGTERM` handler cannot
save it: the kill that ends a background tick is uncatchable, so a handler
never runs to clean up on the way out. Idempotent setup covers the same case
without one -- `before` removes its scratch directory before creating it,
rather than assuming it is absent, so a tick killed mid-run leaves debris
that the next run on the same session simply clears before it starts.

Commands every step needs are declared once in `defaults.extra_allowedTools`
rather than repeated on each step. A step's effective permission is exactly the
global set plus its own `extra_allowedTools`, and nothing else. Two levels, both
in `pipeline.json`, both readable in one place -- which is what keeps AS-1 true
as the pipeline grows.

Budgets follow the same shape. A number every step needs is declared once, in
`pipeline.json`'s top-level `budgets`; a step's effective budget is that number,
or its own if it declares one. Most steps never need to: the global figure is a
person's reasonable starting judgement, not a formula, and a wrong one is not
silently wrong -- it surfaces as `exhausted`, naming the wall a step hit, and
gets revised the same way any other value in this file is revised when the
evidence says so. A step declares its own only when it genuinely differs, and it
may override one wall without touching the other -- a tightly scoped step
overriding `max_turns` alone still inherits the global `max_wall_seconds`. This
is the AS-1-compliant version of what `AGENT_TIMEOUT_SECONDS` is today: not that
a shared number is wrong, but that a shared number hidden in orchestrator code,
with no way for any step to differ, is.

This is where the design contains its own uncertainty. Permission is decided
before the activity runs and cannot be widened by it. The setup and the
consequences run as pre- and post-actions on either side of the agent, on the
orchestrator's schedule rather than at the agent's request. What the agent
actually influences is the work product and one status value -- and nothing else
in the system depends on the agent having behaved reasonably.

---

## The pipeline defines flows, not a flow

The orchestrator runs work. It does not know what kinds of work exist.

A **flow** is one kind of work, declared in `pipeline.json`: what it applies to,
what starts it, which steps run in what order, and what its branches and pull
requests are called. The orchestrator knows how to run a flow; the file says
which flows there are.

That distinction is the whole of AS-2 applied to process. A system that knows
about one kind of work has that kind written into it, and every new kind of work
becomes a change to the component every other kind depends on.

### Three shapes a flow can take

These are not the flows. They are the shapes a flow can have, and all three must
be expressible without touching the orchestrator.

| Shape | Started by | Example |
|---|---|---|
| **Work that produces change** | A work item appearing, or a label on it | An issue, taken from description to shipped code |
| **Work that coordinates other work** | A work item whose children are the real work | An epic, which decomposes into issues and closes when its review step confirms the whole, not merely when the parts are closed |
| **Work with no work item behind it** | A schedule | A periodic loop over the codebase, the backlog or the record, which produces work items rather than consuming one |

The second and third both break a design built around the first, and they break
it in different ways.

### Coordinating work needs a trigger that can look outward

A flow that coordinates other work has a stage where it is waiting: the parts
are running and the parent has nothing to do until they finish.

**Waiting is not a step.** It is a later step whose conditions are not yet
met, so the orchestrator finds the item ineligible and moves on, advancing on
a tick once the condition holds. Inventing a step that polls, or that returns
"not yet", would add a sixth outcome the design does not need.

**A trigger must be able to say more than "a label on this item".** "Every
child of this item is closed" is a condition about other work items; without
it, the waiting has to be written in code instead, which is how coordination
ends up inside the orchestrator rather than in the file that is supposed to
describe it.

### A flow is not the only thing that can watch an object

Nothing requires exactly one flow per object kind. What the orchestrator
routes on is a step's own trigger and dependencies, not which flow declared
it, so a second flow may match an object kind a first already covers, as long
as their steps' conditions never make two eligible on the same item at once
-- no different from two steps in one flow, so MI-2 still holds.

That is what makes "closes when the whole is sound" real rather than a
phrase: an epic's children closing is not the soundness check, it is what
makes a review step eligible, and that step -- declared like any other, with
its own allowed commands and expected effect -- is what the epic's closing
actually depends on. What the review judges is a decision for whoever
declares that step, not fixed in advance here.

### The same capability lets a step finish its own work in pieces

An epic waits *while* its children are open. A step can use the identical
capability the other way round: stay eligible *while its own* children are
open, so finishing the item takes several invocations instead of one.

A step's turn and wall-clock budgets bound one invocation, and a
sub-issue-heavy issue can need more of either than any single invocation
should be given, even though no one sub-issue does -- without this, a step
that runs out partway through loses everything back to the last commit, which
is the very start of the issue.

The unit of work shrinks; the contract does not. `complete` still means the
step finished what it was given, because what it was given is now smaller --
no new outcome, no mid-run signal. The orchestrator commits after each
invocation exactly as it does today, so a step that later runs out on
sub-issue four leaves the first three committed rather than nothing. The step
just needs one more thing on the channel every step is already told: which
piece this invocation is for.

A flow's primary branch is created from the default branch unless the flow
says otherwise -- declared the same way the branch name itself is, a token
pattern in `naming`, never computed in code. An epic's sub-issues need this:
their branch has to be cut from the epic's own integration branch
(`feature-{parent_number}`), not `main`, or their work never lands where the
epic expects it to. If that base does not exist -- never created, or already
merged and deleted -- the flow falls back to the default branch rather than
failing over something never guaranteed to be there.

### Scheduled work: how a flow knows it is due

A scheduled flow has no work item, so it has nowhere to carry a label -- and
labels are the state. Where "this last ran on Tuesday" is kept is not kept
anywhere new: every completed step appends a timestamped entry to the log and
metrics branches, so when a flow last ran is a read of the record rather than
a second store to keep in step with it, and a flow that has never run has no
entry, which is the same answer as overdue.

The alternative -- a last-run table, or a cadence in a workflow file -- is
exactly the hidden state the label model exists to avoid, and would put part
of the process definition outside `pipeline.json`. The cadence is declared
with the flow; whether it is due is derived from what already happened.

A scheduled flow also needs a claim of its own, because the `:wip` mutex is a
label on a work item and there is no work item to label -- two runners must
not start the same sweep.

### What a scheduled step may do is declared, like any other step

A scheduled step is a step: what it may do is its allowed commands and its
expected effect, declared in `pipeline.json`, never inferred from the fact
that a schedule started it. A step that only looks is granted no commands
that write, plus whatever it needs to record what it found, and an expected
effect of no change; a step that acts is granted the commands to act -- both
permission sets, visible to anyone reading `pipeline.json`.

**The declaration is what makes it checkable.** A step declaring no change
that produces a commit disagrees with itself, and MI-6 surfaces the
disagreement, the same as for every other step.

### The orchestrator stamps what it creates

A step returns what it produced and the orchestrator writes it (the step
contract); when what it produced is a new work item, the orchestrator also
records which step and which flow produced it. That provenance is what lets a
flow find its own earlier output and raise only what is new since, rather
than repeating the same findings every run -- the same principle as the
cadence above: what already happened is readable from the record, so neither
question needs a store kept in parallel with the thing it describes.

---

## How the orchestrator tells a step where it is

A step -- agent or script, pre-action or post-action -- is a separate process
that knows nothing when it starts. Everything it needs to know about its
situation arrives as environment variables, set by the orchestrator when it
invokes the step.

This is the only channel. A step never works out its own context: it does not
search for the repository root, guess the issue number, decide where to put
working files, or probe whether a human is present. If a step needs to know
something, the orchestrator tells it. If the orchestrator does not tell it, the
step does not need it.

That rule is what makes a step testable in isolation and portable between the
two modes -- and it is why the same script behaves identically under a GitHub
Actions runner and under a chat session.

### What every step is told

| Variable | What it says |
|---|---|
| `AI_AGILE_ROOT` | Where the repository is |
| `AI_AGILE_CONTEXT` | Where the shared agent protocol is |
| `AI_AGILE_EXECUTION_MODE` | Whether *this step* has a human attached |
| `REPO` | Which GitHub repository to act on |
| `WORK_ITEM_KIND`, `WORK_ITEM_NUMBER` | What it is working on |
| `ISSUE_NUMBER` or `PR_NUMBER` | The same, in the form the step expects |
| `SUB_ITEM_NUMBER` (when applicable) | Which piece of the item this invocation covers, for a step invoked once per sub-issue rather than once for the whole item |
| `SESSION_ID`, `SESSION_SCOPE` | Which run this is, and how far it persists |
| `AI_AGILE_SCRATCH` | Where working files go |

`SESSION_ID` is derived from a token pattern declared on the step
(`session.id_pattern`) -- the available tokens, the two `title`/`url`
exclusions, and the retry-suffix behaviour are specified in
[`schema/pipeline.schema.json`](schema/pipeline.schema.json), the
authoritative source (see AS-1).

Credentials are supplied the same way and are deliberately not part of this
list: a step receives what it needs to authenticate and nothing about how that
was arranged.

### Two different questions about mode

"Headless or interactive" means two different things depending on what is being
asked about, and conflating them causes real defects.

| | Question | Who knows |
|---|---|---|
| **How the tick was started** | Did a person run this, or did GitHub Actions? | The orchestrator |
| **How this step runs** | Does *this activity* have a human attached to it? | The step, via `AI_AGILE_EXECUTION_MODE` |

They are not the same, and the second is not derived from the first. When a
person drives a run interactively, the orchestrator is interactive -- but the
agents it spawns are still subprocesses with nobody watching them. An agent must
never behave as though it can ask a question, whichever way the tick began.

So `AI_AGILE_EXECUTION_MODE` answers the second question, and it describes the
activity rather than the run: every activity the orchestrator spawns as a
subprocess is `headless`, whichever way the tick began. The only activity that
is `interactive` is one a person is working through themselves, which is not a
spawned agent at all. The first question is the orchestrator's own,
and any step whose behaviour genuinely depends on it -- how to treat an
emergency stop, whether a human can be prompted right now -- must be told
separately and explicitly.

A step that infers one from the other is wrong, and a step that probes its
environment to find out is wrong twice: it is deciding something the
orchestrator is responsible for telling it (AS-2).

---

## How it uses agents

The orchestrator is deterministic. The agents it invokes are not: they are
language models, and the same prompt over the same input can produce different
work on different runs.

The whole design follows from keeping those two things apart.

**The orchestrator decides. The agent produces.** Routing, state, sequencing and
permission are computed by code from `pipeline.json` and the labels. Nothing an
agent says influences what runs next, beyond the single terminal status it
returns from a fixed set.

**Each agent is a black box.** The orchestrator does not know how an agent
reaches its result and does not inspect its reasoning. It supplies a defined
input, waits, and reads a defined output. This is what makes agents replaceable:
a step can be re-prompted, re-modelled, or reimplemented as a script without
anything else changing.

**The non-determinism is contained at the edges.** Because an agent's only
influence on control flow is one status value, a bad run costs one step and is
visible on the issue. It cannot corrupt the state machine, skip a gate, or
change what happens next.

That containment is only real if the boundary is precise, which is what the
contract below states.

---

## The agent prompt file

An agent step's activity lives in exactly one file: a prompt at
`.claude/agents/{phase}/{short-name}.md`. Declaring the step in
`pipeline.json` is necessary but not sufficient -- the orchestrator will not
invoke an agent that has no matching file, and the file's shape is not left to
convention. It is enforced the same way `pipeline.json` is: a file that does
not conform does not merge.

### Naming carries the phase

An agent's name is `{phase}/{short-name}`, and the name is not cosmetic: the
orchestrator computes the file's path by treating the `/` as a directory
separator, so the name, the file location and the `pipeline.json` `agent`
field are three spellings of one fact, not three facts to keep in sync by
hand.

| Per-ticket | Continuous | On-demand |
|---|---|---|
| `01_product_docs` | `05_continuous` | `00_ondemand` |
| `02_design` | | |
| `03_execute` | | |
| `04_evaluate` | | |

The phase directory uses `NN_snake_case` so it matches the phase enum in
`pipeline.json` and sorts in lifecycle order in a directory listing; the
short-name uses `kebab-case` because it appears in GitHub labels, audit-log
entries and status markers, where hyphens are the standard separator. The two
conventions serve different readers and are not interchangeable. Carrying the
phase as a prefix lets a label, comment or audit-log line reveal which phase
an agent belongs to without opening `pipeline.json`, and it keeps names from
colliding across phases.

`_templates/` holds copy-paste starting points and is never itself referenced
in `pipeline.json`; `00_ondemand/` holds human-triggered agents that sit
outside the per-ticket and continuous phases, run only when a person applies
their `:requested` label or invokes them directly, and sort first by
construction. A phase change is a rename: a new `pipeline.json` entry replaces
the old one, the prior file retires, and closed work keeps the old name in its
audit trail -- an agent's history is not rewritten to match where it lives
today.

### The frontmatter is identity, not entitlement

The file opens with a YAML block, and CI validates it; frontmatter that fails
validation blocks the PR.

| Field | Type | Constraints |
|---|---|---|
| `name` | string | `{phase}/{short-name}`; matches the file's path under `.claude/agents/`; matches `pipeline.json`'s `agent` field |
| `description` | string | One paragraph, plain language, states what the agent does and when it runs |

That is the whole of it. What the step may do and which model it runs on are
not frontmatter fields -- both are entitled activities and process facts in
the sense AS-1 means, declared in `pipeline.json` alone (`extra_allowedTools`;
the model named on the step's own entry) and nowhere else, including here. A
prompt file that also carried a `tools:` or `model:` field would be a second
definition of a fact AS-1 already places in exactly one file -- the precise
failure mode AS-1 exists to rule out, not a convenience.

### The tool vocabulary a step's entitlement is drawn from

`extra_allowedTools` (AS-1) names commands from a fixed vocabulary:

| Tool | What it does |
|---|---|
| `Bash` | Runs shell commands |
| `Read` | Reads files |
| `Glob` | Pattern-based file lookup |
| `Grep` | Content search |
| `Edit` | In-place file edits |
| `Write` | Creates files |
| `WebFetch` | Fetches URLs -- forbidden by default |
| `WebSearch` | Web search -- forbidden by default |

The rule for granting them is the smallest set that lets the step do its job,
not the largest one that might someday be convenient: `Edit` and `Write` go to
a step that writes files, not to a reviewer that only reads. `WebFetch` and
`WebSearch` are forbidden by default for two reasons that both point the same
way -- fetched content can carry text that steers the agent (prompt
injection), and issue or PR content can be encoded into an outbound URL (data
exfiltration). A step that genuinely needs external content requests it
through a controlled endpoint, and the grant is a documented exception, not a
quiet default.

### The body is seven required sections, in order

| # | Section | Purpose |
|---|---|---|
| 1 | Role statement | What the agent owns, in plain English |
| 2 | Opening announcement | Posts the start `announcement` comment before any work begins |
| 3 | Read-input steps | Gathers context from the work item, comments and files -- fresh every run, never assumed from a prior one |
| 4 | Work steps | The agent's actual job, one step per logical action |
| 5 | Closing announcement | Posts the end `announcement` comment naming what was produced |
| 6 | Terminal status step | Returns exactly one outcome, as the step contract requires |
| 7 | Behaviour rules | A short, specific, testable list of hard constraints -- the last line of defence against the agent doing something the design did not intend |

A prompt file does not restate the shared protocol every agent already reads
before it starts (the marker formats, the status contract, what a step must
never do) -- repeating it in each prompt is exactly the kind of second
definition P-2 exists to prevent, and it drifts the moment one copy is edited
and the others are not. What belongs in a prompt is only what is specific to
that agent: its inputs, its work, its artefact, and the rules that apply to
it alone.

---

## The step contract

Binds every step, in both modes, whether its activity is an agent or a script. A
step that does not meet this is not a different kind of step -- it is a defect.

Most of the contract exists because an agent is not deterministic, and a script
meets those clauses by construction: a script cannot replay a previous answer or
improvise past a refusal. But the clauses still apply to it. What a script must
do deliberately is return one status, keep its files where they belong, and
report honestly when it did nothing -- which is exactly where
`commit-agent-work.sh` and `merge-docs-pr.sh` have failed.

### What the orchestrator provides

| Provided | Guarantee |
|---|---|
| **One work item** | Exactly one issue or PR. The agent never chooses its own subject |
| **Its allowed commands** | Everything the step may do, complete and enforced. An action outside the set is refused, not merely discouraged. Where the environment refuses something the set permits, the step is told before it starts, not when it tries |
| **A scratch directory** | An existing, writable path for working files, prepared before the agent starts and removed after |
| **Two budgets** | A bounded number of turns and a bounded wall-clock time -- the pipeline-wide default, or this step's own override where it genuinely differs -- each known to be enough for the work the step declares |
| **Its instructions** | A prompt whose every instruction is executable under the commands allowed |
| **A model** | Which model this step runs on, chosen when the step was declared. A step does not choose its own model, any more than it chooses its own permissions |

**The smallest model that does the job, chosen deliberately.** A more
expensive model than the step needs wastes budget without improving the
result; a cheaper one than the step needs produces an artefact that fails
review and gets re-run anyway, which costs more than the model it saved.
Sonnet is the default; stepping up or down from it is a decision made once,
when the step is declared, for that step specifically -- not a blanket
setting and not something the step revisits at runtime.

### What a step must return

A step returns a value, the way any process returns a value: it writes one
result to a path the orchestrator gave it, and the orchestrator reads it. It
does not announce its outcome in prose that something else has to parse back
out.

That matters because the outcome has to carry more than a single word. A step
must be able to say it finished, and also what it left undone -- and no word
from a fixed set can say the second thing.

| Returned | Requirement |
|---|---|
| **An outcome** | Exactly one, from the set below. Never absent, never two, never invented |
| **A summary of what it did** | Its own account, in plain words, including when it did nothing |
| **What it expected to change** | The effect the step believes it had, so the orchestrator can compare it against what actually changed (MI-6) |
| **What it did not do** | Present and empty when the step finished everything. "I finished" is an assertion the step makes, never a silence the orchestrator interprets |
| **Its output** | Whatever the step produces -- a review, a classification, a plan. Returned, not posted |
| **Its files, in the repository or scratch** | Real work in the tree, working files in scratch. Nothing anywhere else |

**No result is a failure.** A step that returns nothing has not returned a
value, and that is all it means. Nothing is inferred from a clean exit.

The orchestrator writes the summary and the output to the issue as structured
comments. The step does not.

**The same rule covers changing what is already there, not only adding a
comment.** `prd-writer` rewriting an issue body into a PRD and `coder` ticking
off one entry in a todos-block subsection are the same case: the step's job is
to decide what the new content should be, not to apply it. It returns that
content as its output, the same as any other result, and the orchestrator is
what writes it to GitHub -- a full-body replace for a rewrite, a
section-scoped patch for a partial update. Reading the current body, applying
the change, and retrying if another write landed first is concurrency
handling, and concurrency handling is post-action plumbing: the same class of
work as staging and pushing a commit after `git_ops.commit_after`, not
something a step's own code performs. A step that called the GitHub API to
apply its own edit would be a step writing to the issue, which the prior
section already forbids -- this is not a special case of that rule, it is the
same rule.

### What lands on the issue

"Structured comment" is a specific thing, not a style. Every comment the system
writes opens with a marker on its own line, and the machine-readable content
follows in a fenced block. Prose may sit alongside it for a human to read; where
the two disagree, the structured content is what counts.

| Marker | What it carries |
|---|---|
| `announcement` | A step started, or finished, and what it did |
| `artefact` | Something produced for a person to read -- a review, a PRD, a plan |
| `session` | Which run this was, for the pair of work item and step |
| `claim` | A step taking the mutex on this item, so a concurrent runner can see it |
| `snapshot` | Human-authored content preserved verbatim before a step rewrote it |

Every marker carries the acting step's name. This matters because every step
posts under the same account, so the marker is the only place an individual
step's identity appears in the timeline -- a person can see which step said
what by reading one line per comment, and tooling can select every artefact from
one step with a regex rather than parsing bodies.

**`snapshot` is a safety property, not bookkeeping.** Some steps rewrite content
a person wrote -- an issue body becoming a specification is the standard case.
Agents draft and humans decide (P-10), so the original has to survive the
rewrite: without it, an agent's rewrite silently replaces what a person asked
for, and nobody can tell what changed.

### Todo lists in issue and PR bodies

Some work needs a list that survives many runs, not one comment's worth of
state -- a build plan, acceptance criteria, a standards remediation list, test
scenarios. That list lives in the body of the issue or PR it belongs to, below
any human-authored prose, under an `## AI Agile -- Tasks` heading, wrapped in
an outer marker pair. Each subsection sits inside its own marker pair nested
within it, so the step that owns one subsection can rewrite it without
touching what another step owns.

**This is also how a step is re-invoked across many runs without redoing what
it already finished.** "A re-run does the work again" (below) means the
*effect*, not every item in it: `coder` invoked a second time for the same
issue reads which entries are already checked, does the ones that are not,
and ticks them off in turn -- the list is what makes "what remains" a fact the
step reads rather than a state it has to reconstruct or re-derive each time.

| Subsection | On issue | On PR | Owner |
|---|---|---|---|
| Build plan | yes | yes, mirrored | the step that turns the issue into a plan (issue); `coder`, ticking an item off as its commit lands (PR) |
| Acceptance criteria | yes | no | `prd-writer` |
| Standards remediations | no | yes | the step that reviews standards compliance |
| Test scenarios | no | yes | the step that writes the scenarios (populates); the step that runs them (ticks off) |

A checkbox is `- [ ]` (pending) or `- [x]` (done). Every state change carries a
timestamp and the actor that made it -- raised, and done, blocked, or skipped
the same way -- so the list is a record of who did what and when, not only
what is true now. An actor is a step, a person, or the orchestrator itself.

A step touches only the subsection it owns, and never removes a checked
item -- the item is the record that the work happened. Writing one is the
same case the previous section already states: the step returns the
subsection's new content as its output, and the orchestrator applies it as a
section-scoped patch to the body.

### Some limits are not ours

A step's allowed commands are what the design permits. The environment it runs
in has limits of its own, and they do not always agree: a credential can be
refused write access to somewhere the allowlist happily allows, and no
declaration on our side changes that.

**A step must learn such a limit before it starts, not when it hits it.** A step
that discovers the refusal at the moment it tries has already done the work, and
its options at that point are all bad -- fail with the work finished, or find
another way, which is the improvisation the contract forbids. Told in advance,
it can do the thing that is actually useful: produce the change somewhere the
limit does not apply, and say plainly that a person must carry it the last step.

This is a small class, but it has to be named. Otherwise each such limit is
rediscovered as a defect, then written into one prompt as a warning -- which
holds only for the step whose author knew, and only for as long as nobody edits
the prompt.

### The outcomes

Five, and which of them a step may choose is itself part of the boundary.

| Outcome | Set by | Means |
|---|---|---|
| `complete` | the step | It did the whole thing |
| `review` | the step | It did its work, and names what a person must act on before the next step |
| `blocked` | the step | It cannot proceed, and says what it needs |
| `failed` | the orchestrator | The step broke: it crashed, returned nothing, or returned something malformed |
| `exhausted` | the orchestrator | The step ran out of one of its budgets before returning. The record says which |

**`review` carries the same obligation `blocked` does.** Doing the work is not
the whole of what a step returns when it emits `review` -- it also names what a
person must act on, the same way `blocked` names what would unblock it. A step
with no declared gate has nothing legitimate to name, so it has no legitimate
use of `review` at all: MI-4's rule that every halt has a documented exit
applies to `review` exactly as it applies to `blocked`.

A step never sets the last two, because a step that broke is in no position to
report it, and one that hit the turn wall never got to write anything at all.

`exhausted` is separate from `failed` because the two ask for different things
from a person. A failure means read the logs and fix something. Exhaustion means
a budget does not fit the step: raise it, or make the step smaller. Collapsing
them makes budget calibration permanently invisible.

There are two walls and a step can hit either. Turns bound how much work it may
attempt; wall-clock time bounds how long it may hold the step open, which is
what stops a stalled run occupying the pipeline indefinitely. They are separate
because they fail separately -- a step can burn its turns in a minute, or spend
an hour inside a single one -- but the remedy has the same shape either way, so
one outcome covers both and the record names the wall that was hit.

It also settles what a retry means. **The orchestrator retries `failed` and
never retries `exhausted`** -- not because a retry would behave identically
(an agent is not deterministic; it might finish in fewer turns next time), but
because the budget itself does not change between runs. If a step genuinely
needs more turns or wall-clock time than it was given, an identical retry
against an identical wall is waste that costs a full budget to learn nothing
new: the fix is raising the budget or shrinking the step, never another
attempt at the same one.

### An invocation can be withdrawn

Not every invocation reaches an outcome. Sometimes a step is started and the
system takes it back: an upstream limit is hit before the work could begin, and
the step never got a fair run.

**A withdrawn invocation produces no outcome, deliberately.** The step returns to
exactly the state it was in before, its lock is released, and a later tick
invokes it again. Recording it as `failed` would be a lie about a run that never
happened -- and worse, an expensive one, since `failed` needs a person to clear
it, so someone would be asked to intervene on a step that was never given a
chance to work.

This is not a sixth outcome. It is the absence of one, and the difference
matters: an outcome says what a run did, and there was no run to describe.

**The attempt is still recorded.** Time passed and budget may have been spent,
so the record shows that the step was started and withdrawn, and why. Otherwise
attempts vanish -- and a person reading the trail to work out why an issue sat
still for an hour would find nothing at all, which is exactly the silence MI-6
exists to prevent.

### The three a person sets

An outcome is what a *run* produced. Three more states exist because a person
put them there, and they are not outcomes of anything:

| Status | Set by | Means |
|---|---|---|
| `requested` | a person | Run this step on this item now, whatever its normal trigger would say |
| `approved` | a person | The gate is crossed. This is the record of a human decision (MI-7) |
| `skipped` | a person | This step does not apply to this item, and I am accountable for that |

`skipped` is terminal and **counts as `complete` when the orchestrator resolves
what may run next**, which is what makes it useful: it releases everything
downstream without pretending work was done. It is also an exit under MI-4 --
for a step that can never succeed on this particular item, skipping it is the
way forward, and the label is the whole record of who decided that.

Together with `:wip`, these are the nine states a step can be in. Five are the
machine's account of a run; three are a person's instruction to the machine;
`:wip` is neither -- it is the mutex, present only while a step is actually
running.

### How the obligations below are enforced

The four obligations in the next section are not enforced the same way, and
saying which is which is the difference between a contract and a wish.

| Obligation | Enforced by |
|---|---|
| Out of budget is its own outcome | **Vocabulary** -- `exhausted` exists, and the orchestrator sets it from what the run reports |
| Partial work is declared | **Vocabulary** -- the result carries what was left undone, present and empty when nothing was |
| Blocked means say so | **Evidence** -- a step that improvised past a refusal declares an effect it did not produce, and MI-6 compares the two |
| A re-run does the work again | **Evidence** -- a replayed answer has no change behind it, and MI-6 sees a declared effect with no diff |

Two mechanisms, not four. No return format can stop a step reporting success
after improvising, so the first two obligations are structural and the last two
are caught by observation. Anything claiming to enforce the last two by format
alone is claiming something it cannot do.

**One limit, stated rather than glossed.** A step that hits the turn wall never
writes a result, so *what it did not do* only ever captures work a step
deliberately left. Being cut off mid-task is caught by `exhausted` and the
diff, never by the declaration -- which means the step most likely to have
unfinished work is the one that could not tell you about it.

### What a step must never do

- **Write to the issue or PR.** No comments, no edits, no labels. A step returns
  what it produced and the orchestrator records it. Exactly one thing writes to
  GitHub, so there is one format, one failure path, and one place where
  append-only is enforced.
- **Decide what runs next.** Routing belongs to the orchestrator.
- **Apply its own lifecycle labels.** `:wip`, `:complete`, `:review`, `:failed`
  and `:exhausted` are the orchestrator's record of the step, not the step's own
  claim -- and the last two it could not truthfully make about itself anyway.
- **Approve a gate.** Agents draft, humans decide (P-10). No exceptions, in
  either mode.
- **Act outside its allowed commands**, or route around a refusal.
- **Rewrite or delete history.** No step's allowed commands may include
  `git reset`, `git push --force`, `git branch -D`, or any other command
  that rewrites or deletes history, however narrowly a step's other grants
  are scoped. These are operator-only actions taken outside the pipeline,
  not something any `pipeline.json` entry can grant.
- **Depend on state from outside its own (object, agent) session.** Sessions
  never cross-pollinate -- a different agent on the same object, or the same
  agent on a different object, starts with no memory of the other (P-7). A
  re-invocation of the same agent on the same object does resume its own
  prior conversation, but that memory is never a substitute for the work item
  and git as the source of truth, and it does not excuse the next obligation.

### What a step must do when it cannot comply

These obligations are what make a non-deterministic worker safe to depend on.
They matter more than the happy path, because an agent that fails quietly is
indistinguishable from one that succeeded.

- **Blocked means say so, and say what would unblock it.** A step that cannot
  perform an instruction reports that, stops, and states what it needs. It does
  not substitute a different approach and report success. This is the whole of
  how a step asks for something: no spawned step can ask a question and wait for
  an answer, because nobody is attached to it -- so the halt is the question, and
  a person answers by fixing the cause and clearing the label. A `blocked` that
  does not say what would resolve it is a halt with no exit, which MI-4 forbids.
- **A re-run does the work again.** Re-invoking an agent performs the work
  afresh. Returning a previous run's result is a failure, however plausible the
  answer. "Afresh" means the effect, not the record: a re-run must not open a
  second PR, create a second branch, or double-apply a label, but its artefact
  comment is a new one, headed `(Re-run)`, never an edit to the previous
  comment in place -- the trail of what changed between rounds is evidence,
  and overwriting a prior artefact destroys the only record that a finding was
  ever raised.
- **Out of budget is its own outcome.** Exhausting the turn budget is reported
  as exhausting the turn budget, never as the work failing. The two demand
  different responses.
- **Partial work is declared.** An agent that completed some of its task says
  which part. Silence is read as completion, so silence about a gap is a false
  report.

---

## The promises

Eleven promises in two families:

- **AS -- architectural separation.** Where a fact, or a piece of work, is
  allowed to live. Three promises about structure.
- **MI -- mode invariant.** What must hold identically however the work was
  started. Eight promises, each with a both-modes clause.

Each promise states what it means for you, why it matters, exactly what is
being claimed, and how it is tested. Closing the gap between this document
and what the implementation currently keeps is sequenced on issue #393.

---

### AS-1 -- One file tells you what the pipeline does

> **You can read one file and know what will happen: which steps run, in what
> order, what has to finish first, what each step is allowed to touch, and what
> each is supposed to change. Nothing behaves in a way that file does not
> describe.**

`pipeline.json` is the authoritative definition of seven concerns, and nothing
else defines any of them:

| Concern | Declared as | What it covers |
|---|---|---|
| **Process** | step entries | Which steps exist, what each one is -- including which model an agent step runs on -- and which phase it belongs to |
| **Sequence** | `trigger` | What triggers a step and what it emits |
| **Dependencies** | `dependencies` | What must have completed before a step is eligible |
| **Entitled activities** | `defaults.extra_allowedTools`, `extra_allowedTools` | Everything a step may do, globally and per step, plus lifecycle actions and post-steps |
| **Expected effect** | `expected_effect` | What the step is supposed to change -- commits, files, labels, comments -- or nothing, declared explicitly |
| **Flows** | flow entries | Which kinds of work exist, what each applies to, what starts it, and what its branches and pull requests are called |
| **Budgets** | `max_turns` and `max_wall_seconds`, declared once globally and overridable per step; a per-tick cap on work started, global only | What may be consumed: how much a step may attempt, how long it may hold the pipeline, and how much work a single tick takes on |

The table states what the seven concerns are. What each is called, its exact
shape, and which are required is a JSON Schema:
[`schema/pipeline.schema.json`](schema/pipeline.schema.json). Same rule applied
one level down -- the schema is the machine-readable source for the target
shape, and the written reference
([`generated/pipeline-schema-reference.md`](generated/pipeline-schema-reference.md))
is generated from it rather than restated here, so this table and that
reference cannot drift apart by one of them being hand-edited. This document
still states what is true and why; the schema states exactly what a
conforming `pipeline.json` looks like.

**Why JSON, not YAML or TOML.** JSON has a published schema language with
broad tooling, and it is what the orchestrator reads directly -- no parser
ambiguity, no format the CLI has to translate first. The same schema
validates in CI, in editors, and in pre-commit hooks uniformly. JSON's
verbosity is a low cost here specifically because the file is generated-from
for human reading, never hand-read in raw form.

**A helper script maintains `pipeline.json` directly.** Adding a step or
changing a setting on an existing one goes through it, not a hand-edit:
given a step whose prompt file already exists, the script adds its entry to
`pipeline.json` or updates a field on one already there, validating against
the schema as it writes. The prompt file itself is authored separately --
the script's job is the graph, not the behaviour, the same split this
document draws between `pipeline.json` and `.claude/agents/`.

This is the general rule "one machine-readable source per concern; human views
are generated" (P-2) applied to the pipeline itself: every structured fact
about the system lives in exactly one machine-readable file with a published
schema, and the human-readable view of it -- a markdown table, a diagram -- is
generated from that source and committed as build output, never hand-edited.
It matters most here for allowed commands: a permission defined in two places
is a security property that holds in one reading and not the other, and a second
definition is easy to add without noticing -- a constant in the orchestrator, a
line in an agent's frontmatter, a grant in a settings file.

**Selection by classification.** A work item carries a `type:` label --
`security`, `bug`, `enhancement`, `tech-debt`, `spike` -- and, independently, a
`size:` label (`S`/`M`/`L`). Neither changes what a step *does*; the same
`coder` runs the same way regardless of either. What they're allowed to change
is which flow a work item enters, and which steps within that flow are
eligible, declared as a `type` and/or `labels` restriction on a flow's or a
step's own trigger. That is the mechanism selection needs, and it is one
mechanism at both levels: a flow's trigger restricts which items enter it
(`type`, for the type dimension specifically, since a work item carries
exactly one; `labels`, a general AND-combination, for everything else); a
step's trigger restricts which of a flow's items make it eligible the same
way. `type: enhancement` and `size: M` together is what a step's trigger
checks to run only on a medium enhancement -- combining two dimensions is not
a special case, it's the same `labels` array with two entries. Selection is
positive (a trigger states what it matches; there is no exclude list to forget
one entry of), so keeping `spike` out of the default flow means the default
flow's `type` list omits it, or a dedicated flow claims it -- not a rule
written elsewhere that has to be kept in sync. `security`, `bug`,
`enhancement`, and `tech-debt` currently share the one default flow and run
identically at the flow level, diverging only step by step on `size` (see
[lifecycle.md, What runs, for each type and
size](lifecycle.md#what-runs-for-each-type-and-size)); a repository is free to
add a flow restricted to a subset of them if it ever needs one to diverge at
the flow level too, but the mechanism existing is not an invitation to use it
without a reason.

A third label dimension, `priority:` (`high`/`medium`/`low`), is deliberately
never a selection criterion -- it never appears in a `type` or `labels`
restriction, at either level, and neither do `blocks:`/`blockedby:`. All
three answer a different question, addressed in [Which eligible item runs
next](#which-eligible-item-runs-next): given several eligible items, which
does the orchestrator work on first, and is a not-yet-started item eligible
at all.

**A repository may have its own.** The pipeline ships with a default definition,
and a repository can replace it entirely with one of its own. That does not
weaken this promise: there is still exactly one effective definition for any
repository, and it is still readable in one file, still complete, and still the
only thing that decides what happens. What this promise forbids is a definition
living somewhere nobody would think to read -- a constant in the orchestrator, a
field in an agent's frontmatter, a grant in a settings file. A second declared
file that replaces the first outright is not that.

**All or nothing.** A local `pipeline.json` is not a set of changes layered over
the shipped one -- it is a complete pipeline definition in its own right,
validating against the identical schema, with every flow, process and budget the
repository needs stated in it. There is no partial override, no per-flow
precedence, and nothing to merge. Presence means the repository's file decides
everything; absence means the shipped default decides everything. Kept
deliberately simple: naming which flows are overridden and which fall through to
the default would add a second axis -- which file said what -- to a promise that
exists specifically to keep there being only one.

**Where it lives.** `pipeline/pipeline.json` in the repository itself, mirroring
the path of the file it overrides so the relationship needs no explaining.

**Most repositories will not have one, and nothing creates it for them.** The
shipped definition is read from the framework every time; onboarding puts no
copy anywhere. The local file exists only when someone writes one, and its
absence is the ordinary case meaning "the default, entirely" -- never a file
seeded empty that would sit where a reader expects the pipeline to be
defined while actually defining nothing.

Where it does exist it is the repository's own: never overwritten by a sync, and
committed normally rather than gitignored. What a repository decided about its
process has to survive every framework version -- which is precisely what the
framework's own files must not do. The shipped definition can be replaced
wholesale on upgrade; the local one is never touched.

**The cost, stated.** A repository that goes local stops tracking the default
entirely -- every flow, not just the one it needed to change. The framework may
improve its version and the repository will not see any of it, the same way a
fork does not. That is the trade for the simpler rule: nothing to reconcile
between two files, at the cost of losing the rest when only one part needed to
differ.

**Precisely.** Process, sequence, dependencies, entitled activities, expected
effect, flows and budgets are defined in the pipeline definition -- the shipped
default, or a repository's own complete replacement of it -- and nowhere else. No
constant in the orchestrator, no agent frontmatter field, and no settings file
adds to, narrows or overrides any of the seven. A limit is a definition like any
other: a budget that lives as a constant in orchestrator code is a step's
declared allowance that no reader of the process definition can see, and with no
override mechanism at all, the same number is asserted to fit every step in the
pipeline whether it does or not. A shared default in `pipeline.json`, visible
and overridable, is not this problem -- it is the fix for it (see 'Every step
has the same four parts'). In particular no name is computed in code:
a branch or pull-request name that is a string built inside the orchestrator is
a definition living outside the file that is supposed to hold it.

**Test.** The resolved command set for every step is derivable from
`pipeline.json` alone. Any permission that cannot be traced to it is a test
failure. The same for triggers, dependencies, and expected effect: every step
declares one, and a step declaring no effect that produces one is as much a
failure as the reverse. Both the shipped `pipeline.json` and a repository's own
validate against `schema/pipeline.schema.json` -- a definition the schema
rejects is not a test failure to discover later, it is a file that does not
parse.

**Always the version on `main`, never the version the tick is about.** A tick
is often triggered by a pull request, and the default checkout for a
`pull_request` event is that PR's own merge ref -- which would let a PR
editing `pipeline.json`, the orchestrator itself, or an agent prompt alter the
run that is supposed to be reviewing it. So the orchestrator always runs its
own code, `pipeline.json` and the agent prompts from `main`, regardless of
what triggered the tick, and never from the ref the event points at. The PR's
own content is still reviewed -- over the API, not by checking out its ref --
so nothing about this pins stale content, only which copy of the *process
definition itself* governs the run.

---

### AS-2 -- The orchestrator only coordinates

> **Changing how the process works means changing configuration and scripts,
> not the orchestrator. Nothing that produces or changes an artefact lives
> inside it.**

The orchestrator's job is to read the state, select the one step whose
conditions are met, run it, and record the outcome. That is coordination. Every
other kind of work -- writing a file, committing, cleaning up, posting a
record, computing a number -- is value-add work, and belongs in a step, a
pre-action or a post-action, all of which are scripts or agents.

This is what keeps the process malleable. When value-add work accumulates inside
the coordinator, evolving the process starts requiring changes to the one
component every step depends on -- so each change carries the risk of breaking
work unrelated to it, and the pipeline becomes expensive to change in exactly
the way a pipeline should be cheap to change.

It also keeps AS-1 honest. Work embedded in the orchestrator is work that
`pipeline.json` does not describe, so a reader of the process definition would
not know it happens.

**Precisely.** The orchestrator performs only: reading state, selecting the next
step, claiming and releasing the mutex, invoking the step, and recording the
outcome as a label and an audit entry. Everything else is a script or an agent
named in `pipeline.json`.

**Test.** Adding a step, removing a step, reordering steps, or changing what a
step may do requires no change to `pipeline_orchestrator.py`.

---

### AS-3 -- A command names something; it does not do something

> **Every `/maos-*` command is a thin wrapper. It says what to run and passes
> along what you typed. Nothing else.**

A slash command is an entry point, not a program. It names a step, a script or
an agent, and hands over the arguments. If a command describes a procedure --
first do this, then check that, then apply the other -- then the procedure is
logic, and logic in a command file is logic that `pipeline.json` does not
describe and no script contains.

This is AS-2 one level further out. Value-add work does not belong in the
coordinator, and it does not belong in the thing that starts the coordinator
either. Procedure written into a command cannot be tested, cannot be reused by
the headless path, and drifts from the process definition silently -- because
nothing reads a command file except a person typing the command.

It also keeps the command surface honest about what it is. `/maos-{agent}`
should mean exactly one thing: run that agent. A namespace where some entries
are one-line aliases and others are multi-page procedures teaches nobody
anything.

**Precisely.** Every command either is generated from `pipeline.json`, or names
a single script or agent and passes its arguments through. No command contains
conditional logic, a loop, or a sequence of steps.

**Test.** Every command file resolves to a generated wrapper or a single named
target. A command containing a numbered procedure, a conditional, or a retry
loop is a test failure.

---

### MI-1 -- An issue means the same thing to everyone

> **The labels on an issue tell you where the work has got to, and they mean
> the same thing whether a person or the headless runner put them there.**

Labels are the only state, so their meaning must not depend on their origin. If
it does, the same label on two issues means two different things according to
history nobody can see, and an issue cannot be handed between modes.

**Precisely.** No label is specific to one mode, and no step interprets a label
differently depending on which actor applied it.

**Test.** Every label in `statuses.json` has exactly one documented meaning, and
no step's behaviour branches on who applied it.

---

### MI-2 -- The same situation always produces the same next step

> **Two people looking at the same issue get the same answer about what happens
> next. So does the headless runner.**

This is what makes the pipeline explainable. Without one routing decision you
cannot tell someone what will happen when they approve something, and two
implementations of routing drift invisibly until they disagree on a specific
issue.

**Precisely.** Given identical state, both modes select the same next step.
Routing is computed in exactly one place. A driver may read the pipeline
definition to explain what will happen, never to decide it.

**Test.** Run the resolver and the real dispatch path over the same issue state
and assert identical selection, for every step.

---

### MI-3 -- An agent can only ever do what you allowed

> **The limits on what an agent can touch are the same limits however the work
> was started. There is no looser path.**

A re-implementation of enforcement must be kept in step with the original
forever, and it will not be. Every divergence is a security property that holds
in one mode and silently not in the other, with no way to tell from outside.
This is the most expensive promise in the list to break.

**Precisely.** Whatever enforces a step's allowed commands is the **same
mechanism** in both modes, not an equivalent one. Neither mode re-implements the other's
enforcement.

**Test.** Exactly one component decides whether an action is permitted, and both
modes route through it. A second implementation is a test failure, not a design
choice.

**Note.** AS-1 and MI-3 are two halves of one property. AS-1 says permissions
are *written down* in one place. MI-3 says they are *enforced* by one mechanism.
Either alone still leaves room for disagreement.

---

### MI-4 -- Nothing gets stuck with no way out

> **Every state the work can reach has a way forward that you can actually
> perform -- in a chat session or on the runner.**

A halt with no exit is not a pause, it is a loss. Recovering from one means
editing state by hand outside the system, which nobody sees and nothing records
-- the exact un-auditable intervention the label model exists to prevent.

**Precisely.** Any state a run can enter has a documented exit performable in
both modes. A state reachable in one mode and escapable only in the other is a
defect.

**Clearing a halt is a claim, not a click.** The exits from `blocked` and
`failed` are a person removing the label, and that act means something specific:
*I have dealt with the cause.* The next tick takes it literally and runs the
step again.

So the meaning has to be the same for everyone, or the exit is worse than none.
A label cleared to make a red thing go away sends the step straight back into
whatever stopped it, and the second failure looks identical to the first -- so
the trail now says a step failed twice for the same reason, with nothing
recording that the first clearance was a guess. The label model can show who
cleared a halt and when; it cannot show whether they fixed anything, which is
exactly why what the act means must be agreed rather than assumed.

**The orchestrator posts the recovery guidance, not just the step.** A
step's own account can be terse, and a step cut off mid-task is the one most
likely to explain itself badly. So a halt's exit is never left to whatever
the step happened to say: on every `review`, `blocked`, or `failed`
transition, the orchestrator's own closing `announcement` carries the same,
consistent recovery guidance -- naming what the halt means and what clears it
-- independent of how well the step's own report was worded. It is not a
sixth kind of comment; it is what the orchestrator, rather than the step,
puts in the one it already posts.

#### A step can vanish, and the lock it holds must come back

Every outcome assumes the step got far enough to return one. A step can also
just stop existing -- the machine running it is lost, the process is killed
outright, the tick is cancelled between one write and the next. Nothing is
returned, so no outcome is produced, and the `:wip` the step was holding stays
where it is.

That label is the mutex, and it blocks the pipeline. So a step that vanishes
does not merely fail: it takes that pairing of work item and step out of the
system permanently, and the only way back is a person deleting a label by hand
-- the un-auditable intervention this promise exists to prevent.

**Releasing the lock on the way down is not enough.** Catching a termination
signal and clearing the label first covers the tidy cases, and none of the ones
that matter: a process killed outright runs no handler, and a lost machine
cannot clear anything.

So the reclaim has to be something a *later* tick does, by looking at the label
rather than at the run. A `:wip` older than that step's wall-clock budget cannot
still be legitimately running -- the budget is the whole of what "still running"
means -- so the orchestrator takes the lock back, records the step as `failed`,
and says why. It returned nothing, which is what `failed` means; no sixth
outcome is needed for it.

**A reclaim counts as an attempt, the same as a crash.** Retrying `failed`
draws from the one retry budget regardless of why the step landed there -- a
step that hangs the identical way on every invocation still exhausts its
retries and lands on a `failed` a person must clear, rather than reclaiming,
retrying, and hanging again indefinitely with nothing ever escalating.

This is the second reason the wall-clock budget belongs per step in
`pipeline.json` (AS-1). One number for every step means either a slow step is
reclaimed while it is still working, or a fast one stays stranded for as long as
the slowest step in the pipeline might legitimately take.

**Test.** Every status in `statuses.json` where `blocks_pipeline` is true names
a `cleared_by`, that exit is reachable from the step's own configuration, and it
is performable in both modes.

---

### MI-5 -- The result does not depend on who was watching

> **A step does the same thing whether you watched it or not. The trail on the
> issue records the work, not who was present.**

If effects vary by mode, the artefact trail stops being evidence: two issues
cannot be compared, because they were produced under different conditions.

**Precisely.** A step's pre-actions, activity and post-actions produce the same
effects in both modes, in the same order. A mode may differ in **who
triggers** a step, never in **what the step does**.

**Test.** Run the same step in both modes against equivalent state and diff the
resulting issue timeline, ignoring timestamps and actor.

---

### MI-6 -- You can believe what the system tells you

> **Every step says what it did, including when it did nothing -- and the
> orchestrator separately records what actually changed. Where the two
> disagree, you are told.**

The reports are all you have. Nobody watches a headless run: you read the issue
afterwards and believe it. So a step that reports success while doing nothing
does more than fail, it makes everything after it meaningless -- a check that
says it tested a commit proves nothing if the step before it silently pushed no
commit.

Asking a step to announce its own silence is not enough on its own. A step that
does nothing usually does not know it did nothing. So the system records two
things about every step and compares them:

| | What it is | Who produces it |
|---|---|---|
| **The account** | What the step says it did, in its own words | The step |
| **The evidence** | What actually changed -- commits, files, labels, comments | The orchestrator, by observation |

Each step also declares in `pipeline.json`, as `expected_effect`, what it is
supposed to change. `coder` produces commits; `pr-reviewer` produces none, and
says so rather than leaving it unstated. That makes the comparison
meaningful in both directions: a step that should change something and did not
is as wrong as a step that changed something it had no business touching.

**Precisely.** Every step returns a summary of what it did, and doing nothing is
a result reported as one. The orchestrator observes the actual change
independently, compares it against the step's declared expected effect, and
records both. A disagreement between account, evidence and expectation is
surfaced, not buried. Silence is read as success, so silence about a non-event
is a false report.

**Test.** Every step returns a summary on the path where it acted and the path
where it did not. Every step declares its expected effect. The orchestrator
records the observed change for every step and flags any case where account,
evidence and expectation do not agree. After a run in either mode, both branches
carry one appended record per completed step, and the two runs are
indistinguishable in what they wrote.

#### Where the record lives

A record that survives only as long as someone is watching is not a record. The
account, the evidence and the measurements are
written to two protected orphan branches -- `ai-agile/log` for the narrative of
what happened, `ai-agile/metrics` for what it cost -- appended once per
completed step. Both are written by a git push, so both work identically whether
the run was started by a schedule or by a person; neither depends on a console
that scrolls away or a build log that ages out. The branches are orphan and
carry only their own data: a log branch that also carries a copy of the
repository is a second, stale copy of the repository.

#### The shape of one record

Each appended entry is one JSON object, e.g.:

```json
{
  "ts": "2026-05-04T14:23:11Z",
  "event": "agent.complete",
  "agent": "01_product_docs/prd-writer",
  "issue": 42,
  "status": "complete"
}
```

Required on every entry: `ts` (an ISO-8601 timestamp), `event` (the type, from
the table below), `agent` (the `pipeline.json` name, or null for a
system-level event with no associated step), `issue` (the work item number, or
null for a PR or a global event), and `status` (the resulting status).
Alongside them, and each nullable: `detail` (a human-readable note -- a stop
reason, an exit code, a mode), `session_id` (the (object, agent) session this
entry belongs to), `object` (`{"kind": "issue"|"pr", "id": number, "repo":
"owner/repo"}`), `actor` (who triggered the run -- the first of the two mode
questions above, not the second: `{"kind": "orchestrator", "id":
"github-actions", "human": null}` for a scheduled or unattended run, `{"kind":
"orchestrator", "id": <actor-id>, "human": true}` for a human-initiated one),
and `duration_ms` (the run's wall-clock duration).

| Event | Emitted when |
|---|---|
| `agent.invoked` | The orchestrator launched the step |
| `agent.complete` | The step returned `complete`, or a gate promotion completed |
| `agent.review` | The step returned `review` |
| `agent.blocked` | The step returned `blocked` |
| `agent.failed` | The step crashed, timed out, or exited without a sentinel |
| `gate.approved` | A human applied the gate label; gate promotion ran |
| `lock.reclaimed` | A stale `:wip` was force-reclaimed |
| `system.emergency_stop` | The stop marker was detected; the orchestrator exited without invoking anything |

One entry per completed step -- the same "one appended record per completed
step" the test above already requires, named down to its fields.

---

### MI-7 -- Only a person approves

> **An approval needs a human decision, recorded the same way every time. The
> system cannot approve itself, and cannot be tricked into it by timing.**

Agents draft and humans decide (P-10) is the basis of the product. A gate
enforced differently in one mode is a gate not enforced, and a guard that admits
an approval when its check is inconclusive is a guard that fails at exactly the
moment it is needed.

**Precisely.** The decision is always a person's, in both modes, and nothing
else may originate it. The record is always the same gate label, in both modes,
readable by either. A gate is crossed only by a person's own label (headless) or
by the orchestrator recording a confirmation the driver relayed (interactive) --
never by an agent, and never by a driver writing the label itself. An approval
the orchestrator cannot establish a person stood behind is refused, not admitted.

**Test.** In headless mode, a gate label applied by any non-human actor is
rejected. In interactive mode, an approval recorded by the orchestrator on a
relayed human confirmation is honoured. No agent can cause either, in either
mode. An inconclusive check refuses rather than admits.

**A gate label and its promotion appear together, or not at all.** A
downstream step's dependency check reads `{agent}:complete` and
`{gate}:approved` as a pair -- the orchestrator guarantees both are present
or neither is, so a transient state where the gate label exists but the
promotion has not yet landed is never visible to anything checking
eligibility. What a downstream step sees is binary: the gate was crossed, or
it was not.

#### Why this is built as unreachability, not detection

The obvious rule -- "no bot may apply a gate label" -- does not work. In
interactive mode the chat-AI writing the label on the person's instruction is
the supported path: it is transcribing a decision, not making one. But
transcription and origination look identical at the point of writing, both being
a non-human actor applying a label, so no amount of actor-checking separates
them.

So the design does not try to detect origination. It makes origination
unreachable.

The orchestrator is the only component that is neither an agent nor a
credential-holder, and it knows first-hand how it was invoked. That fact cannot
be forged: an agent's entire output surface is one status value from a fixed
set, so there is no message an agent can send that means "approve this", and
nothing downstream sets the mode.

That gives a rule with no ambiguity to resolve:

| Mode | How a gate can be crossed |
|---|---|
| **Headless** | Only by a label a **person** applied, asynchronously, from their own account. The pipeline itself can never cross a gate, because no human is present during the tick to have decided anything |
| **Interactive** | The **orchestrator** records the approval, having been told by the driver that the person confirmed. The driver never writes the gate label itself |

The requirement is identical in both -- a person decided. What differs is the
evidence available to show it, which is a legitimate difference under MI-8 and
is listed as one.

#### How a non-human actor is recognised

The rule above turns on telling a person's action from the system's, so that
distinction has to be real at the point GitHub records it, not inferred
afterwards.

Everything the system does on GitHub acts as a **dedicated identity of its
own** -- not a person's account, and not the generic identity a CI run gets by
default. The default is the trap: it makes every action the system takes look
like any other automation in the repository, so agent activity cannot be told
apart from unrelated CI in the same timeline, and "was this applied by a
person?" stops having an answer.

A dedicated identity buys four things, and MI-7 needs the first:

| | |
|---|---|
| **Decidability** | "A person applied this label" is a fact readable off the timeline, not a guess |
| **Least privilege** | The identity is scoped to exactly what steps need -- no administration, no secrets, no settings |
| **Legibility** | A distinct name and avatar makes agent activity obvious to a person scanning the issue |
| **Isolation** | The system's API usage does not consume a contributor's quota |

The identity is the system's, not any one step's: every step acts under it, which
is why the marker on each comment carries the step's name. Two mechanisms can
back it -- an installed application with short-lived rotating credentials, or a
dedicated account with a long-lived token that someone has to rotate. The first
is better and the difference is operational, not architectural: what MI-7
requires is only that the system's actions are attributable to the system.

**One assumption must be asserted rather than trusted:** that a non-headless
invocation genuinely has a person present. There is no independent check for
this -- it holds today only because the interactive path exists nowhere
except inside a chat session, the same unreachability logic as above, not a
runtime verification the orchestrator performs. If anything ever invokes the
orchestrator non-headlessly without a human, this guarantee disappears
silently, because nothing exists to catch that case: what has to hold is that
the interactive path stays unreachable except through a chat session, not
that the orchestrator can somehow tell.

---

### MI-8 -- Any difference is written down

> **There is a short list of things that differ between headless and interactive
> mode. Anything not on that list is a bug.**

Without an enumerated list the two modes drift apart one reasonable
accommodation at a time, each invisible on its own, until they are different
products.

**Precisely.** Anything that legitimately differs is listed in
[What is allowed to differ](#what-is-allowed-to-differ) with a reason. An
unlisted difference is a defect, not a feature.

**Test.** Every mode-conditional branch in the orchestrator, the scripts and the
agent prompts maps to a listed difference.

---

## Headless and interactive

**Headless.** A continuous background process on GitHub Actions. It starts when
an issue or pull request changes, or on a timer, and nobody is watching. Work
keeps moving without anyone present, and approvals wait for whoever next looks
at the issue. This is the primary mode.

**Interactive.** A chat session in Claude Code. You run `/maos-run {N}` and drive
one issue forward a step at a time, watching each agent work and answering
approvals as they arrive. This is how work gets unblocked, debugged, and pushed
when someone is at the keyboard.

You must be able to start an issue in one mode, walk away, and have the other
finish it, with no difference in the result. That is what the eleven promises
above are for.

### The three interactive commands

Interactive mode offers three things. Two of them run the pipeline and one
openly does not, and they must not share a name.

| Command | What it invokes | Activity performed by | Mode |
|---|---|---|---|
| `/maos-run {N}` | The orchestrator, repeatedly -- one step per invocation, each picking the next eligible step | a spawned agent or script | `headless` |
| `/maos-{agent} {N}` | The orchestrator, naming one step, which it spawns as a subprocess exactly as the headless path does | a spawned agent or script | `headless` |
| `/maos-{agent}-i {N}` | The orchestrator in resolve-only mode; you then work through the step's instructions | you and the chat-AI | `interactive` |

**All three advance state, and none of them advances it by hand.** The
orchestrator performs every label transition, every artefact comment, every
post-action and commit -- in interactive mode exactly as in headless. A driver
command never applies a lifecycle label, never posts an artefact, and never
performs a step's work itself. Hand-mirroring any of that is how a run ends up
with misplaced artefacts, missing downstream labels and orphaned branches, and
it is the single rule that keeps an interactive run indistinguishable from a
headless one in the record.

There are two exceptions, both narrow and both about the driver relaying
something only a person can supply: applying the `{agent}:approved` gate label
on a confirmation you gave (MI-7), and marking a pull request ready when a
restricted session blocks the operation the orchestrator would otherwise use.
Neither is value-add work; both are the driver acting as a hand for something
the environment denied.

The orchestrator already separates resolving from spawning. Resolving an
invocation and spawning it are distinct operations: the resolve-only path
reports `AI_AGILE_EXECUTION_MODE=interactive`, and the spawn path reports
`headless`. Every command is a thin wrapper over one of those two (AS-3), and
the per-agent pair is generated from `pipeline.json` so neither can drift from
the step it names.

**Why the distinction is load-bearing, not cosmetic.** `/maos-{agent}` is the
pipeline: same prompt, same allowed commands, same enforcement, so what you
see is what the headless runner would do, which is the only thing that makes
it useful for reproducing a problem. `/maos-{agent}-i` is **not the
pipeline**, and does not pretend to be: you and the chat-AI work through the
agent's instructions together, in your session, with your permissions --
nothing is enforced against an agent's allowlist, because no agent is
running, a person is, with an assistant.

**It still advances the pipeline, and the record says how.** Not being an
agent invocation does not make it a private exercise: the step returns its
result the way every step does, and the orchestrator records it, including
that a person performed the activity rather than a spawned agent. That
provenance is what keeps two things true at once -- an in-the-loop run is a
legitimate way to move an issue forward, and it is not evidence of what the
pipeline would do unattended -- and it is also what resolves an apparent
contradiction with MI-3: enforcement is still one mechanism, the platform's
own on the spawn path, and the in-the-loop command needs no second one
because it is not an agent invocation to enforce.

**The risk this creates, stated plainly.** Someone reaches for `-i` believing
they are testing what the pipeline does. They are not: different context,
different permissions, a human able to intervene. The naming carries that
distinction, and the recorded provenance is the backstop against a mistaken
belief in the chat becoming a mistaken conclusion from the record.

---

### How people interact with it

**In headless mode, GitHub is the only channel** -- labels and comments on
the issue, nothing else. **In interactive mode you can also talk to the
chat-AI**, in your own words, and it writes the labels and comments that
carry your intent: a scribe, not a decision-maker, never originating a
decision it only transcribes (MI-7). The record is identical either way --
nothing that influenced the work exists only in a chat transcript.

---

## What is allowed to differ

The complete list. Anything not here is a defect.

| Difference | Headless | Interactive | Why this is legitimate |
|---|---|---|---|
| Who starts a step | A GitHub event or a timer | A person running `/maos-run` | This is the whole point of having two modes |
| Where you watch it | Issue and pull-request activity | The same, plus live agent output | What you see is not what happened; the trail is identical |
| Which credentials are used | Repository secrets | The session's own login | The environments genuinely differ; the *authority* those credentials carry must not |
| How long an approval waits | Until someone next looks | Immediately | A person being present is the difference |
| How you address the pipeline | Labels and comments on the issue | The same, or in your own words to the chat-AI, which writes them for you | Only the channel differs; what lands on the issue is identical |
| Who writes a gate label | Only the person, from their own account | The orchestrator, on a confirmation the driver relays | The decision is the person's either way; only the evidence available to show it differs (MI-7) |
| Whether the emergency stop applies | Halts the run before any step | Logged, and the run proceeds | The stop exists to halt unattended automation. A person driving one issue by hand is not unattended, and stopping them too would remove the means of investigating whatever caused the stop |
| How many items advance at once | Several, where their components do not overlap -- one run working through them in turn | Several, where their components do not overlap -- one instance per item, each started by a person | The invariant is identical (see 'Working on several things at once'); only the shape differs -- one process serving many items, or many separately-started processes each serving one. An issue driven either way leaves the same trail |

Everything else is governed by the promises above and must be identical.

Two things are often mistaken for legitimate differences and are not:

- **How permissions are enforced** (MI-3). Whether a mode can use the platform's
  own enforcement is a consequence of how it starts agents, which is a choice,
  not a constraint.
- **Which errors can be recovered from.** A refused query and a refused
  repository are different failures needing different responses, but which one
  you get must never depend on how the work was started.

