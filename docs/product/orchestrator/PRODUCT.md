# The Orchestrator Product

The single description of what the orchestrator is and what it promises.

This document describes the target design (issue #393). It states what the
product does, not what the implementation currently manages -- the gap between
the two is tracked separately in [`gap_analysis.md`](gap_analysis.md).

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
- [Core requirements](#core-requirements)
- [The state machine](#the-state-machine)
- [The pipeline defines flows, not a flow](#the-pipeline-defines-flows-not-a-flow)
- [How the orchestrator tells a step where it is](#how-the-orchestrator-tells-a-step-where-it-is)
- [How it uses agents](#how-it-uses-agents)
- [The step contract](#the-step-contract)
- [The promises](#the-promises)
- [Headless and interactive](#headless-and-interactive)
- [What is allowed to differ](#what-is-allowed-to-differ)
- [Status of this document](#status-of-this-document)

---

## The state machine

The labels on a work item are the state. A step is a transition. The orchestrator
reads the labels, selects the one step whose conditions are met, runs it, and
writes the outcome back as a label.

Because state lives on the work item, there is nothing to recover and no
position that exists only in memory. Any orchestrator process reading settled
labels reaches the same conclusion.

**Settled is the load-bearing word.** A label write is not visible instantly, so
two runs overlapping inside that window read different states and both conclude
the step is eligible -- and the write that starts the race is the orchestrator's
own `:wip`, which fires an event that starts the next run. The window is only
wide enough to matter for steps that run long, which is what makes it a
sporadic, hard-to-reproduce duplicate rather than a permanent fault.

So one thing does have to be synchronised: **at most one orchestrator run at a
time.** Once runs are serialised, every run begins with settled labels and the
`:wip` check becomes a fast skip rather than a guard against a race. The state
model is unchanged -- labels are still the whole of it -- but "read the labels
and act" is only deterministic if no other run is mid-write.

Serialising runs decides more than it looks. One run at a time, and a run that
waits for each step it starts, means the pipeline is **sequential**: no two
steps are ever in flight together, so nothing needs limiting to keep them apart.

One limit is still needed, and it is not about concurrency. When a burst of work
becomes eligible at once -- a hundred issues, a backlog import -- something has
to bound how much a single pass takes on, or one tick tries to do all of it. That
is a cap on how much work a tick *starts*, and it belongs with the other budgets
rather than fixed in code: one number chosen once for every situation is a
number nobody can tune for the case in front of them.

### Working on several things at once

One orchestrator works on one item at a time; that part is settled, and the
serialisation above is what makes it safe. Nothing says there may only be one
orchestrator.

**Two runs on two different issues are fine right up until they touch the same
code.** Labels keep two runs off the same *item*, and that is all they do. Two
issues that both change the same module have nothing keeping them apart: each
run reads a tree the other is about to change, and the collision surfaces as a
merge conflict at best and as two half-correct changes at worst.

So the unit that has to be exclusive is not the issue, it is **the part of the
system the work touches**.

#### The issue says which parts it touches

An issue carries a `component:` label for each part of the system it affects,
and may carry several. Before an item starts, it takes a claim on every
component it names, and it starts only if it can take them **all**. Several
items proceed together exactly when none of them wants a component another is
holding.

**Claimed together, released together.** An item never holds part of what it
needs while waiting for the rest -- so two items can never end up each holding
something the other is waiting on. Either everything an item named is free and
it starts, or nothing is taken and it waits. That all-or-nothing rule is the
whole of what keeps this from deadlocking, and it is worth more than the
throughput it costs.

**An issue with no component label runs alone.** Not knowing what something
touches is not the same as knowing it touches nothing, so an untagged item
claims everything: it waits for all work to finish and all work waits for it.
The pipeline is then exactly as sequential as it is today, and becomes parallel
only where someone has said enough for that to be safe.

**The cost is that broad work waits for a quiet moment.** An item naming six
components needs all six free at once, and a steady stream of single-component
work can keep it waiting. That is the honest trade: the alternative is letting
it start while something it will change is already being changed.

This is what makes the feature available now rather than pending. Working out
what an issue affects by inspection is hard, and has to be trusted before it can
be relied on; a label is a claim someone made, visible on the issue, and wrong
in ways a person can see and correct.

**Nothing knows what the components are.** There is no register of them, in
`pipeline.json` or anywhere else. The orchestrator reads whatever
`component:` labels an item carries, treats them as opaque names, and compares
them for equality. Components exist because someone wrote one on an issue, and
a repository's set is whatever its issues happen to say -- which is what keeps
the orchestrator coordinating rather than knowing about the system it is
building.

**The claim is only as good as the person making it.** Two failures follow, both
silent, both landing in the same place. An issue tagged with two of the three
components it touches is *more* dangerous than one tagged with none, because it
will be allowed to run beside something it collides with. And `component:auth`
and `component:authentication` are two different components as far as equality
is concerned, so a near-miss reads as no overlap at all.

A register would not fix either. Picking the wrong valid name is as easy as
mistyping one, and the register would be a second thing to maintain and a
second place to be wrong. The control is the same in both cases and it is not
mechanical: the labels are visible on the issue and in the repository's label
list, so a divergent name is something a person can see -- and the label picker
pushes towards names already in use without anything having to enforce it.

**Deciding is not the same as isolating.** Component labels answer whether two
runs *may* proceed together. They do nothing about two runs sharing one working
tree, where the second run's checkout disturbs the first whatever either one
touches. Parallelism needs both: the labels to decide, and separate working
trees so the decision means something.

And keeping two runs off one item stays a separate requirement throughout. The
race that forced serialisation is about one item being read twice, and no
partitioning by component addresses it.

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
are running and the parent has nothing to do until they finish. The process
document defines what our epic flow actually does; two things about it are the
orchestrator's problem.

**Waiting is not a step.** "Wait for the parts" is not something that runs and
returns; it is a later step whose conditions are not yet met. The orchestrator
finds the item ineligible and moves on, and it advances on a tick once the
condition holds. Making waiting into a step means inventing something that
polls, and a step that returns "not yet" is a sixth outcome the design does not
need.

**A trigger must be able to say more than "a label on this item".** "Every child
of this item is closed" is a condition about other work items. Without it, a
flow that coordinates work cannot be declared at all -- the waiting has to be
written in code instead, which is how coordination ends up inside the
orchestrator rather than in the file that is supposed to describe it.

### A flow is not the only thing that can watch an object

Nothing requires exactly one flow per object kind. What the orchestrator
actually routes on is a step's own trigger and dependencies, not which flow
declared it -- so a second flow may match an object kind a first flow already
covers, as long as their steps' conditions never make two steps eligible on the
same item at once. Two flows sharing an object kind is then no different from
two steps in one flow: MI-2 still holds, because it is a property of trigger
conditions, not of flow boundaries.

That is what makes "closes when the whole is sound" a real thing rather than a
phrase. An epic's children closing is not itself the soundness check -- it is
what makes a review step eligible. That step, declared like any other step with
its own allowed commands and expected effect, is what the epic's closing
actually depends on. What the review judges is a decision for whoever declares
that step, not something fixed in advance here.

### The same capability lets a step finish its own work in pieces

An epic waits *while* its children are open. A step can use the identical
capability the other way round: stay eligible *while* its own children are
open, so that finishing the item takes several invocations instead of one.

**Why this matters.** A step's turn and wall-clock budgets bound one
invocation. An issue decomposed into several sub-issues can need more of
either than any single invocation should be given, even though no one
sub-issue does. Giving the whole issue to one invocation means a step that
runs out partway through loses everything back to the last commit -- which,
because the orchestrator commits once per invocation, is the very start of
the issue.

**The unit of work shrinks; the contract does not change.** When a step is
invoked this way, its job for that invocation is one sub-issue, not the whole
issue. `complete` still means exactly what it always means -- the step
finished what it was given -- because what it was given is now smaller. No
new outcome, no mid-run signal, no change to "exactly one result per
invocation." The orchestrator commits after that one result exactly as it
does today, so a step that later runs out on sub-issue four leaves one, two
and three committed rather than nothing.

**The step needs to be told which piece is its.** A work item number is not
enough once a step can be invoked several times against the same item for
different pieces of it; the step also needs to know which one this
invocation is for. That is an addition to what every step is told, not a new
concept -- the same channel, one more thing on it.

### A branch is not always cut from the default

A flow's primary branch is created from the repository's default branch unless
the flow says otherwise -- declared the same way the branch name itself is, a
token pattern in `naming`, never computed in code. An epic's sub-issues need
this: their branch has to be cut from the epic's own integration branch
(`feature-{parent_number}`), not `main`, or their work never lands where the
epic expects it to. If the computed base does not exist -- the epic's branch
was never created, or has already been merged and deleted -- the flow falls
back to the repository's default branch rather than failing over something
that was never guaranteed to be there.

### Scheduled work: how a flow knows it is due

A scheduled flow has no work item, so it has nowhere to carry a label -- and
labels are the state. The question that follows is where "this last ran on
Tuesday" is kept.

**It is not kept anywhere new.** The record already holds it. Every completed
step appends one entry, timestamped, to the log and the metrics branches, so
when a flow last ran is a read of the record rather than a second store to keep
in step with it. A flow that has never run has no entry, which is the same
answer as overdue.

This matters more than it looks. The alternative -- a table of last-run times,
or a cadence written into a workflow file -- is exactly the hidden state the
label model exists to avoid, and in the workflow-file case it would put part of
the process definition outside `pipeline.json`. The cadence is declared with the
flow; whether it is due is derived from what already happened.

A scheduled flow also needs a claim of its own, because the `:wip` mutex is a
label on a work item and there is no work item to label -- two runners must not
start the same sweep.

### What a scheduled step may do is declared, like any other step

A scheduled step is a step. What it may do is its allowed commands and its
expected effect, declared in `pipeline.json` -- not a property the orchestrator
infers from the fact that a schedule started it.

A step that only looks is expressed by granting it no commands that write, plus
whatever it needs to record what it found, and declaring an expected effect of
no change to the repository. A step that acts is expressed by granting it the
commands to act. Neither is special-cased and neither is inferred from the fact
that a schedule started it: both are permission sets, visible to anyone reading
`pipeline.json`, which is the whole point of them living there rather than in
the orchestrator.

**The declaration is what makes it checkable.** A step declaring no change that
produces a commit disagrees with itself, and MI-6 surfaces the disagreement.
That holds for every step, not just scheduled ones: the guarantee comes from
comparing the declaration against what happened, never from a rule about a
category of work.

### The orchestrator stamps what it creates

A step returns what it produced and the orchestrator writes it (the step
contract). When what a step produced is a new work item, the orchestrator
records which step and which flow produced it.

That provenance is what lets a flow find its own earlier output. A step that
runs repeatedly can then read what it already reported and raise only what has
appeared since, rather than repeating the same findings every run until nobody
reads them. Whether a given step does that is the step's business; the
orchestrator's part is only that the trail exists to be read.

It is the same principle as the cadence above. What a flow already said is
readable from the work item that says it, and when the flow last ran is readable
from the record -- so neither question needs a store kept in parallel with the
thing it describes.

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
never retries `exhausted`** -- the same step against the same wall is
deterministic, so a second run is waste that costs a full budget to learn
nothing.

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
  answer.
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
being claimed, and how it is tested. Whether the implementation currently keeps
each one is recorded in [`gap_analysis.md`](gap_analysis.md).

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

This is P-2 ("one machine-readable source per concern") applied to the pipeline
itself. It matters most for allowed commands: a permission defined in two places
is a security property that holds in one reading and not the other, and a second
definition is easy to add without noticing -- a constant in the orchestrator, a
line in an agent's frontmatter, a grant in a settings file.

**Selection by classification.** A work item's classification -- `bug`, `toil`,
`enhancement`, `feature`, `spike` -- does not change what a step does; the same
`coder` runs the same way regardless of it. It is allowed to change exactly one
thing: which flow a work item enters, declared as a `classification`
restriction on a flow's trigger. That is the mechanism flow selection needs.
Selection is positive (a flow's trigger states what it matches; there is no
exclude list to forget one entry of), so keeping `spike` out of the default flow
means the default flow's classification list omits it, or a dedicated flow
claims it -- not a rule written elsewhere that has to be kept in sync. `bug`,
`enhancement`, `feature` and `toil` currently share the one default flow and run
identically; nothing today needs them to diverge, so nothing declares that they
do. A repository is free to add a flow restricted to a subset of them if it ever
needs one to behave differently, but the mechanism existing is not an invitation
to use it without a reason.

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
absence is the ordinary case meaning "the default, entirely".

That matters more than it sounds. A file seeded empty into every repository
would sit exactly where a reader expects the pipeline to be defined while
defining nothing, and would be the obvious place to edit for anyone who had not
read this. Absent, there is one definition to find; present, it is present
because someone decided something.

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
invocation genuinely has a person present. That is true by construction today,
because the interactive path exists only inside a chat session. If anything ever
invokes the orchestrator non-headlessly without a human, this guarantee
disappears silently -- so the orchestrator refuses to record an approval when it
cannot establish that a person is there.

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

**Why the distinction is load-bearing, not cosmetic.**

`/maos-{agent}` is the pipeline. Same prompt, same allowed commands, same clean
context, same enforcement. What you see is what the headless runner would do,
which is the only thing that makes it useful for reproducing a problem.

`/maos-{agent}-i` is **not the pipeline**, and does not pretend to be. You and
the chat-AI work through the agent's instructions together, in your session,
with your permissions and your context. Nothing is enforced against an agent's
allowlist, because no agent is running -- a person is, with an assistant.

**It still advances the pipeline.** Not being an agent invocation does not make
it a private exercise. The step was performed and it produced something, so it
returns its result the way every step does, and the orchestrator records it: the
label transition, the artefact comment, the observed change. Work done in the
loop lands on the issue exactly as work done by a spawned agent -- because
nothing that influenced the work may exist only in a chat transcript.

**What the record must carry is how it was produced.** The result says that a
person performed the activity rather than a spawned agent. Enforcement did not
apply, the context was the session's, and a human could intervene at any point,
so an in-the-loop run is a legitimate way to move an issue forward and is not
evidence of what the pipeline would do unattended. Recording the provenance is
what keeps both of those true at once, and it is what lets a conformance check
tell the two apart instead of trusting a naming convention.

That last point resolves what would otherwise be a contradiction with MI-3.
Enforcement must be one mechanism, and it is: the platform's own, on the spawn
path. The in-the-loop command needs no second enforcement mechanism because it
is not an agent invocation to enforce. The control there is the person, who is
present, whose session it is, and who is accountable for what they run.

**The risk this creates, stated plainly.** Someone reaches for the `-i` command
believing they are testing what the pipeline does. They are not: different
context, different permissions, a human able to intervene. The naming carries
that distinction and must stay obvious. The recorded provenance is the backstop:
the trail says which runs were driven by hand, so a mistaken belief in the chat
does not become a mistaken conclusion from the record.

---

### How people interact with it

**In headless mode, GitHub is the only channel.** You add labels and write
comments on the issue. There is nobody to talk to and nothing else to use. Every
instruction you can give the pipeline is expressible as a label or a comment,
because that is the entire interface.

**In interactive mode you can also talk to the chat-AI**, in your own words --
feedback, corrections, instructions, questions. The chat-AI then writes the
labels and comments that carry your intent to the pipeline. You are not bypassing
GitHub; you are dictating to something that writes GitHub for you.

Two consequences follow, and both matter.

The **record is identical**. Whatever you say in the chat ends up on the issue as
a label or a comment, so an issue driven interactively is indistinguishable, as
a record, from one driven headlessly. Nothing that influenced the work exists
only in a chat transcript.

The **chat-AI is a scribe, not a decision-maker**. When it applies a gate label
it is transcribing a decision you made, and it may never originate one. That
distinction is the whole of MI-7, and it is the reason a blanket "no bot may
apply a gate label" rule is wrong: it would forbid the supported interactive
path along with the thing it means to prevent.

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
| How many items advance at once | Several, where their components do not overlap | One | A session is one conversation and a person drives one issue through it; there is no second conversation to drive a second issue. What differs is throughput, never what happens to any one item -- an issue driven either way leaves the same trail |

Everything else is governed by the promises above and must be identical.

Two things are often mistaken for legitimate differences and are not:

- **How permissions are enforced** (MI-3). Whether a mode can use the platform's
  own enforcement is a consequence of how it starts agents, which is a choice,
  not a constraint.
- **Which errors can be recovered from.** A refused query and a refused
  repository are different failures needing different responses, but which one
  you get must never depend on how the work was started.

---

## Status of this document

| Topic | Authoritative source | State |
|---|---|---|
| Core requirements | this document | draft |
| The state machine and activity shape | this document | draft |
| How a step is told where it is | this document | draft |
| How it uses agents, and the step contract | this document | draft -- supersedes parts of `12-agent-spec.md` |
| The promises (AS-1 to AS-3, MI-1 to MI-8) | this document | draft |
| Headless and interactive | this document | draft -- supersedes `17-operating-modes.md` |
| Conformance and traceability | [`gap_analysis.md`](gap_analysis.md) | current |
| Vision and problem | this document | draft |
| Principles P-1 to P-16 | `02-principles.md` | not yet superseded |
| Pipeline configuration, target shape | [`schema/pipeline.schema.json`](schema/pipeline.schema.json) | current |
| Pipeline configuration, as it exists today | `pipeline.json` itself (AS-1); `05-pipeline-config.md` documents its current schema | not yet superseded |
| The process itself -- which flows exist, their phases and forks | [`04-lifecycle.md`](04-lifecycle.md) | **stays there by design.** This document says the orchestrator can run whatever flows `pipeline.json` declares; which flows those are, and why, is process |
| Status model, gates | `06`, `07` | not yet superseded |
| Orchestrator responsibilities | `11-orchestrator.md` | not yet superseded |
| Agent specification | `12-agent-spec.md` | partially superseded |
| Standards model | `14-standards.md` | not yet superseded |
