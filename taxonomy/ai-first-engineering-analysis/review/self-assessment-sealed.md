# Sealed Self-Assessment

**Written before the independent review, to be opened only after the review returns.**

This is my own list of what I believe is wrong or weak in the report and model. It exists
so the independent review can be scored against it. Do not show it to the reviewer.

---

## Defects I believe are present

### Critical

**S1 — The span-of-control anchor is unsourced and carries the whole result.**
Every other parameter has a citation. "A supervisor oversees five developers" has none.
Reported spans run 4 to 10+. At span 7 the team is 2.35 FTE and −52%, and the paper's
central negative finding — that a two-person team is unreachable — collapses. The report
now admits this in §5, but the admission sits after the conclusion has been stated three
times, and the headline number is still quoted without the qualifier in most places.

**S2 — R is derived from 42%-AI teams and applied to 100%-agent teams.**
§1.2 quotes Faros warning that agent-primary work is "an order of magnitude" worse than
what its data measures, then §3 uses R derived from that data anyway. The report states
the contradiction but does not resolve it. If the warning is right, R is a lower bound
and every figure is optimistic.

### Major

**S3 — The unit of work is under-defined for the token model.**
"One developer-year of merged output" is defined, but the token calculation assumes 150
merged tasks per unit. That number is asserted, not sourced, and it scales the AI cost
linearly. At 300 tasks/unit the AI bill doubles.

**S4 — Yield is a free parameter in the token model.**
The share of agent runs that merge (25–60%) is my estimate. It moves cost per unit by a
factor of 2.4 and nothing constrains it.

**S5 — The old team's cost may be overstated.**
1 lead at $250k + 5 developers at $200k assumes all five are fully-loaded senior
developers. A real six-person team usually has a mix including juniors. If the old team
averages $170k, the saving falls by roughly 8 percentage points.

**S6 — Quality neutrality is asserted, not modelled.**
The report holds quality constant by assumption while citing evidence that quality
degrades. Removing the refactoring line made this worse, not better: the obligation to
commission refactoring is now a recommendation with no cost attached.

### Moderate

**S7 — "5 units" is never validated as the right output target.**
Constant output is the right frame for comparability but is never defended against the
alternative that AI-first teams should ship more.

**S8 — Supervisor rate of $240k is a judgement with no source.**
It is flagged as such, but it moves the answer by 14 points across its stated range.

**S9 — The 90-day survival filter is recommended but never applied.**
The measurement guidance tells readers to count merged units surviving 90 days. No figure
in the report uses that basis, including the unit definition itself.

**S10 — Appendices contain superseded analysis.**
Appendix F retains material from earlier framings — Configuration A/B language, break-even
budgets, throughput-parity thresholds — that no longer matches the body. A reader who
reaches the appendices will find a different model described.

### Minor

**S11 — The token price of $1–3/Mtok blended is undated and will go stale quickly.**

**S12 — "83% authors / 17% supervisors" for the old team is derived from headcount, not
from time allocation, and overstates the contrast.**

---

## What I believe is sound

- The core inversion: supervision capacity, not authoring speed, is the binding constraint
  in an agent-primary team. This follows from the definition of the configuration.
- The identity `supervisors = target × R / span`. The arithmetic is trivially correct.
- The structural argument for R > 1: no accountability transfer, no trust accumulation,
  intent as a second axis. These do not depend on model capability.
- The finding that AI spend is a small share of total cost and invariant to R.
- The absence finding: no published research compares the two team types.
- The direction of the result. The magnitude is not robust; the sign is, across most of
  the sensitivity band.

---

## What I most expect the reviewer to find that I have missed

Errors in the appendices, which have been revised least and checked least. And something
in the token model, which is the newest work and has had the least scrutiny.
