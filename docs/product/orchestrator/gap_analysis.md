# Gap Analysis

What the implementation does today, measured against the target design in
[`PRODUCT.md`](PRODUCT.md).

`PRODUCT.md` states what the product is. This document states how far the code
is from it. Keeping them apart means the design can be read as a design, and the
gap can change without the design changing.

Current as of 25 August 2026, commit `37e3566` on `main`.

---

## Summary

| Promise | Status | Defects |
|---|---|---|
| AS-1 One file tells you what the pipeline does | VIOLATED (allowed commands) | #326, #356, #362 |
| AS-2 The orchestrator only coordinates | VIOLATED | #308, #387 |
| AS-3 A command names something, it does not do something | VIOLATED (4 of 16) | #377 |
| How a step is told where it is | PARTIAL | #314 |
| MI-1 An issue means the same thing to everyone | PARTIAL, UNTESTED | #380 |
| MI-2 Same situation, same next step | VIOLATED | #356 |
| MI-3 An agent can only do what you allowed | VIOLATED | #335, #356, #374, #383, #388 |
| MI-4 Nothing gets stuck with no way out | VIOLATED | #377, #380, #314 |
| MI-5 The result does not depend on who watched | UNTESTED | none known |
| MI-6 You can always tell what happened | VIOLATED | #308, #315, #326, #334, #343, #346, #358, #362, #378, #387, #388 |
| MI-7 Only a person approves | VIOLATED | #377 |
| MI-8 Any difference is written down | PARTIAL | -- |

**Nine of eleven are broken or unverified, and none has a test.**

That last point is the one to act on first. Until each promise has a test,
`PRODUCT.md` describes an intention rather than a property, and defects keep
arriving by surprise instead of being derived from this table.

The agent contract in `PRODUCT.md` has no conformance rows yet. It was written
after this analysis and nothing has been measured against it -- which is itself
a gap, and the likeliest place for the next round of defects, since the obligations
it states (blocked means say so, a re-run does the work again, out of budget is
its own outcome) are exactly the behaviours #358 and the `max_turns` failures
violated.

---

## AS-1 -- One file tells you what the pipeline does

**Status:** `VIOLATED` for allowed commands. `KEPT` for process, sequence and
dependencies.

Permissions come from four places, and the largest is hardcoded rather than
configured:

| Source | Size | Kind |
|---|---|---|
| `BASE_AGENT_TOOLS`, `pipeline_orchestrator.py:2712` | 28 entries | Python constant |
| Agent frontmatter `tools:` | 14 agent files | Prompt metadata |
| `pipeline.json` defaults + per-step | 2 + 8 steps | Configuration |
| `.claude/settings.json` `permissions.allow` | 1 entry | Session config |

Three defects trace directly to the split: **#326** was a defect in
`BASE_AGENT_TOOLS` itself (patterns failed to match quoted URLs, blocking agents
outright in headless mode); **#362** is a defect in the `settings.json` path (the
grant is silently dropped when the workspace is untrusted); **#356** was drift
between sources during resolution.

The target -- `defaults.extra_allowedTools` plus per-step `extra_allowedTools`,
both in `pipeline.json` and nowhere else -- is proposed in **#357**, which is
open and predates the design document. The field names stay as they are; what
changes is that no other source contributes.

---

## AS-2 -- The orchestrator only coordinates

**Status:** `VIOLATED`.

`pipeline_orchestrator.py` is 5,475 lines and performs value-add work directly
rather than delegating it to a step, a pre-action or a post-action:

| Work done in the orchestrator | Should be |
|---|---|
| `BASE_AGENT_TOOLS` -- 28 permission entries | Data in `pipeline.json` (AS-1) |
| Repo-root sweep -- deletes files an agent left behind | A post-action script |
| Scratch directory setup and teardown | Pre- and post-action scripts |
| Metrics ledger append | A post-action script |
| Deciding when to invoke `commit-agent-work.sh` | A declared post-action, run because the step declares it |

Only the last is arguable -- invoking a script is coordination -- but the
*condition* under which it runs is currently a rule inside the orchestrator
rather than a declaration in `pipeline.json`, which is how #308 and #387 became
possible: the rule was wrong, and no reader of the process definition could see
it.

The self-approval guard is genuinely coordination and belongs where it is.

**Consequence.** Evolving the process currently requires editing the one
component every step depends on. Several defects in the review window are
changes to the orchestrator that broke work unrelated to their purpose, which is
the specific risk AS-2 exists to remove.

