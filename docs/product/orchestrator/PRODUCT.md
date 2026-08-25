# The Orchestrator Product

The single description of what the orchestrator is and what it promises.

This document is being authored from first principles as the target design
(issue #393). It supersedes the numbered documents `01-vision.md` through
`17-operating-modes.md` section by section as it is written; until a section
exists here, the numbered document remains authoritative for that topic. The
[status table](#status-of-this-document) records which is which.

Every promise below states how it is tested and whether the system keeps it
today. A promise with no test is not a promise, and is marked as such.

---

## Contents

- [What the orchestrator is](#what-the-orchestrator-is)
- [The promises](#the-promises)
- [Working two ways](#working-two-ways)
- [What is allowed to differ](#what-is-allowed-to-differ)
- [Which promises we keep today](#which-promises-we-keep-today)
- [Status of this document](#status-of-this-document)

---

## What the orchestrator is

You describe a piece of work as a GitHub issue. The orchestrator walks it
through the steps that turn an issue into shipped code -- writing the
requirements, drafting the design, building it, reviewing it -- using an AI
agent for each step. You approve at named points along the way.

Everything it does is recorded on the issue itself. The labels on an issue tell
you exactly where it has got to. There is no separate dashboard, no database,
and no hidden state: if you can read the issue, you know the position.

It runs two ways. **Overnight**, unattended, moving work forward while nobody is
watching. Or **live**, in a session at your keyboard, where you drive it one step
at a time and answer approvals immediately. Both are the same product.

---

## The promises

Nine promises. Each is written first as what it means for you, then as the
precise property an engineer can test.

They exist because most of what has gone wrong with this system has been a
promise nobody had written down. Of the 27 defects filed between 15 and 25
August 2026, **11 were the two ways of running behaving differently** -- more
than any other cause. Nothing said they had to match, so nothing noticed when
they stopped.

---

### AS-1 -- One file tells you what the pipeline does

> **You can read one file and know what will happen: which steps run, in what
> order, what has to finish first, and what each step is allowed to touch.
> Nothing behaves in a way that file does not describe.**

**Without it,** the real behaviour lives partly in a config file and partly
somewhere else, so the honest answer to "what will this do?" becomes "read the
code and find out". Worse, when two places disagree about what a step may touch,
a permission you thought you had removed is still in force somewhere.

**Precisely.** `pipeline.json` is the authoritative definition of four concerns
and nothing else defines any of them:

| Concern | What it covers |
|---|---|
| **Process** | Which steps exist, what each one is, and which phase it belongs to |
| **Sequence** | What triggers a step and what it emits |
| **Dependencies** | What must have completed before a step is eligible |
| **Entitled activities** | What each step is permitted to do -- tools, commands, environment |

This is P-2 ("one machine-readable source per concern") applied to the pipeline
itself.

**Test.** The resolved entitlement set for every step is derivable from
`pipeline.json` alone. Any entitlement that cannot be traced to it is a test
failure. The same for triggers and dependencies.

**Today:** `VIOLATED` for entitlements; `KEPT` for process, sequence and
dependencies. Entitlements come from four places:

| Source | Size | Kind |
|---|---|---|
| `BASE_AGENT_TOOLS`, `pipeline_orchestrator.py:2712` | 28 entries | Python constant |
| Agent frontmatter `tools:` | 14 agent files | Prompt metadata |
| `pipeline.json` defaults + per-step | 2 + 8 steps | Configuration |
| `.claude/settings.json` `permissions.allow` | 1 entry | Session config |

The largest block is hardcoded, not configured. Three defects trace to the
split: **#326** was a defect in `BASE_AGENT_TOOLS` itself, **#362** is a defect
in the `settings.json` path, **#356** was drift between sources during
resolution. #357 already proposes this fix and predates this document.

---

### MI-1 -- An issue means the same thing to everyone

> **The labels on an issue tell you where the work has got to, and they mean
> the same thing whether a person or the scheduler put them there.**

**Without it,** you cannot trust what you are looking at. The same label on two
issues means two different things depending on history you cannot see.

**Precisely.** No label is specific to one way of running, and no step
interprets a label differently depending on which actor applied it.

**Test.** Every label in `statuses.json` has exactly one documented meaning, and
no step's behaviour branches on who applied it.

**Today:** `PARTIAL, UNTESTED`. Labels are shared and none is mode-specific, but
nothing enforces it, and #380 shows a case where meaning depends on step
configuration rather than on the label: `:review` means "waiting for a named
approval" for most steps and "stuck with no way out" for a step that names no
approval.

---

### MI-2 -- The same situation always produces the same next step

> **Two people looking at the same issue get the same answer about what happens
> next. So does the scheduler.**

**Without it,** the pipeline is unpredictable in the way that matters most: you
cannot tell someone what will happen when they approve something.

**Precisely.** Given identical state, both ways of running select the same next
step. Routing is computed in exactly one place. A driver may read the pipeline
definition to explain what will happen, never to decide it.

**Test.** Run the resolver and the real dispatch path over the same issue state
and assert identical selection, for every step.

**Today:** `VIOLATED`. `/maos-run` correctly leaves routing to the orchestrator,
but `/run-agent` resolves invocation parameters through a separate path. #356 is
that drift realised -- it returned 24 tools where the real run passes 93. It was
fixed; the duplicated path remains and nothing tests the two against each other.

---

### MI-3 -- An agent can only ever do what you allowed

> **The limits on what an agent can touch are the same limits however the work
> was started. There is no looser path.**

**Without it,** a restriction you rely on holds when the scheduler runs the work
and quietly does not when you run it yourself. You would have no way to tell
from the outside.

**Precisely.** Whatever constrains an agent's actions is the **same mechanism**
in both ways of running, not an equivalent one. No mode re-implements another
mode's enforcement.

**Test.** Exactly one component decides whether an action is permitted, and both
ways of running route through it. A second implementation is a test failure, not
a design choice.

**Today:** `VIOLATED`, and this is the expensive one. Running overnight uses the
platform's own enforcement when it starts an agent. Running live cannot, because
`/run-agent` executes agent instructions inside the caller's own session -- so it
re-implements enforcement in shell script: an allowlist written to a file, a
hook on every action, and a command parser. `run-agent.md` says as much in its
own words.

That re-implementation has produced five defects: **#335** (blocked everything),
**#356** (dropped permissions), **#374** (two live runs overwrote each other's
limits -- `[SECURITY]`), **#383** (refuses 31% of all agent instructions),
**#388** (the limits may never load at all).

**The cheapest way to keep this promise is deletion, not repair.** If the live
path started agents the same way the overnight path does, the platform's own
enforcement would apply and the whole re-implementation could be removed. What
would be lost is watching the agent work in your session. That trade-off has not
been evaluated; it is the central question for #393.

**Note.** AS-1 and MI-3 are two halves of one property. AS-1 says permissions are
*written down* in one place. MI-3 says they are *enforced* by one mechanism.
Either alone still leaves room for disagreement.

---

### MI-4 -- Nothing gets stuck with no way out

> **Every state the work can reach has a way forward that you can actually
> perform -- at your desk or overnight.**

**Without it,** work silently parks somewhere with no exit, and recovering it
means someone editing state by hand outside the system, which nobody sees and
nothing records.

**Precisely.** Any state a run can enter has a documented exit performable in
both ways of running. A state reachable one way and escapable only the other is
a defect.

**Test.** Every status in `statuses.json` where `blocks_pipeline` is true names
a `cleared_by`, that exit is reachable from the step's own configuration, and it
is performable both unattended and in-session.

**Today:** `VIOLATED`, three ways -- but not in the way it first appears.

`statuses.json` already names two exits for `:review`: *"orchestrator (on
gate-label application) or human (removes label)"*. The second is a genuine
documented exit, so removing the label is not the out-of-band hack it looks
like.

The defect is narrower and worse. **#380** -- when a step emits `:review`
without naming a gate, the *first* exit does not exist for it: there is no label
to apply. Only the human-removes-label exit remains, and neither the
orchestrator nor `/maos-run` mentions it. The tooling documents the exit that is
unavailable and stays silent about the one that works, so the issue reads as
permanently stuck. That happened twice on 25 August. **#377** -- the live driver
is documented to record its own approval, but the self-approval guard rejects
it, so the documented procedure cannot work. **#314** -- the emergency stop has
no defined behaviour for live runs.

The lesson generalises: the machine-readable source held more truth than the
prose describing it. That is the argument for generating these views rather than
authoring them.

---

### MI-5 -- The result does not depend on who was watching

> **A step does the same thing whether you watched it or not. The trail on the
> issue records the work, not who was present.**

**Without it,** the artefact trail stops being evidence. You cannot compare two
issues, because they were produced under different conditions.

**Precisely.** The side effects of a step -- labels, comments, commits,
artefacts -- are identical in both ways of running and occur in the same order.
A mode may differ in **who triggers** a step, never in **what the step does**.

**Test.** Run the same step both ways against equivalent state and diff the
resulting issue timeline, ignoring timestamps and actor.

**Today:** `UNTESTED`. No known violation and no test. Listed because its
absence would be invisible until it mattered.

---

### MI-6 -- You can always tell what actually happened

> **Every check says whether it ran and what it decided. Nothing reports
> success while doing nothing.**

**Without it,** a green tick means nothing. This is the promise whose absence
has cost the most: when a control fails by claiming success, every signal
downstream of it -- passing tests, a clean review, a completed step -- is
evidence of nothing at all.

**Precisely.** Every control reports whether it engaged and what it decided, in
both ways of running, in the same form. No control is silent one way and loud
the other, and none is silent in both.

**Test.** Every control emits a decision line on both the engaged and the
skipped path, and the two ways of running produce the same line.

**Today:** `VIOLATED`, and this is the widest failure. Nine of the 27 defects
report success while doing nothing: #308, #315, #343, #346, #358, #362, #378,
#387, #388. Several are additionally one-sided -- #346 misreports only live,
#326 blocked agents only overnight, #334 failed only in restricted sessions.

---

### MI-7 -- Only a person approves

> **An approval needs a human decision, recorded the same way every time. The
> system cannot approve itself, and cannot be tricked into it by timing.**

**Without it,** the approval gates are decoration. The whole basis of the
product is that people decide and agents draft.

**Precisely.** A gate requires a human decision recorded through the same
mechanism in both ways of running. Neither may self-approve, and neither may
record approval in a way the other cannot read.

**Test.** A gate label applied by a non-human actor is rejected both ways; one
applied by a human is honoured both ways.

**Today:** `VIOLATED`, twice over. The guard correctly rejects agent-applied
approvals -- but the live driver has no other way to record a decision, so it
cannot cross a gate at all (#377). And the guard **fails open**: when GitHub's
timeline has not yet caught up, it logs `no 'labeled' event found ... allowing
(fail-open)` and lets the approval through. Timeline reads are eventually
consistent, so an agent-applied approval passes under lag. Both were observed on
25 August.

---

### MI-8 -- Any difference is written down

> **There is a short list of things that differ between running overnight and
> running live. Anything not on that list is a bug.**

**Without it,** the two ways drift apart one reasonable accommodation at a time,
each invisible, until they are different products. That is what happened here.

**Precisely.** Anything that legitimately differs is listed in
[What is allowed to differ](#what-is-allowed-to-differ) with a reason. An
unlisted difference is a defect, not a feature.

**Test.** Every mode-conditional branch in the orchestrator, the scripts and the
agent prompts maps to a listed difference.

**Today:** `PARTIAL`. `17-operating-modes.md` lists differences, but as things
that happen to be true today rather than differences argued to be permanent.
Nothing distinguishes an intended difference from an unrepaired defect.

---

## Working two ways

**Overnight.** GitHub Actions starts the orchestrator when an issue or pull
request changes, or on a timer. Nobody is watching. Work moves forward while the
team sleeps, and approvals wait for whoever next looks. This is the primary way
it runs.

**Live.** You run `/maos-run {N}` in a session and drive one issue forward step
by step, watching each agent work and answering approvals as they arrive. This is
how work gets unblocked, debugged, and pushed when someone is at the keyboard.

You must be able to start an issue one way, walk away, and have the other finish
it, with no difference in the result. That is what the nine promises above are
for.

---

## What is allowed to differ

The complete list. Anything not here is a defect.

| Difference | Overnight | Live | Why this is legitimate |
|---|---|---|---|
| Who starts a step | A GitHub event or a timer | A person running `/maos-run` | This is the whole point of having two ways |
| Where you watch it | Issue and pull-request activity | The same, plus live agent output | What you see is not what happened; the trail is identical |
| Which credentials are used | Repository secrets | The session's own login | The environments genuinely differ; the *authority* those credentials carry must not |
| How long an approval waits | Until someone next looks | Immediately | A person being present is the difference |

Everything else is governed by the promises above and must be identical.

Two things are often mistaken for legitimate differences and are not:

- **How permissions are enforced** (MI-3). That the live path cannot use the
  platform's own enforcement today is a consequence of how it starts agents,
  which is a choice, not a constraint.
- **Which errors can be recovered from.** A refused query and a refused
  repository are different failures needing different responses, but which one
  you get must never depend on how the work was started.

---

## Which promises we keep today

| Promise | Today | Defects |
|---|---|---|
| AS-1 One file tells you what the pipeline does | VIOLATED (permissions) | #326, #356, #362 |
| MI-1 An issue means the same thing to everyone | PARTIAL, UNTESTED | #380 |
| MI-2 Same situation, same next step | VIOLATED | #356 |
| MI-3 An agent can only do what you allowed | VIOLATED | #335, #356, #374, #383, #388 |
| MI-4 Nothing gets stuck with no way out | VIOLATED | #377, #380, #314 |
| MI-5 The result does not depend on who watched | UNTESTED | none known |
| MI-6 You can always tell what happened | VIOLATED | #308, #315, #326, #334, #343, #346, #358, #362, #378, #387, #388 |
| MI-7 Only a person approves | VIOLATED | #377 |
| MI-8 Any difference is written down | PARTIAL | -- |

**Seven of nine are broken or unverified, and none has a test.**

That is the first thing to change. Until each promise has a test, this document
says what the product ought to do rather than describing what it does -- and the
defects keep arriving by surprise instead of being derived from the gap.

---

## Status of this document

| Topic | Authoritative source | State |
|---|---|---|
| What the orchestrator is | this document | draft |
| The promises (AS-1, MI-1 to MI-8) | this document | draft |
| Working two ways | this document | draft -- supersedes `17-operating-modes.md` |
| Vision and problem | `01-vision.md` | not yet superseded |
| Principles P-1 to P-16 | `02-principles.md` | not yet superseded; three known contradictions |
| Pipeline configuration | `pipeline.json` itself (AS-1); `05-pipeline-config.md` documents its schema | not yet superseded |
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
