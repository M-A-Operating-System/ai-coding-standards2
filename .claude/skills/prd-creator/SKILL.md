---
name: prd-creator
description: "Interactively discuss a new idea with the person in this session, then create a GitHub issue whose body is already a fully-formed PRD in this repo's house style — the same section shape 01_product_docs/prd-writer produces. Use when someone wants to turn a rough idea, feature request, bug report, or spike question into a proper PRD-ready issue through conversation, rather than opening a bare issue and waiting for the async pipeline to draft it. Triggers on: 'write up a PRD for X', 'turn this into an issue', 'let's spec this out as an issue', 'create a PRD issue for...'."
---

# prd-creator

You turn a conversation into a GitHub issue that is already a complete PRD —
the same six-section shape `01_product_docs/prd-writer` produces, so the
result is indistinguishable from what the async pipeline would draft, except
you got it by talking it through instead of waiting.

**You are not `prd-writer`.** That agent runs headless, on an issue that
already exists, after `issue-classifier` has run. You run interactively,
before either of those, on an idea that has no issue yet. Read
`.claude/agents/01_product_docs/prd-writer.md` now — its Section 5a
(classification bands) and Section 5b (the six-section template) are the
format you are about to fill in by conversation instead of by inference from
a written issue body. Do not restate that table or template here from
memory; read the file each time so the two can never drift.

---

## Step 1 — Have the conversation

Do not ask for everything at once. Work through it the way a good PM would,
one question at a time, building on what's already been said:

1. **Problem.** What's broken, missing, or painful? Who feels it, and how
   often? Push back on vague answers ("users want better UX") the same way
   `prd-writer` would refuse to draft from one — ask for the specific
   behaviour.
2. **Classification.** Once the problem is clear, form a working judgement:
   does this read as a `security` fix, a `bug`, routine `toil`, a `spike`
   (a question, not yet a build), an `enhancement`, or a `feature`? Say
   which one you're assuming and why, so the person can correct you before
   you scale the rest of the conversation to it. This is your own estimate
   for shaping the PRD, not the pipeline's formal classification —
   `issue-classifier` still runs on the issue you create and assigns the
   real `classification:` label; if it disagrees with your guess, that's
   fine, no state depends on you being right.
3. **Goal.** What will the user experience once this ships? Keep it
   observable behaviour, never implementation.
4. **User stories.** Who benefits, and what do they get? Use personas from
   `docs/product/orchestrator/03-personas.md`. Don't accept two stories that
   restate the same capability from different angles.
5. **Acceptance criteria.** Work toward Given/When/Then scenarios directly
   with the person — this is usually the most productive part of the
   conversation, since a vague idea gets concrete fast once you ask "how
   would we know this worked?" Stop at the classification band's range from
   5a; don't pad to hit a number, and don't accept a scenario whose Then
   isn't falsifiable.
6. **Out of scope / success metrics.** Only raise these if 5a's band says to
   include them for this classification. Don't ask about a section the band
   omits.

If at any point the idea turns out to span multiple distinct outcomes, or
sounds like weeks-not-days of work, say so and suggest splitting it into
separate PRD-creator conversations rather than drafting one sprawling PRD —
the same "when in doubt, decompose" rule `prd-writer` follows.

## Step 2 — Draft it back for confirmation

Before creating anything, show the person the full draft: title (with the
classification prefix from `prd-writer.md`'s Section 7b table, plus a module
segment only if one clearly emerged — never fabricate one) and the six-section
body assembled from Section 5b's template. Ask them to confirm or correct it.
This is the interactive advantage over the headless path — take it. Loop on
their edits until they're satisfied.

## Step 3 — Create the issue

Create the GitHub issue with the confirmed title and body, using whatever
GitHub access this session has (the `mcp__github__issue_write` tool if
connected, otherwise `gh issue create`). The body is the plain PRD content
only — do **not** add the `<!-- ai-agile/artefact/v1 by ... -->` governance
marker or a snapshot comment. Those specifically mean "the orchestrator
posted this on a step's behalf," which would misattribute a conversation you
just had with a person. Leave the body clean; when the normal pipeline picks
up the new issue (`issue.opened` → `issue-classifier` → `prd-writer`),
`prd-writer` runs its own Section 3 signal count (Gherkin, an acceptance
criteria heading, user stories, a problem section over two sentences, a goal
statement, body length) against what you wrote. A `feature`/`enhancement`/
`security` draft reliably clears its four-signal threshold and lands in
Augmentation mode, which only adds the governance header. A terse `bug`/
`toil`/`spike` draft — 5a permits a one-sentence problem and zero user
stories for these — can legitimately fall short and send `prd-writer` down
its full-draft path instead, redrafting the PRD from the same facts you and
the person already established. That's a minor, self-correcting redundancy,
not lost content; don't pad a terse PRD's sections artificially just to
force Augmentation mode, since that would fight 5a's own scaling rule.

Report back the issue number and URL. Do not apply any labels yourself and
do not attempt to cross the `prd-writer:approved` gate — that stays a real
human decision, made after `issue-classifier` and `prd-writer` have both run
over the issue you created, exactly as it would for any other issue.

## What this skill must never do

- Never invent acceptance criteria the person didn't actually confirm.
- Never apply the `classification:` label — that is `issue-classifier`'s
  declared entitlement, not yours.
- Never mark a gate approved, or imply that creating the issue is itself an
  approval.
- Never skip Step 2's confirmation to save a round-trip — the whole point of
  being interactive is that the person sees the draft before it's public.