**Test to add.** Adding, removing or reordering a step, or changing what a step
may do, requires no change to `pipeline_orchestrator.py`.

---

## AS-3 -- A command names something; it does not do something

**Status:** `VIOLATED` for four of sixteen `maos-*` commands.

The twelve generated wrappers conform exactly. Each is 14 lines and does one
thing:

```
Follow the `run-agent` command with pre-filled arguments:
`run-agent 03_execute/coder $ARGUMENTS`
```

They are produced from `pipeline.json` by
`scripts/generate_slash_commands.py`, so they cannot drift from the pipeline
definition.

The four hand-authored ones are programs:

| Command | Lines | What it holds |
|---|---|---|
| `maos-run` | 182 | The whole interactive drive loop: tick, inspect labels, detect gates, halt conditions, a mark-ready fallback |
| `maos-new-branch-pr` | 75 | A branch-and-PR procedure |
| `maos-rebaseline` | 73 | A rebaseline procedure |
| `maos-merge` | 36 | A merge procedure |

`maos-run` is the largest command file in the repository. `run-agent` itself,
though not in the `maos-*` namespace, is 128 lines for the same reason.

**Why this costs something.** None of that procedure is reachable by the
headless path, testable, or visible to a reader of `pipeline.json`. `maos-run`
step 4c is a worked example: it instructs the driver to apply the gate label
itself, which the self-approval guard rejects (#377). A wrong instruction sat in
a command file for as long as it did precisely because nothing reads a command
file except a person typing the command.

**Where the logic goes.** Each of the four names a script instead. `maos-run`
is the interesting case: under the MI-3 target its drive loop reduces to
"invoke the orchestrator until it halts or reaches a gate", because the
orchestrator already owns tick selection, gate detection and halting. Most of
the 182 lines exist to re-describe things the orchestrator does.

**Test to add.** Every command file resolves to a generated wrapper or a single
named target. A numbered procedure, a conditional or a retry loop in a command
file is a test failure.

---

## How a step is told where it is

**Status:** `PARTIAL`.

The channel exists and is used. The orchestrator sets `AI_AGILE_ROOT`,
`AI_AGILE_CONTEXT`, `AI_AGILE_EXECUTION_MODE`, `REPO`, `WORK_ITEM_KIND`,
`WORK_ITEM_NUMBER`, `ISSUE_NUMBER` or `PR_NUMBER`, `SESSION_ID`,
`SESSION_SCOPE` and `AI_AGILE_SCRATCH` on every step it invokes.

**The orchestrator's own mode is not shared.** `AI_AGILE_EXECUTION_MODE` is
always `headless`, which is correct -- it describes the spawned activity, which
never has a human attached whichever way the tick began, and the code says so
explicitly at `pipeline_orchestrator.py:2676`.

But the *other* mode question -- was this tick started by a person or by GitHub
Actions -- lives only in the `_HEADLESS` module global and is never passed to a
step. Any script whose behaviour legitimately depends on it cannot find out.
That is the shape of **#314**: `.pipeline-stop` needs to behave differently for
an interactive run, and the only component that knows which kind of run it is
does not say.

The risk is the predictable one: a step that needs the answer will infer it from
`AI_AGILE_EXECUTION_MODE`, which answers a different question, or probe its
environment to guess -- both of which the design forbids.

**Test to add.** Every variable a step reads is one the orchestrator sets. A
step that reads an environment variable not in the provided set, or that probes
for context rather than being told, is a test failure.

---

## MI-1 -- An issue means the same thing to everyone

**Status:** `PARTIAL, UNTESTED`.

Labels are shared and none is mode-specific. Nothing enforces it.

**#380** shows a case where practical meaning depends on step configuration
rather than on the label: `:review` means "waiting for a named approval" for
most steps, and "no approval exists to give" for a step that declares no gate.

---

## MI-2 -- The same situation always produces the same next step

**Status:** `VIOLATED`.

`/maos-run` correctly leaves routing to the orchestrator. `/run-agent` resolves
invocation parameters through a separate path.

**#356** is that drift realised -- resolve-only mode returned 24 tools where the
real spawn passes 93. It was fixed; the duplicated path remains and nothing
tests the two against each other.

---

## MI-3 -- An agent can only ever do what you allowed

**Status:** `VIOLATED`. This is the most expensive gap in the list.

Headless mode uses the platform's own enforcement when it starts an agent
subprocess. Interactive mode cannot, because `/run-agent` executes agent
instructions inside the caller's own session -- so it re-implements enforcement
in shell: an allowlist written to a file, a hook on every action, and a command
parser. `run-agent.md` says as much in its own words, describing the hook as
applying "the same restriction the real orchestrator applies via
`--allowedTools`".

That re-implementation has produced five defects:

| Defect | What it did |
|---|---|
| #335 | Denied every Bash call -- matched tool names only, never patterns |
| #356 | Dropped permissions during resolution |
| #374 | Two interactive runs overwrote each other's limits (`[SECURITY]`) |
| #383 | Refuses 31% of all agent shell blocks, including re-run guards |
| #388 | The limits may never load at all, disabling enforcement entirely |

**The design now resolves this by separating the two commands** rather than
choosing between them. `/maos-{agent}` runs the exact step as a subprocess with
native enforcement; `/maos-{agent}-i` resolves the instructions and works
through them with the person, and is explicitly not an agent invocation.

That removes the emulation without removing the capability. The hook, the
command parser, the scope file and the resolve-only grant plumbing all exist to
make the in-session path behave like an unattended agent run. Once that path is
named as what it is -- a person and their assistant, in the person's own session
-- there is nothing for a second enforcement mechanism to enforce, and MI-3 is
satisfied by the platform's own enforcement on the spawn path alone.

Two findings made this cheaper than it first appeared:

- **The split already exists.** #316 deliberately separated resolve from spawn
  and added `--print-prompt`. The resolve-only path already reports
  `AI_AGILE_EXECUTION_MODE=interactive` and the spawn path `headless`. Only one
  command was ever built on top, doing both jobs.
- **Live output is not lost.** The spawn path already streams agent output with
  `--verbose` (`_should_emit_stream_line`, `pipeline_orchestrator.py:1950`), so
  the visibility cost of running the exact step as a subprocess is far smaller
  than assumed.

What is genuinely lost on the exact-step path is intervening mid-run, which the
agent contract says should not be possible anyway. That capability moves to the
`-i` command, where it is honest.

**Not implemented.** Both commands need generating from `pipeline.json`, the
existing 12 wrappers change meaning (they currently resolve to the in-session
path), and the hook, parser and scope file can then be deleted.

---

## MI-4 -- Nothing gets stuck with no way out

**Status:** `VIOLATED`, three ways -- but not in the way it first appears.

`statuses.json` already names two exits for `:review`: *"orchestrator (on
gate-label application) or human (removes label)"*. The second is a genuine
documented exit, so removing the label is not an out-of-band hack.

