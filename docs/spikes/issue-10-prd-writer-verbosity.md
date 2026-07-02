# Spike findings — Reduce prd-writer agent verbosity

**Issue:** [#10](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/10) — `[SPIKE] - pipeline - Reduce prd-writer agent verbosity`
**Author:** `05_execute/coder` (spike findings)
**Date:** 2026-05-15
**Source files reviewed:** `.claude/agents/01_product_docs/prd-writer.md`, the live PRD comments on issue #10.

---

## TL;DR

PRD length is driven by template instructions in
`.claude/agents/01_product_docs/prd-writer.md` that **mandate all six sections,
prescribe paragraph-length bodies, and embed an implicit 3-scenario Gherkin
floor**. The classification (bug / spike / feature / …) is read but never used
to scale the template. The fix is to (a) make four of the six sections
explicitly omissible when there is nothing to say, (b) replace paragraph
prescriptions with "one sentence is enough when the issue is small", (c) remove
the 3-scenario floor and add an explicit upper-bound discipline, and (d)
introduce a one-line scale-by-classification table the agent consults before
drafting. The section headers and their order must remain unchanged — downstream
agents parse them.

This spike includes **four concrete before/after prompt changes** and one
adjacent cleanup. Any of the four can ship independently; together they remove
the bulk of the padding the issue describes.

---

## Evidence — issue #10 itself demonstrates the problem

The original issue body (snapshot comment on #10):

> Make recommendations on how to dial back the verbosity of the pdd user
> stories and spec.

The first PRD the prd-writer produced for that one sentence had:

- **3 user stories** (Stakeholder / Reviewer / Engineer — Reviewer and Engineer
  restate the same desired outcome from different viewpoints rather than
  describe distinct user-visible capabilities)
- **6 Gherkin scenarios** (one of which — "Section headers and order are
  unchanged" — is a constraint on the implementation rather than a user-visible
  acceptance condition)
- **Out of scope** populated with three bullets, two of which restate the
  Goal in negative form
- **Success metrics** populated with three bullets even though the success
  signal is identical to acceptance criterion #1 ("a smaller PRD is
  produced")

Re-stating the same desired outcome through different personas, inventing
scenarios to meet an implicit quota, and filling Out-of-Scope / Success-Metrics
with paraphrases of the Goal are the three visible symptoms. The same prompt
produces them every time, regardless of issue scope.

---

## Root verbosity drivers in the prd-writer prompt

Numbered for cross-reference with the recommendations below.

### D-1 — "Six sections, in this order" with only one conditional

`.claude/agents/01_product_docs/prd-writer.md:72` reads:

> Six sections, in this order. Downstream agents parse these headers —
> use them verbatim.

This phrasing tells the agent that all six headers must appear. Only **Out of
scope** carries an explicit `(Omit this section if nothing is genuinely
ambiguous.)` (line 111). **Success metrics** has a weak `Omit if obvious or
already covered by acceptance criteria` (line 119) but is otherwise
indistinguishable from required sections. **Problem**, **Goal**, **User
stories**, and **Acceptance criteria** have no omit clause at all. The
template's natural pressure is therefore to fill every section, even when the
issue body has nothing substantive to put there.

### D-2 — Paragraph prescriptions for Problem and Goal

Lines 80 and 86 each open with "One paragraph." A one-line bug ("typo in
`status.sh:42`") does not need a paragraph about "what hurts, who feels it,
how often." The prompt does not offer a shorter form for small-scope issues,
so the agent fills with plausible-sounding context to reach paragraph length.

### D-3 — Implicit Gherkin floor of three scenarios

Step 6 (decomposition advice, line 241) reads:

> Each child should have one user goal, touch one bounded context, and produce
> a PRD with 3–7 Gherkin scenarios.

This is the **only quantitative guidance the prompt offers for the size of the
Gherkin section.** Even though it lives in the decomposition path, it
establishes "3 scenarios is the floor" in the agent's working context. Step 3
(lines 99–103) says "Cover the happy path and any edge cases the issue body
demands — no more." but provides no example of when one scenario is enough,
and is overridden by the more concrete 3–7 number.

### D-4 — Classification is read but never applied

Step 1 (lines 34–39) fetches the classifier artefact so the agent knows the
issue type. Step 3 then proceeds with **identical instructions for every
classification.** A spike (whose deliverable is knowledge, not code) gets the
same Gherkin scaffolding as a feature; a bug fix gets the same Out-of-Scope
and Success-Metrics treatment as a multi-week feature. The classification
exists in the working context but contributes nothing to template selection.

### D-5 — Always-on Standards-check footer

Lines 122–125 instruct the agent to append a Standards-check line whether or
not violations exist. In a repo where `ai-agile/standards/` is empty (as
today), this footer is pure boilerplate appearing on every PRD.

### D-6 — User-stories framing encourages persona-multiplication

Lines 89–92 say "One story per distinct user-visible capability" — sound in
spirit — but follow with the formula `**As a** {persona}, **I want**
{capability}, **so that** {outcome}.` and a persona-fishing instruction. There
is no caution against re-stating the same capability from multiple personas'
viewpoints. The issue-10 PRD demonstrates the failure mode: one capability
("PRDs proportional to scope") expressed three times via three personas.

---

## Recommendations — before / after prompt changes

Each recommendation is a literal, drop-in edit to
`.claude/agents/01_product_docs/prd-writer.md`. A follow-on enhancement issue
can pick up these diffs without further investigation.

### R-1 — Add a "Scale by classification" instruction before Step 3

Addresses **D-4** (classification ignored) and provides anchor for **D-1, D-3**.

**Add a new sub-step at the top of Step 3** (currently line 70). Insert
between the Step 3 header and "Six sections, in this order.":

> **Step 3a — Scale the PRD to the classification.**
>
> Before drafting, read the classifier verdict and pick the size band. Section
> headers and order are unchanged across all bands; what changes is what is
> required inside each section.
>
> | Classification | Problem | Goal | User stories | Gherkin scenarios | Out of scope | Success metrics |
> |---|---|---|---|---|---|---|
> | `bug` | 1–2 sentences naming the drift from target state | One sentence: the corrected behaviour | 0–1 (often the existing user story already covers it; omit if so) | 1–2 (the regression + maybe one related path) | Omit unless reviewers might over-correct | Omit; the bug being fixed is the metric |
> | `toil` | 1–2 sentences naming the operational pain | One sentence: the post-change state | 0–1 | 1–3 | Omit unless scope creep is likely | Omit unless there is a measurable target (perf, cost) |
> | `spike` | 1–2 sentences naming the question and why now | One sentence: what artefact the spike delivers | 1 (the persona who consumes the findings) | 1–3 acceptance conditions on the **findings**, not on code | Often useful — list what is explicitly out of the spike's scope | Often omitted — acceptance criteria already define "done" |
> | `enhancement` | 1 paragraph | 1 paragraph | 1–3 | 2–5 | Include if scope ambiguity exists | Include if there is a measurable target |
> | `feature` | 1 paragraph | 1 paragraph | 1–5 | 3–7 | Include | Include |
>
> A trivial issue produces a short PRD because the bands above demand less,
> not because section headers are removed. If a section's band says "0–1" or
> "Omit", produce exactly the amount the issue warrants — never fill to reach
> a quota.

**Why it works:** moves the implicit 3–7 floor into per-classification limits,
makes "omit" a first-class outcome for four sections in three of the five
classifications, and uses the classifier verdict the agent already reads.

### R-2 — Replace "One paragraph" with conditional length on Problem and Goal

Addresses **D-2**.

**Before** (line 80):

> ### Problem
>
> One paragraph. What hurts, who feels it, how often. Name the specific
> broken or missing behaviour — not "users want better UX".

**After:**

> ### Problem
>
> Short bug/toil/spike: 1–2 sentences naming the specific broken, missing,
> or unknown behaviour. Enhancement/feature: one paragraph covering what
> hurts, who feels it, and how often. Never "users want better UX" — name
> the specific behaviour.

**Before** (line 86):

> ### Goal
>
> One paragraph. What success looks like in user-observable terms.
> Phrase as the change the user will experience, not the implementation.

**After:**

> ### Goal
>
> Short bug/toil/spike: one sentence naming the corrected behaviour or the
> artefact the spike delivers. Enhancement/feature: one paragraph naming the
> user-observable change. Phrase as what the user will experience, never the
> implementation.

**Why it works:** stops compelling paragraph-length output for one-line issues
while keeping the larger form available where it adds signal.

### R-3 — Remove the implicit Gherkin floor and add upper-bound discipline

Addresses **D-3**.

**Before** (lines 99–103):

> ### Acceptance criteria (Gherkin)
>
> One scenario per distinct acceptance condition. Each Then-clause must
> be falsifiable by a tester or automated test. Cover the happy path and
> any edge cases the issue body demands — no more.

**After:**

> ### Acceptance criteria (Gherkin)
>
> One scenario per distinct acceptance condition the issue body or
> classification band requires (see Step 3a). Each Then-clause must be
> falsifiable by a tester or automated test. Stop at the smallest set that
> covers the happy path plus the edge cases the issue body explicitly
> raises — **do not add scenarios to reach a perceived minimum.** If two
> scenarios would have the same Then-clause restated, keep one.

**Also**: in Step 6 (decomposition), change line 241:

> Each child should have one user goal, touch one bounded context, and produce
> a PRD with **3–7** Gherkin scenarios.

to:

> Each child should have one user goal, touch one bounded context, and produce
> a PRD whose Gherkin scenario count matches the classification band in
> Step 3a (typically 2–5 for enhancements, 3–7 for features).

**Why it works:** the "3–7" number is the strongest verbosity anchor in the
file. Re-binding it to the per-classification table in R-1 prevents it leaking
into bug / toil / spike drafts.

### R-4 — Make Out-of-Scope and Success-Metrics explicitly omissible by default

Addresses **D-1** (every section feels required) and **D-5** (Standards-check
boilerplate).

**Before** (lines 109–119):

> ### Out of scope
>
> (Omit this section if nothing is genuinely ambiguous.)
>
> - {What is excluded and why}
>
> ### Success metrics
>
> Observable signals — a dashboard, log query, or audit-log event —
> that confirm the feature is working in production. Omit if obvious or
> already covered by acceptance criteria.

**After:**

> ### Out of scope
>
> Omit this section by default. Include it only when reviewers are likely to
> mistake adjacent work as in-scope, or when the classification band in
> Step 3a says to include. Never paraphrase the Goal in negative form.
>
> - {What is excluded and why}
>
> ### Success metrics
>
> Omit this section by default. Include it only when there is a concrete
> observable signal (dashboard, log query, audit-log event) that is not
> already restated by an acceptance criterion, and when the classification
> band in Step 3a says to include.

**And** for the Standards-check footer (lines 122–125), change:

> Append a **Standards check** line after the six sections:
> - If product-layer (`ai-agile/standards/product/*.json`) violations
>   exist: list them by STD ID.
> - Otherwise: `Standards check: no product-layer violations identified.`

to:

> Append a **Standards check** line after the sections **only when
> product-layer (`ai-agile/standards/product/*.json`) violations exist**,
> listing them by STD ID. If there are no violations (or no product-layer
> standards files exist), omit the footer.

**Why it works:** "omit by default, include when needed" inverts the burden —
the agent has to justify *including* the section, not justify *omitting* it.
Removes the no-op Standards footer on every PRD in repos with empty standards
dirs.

### R-5 — Add an anti-pattern caution to User stories

Addresses **D-6**.

**Before** (lines 88–96):

> ### User stories
>
> One story per distinct user-visible capability:
>
> - **As a** {persona}, **I want** {capability}, **so that** {outcome}.
>
> Pick personas from `docs/product/orchestrator/03-personas.md`. "As a
> developer" stories are suspect — if there is no user-observable
> benefit, it is technical-intermediate work, not a feature PRD.

**After:**

> ### User stories
>
> One story per distinct user-visible capability:
>
> - **As a** {persona}, **I want** {capability}, **so that** {outcome}.
>
> Pick personas from `docs/product/orchestrator/03-personas.md`. "As a
> developer" stories are suspect — if there is no user-observable benefit,
> it is technical-intermediate work, not a feature PRD.
>
> **Do not write multiple stories that re-state the same capability from
> different personas' viewpoints.** If two stories would have the same
> `I want {capability}` clause, keep one and pick the persona that most
> directly experiences the outcome.

**Why it works:** the issue-10 PRD's three-story pile-up is exactly the
pattern this caution names. Naming it explicitly is cheaper than catching it
in review every time.

---

## How to verify the change after it ships

A follow-on implementation issue can verify R-1 to R-5 with this small,
mechanical check rather than a subjective re-read:

1. Re-run the prd-writer against the snapshot body of issue #10 (one sentence:
   "Make recommendations on how to dial back the verbosity of the pdd user
   stories and spec.").
2. The resulting PRD must:
   - Use the **spike** classification band (1 user story, 1–3 Gherkin
     scenarios, no Success-Metrics section, optional Out-of-Scope).
   - Have **Problem** and **Goal** in 1–2 sentences each, not paragraphs.
   - Have **no Standards-check footer** (the `ai-agile/standards/` dir is
     empty in this repo today).
3. The six section headers must still appear in the same order with the same
   spelling. (R-1 to R-5 explicitly preserve this — the contract with
   downstream parsing agents is unchanged.)
4. Total character count of the live-target PRD section is lower than the
   pre-change PRD on the same issue. The pre-change baseline is the PRD
   currently in `gh issue view 10 --json body` (≈ 3,500 chars). A
   well-tuned output for this spike-classified body should be ≈ 700–1,200
   chars.

---

## Out of scope for this spike

- Implementing the prompt changes. Tracked as a follow-on enhancement issue.
- Verbosity of artefacts produced by other agents (architect designs, build
  plans, test specs). Same patterns may apply but were not investigated.
- Changes to the **classifier** prompt or the labels it applies. R-1 depends
  on the classifier's verdict being accurate; today it is.
- Adding numeric character-count caps to the prompt. The classification
  bands are a softer, more durable constraint than character limits and let
  the agent calibrate to the issue rather than to a literal length.

---

## Suggested follow-on issue title

`[ENHANCEMENT] - pipeline - Apply scope-proportional template to prd-writer prompt`

The body can link directly to this file and the five recommendations above.
