# Citation Traceability Audit

## Second adversarial review of *The Cost Structure of AI-First Engineering Teams*

**Audit date:** 13 August 2026
**Subject:** v3.0, audited claim by claim; corrections applied and reissued as v3.1.
**Test applied:** not *"is this source accurate?"* — that was the first review — but *"does every factual claim tie to a directly attributed source with a resolvable reference, and does the document contradict itself?"*

---

## 1. Verdict

**v3.0 failed the traceability test on two counts, one of which I introduced myself.**

The first review (source validation) checked whether cited sources said what the paper claimed. It did not check whether *every claim was cited at all*, nor whether the v3.0 rewrite left the document internally consistent. Both gaps were real.

**Twenty-one defects were found: five internal contradictions, twelve unsourced or under-attributed claims, and four bibliographic failures.** Every one has been corrected in v3.1.

The single most consequential finding is structural: **v3.0 carried 38 numbered references and not one inline citation.** A reader could not trace any specific claim to any specific source without reverse-engineering it from the appendix. A reference list without a citation apparatus is a bibliography, not attribution — it demonstrates that reading occurred without establishing which claim rests on which reading.

The second most consequential finding is that **five of the contradictions were introduced by the v3.0 corrections themselves.** Changing the base case from the Microsoft-anchored scenario to the realistic one updated §5.3 but left the §5.2 parameters table asserting the old values. For a document whose entire purpose is a numeric recommendation, a parameters table contradicting the results table is a serious defect, and it was created by the act of fixing something else.

---

## 2. Class A — Internal contradictions

These are the most damaging category, because a self-contradicting document cannot be relied on even where each individual claim is sourced.

| # | Defect | Severity | Status |
|---|---|---|---|
| **T1** | **§5.2 parameters table stated "Config A +24% / Config B +50% — Microsoft" as the model parameters, while §5.3 ran the realistic base case at +12%/+20%.** The two tables were three pages apart and directly contradicted each other. Introduced by the v3.0 base-case change. | **Critical** | Fixed — table now states the +12%/+20% base case with the alternative scenarios listed separately, each with references. |
| **T2** | §5.3 read "Three scenarios are therefore reported" immediately above a table of **four** scenarios. Introduced when `realistic` was added. | Moderate | Fixed. |
| **T3** | §1.3 read "Three limitations should be held throughout" and then listed **four** (the fourth added in the product-manager revision). | Moderate | Fixed. |
| **T4** | §6.3 recommended a "**hard** cap at $1,500" as the Uber control, while §4.4 — corrected in v3.0 — establishes that Uber's cap is a **soft** ceiling with a permission-based escalation path. The recommendation contradicted the evidence it cited. | **Major** | Fixed — now recommends the ceiling *with* the escalation path, and notes that copying the number without it copies half the control. |
| **T5** | §4.1 attributed "$150–250 per engineer per month" to **Uber**. That band is Anthropic's cross-enterprise average [6]; the Uber-specific verified figure is $500–2,000 for power users. The same sentence also said "before the introduction of a flat cap," contradicting §4.4. | **Major** | Fixed — misattribution removed and explicitly noted as removed. |

**Root cause.** All five arise from editing a long document section-by-section without a consistency pass. The first review corrected facts; it did not re-read the whole document afterwards. That is now recorded in §2 of the paper as a known failure mode of this revision process.

---

## 3. Class B — Unsourced or under-attributed claims

The audit's core test: every quantitative or factual assertion must carry a reference, or state explicitly that it is the author's derivation.