The defect is narrower and worse:

- **#380** -- when a step emits `:review` without naming a gate, the *first*
  exit does not exist for it: there is no label to apply. Only the
  human-removes-label exit remains, and neither the orchestrator nor
  `/maos-run` mentions it. The tooling documents the exit that is unavailable
  and stays silent about the one that works, so the issue reads as permanently
  stuck. Recovery was performed by hand twice on 25 August.
- **#377** -- the interactive driver is documented to record its own approval,
  but the self-approval guard rejects it, so the documented procedure cannot
  work.
- **#314** -- the emergency stop has no defined behaviour for interactive runs.

The general lesson: the machine-readable source held more truth than the prose
describing it. That is the argument for generating views rather than authoring
them.

---

## MI-5 -- The result does not depend on who was watching

**Status:** `UNTESTED`. No known violation and no test.

Recorded because its absence would be invisible until it mattered: nothing today
would detect a step whose pre-actions, activity or post-actions behaved
differently under a runner than under a driver.

The stated test -- run the same step in both modes and diff the timeline -- is
expensive enough that it will not be run casually. A cheaper proxy is worth
finding.

---

## MI-6 -- You can always tell what actually happened

**Status:** `VIOLATED`. This is the widest gap.

Nine of the 27 defects filed between 15 and 25 August report success while doing
nothing:

| Defect | Reported | Actually did |
|---|---|---|
| #308 | step complete | never committed the agent's work |
| #315 | `:failed` | the agent had genuinely succeeded |
| #343 | "deleted the head branch" | the delete was denied |
| #346 | auth unavailable | the CLI was working |
| #358 | feedback addressed | replayed a previous answer, changed nothing |
| #362 | permission denied | a grant was configured, and was dropped |
| #378 | step complete | left the diff uncommitted |
| #387 | commit step completed | pushed nothing; CI ran on stale code |
| #388 | enforcement active | may be disabled entirely |

