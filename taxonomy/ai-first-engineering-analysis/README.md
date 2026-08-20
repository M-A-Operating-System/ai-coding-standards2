# AI-First Engineering Team Analysis — Artifact Bundle

**13 August 2026**

## What this is

An analysis of what an equivalent engineering team looks like in an AI-first world:
agents authoring, humans supervising, output and quality held constant.

**Headline finding.** A conventional team of six — one tech lead and five developers —
is replaced by roughly **three people**, all supervisors, at about **34% lower cost**.
Not the two-person team the AI-first argument usually assumes. The result turns on one
parameter, **R**: the effort to supervise a unit of agent-authored work relative to a
unit of human-authored work. Published data puts R near 3.29, and the team size is
simply R.

**Confidence.** The direction is robust; the magnitude is not. The sensitivity band runs
from +2% to −56% depending on three parameters that are not directly measured. The most
influential of them — span of control — is an assumption with no source, and at the top
of its plausible range the paper's central negative finding does not hold. Section 5 of
the report sets this out.

---

## Contents

```
report/
  ai-first-engineering-cost-structure.md   The report. Body ~3,700 words,
                                           plus six appendices and 51 sources.

model/
  ai_team_cost_model.py                    Runnable model. Every figure in the
                                           report is computed here.
                                           Python 3.11+, no dependencies.
                                           Run: python3 ai_team_cost_model.py

review/
  adversarial-review-brief.md              Paste-ready brief for an independent
                                           adversarial review in a fresh session.
  self-assessment-sealed.md                My own list of suspected defects,
                                           written before any review. Open only
                                           AFTER a review returns, and do not
                                           show it to the reviewer.

archive/
  independent-source-validation-review.md  Source-validation audit of an earlier
  citation-traceability-audit.md           draft, under a different title and a
                                           different model. SUPERSEDED — retained
                                           for provenance only. Do not read these
                                           as describing the current report.
```

---

## Reading order

**For the decision:** the report's first two pages. Question, answer table, and the
recommendation. Everything after that is the supporting case.

**To check the numbers:** run the model, then read report §2–§4. Every figure in the
body reconciles to model output.

**To attack it:** report §5 ("How Much of This Is Assumption") lists the three parameters
that carry the result and what each does to the answer. Start there.

---

## Provenance conventions

Assertions in the report are marked as one of: **sourced** `[n]`, **single-sourced**,
**uncorroborated**, **author's derivation**, or **author's estimate**. A claim carrying
neither a reference nor a marking is a defect. No conclusion rests on an uncorroborated
or estimated claim. Full conventions in Appendix B of the report.

## Scope

**Engineering function only** — the tech lead and the developers. The same method applies
to product management, QA, design and support, and the arithmetic would be similar. Those
are excluded to keep the analysis to one role where the evidence is strongest. **A
whole-organisation figure cannot be read off this report**, and would be larger.

## Standing limitation

No published research compares a traditional engineering team with an AI-first team. The
literature measures productivity change when conventional teams adopt AI tooling, which
is a different question. This is an extrapolation from adjacent evidence, not a finding.
