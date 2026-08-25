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

**A command names something; it does not do something.** Every `/maos-*`
command is a thin wrapper that says what to run and passes along what you typed.
Procedure written into a command is logic living where nothing can test it and
the headless path cannot reuse it.

**One file defines the process.** `pipeline.json` says which steps exist, what
starts each one, what must finish first, and what each is permitted to do.
Nothing behaves in a way that file does not describe, and nothing else defines
any of those four things.

**Steps produce output; the orchestrator posts it.** Every step, agent or
script, returns what it produced and a summary of what it did. The orchestrator
writes those to the issue as structured comments. A step never posts anything
itself, so there is exactly one thing writing to GitHub and exactly one format
to read.

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
that cannot reach a conclusion refuses rather than admits. Rather than trying to
detect an agent approving itself, the design makes it unreachable: in headless
mode only a person can cross a gate, and in interactive mode only the
orchestrator records one -- and an agent can reach neither.

**People speak to the pipeline through GitHub, or through the chat.** In
headless mode the issue is the only channel: you add labels and write comments,
and that is the whole of the interface. In interactive mode you can also talk to
the chat-AI in your own words, and it writes the labels and comments for you.
The record is identical either way -- the difference is whether you write it
yourself or dictate it.

**Nothing gets stuck.** Every state the work can reach has a way forward that
someone can actually perform. A halt is a pause, never a loss.

**Every step says what it did, and the orchestrator checks.** Each step reports
what it did including when it did nothing, and the orchestrator separately
records what actually changed. Where the account and the evidence disagree, you
are told -- because a step that reports success while doing nothing makes every
signal after it meaningless.

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

| Part | Declared in `pipeline.json` as | What it is | Determinism |
|---|---|---|---|
| Allowed commands | `extra_allowedTools` | Everything this activity may do. Anything else is refused | Data |
| Pre-actions | `defaults.agent_lifecycle.before` | Work performed before the activity -- checking out the branch, preparing the scratch directory | Code |
| The activity | `type` with `agent` or `script` | The step itself: an AI agent, or a script | Deterministic when a script; **not deterministic when an agent** |
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
| **A summary of what it did** | Its own account, in plain words, including when it did nothing |
| **Its output** | Whatever the step produces -- a review, a classification, a plan. Returned, not posted |
| **Its files, in the repository or scratch** | Real work in the tree, working files in scratch. Nothing anywhere else |

The orchestrator writes the summary and the output to the issue as structured
comments. The step does not.

### What the agent must never do

- **Write to the issue or PR.** No comments, no edits, no labels. A step returns
  what it produced and the orchestrator records it. Exactly one thing writes to
  GitHub, so there is one format, one failure path, and one place where
  append-only is enforced.
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

Eleven promises. Each states what it means for you, why it matters, and how it is
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
| **Entitled activities** | `defaults.extra_allowedTools`, plus each step's `extra_allowedTools`, lifecycle actions and post-steps |

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

Each step also declares in `pipeline.json` what effect it is *expected* to have.
`coder` produces commits; `pr-reviewer` produces none. That makes the comparison
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
evidence and expectation do not agree. Both modes produce the same records.

---

### MI-7 -- Only a person approves

> **An approval needs a human decision, recorded the same way every time. The
> system cannot approve itself, and cannot be tricked into it by timing.**

Agents draft and humans decide (P-10) is the basis of the product. A gate
enforced differently in one mode is a gate not enforced, and a guard that admits
an approval when its check is inconclusive is a guard that fails at exactly the
moment it is needed.

**Precisely.** Two things are separate and must stay separate:

| | Requirement |
|---|---|
| **The decision** | Always a person's, in both modes. Nothing else may originate it |
| **The record** | Always the same gate label, in both modes, readable by either |

The obvious rule -- "no bot may apply a gate label" -- does not work. In
interactive mode the chat-AI writing the label on the person's instruction is
the supported path: it is transcribing a decision, not making one. But
transcription and origination look identical at the point of writing, both being
a non-human actor applying a label, so no amount of actor-checking separates
them.

**So the design does not try to detect origination. It makes origination
unreachable.**

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

**This depends on one assumption, which must be asserted rather than trusted:**
that a non-headless invocation genuinely has a person present. That is true by
construction today, because the interactive path exists only inside a chat
session. If anything ever invokes the orchestrator non-headlessly without a
human, this guarantee disappears silently -- so the orchestrator must refuse to
record an approval when it cannot establish that a person is there.

**Test.** In headless mode, a gate label applied by any non-human actor is
rejected. In interactive mode, an approval recorded by the orchestrator on a
relayed human confirmation is honoured. No agent can cause either, in either
mode. An inconclusive check refuses rather than admits.

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

### Two ways to run a single agent

Interactive mode offers two different things, and they must not share a name.

| Command | What it does | Mode |
|---|---|---|
| `/maos-{agent} {N}` | Runs the **exact step**. The orchestrator resolves it and spawns it as a subprocess, exactly as the headless path does | `headless` |
| `/maos-{agent}-i {N}` | Resolves the step and works through its instructions **with you**, in the session | `interactive` |

The orchestrator already separates these. Resolving an invocation and spawning
it are distinct operations: the resolve-only path reports
`AI_AGILE_EXECUTION_MODE=interactive`, and the spawn path reports `headless`.
Both commands are thin wrappers over one of those two (AS-3), and both are
generated from `pipeline.json` so they cannot drift from it.

**Why the distinction is load-bearing, not cosmetic.**

`/maos-{agent}` is the pipeline. Same prompt, same allowed commands, same clean
context, same enforcement. What you see is what the headless runner would do,
which is the only thing that makes it useful for reproducing a problem.

`/maos-{agent}-i` is **not the pipeline**, and does not pretend to be. You and
the chat-AI work through the agent's instructions together, in your session,
with your permissions and your context. Nothing is enforced against an agent's
allowlist, because no agent is running -- a person is, with an assistant.

That last point resolves what would otherwise be a contradiction with MI-3.
Enforcement must be one mechanism, and it is: the platform's own, on the spawn
path. The in-the-loop command needs no second enforcement mechanism because it
is not an agent invocation to enforce. The control there is the person, who is
present, whose session it is, and who is accountable for what they run.

**The risk this creates, stated plainly.** Someone reaches for the `-i` command
believing they are testing what the pipeline does. They are not: different
context, different permissions, a human able to intervene. The naming carries
that distinction and must stay obvious, because nothing else prevents the
mistake.

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
| The promises (AS-1 to AS-3, MI-1 to MI-8) | this document | draft |
| Headless and interactive | this document | draft -- supersedes `17-operating-modes.md` |
| Conformance and traceability | [`gap_analysis.md`](gap_analysis.md) | current |
| Vision and problem | `01-vision.md` | not yet superseded |
| Principles P-1 to P-16 | `02-principles.md` | not yet superseded |
| Pipeline configuration | `pipeline.json` itself (AS-1); `05-pipeline-config.md` documents its schema | not yet superseded |
| Lifecycle, status model, gates | `04`, `06`, `07` | not yet superseded |
| Orchestrator responsibilities | `11-orchestrator.md` | not yet superseded |
| Agent specification | `12-agent-spec.md` | partially superseded |
| Standards model | `14-standards.md` | not yet superseded |
