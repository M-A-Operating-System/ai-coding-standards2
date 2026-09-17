# Bug review: 15-25 August 2026

Every defect filed against `M-A-Operating-System/ai-coding-standards2` in the
last ten days, read in full and grouped by what actually broke.

**27 defects in 10 days** -- 2.7 per day. 14 closed, 13 still open. Of the 45
issues created in this window, 27 were defects; the other 18 were features,
enhancements, toil and spikes.

Not one of the 27 is about a product the pipeline exists to deliver. All 27 are
the pipeline's own machinery failing.

---

## Contents

- [The pattern](#the-pattern)
- [1. Enforcement and permissions](#1-enforcement-and-permissions-9) -- 9 defects
- [2. Git, commit and state mechanics](#2-git-commit-and-state-mechanics-9) -- 9 defects
- [3. Control flow and the state machine](#3-control-flow-and-the-state-machine-5) -- 5 defects
- [4. Scratch and file hygiene](#4-scratch-and-file-hygiene-2) -- 2 defects
- [5. Tooling traps](#5-tooling-traps-2) -- 2 defects
- [Fix chains](#fix-chains)
- [Method](#method)

---

## The pattern

Three things recur across the whole set, and they matter more than any
individual bug.

### Silent success is the dominant failure mode

The most common defect in this window is not "X crashes". It is **"X reports
success while doing nothing"**. At least nine of the 27 are exactly that:

| Issue | Reported | Actually did |
|---|---|---|
| #308 | step complete | never committed the agent's work |
| #315 | `:failed` | the agent had genuinely succeeded |
| #343 | "deleted the head branch" | delete was denied |
| #346 | auth unavailable | the CLI was working |
| #358 | feedback addressed | replayed a previous answer, changed nothing |
| #362 | permission denied | a grant *was* configured, and was dropped |
| #378 | step complete | left the diff uncommitted |
| #387 | commit step completed | pushed nothing; CI ran on stale code |
| #388 | enforcement active | may be disabled entirely |

When a control fails by reporting success, every downstream signal -- green CI,
a clean review, a `:complete` label -- becomes evidence of nothing. Several of
these were only caught by checking the underlying state directly rather than
trusting the status.

### The enforcement layer is the largest single source

9 of 27 defects (33%) are the mechanisms meant to keep agents safe preventing
them from working at all. Four of those nine -- #326, #335, #356, #362 --
blocked agents outright before they could take a single useful action.

### Fixes are generating the next defect

Four traceable chains, detailed [below](#fix-chains). In each, the fix for one
defect created or exposed the next. This is the clearest signal that the
control surface has more interacting parts than any one change can reason
about.

### Closure speed is not the problem

Of the 14 closed, 11 were closed same-or-next-day (median 0 days, max 4).
Defects are being found and fixed quickly. The problem is arrival rate, not
throughput -- and that four of the closures directly caused a later filing.

---

## 1. Enforcement and permissions (9)

Mechanisms intended to constrain agents, preventing them from doing their job.

### Open

**#383 -- Command substitution refused for 34 agent blocks**
`split-command.py` blocks every command containing `$(`, so 34 shell blocks
across 10 of 13 agents cannot execute the variable-capture they depend on.
Several are *guard* blocks that must read prior state before a destructive
action -- and a refused guard does not fail safe. 31% of all agent bash blocks
are dead. *In flight as of this review.*

**#388 -- Scope file keyed by `$PPID` may never match**
The fix for #374 keys the scope file by `$PPID`, a value produced on two sides
of a process boundary. If writer and hook disagree, the existence check
short-circuits and tool-scope enforcement is disabled *always* -- worse than the
concurrency bug it replaced, and silent.

**#362 -- Coder cannot edit agent-protocol files**
Two silent defects combine: the `.claude/settings.json` allow entry is dropped
when the workspace is untrusted, and `AGENTS.md` was never covered by any grant.
The agent sees a denial with no indication a grant existed.

**#323 -- Coder can never complete a `.claude/*` change**
Claude Code's protected-paths gate is not accounted for in the pipeline design,
so any issue whose fix touches `.claude/` cannot be completed by the coder.

### Closed

**#374 -- Concurrent `/run-agent` invocations bypass tool-scope enforcement** *(SECURITY, 4 days)*
A single fixed-path scope file meant the second writer clobbered the first's
allowlist. Fixed via PR #385 -- which produced #388.

**#356 -- `--print-prompt` drops tool grants** *(1 day)*
Resolve-only mode returned 24 tools where the real spawn gets 93, scoping every
agent to a quarter of its toolset and locking the session.

**#335 -- Hook denies every Bash call** *(same day)*
The scope hook matched tool names only, never `Bash(pattern)` entries, so it
denied everything.

**#346 -- Auth preflight false-negatives on a working CLI** *(same day)*
Blocked every agent step in an interactive session because the preflight
demanded conditions that do not hold in a working environment.

**#326 -- `gh api` allow patterns don't match quoted URLs** *(same day)*
Two consecutive runs blocked at the first step, before the classifier could read
the issue.

---

## 2. Git, commit and state mechanics (9)

The orchestrator's handling of branches, commits and pushes.

### Open

**#387 -- `commit-agent-work.sh` never pushes when the agent self-commits**
The clean-tree guard at line 52 returns before the push at line 208. An agent
that commits its own work leaves a clean tree, so the script exits 0 having
pushed nothing. Observed live: CI passed 4/4 against the *previous* commit and
`pr-reviewer` reviewed code that did not contain the fix, consuming a review
cycle.

**#308 -- `commit_after` skips agents that self-gate to `:review`**
`commit-agent-work.sh` runs only when terminal status is exactly
`STATUS_COMPLETE`, so a gated agent's work is never committed.

**#358 -- A resumed agent session replays its previous result**
The coder's Mode B feedback loop completes normally, reports success, changes
nothing, and consumes a review cycle.

**#373 -- Concurrent ticks share one working tree**
No isolation, no lock, one `HEAD`. The loser's agent output can be committed
onto the winner's branch.

**#381 -- A tick leaves the working tree dirty**
Dirty by design while an agent is mid-write, so session git-hygiene checks fire
wrongly and advise committing another process's half-finished work. *Observed
live during this review.*

**#352 -- Metrics branch carries the whole repo tree**
`ai-agile/metrics` is branched from `main`, so every metrics commit carries
`.claude/`, `docs/`, `pipeline/` and the rest, burying `records.jsonl`.

### Closed

**#378 -- A `commit_after` agent that emits `:review` never commits** *(1 day)*
The human gates on an empty diff. Closed as a duplicate of #308.

**#343 -- `merge-pr.sh` claims a branch delete that was denied** *(same day)*
Reported deletion as accomplished fact without checking, and leaked the API
error into stdout.

**#334 -- Metrics ledger append 403s in restricted sessions** *(same day)*
Contents API `PUT` consistently 403s where `git push` over the same credential
succeeds. Switched to git plumbing.

---

## 3. Control flow and the state machine (5)

Labels, gates, and the paths between them.

### Open

**#380 -- A step emitting `:review` with no `human_gate_label` strands the issue**
There is no label a human can apply to clear the halt, because the step declares
none. Requires deleting a label out of band to recover. *Hit twice during this
review, on #374 and #383.*

**#377 -- `/maos-run` cannot cross a human gate**
Step 4c instructs the driver to apply the gate label itself, but the
self-approval guard rejects any gate label applied by a bot. The documented
procedure cannot work.

**#314 -- `.pipeline-stop` has no protocol for interactive runs**
No defined interactive behaviour, and no staleness alerting for the scheduled
pipeline.

### Closed

**#315 -- A failing `post_step` overwrites a successful agent run** *(1 day)*
The real outcome is discarded and recorded as `:failed`.

**#310 -- `review-cycle:1` applied at first dispatch** *(4 days)*
Mode A runs misdetect as Mode B, wasting turns until `max_turns` failure.

---

## 4. Scratch and file hygiene (2)

### Closed

**#321 -- `AGENTS.md` has no concrete scratch convention** *(2 days)*
The principle was stated but no operational guidance given, so agents invented
their own temp files and leaked them into commits.

**#376 -- Agents still leak scratch files to the repo root** *(1 day)*
"The #321 fix has three parts, and this path evades all three." The `Write` tool
has no path restriction.

---

## 5. Tooling traps (2)

Environment behaviour that misleads agents into wrong conclusions.

### Closed

**#311 -- `Glob` silently misses content behind symlinked directories** *(same day)*
`Glob("standards/*.json")` returned nothing though the files exist. Caused
`prd-writer` to conclude "no standards files exist" -- a real, consequential
misdiagnosis, with no error to signal the miss.

**#367 -- A PR is reviewed by its own modified agents and scripts** *(same day)*
The reviewing machinery is taken from the PR under review, not from `main`. A PR
changing `pr-reviewer.md` or the orchestrator has those changes active while
being reviewed.

---

## Fix chains

Four cases where closing one defect produced the next. Each is stated in the
later issue's own text, not inferred.

```
#321  scratch convention added
  \-- #376  "the #321 fix has three parts, and this path evades all three"
        \-- (PR #382 -- repo-root sweep + scratch rewrite)

#374  scope file was a fixed-path singleton          [SECURITY]
  \-- #388  the $PPID key that replaced it may never match

#335  hook denied every Bash call
  \-- #356  --print-prompt drops the grants that would have fixed it

#308  commit_after skips :review
  \-- #378  same defect, filed again, closed as duplicate
        \-- #387  a third path where the push is unreachable
```

The #374 chain is the one to watch: a security fix merged today may have
replaced a bug that broke enforcement under concurrency with one that disables
it entirely.

---

## What the shape suggests

Three observations that follow from the data rather than from opinion.

1. **Observability before more controls.** Nine defects reported success while
   failing. Making every control state whether it engaged would not fix any one
   of them, but would have made all nine findable in minutes rather than by
   forensics.

2. **Enforcement needs end-to-end tests.** #388 exists because the scope hook
   has a substantial test suite that spawns it via `subprocess.run()`, where the
   key matches by construction -- it has never been exercised the way it is
   actually invoked. A control with no engagement test is a control you are only
   assuming you have.

3. **Every state needs an exit.** #380 and #377 are both states a run can enter
   with no documented way out. Both required editing labels out of band. A state
   machine with unreachable exits is not a state machine.

---

## Method

Issues were read from the GitHub REST API for
`M-A-Operating-System/ai-coding-standards2`, filtered to those *created* between
2026-08-15 and 2026-08-25 (45 issues), then to defects (27). Pull requests are
excluded throughout.

Classification as a defect is by content, not by label: several bug-shaped
issues (#373, #377, #378, #380, #381) carry no `[BUG]` prefix, and #374 is
titled `[SECURITY]`. #316 carries a bug label but is titled `[ENHANCEMENT]` and
is excluded as an enhancement.

Summaries are drawn from each issue's own problem statement. Where a defect is
marked *observed live*, it was reproduced during pipeline runs in this session
rather than inferred from the issue text.

Counts current at commit `37e3566` on `main`, 25 August 2026.