| # | Claim | Finding | Status |
|---|---|---|---|
| **U1** | **§4.6 "Structural shift 4 — second-order infrastructure costs"** — an entire numbered structural finding asserting that AI volume propagates into CI, build, storage and provisioning costs. **Carried no source whatsoever.** | The direction is supportable (Faros documents the volume increase and downstream strain); the *cost magnitude* is not published anywhere. v3.0 presented an unsourced inference as a finding. | Fixed — direction now sourced [23][37][11], and the section states plainly that no published source quantifies the resulting spend and that the §6.2 line is an author estimate. |
| **U2** | §1.3 cross-referenced "Section 5.5" for the product-management asymmetry; renumbering moved it to §5.6. | Stale internal pointer. | Fixed. |
| **U3** | "Senior departures costing $150,000–$300,000 each," attributed to Faros. | **Never independently corroborated.** Carried from an intermediate summary through v2.0 and v3.0 without verification — the same failure mode as the Uber statistics the first review caught. | Fixed — retained as context but explicitly marked uncorroborated and no longer relied upon. |
| **U4** | "30–50% of developers refused to submit tasks... even at $50/hour," presented as reporting on METR's update. | Traces to a **single practitioner blog**, not to METR's own text. Presented in v3.0 with the authority of the METR citation beside it. | Fixed — now attributed to [39] explicitly, distinguished from METR's own statement [20], and flagged single-sourced. |
| **U5** | §4.7 "Independent testing of a single real feature across a dozen model/harness combinations." | Source real and in the reference list, but **not named or cited inline**. | Fixed — [13]. |
| **U6** | §5.2 "Published guidance places fully-loaded year-one cost at 1.5–1.8× base salary." | "Published guidance" is not attribution. Source is Cadence. | Fixed — [14] and [15] for BLS. |
| **U7** | §4.8 "Advisory guidance published in 2026 applies this to AI consumption directly." | Vague attribution for the most legally consequential claim in the paper. | Fixed — EisnerAmper named inline, [31][35]. |
| **U8** | §1.1 three motivating claims (JetBrains tenfold, Uber four months, Microsoft licence wind-down). | All three true and all three sourced elsewhere in the document, but **uncited at the point of assertion** — the reader's first encounter with each figure had no reference. | Fixed — [4][5], [30], [10]. |
| **U9** | Abstract statistics — every headline figure. | An abstract that will be read standalone carried **no references at all**. | Fixed — nine inline citations added. |
| **U10** | §6.2 budget table — six line items totalling $44,400–64,800. | **Entirely unsourced.** Two lines are defensible derivations from published bands; two (CI/compute uplift, evaluation reserve) are pure author estimates presented in a table indistinguishable in styling from sourced data. | Fixed — provenance paragraph added distinguishing derived lines from estimates, and stating that including estimates should not lend them false authority. |
| **U11** | §5.2 PM compensation "$132,000 (Gusto) to $192,000 (job-posting analysis)." | Gusto named; the job-posting analysis was not. | Fixed — [15b], [15c]. |
| **U12** | §3.5, §3.1, §3.3, §3.4, §4.3, §4.5, §4.7, §5.8 — study descriptions. | Studies named in prose but with no resolvable pointer to the reference list. | Fixed — inline citations throughout. |

---

## 4. Class C — Bibliographic failures

| # | Defect | Status |
|---|---|---|
| **B1** | **No inline citation apparatus existed.** 38 references, zero body citations. | Fixed — **83 inline citations** added, plus a stated citation convention in §2. |
| **B2** | A raw `<cite index="92-1">` markup artefact survived into §1.3 — an internal tool marker with no URL, meaningless to any reader. | Fixed — replaced with proper attribution [37]. |
| **B3** | **Ten defined references were never cited from the body** (8, 9, 15a, 15d, 15e, 16, 17, 18, 21, 32) — present in the bibliography but bound to no claim. | Fixed — all ten now bound to specific assertions. |
| **B4** | One inline citation [39] was introduced with no corresponding reference entry. | Fixed — entry added, with its single-source limitation stated in the reference itself. |

**Post-fix bibliographic integrity check (automated):**

```
UNRESOLVED (cited but undefined): none
UNCITED    (defined but unused): none
Total inline citations: 83
```

---

## 5. What passed

Worth stating, since an adversarial review that reports only failures is not calibrated:

- **Every numeric result in §5 reconciles exactly to the companion model.** Ten headline figures cross-checked against `ai_team_cost_model.py` output; all matched.
- **The four errata notes added in v3.0 are accurate** and correctly describe what was wrong, including the misattribution to Simon Willison.
- **The single-sourced flags added in v3.0 held up** — no additional uncorroborated claims were found beyond U3 and U4.
- **No new factual errors** were found in the source content itself. The first review's substantive corrections are intact.
- **The METR treatment remains the most careful in the retrieved literature**, correctly separating the valid 2025 finding from the withdrawn 2026 follow-up.

---

## 6. Assessment

The two reviews together expose a pattern worth naming, because it is the same pattern the paper documents in its own subject matter.

The first review found that **confident-sounding numbers relayed through an intermediate summary were the ones that failed** — the Uber statistics were the most quotable and the least checked. This second review finds that **the claims with no source at all were the ones nobody thought to check**, because an assertion with no citation attracts no scrutiny of its citation. §4.6 survived three drafts as a numbered structural finding without a single reference behind it.

Both failures are verification-gap failures, and both are precisely what the paper argues happens to engineering organisations under AI-first operation: generation is cheap, verification is expensive, and the cost surfaces later. A document produced quickly with AI assistance exhibits the same economics as a codebase produced quickly with AI assistance. The correct response is the same in both cases — instrument the verification step explicitly rather than trusting that fluent output is correct output.

**v3.1 should be considered traceable but not independently peer-reviewed.** Every claim now resolves to a named source or a declared derivation. That is a floor, not a ceiling: it establishes that assertions can be checked, not that a third party has checked them.

---

*Audit performed against v3.0 as at 13 August 2026. Corrections applied and reissued as v3.1. Bibliographic integrity verified programmatically.*