Three are additionally mode-specific: **#346** misreports only in interactive
mode, **#326** blocked agents only in headless mode, **#334** failed only in
restricted sessions.

---

## MI-7 -- Only a person approves

**Status:** `VIOLATED`, two ways -- and the first is a design conflict, not a
coding defect.

**The guard cannot tell transcription from origination.** It rejects any gate
label applied by a non-human actor. In headless mode that is correct. In
interactive mode the chat-AI writing the label on the person's instruction is
the *supported path*, so the guard rejects the very mechanism the product
depends on, and the interactive driver cannot cross a gate at all (**#377**).

Both cases look identical where the guard inspects them -- a bot actor on a
`labeled` event -- so no refinement of actor-checking resolves it. Whichever way
the guard is set today, one of two rules is broken: either agents can approve,
or interactive mode cannot.

**The design now answers this** (MI-7): stop trying to detect origination and
make it unreachable instead. In headless mode only a person can cross a gate,
because no human is present during the tick. In interactive mode the
orchestrator records the approval on a confirmation the driver relays, and never
the driver itself. An agent can reach neither path -- its whole output surface is
one status value from a fixed set.

Nothing of this is implemented. What it needs:

| Change | Where |
|---|---|
| The driver stops applying gate labels | `maos-run.md` step 4c, which currently instructs it to |
| The orchestrator gains a way to be told "the person confirmed" | New; no such channel exists |
| The orchestrator refuses to record an approval when it cannot establish a person is present | New; the assumption is currently implicit |
| The guard's rule becomes mode-dependent | Currently one rule for both modes |

The assumption to assert rather than trust: a non-headless invocation genuinely
has a person present. True by construction today -- the interactive path exists
only inside a chat session -- but nothing enforces it, and if anything ever
invokes the orchestrator non-headlessly without a human the guarantee
disappears silently.

**The guard also fails open.** When GitHub's timeline has not yet surfaced the
`labeled` event it logs `no 'labeled' event found ... allowing (fail-open)` and
admits the approval. Timeline reads are eventually consistent, so an
agent-originated approval passes under lag. This one *is* a straightforward
defect -- an inconclusive check must refuse -- and is independent of the conflict
above. Both behaviours were observed on 25 August, on the same day.

---

## MI-8 -- Any difference is written down

**Status:** `PARTIAL`.

`17-operating-modes.md` documents differences, but as a comparison table plus a
list of *current limitations* -- things that happen to be true today, not
differences argued to be permanent. Nothing distinguishes an intended difference
from an unrepaired defect, and no test maps mode-conditional code branches to
either.

---

## Contradictions between the documents and the code

Carried forward for resolution as `PRODUCT.md` supersedes each numbered
document.

**P-16 commit mode.** P-16 names `coder` a Mode 1 (agent-driven commit) agent.
`pipeline.json` configures it `commit_after: true`, which is Mode 2. `coder.md`
instructs it never to run `git commit` or `git push`, and says "the orchestrator
(not you) will". Three sources, three positions. The agent was observed
self-committing on 25 August, which stranded its work (#387).

**P-16 git grant.** P-16 states agent allowlists must name specific git
subcommands, "never the bare `Bash(git *)` glob". `coder`'s only git grant is
`Bash(git *)`, which admits `git reset --hard`, `git push --force` and
`git branch -D` -- the three commands P-16 separately forbids for all actors in
both modes. This is a live security exposure, not only a documentation gap.

**P-9 concurrency.** P-9 mandates unconstrained cross-issue parallelism and
names `impact-assessor` and `dependency-resolver` as the agents that make it
safe. Neither exists in `pipeline.json` or as a prompt file, and the
orchestrator has no `blocked-by` handling (#135). The concurrency model runs
with its entire safety layer unimplemented, on a single shared working tree
(#373).

---

## Frozen work

All 13 open defects carry the `blocked` label as of 25 August, pending the
target design. Nine of the sixteen pipeline steps skip a blocked issue.

They are not abandoned. Each will be re-derived from `PRODUCT.md` as a
conformance gap, a duplicate of one, or dropped because the design removes the
mechanism it lives in. On current expectation roughly five would be **dissolved**
rather than fixed -- #373, #381, #383, #387, #388 -- because the mechanisms they
are defects in would no longer exist.

That expectation depends on which way #393 resolves MI-3. If the interactive
path keeps its own enforcement, #383 and #388 stay real and the dissolved count
drops to three.
