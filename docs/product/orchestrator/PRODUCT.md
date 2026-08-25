# The Orchestrator Product

The single description of what the orchestrator is and what it promises.

This document describes the target design (issue #393). It states what the
product does, not what the implementation currently manages -- the gap between
the two is tracked separately in [`gap_analysis.md`](gap_analysis.md).

---

## Core requirements

Read these together. Everything after this section is detail.

**Work is a GitHub issue, and the issue is the record.** You describe a piece of
work as an issue. The orchestrator walks it through the steps that turn an issue
into shipped code, and everything it does is written back to that issue. There
is no dashboard, no database, no hidden state. If you can read the issue, you
know exactly where the work has got to.

**The orchestrator is a state machine.** The labels on the issue are the state.
Steps are the transitions between states. The machine is deterministic: given
the same labels it always chooses the same next step, and that choice is
computed by code, never by a model.

**Every activity has the same four parts.** Each step declares the commands it
is allowed to run, the deterministic work that happens before it, the activity
itself, and the deterministic work that happens after. The activity is either an
AI agent or a script; the work before and after is always scripts. So a step
whose activity is a script is deterministic end to end, and only a step with an
agent has any uncertainty in it at all. Commands every step needs are declared
once, globally, rather than repeated on each step.

**A step is told everything it needs to know.** Each step runs as a separate
process and learns its situation entirely from environment variables the
orchestrator sets: where the repository is, what it is working on, where to put
working files, and whether a human is attached to it. A step never works its own
context out, and never probes to find out.

**The orchestrator coordinates and nothing else.** It reads the state, picks the
next step, runs it, and records what happened. Every piece of work that produces
or changes anything is a step, a pre-action or a post-action -- all of them
scripts or agents. No value-add work lives in the orchestrator. Changing the
process means changing `pipeline.json` and the scripts it names; it should not
mean changing the orchestrator.

**One file defines the process.** `pipeline.json` says which steps exist, what
starts each one, what must finish first, and what each is permitted to do.
Nothing behaves in a way that file does not describe, and nothing else defines
any of those four things.

**Agents produce; they never decide.** An agent is a black box that receives a
work item and returns a result. It cannot choose what runs next, cannot set its
own state, cannot approve anything, and cannot act outside the commands it was
allowed. Its only influence on the machine is a single status value from a fixed
set.

**Agents are not deterministic, and the design assumes it.** The same prompt can
produce different work on different runs. That is contained by keeping every
consequential decision in code, so a poor run costs one step, is visible on the
issue, and cannot corrupt anything.

**An agent that cannot comply says so.** Being blocked, running out of budget,
or finishing only part of the work are distinct outcomes and each is reported as
itself. An agent never substitutes a different approach and reports success,
because a silent workaround is an unrecorded change to the process.

**Only a person approves.** Named gates require a human decision, recorded the
same way every time. The system cannot approve itself, and an approval check
that cannot reach a conclusion refuses rather than admits.

**People speak to the pipeline through GitHub, or through the chat.** In
headless mode the issue is the only channel: you add labels and write comments,
and that is the whole of the interface. In interactive mode you can also talk to
the chat-AI in your own words, and it writes the labels and comments for you.
The record is identical either way -- the difference is whether you write it
yourself or dictate it.

**Nothing gets stuck.** Every state the work can reach has a way forward that
someone can actually perform. A halt is a pause, never a loss.

**Every control says what it did.** Each check reports whether it engaged and
what it decided. Nothing reports success while doing nothing, because a control
that fails quietly makes every signal after it meaningless.

**It runs two ways, and they behave identically.** Headless as a continuous
background process on GitHub Actions, or interactive inside a chat session in
Claude Code. You can start work in one, walk away, and let the other finish it.
The short list of things that legitimately differ is written down; anything else
that differs is a bug.

---

## Contents

- [The state machine](#the-state-machine)
- [How the orchestrator tells a step where it is](#how-the-orchestrator-tells-a-step-where-it-is)
- [How it uses agents](#how-it-uses-agents)
- [The agent contract](#the-agent-contract)
- [The promises](#the-promises)
- [Headless and interactive](#headless-and-interactive)
- [What is allowed to differ](#what-is-allowed-to-differ)
- [Status of this document](#status-of-this-document)

---

## The state machine

The labels on a work item are the state. A step is a transition. The orchestrator
reads the labels, selects the one step whose conditions are met, runs it, and
writes the outcome back as a label.

Because state lives on the work item, any orchestrator process reading it
reaches the same conclusion. There is nothing to synchronise, nothing to
recover, and no position that exists only in memory.

### Every activity has the same four parts

| Part | What it is | Determinism |
|---|---|---|
| `allowed_commands` | Everything this activity may do. Anything else is refused | Data |
| `pre_actions` | Work performed before the activity -- checking out the branch, preparing the scratch directory | Code |
| `activity` | The step itself: an AI agent, or a script | Deterministic when a script; **not deterministic when an agent** |
| `post_actions` | Work performed after -- committing, pushing, labelling, posting the artefact | Code |

Three of the four parts are always code or data. The fourth is code too, unless
the step uses an agent -- so uncertainty enters the system at exactly one place,
and only for the steps that need judgement. A step whose activity is a script is
deterministic from end to end.

Commands every step needs are declared once as `global_allowed_commands` rather
than repeated on each step. A step's effective permission is exactly the global
set plus its own `allowed_commands`, and nothing else. Two levels, both in
`pipeline.json`, both readable in one place -- which is what keeps AS-1 true as
the pipeline grows.

This is where the design contains its own uncertainty. Permission is decided
before the activity runs and cannot be widened by it. The setup and the
consequences run as pre- and post-actions on either side of the agent, on the
orchestrator's schedule rather than at the agent's request. What the agent
actually influences is the work product and one status value -- and nothing else
in the system depends on the agent having behaved reasonably.

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

So `AI_AGILE_EXECUTION_MODE` answers the second question and is `headless` for
every spawned activity, always. The first question is the orchestrator's own,
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

## The agent contract

Binds every step whose activity is an agent, in both modes. An agent that does
not meet this is not a different kind of agent -- it is a defect.

A step whose activity is a script is bound by the same contract, and meets most
of it by construction: a script cannot replay a previous answer or improvise
past a refusal. What it must still do is return one status, keep its files where
they belong, and report honestly when it did nothing -- which is exactly where
`commit-agent-work.sh` and `merge-docs-pr.sh` have failed.

### What the orchestrator provides

| Provided | Guarantee |
|---|---|
| **One work item** | Exactly one issue or PR. The agent never chooses its own subject |
| **Its allowed commands** | Everything the agent may do, complete and enforced. An action outside the set is refused, not merely discouraged |
| **A scratch directory** | An existing, writable path for working files, prepared before the agent starts and removed after |
| **A turn budget** | A bounded number of turns, known to be enough for the step's declared work |
| **Its instructions** | A prompt whose every instruction is executable under the commands allowed |

### What the agent must return

| Returned | Requirement |
|---|---|
| **Exactly one terminal status** | From the fixed set in `statuses.json`. Never absent, never two, never invented |
| **Its artefacts, on the work item** | Posted to the issue or PR, append-only. A re-run adds; it never rewrites |
| **Its files, in the repository or scratch** | Real work in the tree, working files in scratch. Nothing anywhere else |

### What the agent must never do

- **Decide what runs next.** Routing belongs to the orchestrator.
- **Apply its own lifecycle labels.** `:wip`, `:complete`, `:review`, `:failed`
  are the orchestrator's record of the agent, not the agent's own claim.
- **Approve a gate.** Agents draft, humans decide (P-10). No exceptions, in
  either mode.
- **Act outside its allowed commands**, or route around a refusal.
- **Depend on state from a previous run** that is not on the work item or in
  git. There is no memory between invocations beyond what is recorded.

### What the agent must do when it cannot comply

These obligations are what make a non-deterministic worker safe to depend on.
They matter more than the happy path, because an agent that fails quietly is
indistinguishable from one that succeeded.

- **Blocked means say so.** An agent that cannot perform an instruction reports
  it and stops. It does not substitute a different approach and report success.
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

Ten promises. Each states what it means for you, why it matters, and how it is
tested. Whether the implementation currently keeps each one is recorded in
[`gap_analysis.md`](gap_analysis.md).

---

### AS-1 -- One file tells you what the pipeline does

> **You can read one file and know what will happen: which steps run, in what
> order, what has to finish first, and what each step is allowed to touch.
> Nothing behaves in a way that file does not describe.**

`pipeline.json` is the authoritative definition of four concerns, and nothing
else defines any of them:

| Concern | What it covers |
|---|---|
| **Process** | Which steps exist, what each one is, and which phase it belongs to |
| **Sequence** | What triggers a step and what it emits |
| **Dependencies** | What must have completed before a step is eligible |
| **Entitled activities** | `global_allowed_commands`, plus each step's `allowed_commands`, `pre_actions` and `post_actions` |

This is P-2 ("one machine-readable source per concern") applied to the pipeline
itself. It matters most for allowed commands: a permission defined in two places
is a security property that holds in one reading and not the other, and a second
definition is easy to add without noticing -- a constant in the orchestrator, a
line in an agent's frontmatter, a grant in a settings file.

**Test.** The resolved command set for every step is derivable from
`pipeline.json` alone. Any permission that cannot be traced to it is a test
failure. The same for triggers and dependencies.

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

**Precisely.** Whatever enforces `allowed_commands` is the **same mechanism** in
both modes, not an equivalent one. Neither mode re-implements the other's
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

**Test.** Every status in `statuses.json` where `blocks_pipeline` is true names
a `cleared_by`, that exit is reachable from the step's own configuration, and it
is performable in both modes.

---

### MI-5 -- The result does not depend on who was watching

> **A step does the same thing whether you watched it or not. The trail on the
> issue records the work, not who was present.**

If effects vary by mode, the artefact trail stops being evidence: two issues
cannot be compared, because they were produced under different conditions.

**Precisely.** A step's `pre_actions`, `activity` and `post_actions` produce the
same effects in both modes, in the same order. A mode may differ in **who
triggers** a step, never in **what the step does**.

**Test.** Run the same step in both modes against equivalent state and diff the
resulting issue timeline, ignoring timestamps and actor.

---

### MI-6 -- You can always tell what actually happened

> **Every check says whether it ran and what it decided. Nothing reports
> success while doing nothing.**

A control that fails by claiming success poisons everything downstream of it:
passing tests, a clean review and a completed step all become evidence of
nothing. Silence and success must never look the same.

**Precisely.** Every control reports whether it engaged and what it decided, in
both modes, in the same form. No control is silent in one and loud in the other,
and none is silent in both.

**Test.** Every control emits a decision line on both the engaged and the
skipped path, and both modes produce the same line.

---

### MI-7 -- Only a person approves

> **An approval needs a human decision, recorded the same way every time. The
> system cannot approve itself, and cannot be tricked into it by timing.**

Agents draft and humans decide (P-10) is the basis of the product. A gate
enforced differently in one mode is a gate not enforced, and a guard that admits
an approval when its check is inconclusive is a guard that fails at exactly the
moment it is needed.

**Precisely.** Three things are separate and must stay separate:

| | Requirement |
|---|---|
| **The decision** | Always a person's, in both modes. Nothing else may originate it |
| **The record** | Always the same gate label, in both modes, readable by either |
| **The hand that writes it** | The person in headless mode; the chat-AI, on the person's instruction, in interactive mode |

The third line is why "no bot may apply a gate label" is the wrong rule. In
interactive mode the chat-AI writing the label **is** the supported path -- it
is transcribing a decision, not making one. The rule that must hold is narrower
and harder: **an agent may never originate an approval, and the system must be
able to tell transcription from origination.**

Both look identical at the point of writing -- a non-human actor applying a
label -- so the distinction has to be carried by something other than the actor.
An inconclusive check refuses.

**Test.** A gate label originated by an agent is rejected in both modes. A gate
label carrying a human decision is honoured in both, whether the person or the
chat-AI wrote it. An unresolvable check refuses rather than admits.

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
finish it, with no difference in the result. That is what the ten promises
above are for.

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
| Who writes the label | The person | The person, or the chat-AI transcribing them | The decision is the person's either way (MI-7) |

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
| How it uses agents, and the agent contract | this document | draft -- supersedes parts of `12-agent-spec.md` |
| The promises (AS-1, AS-2, MI-1 to MI-8) | this document | draft |
| Headless and interactive | this document | draft -- supersedes `17-operating-modes.md` |
| Conformance and traceability | [`gap_analysis.md`](gap_analysis.md) | current |
| Vision and problem | `01-vision.md` | not yet superseded |
| Principles P-1 to P-16 | `02-principles.md` | not yet superseded |
| Pipeline configuration | `pipeline.json` itself (AS-1); `05-pipeline-config.md` documents its schema | not yet superseded |
| Lifecycle, status model, gates | `04`, `06`, `07` | not yet superseded |
| Orchestrator responsibilities | `11-orchestrator.md` | not yet superseded |
| Agent specification | `12-agent-spec.md` | partially superseded |
| Standards model | `14-standards.md` | not yet superseded |
