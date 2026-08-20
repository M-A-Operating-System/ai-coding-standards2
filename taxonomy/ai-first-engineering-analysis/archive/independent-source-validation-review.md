# Independent Source Validation and Assessment

## Adversarial review of *The Cost Structure of AI-First Engineering Teams* (v2.0)

**Review date:** 13 August 2026
**Scope:** Every source cited in v2.0 retrieved and checked against primary material or, where the primary is paywalled or gated, against three or more independent secondary reports.
**Reviewer stance:** Adversarial. The objective was to find errors, not to confirm the paper.

---

## 1. Verdict

**The paper's central arithmetic is sound. Its evidence base is not evenly reliable, and its base case is anchored on the wrong study.**

Fourteen defects were identified: two critical, four major, four moderate, four minor. Two of the critical and major defects originate in figures relayed from a prior conversation and incorporated into v2.0 without independent verification — a process failure the paper's own methodology section (§2) implicitly claimed not to have committed.

The most consequential findings are:

- **Three unverified Uber statistics** in §4.4 are uncorroborated and one is contradicted by Uber's CEO on the record.
- **An explicit misattribution**: the paper claims a derived calculation as the author's own when it is Simon Willison's, published.
- **The Stanford figures are materially misrepresented**, omitting the single most decision-relevant number in that study — a *net* effect of 15–20% after rework.
- **The "optimistic" scenario is anchored on the outlier study**, which is also the one with the most disclosed conflict of interest. Three independent datasets converge in the low-to-mid teens; the paper's base case sits at +24%/+50%.
- **A primary source explicitly disclaims the extrapolation the paper performs.** Faros states that agentic authoring is under 1% of PRs in its dataset and warns that removing the human from the loop worsens every metric by roughly an order of magnitude.
- **A deep internal inconsistency**: the paper cites extensive evidence that merged-PR counts are inflated by AI, then uses merged PRs as its output denominator. This biases the model *in favour* of Configuration B.
- **The accounting section (§4.8) is directionally wrong.**

None of this reverses the paper's bottom line — if anything the corrected evidence strengthens the recommendation against substitution. But several specific numbers must not be used in a business case as written.

---

## 2. Source validation register

Legend: **✅ Verified** (primary or 3+ independent secondary) · **⚠️ Verified with correction** · **❌ Failed** · **◐ Partially verified**

| # | Claim as stated in v2.0 | Status | Finding |
|---|---|---|---|
| 1 | Microsoft: +24.0% merged PRs [CI +14.5%, +33.7%]; +50.1% at 5+ tool-days | ✅ | Primary retrieved (arXiv:2607.01418). Exact. Placebo test and authorship conflict disclosure confirmed as described. |
| 2 | Microsoft: Copilot CLI +24.9% vs Claude Code +11.4% | ✅ | Primary. Correctly reported, including the authors' own hypotheses for the gap. |
| 3 | Anthropic: ~$13/dev/active day; $150–250/dev/month; 90% under $30/day | ✅ | Primary (code.claude.com/docs/en/costs). Exact. |
| 4 | DORA J-curve; $344,000 downtime impact; 5%→6% change failure rate | ✅ | Confirmed via InfoQ reporting of the DORA 2026 ROI report. Figures and framing accurate. |
| 5 | DORA discourages headcount reduction | ✅ | Confirmed. Accurately characterised. |
| 6 | METR: −19%; forecast +24%, self-assessed +20% | ✅ | Primary. Exact, including the three-way divergence. n=16, 246 tasks, Cursor Pro with Claude 3.5/3.7. |
| 7 | METR 2026 follow-up withdrawn as unreliable; no current point estimate | ✅ | Primary. v2.0's correction of the prior chat's −18%/−4% figures is **validated and was the right call**. Follow-up covers 57 developers, 143 repos, 800+ tasks. |
| 8 | DX: 400+ companies, AI usage +65%, median PR throughput +7.76%, mean 13.1% | ✅ | Primary (getdx.com report page and three DX secondary posts). Exact. Additional detail: gamification filtered by excluding teams with individual PR targets. |
| 9 | Faros: 22,000 developers, 4,000 teams; +16.2% PRs/dev, +33.7% tasks, +66.2% epics | ✅ | Primary PDF plus five independent secondary. Exact. |
| 10 | Faros: bugs +54%, incidents/PR +242.7%, churn +861%, 31% merging unreviewed | ✅ | Confirmed. PR size +51% also confirmed. |
| 11 | Faros: maturity does not insulate | ✅ | Confirmed verbatim in the primary PDF. |
| 12 | Faros: $1.14 vs $3.66 per task; ~$900k/yr at 30k tasks/month | ◐ | Not independently corroborated in this pass. Plausible and consistent with Faros's published cost work, but **flag as single-sourced**. |
| 13 | GitClear: duplication +81%, error-masking +47%, cross-file calls −35%, legacy maintenance −74% | ✅ | Primary. Exact. Dataset is 623M changes, 2023–2026, with GitKraken. |
| 14 | GitClear: refactored code 21% (2022) → 3.8% (2026) | ⚠️ | **The 21%/2022 figure is not GitClear's.** Their series: ~24–25% (2020–21) → 9.5% (2024) → 3.8% (2026 edition). GitClear's own headline is refactoring line moves down 70%. |
| 15 | GitClear: 73.0 duplicated blocks per million changed lines | ❌ | **Not found in any retrieved GitClear material.** Cannot substantiate. Recommend deletion. |
| 16 | GitClear: heavy AI users out-produce non-users 4–10x; gap pre-dated AI; ~25% against own past | ⚠️ | 4–10x and the pre-dating confirmed. **The "closer to 25%" figure could not be confirmed** — source text truncated. Also **this is a different GitClear study** ("AI Coding Tools Attract Top Performers", Jan 2026), not the Maintainability Gap paper the citation points to. |
| 17 | Kim & Koning: ~25% smaller (YC), ~12% (PitchBook); process channel does not predict headcount | ✅ | Primary PDF plus HBS, Forbes, TIME, HRD. Exact, including the 2.6x tool-naming figure and its failure to predict once controlled. |
| 18 | Kim & Koning: services firms ~70% smaller / run at ~30% of peers | ✅ | Confirmed in primary. |
| 19 | Stanford: 35–40% greenfield, ≤10% complex legacy | ⚠️ | **Materially incomplete — see Defect M1.** Actual structure is a 2×2 matrix with a net figure the paper omits entirely. |
| 20 | Stanford Canaries: entry-level employment effects | ⚠️ | Real, but the paper cites the superseded edition. August 2025: 13%. **August 2026 update with data through June 2026: 19%**, and the divergence has widened. |
| 21 | Uber: $1,500/month cap per employee per agentic tool | ✅ | TechCrunch/Bloomberg plus four independent. Confirmed. |
| 22 | Uber: annual AI budget exhausted in four months | ✅ | Confirmed; disclosed by CTO Praveen Neppalli Naga in April via The Information. |
| 23 | Uber: power users $500–$2,000/month | ✅ | Confirmed. |
| 24 | Uber: adoption 32% (Feb) → 84% (Mar) | ❌ | **Uncorroborated.** No retrieved source contains these figures. |
| 25 | Uber: ~70% of committed code from those tools | ❌ | **Uncorroborated and contradicted.** CEO Dara Khosrowshahi is reported saying about 10% of Uber's code was AI-created. |
| 26 | Uber: ~11% of live backend updates agent-written, no human in loop | ❌ | **Uncorroborated.** No retrieved source contains this. |
| 27 | Uber: ~$36,000/engineer/yr ≈ 10% of $330,000 — "this arithmetic is the present author's" | ❌ | **Misattribution.** This is Simon Willison's published calculation, and he states 11%, not 10%. |
| 28 | GitLab: review times +91%; $0.25 flat per review; $15–25 token-metered alternatives | ✅ | Confirmed. Note: the +91% figure traces to Faros's **2025** report (10,000 developers), not 2026. |
| 29 | Larridin: $200–$2,000+/engineer/month agentic; $200–600 blended | ✅ | Confirmed as stated. Vendor-adjacent, correctly flagged in the paper. |
| 30 | Tunguz: top 1% ~$89k/engineer/yr ≈ 40% of $224k; median $137 | ✅ | Confirmed. |
| 31 | DX: 1–3% of engineering budgets; $1,000/dev/yr target | ✅ | Confirmed. |
| 32 | Forbes/Mavvrik: only 15% forecast within 10%; 372 enterprises | ✅ | Confirmed, with the paper's vendor-origin caveat appropriately applied. |
| 33 | FinOps Foundation: 73% of enterprises exceed AI cost projections | ◐ | **Single-sourced via the prior conversation.** FinOps Foundation's GenAI cost-tracking guidance is real; this specific percentage was not independently located. Flag or drop. |
| 34 | Insight Services APAC: $7–$70 per merged feature; ~$30 single-cycle frontier | ✅ | Confirmed. Correctly caveated as single-feature. |
| 35 | Cadence: fully-loaded 1.5–1.8× base; BLS median $133,080 | ✅ | Confirmed. BLS figure is the May 2024 release, correctly stated. |
| 36 | PM compensation ~$150k base convergent | ✅ | Confirmed across KORE1, Gusto, Glassdoor, Recruiting from Scratch. Dispersion correctly characterised. |
| 37 | EisnerAmper: AI consumption cost accounting | ⚠️ | Source is real. **The paper's characterisation of it is directionally wrong — see Defect M4.** |

---

## 3. Defects

### Critical

**C1 — Three fabricated or unverifiable Uber statistics (§4.4).**
The claims that adoption ran 32%→84% between February and March, that ~70% of committed code originated from agentic tools, and that ~11% of live backend updates were agent-written with no human in the loop are not supported by any retrieved source. The 70% figure is directly contradicted by Uber's CEO, reported as saying roughly 10% of the company's code was AI-created. These entered v2.0 from a prior conversation's summary and were not checked.

*Required action:* delete all three. Retain the verified $1,500 cap, four-month budget exhaustion, $500–2,000 power-user band, internal dashboard, and permission-based exception mechanism.

**C2 — Misattributed calculation (§4.4, Appendix A.22).**
The paper states the $36,000/11%-of-package arithmetic is "the present author's, not the source's." It is Simon Willison's, published and widely reported, and his figure is 11% rather than the paper's 10%. Claiming another analyst's published derivation as original work is the most serious defect in the document.

*Required action:* attribute to Willison, correct to 11%, and remove the originality claim.

### Major

**M1 — Stanford figures materially misrepresented (§3.4, §5.4).**
The paper reports "35–40% greenfield; ≤10% complex legacy," sourced second-hand through InfoQ's summary of DORA's citation. The actual study (Denisov-Blanch, ~100,000 engineers, 600+ companies, tens of millions of commits) reports a 2×2 matrix:

| | Greenfield | Brownfield |
|---|---|---|
| Low complexity | 30–40% | 15–20% |
| High complexity | 10–15% | 0–10%, sometimes negative |

Critically, the paper **omits the study's headline result**: gross output rises 30–40%, but after accounting for rework the *net* average is **15–20%**. That net figure is the single most decision-relevant number in the source and it is absent from a paper whose entire model turns on the lift parameter.

*Required action:* replace with the full matrix, foreground the net 15–20%, and cite Stanford directly rather than through two intermediaries.

**M2 — The base case is anchored on the outlier study.**
Corrected, the independent evidence converges:

| Source | Design | Central estimate |
|---|---|---|
| DX | 400+ orgs, longitudinal | +7.76% median, +13.1% mean |
| Faros | 22,000 devs, telemetry | +16.2% PRs/dev |
| **Stanford** | **100k devs, commit analysis** | **+15–20% net of rework** |
| Microsoft | telemetry, within-person | **+24% / +50%** |

Three independent datasets cluster at roughly 8–20%. Microsoft is the outlier — and it is the study whose authors disclose that their employer sells AI tools and owns the vendor of the better-performing tool. The paper labels its Microsoft-anchored scenario "optimistic," which is honest, but then uses it as the reference baseline for the sensitivity sweep and derives its headline $96,774 from it.

*Required action:* make the conservative scenario the base case. The Microsoft-anchored figures should be the upper bound, not the reference.

**M3 — A primary source explicitly disclaims the paper's core extrapolation.**
The Faros 2026 report states that <cite index="92-1">agentic authoring currently accounts for less than 1% of PRs in this dataset</cite>, characterises its data as reflecting AI used as a primary authoring tool *with humans still in the loop*, and warns that removing the human entirely subjects every metric in the report to pressure roughly an order of magnitude greater — adding that the industry is not ready for that transition.

The paper's §1.3 limitation ("no published study of teams operating in the pure form") understates this considerably. It is not merely that the evidence is absent; the largest relevant dataset in the paper contains an explicit warning against the inference the paper builds its model on.

*Required action:* elevate this from a scope note to a foregrounded limitation, quoted and attributed, in both §1.3 and the abstract.

**M4 — The accounting section is directionally wrong (§4.8).**
The paper asserts that substituting metered AI consumption for capitalisable engineering labour reduces the capitalised software asset base and front-loads cost recognition. The cited source says something closer to the opposite: ASC 350-40-30-1 permits direct costs in the application development stage to be capitalised, and EisnerAmper explicitly identifies AI tokens used for coding and functionality creation as capitalisable on that basis, which can materially improve reported results. Subscription and usage fees for SaaS *consumption* are typically expensed; tokens consumed to build a software asset are a different question. ASU 2025-06 further updates internal-use software guidance.

The real issue is not availability but **substantiation**: capitalisation requires per-project attribution of token spend, which most teams cannot produce. That connects directly to the gateway/accounting-layer control the paper already recommends in §6.3, and is a stronger argument than the one currently made.

*Required action:* rewrite. The correct claim is that capitalisation is available but conditional on attribution infrastructure, and that the infrastructure is the same infrastructure needed for cost control.

### Moderate

**D1 — Internal inconsistency in the output metric.**
The paper devotes §4.5 to evidence that AI inflates PR counts — Faros reports PR size +51%, 31% merging unreviewed, churn +861%; GitClear reports rising duplication and falling refactoring; Stanford quantifies rework consuming half the gross gain. It then adopts merged PRs as the output unit for the entire model.

A merged PR under Configuration B is not the same unit of delivered value as a merged PR under Configuration A. Because the degradation scales with AI intensity, and Configuration B is the higher-intensity arm, **the model systematically overstates Configuration B's output.** The paper acknowledges the proxy's weakness in §1.3 but does not carry the implication into the analysis, where it matters most.

*Required action:* state explicitly that the throughput ratios are upper bounds on Configuration B, and consider a rework-discount parameter.

**D2 — GitClear citations conflate two separate studies.**
The selection-effect finding (4–10x, mostly pre-dating AI) comes from "AI Coding Tools Attract Top Performers — But Do They Create Them?" (January 2026), not the Maintainability Gap paper to which the paper attributes it. The "~25% against their own past selves" figure could not be confirmed and should be softened or sourced.

**D3 — The Uber cap is not absolute.**
The paper presents $1,500 as a hard cap and recommends it as such. Reporting is consistent that the cap can be exceeded with permission, tracked against a per-employee dashboard. This is a materially different control design — a soft ceiling with an escalation path, not a hard stop — and the escalation path is arguably the more important half.

**D4 — Stale Stanford Canaries figure.**
The paper cites the August 2025 edition. The August 2026 update, with ADP data through June 2026, reports the gap at 19% and widening, operating primarily through reduced hiring rather than separations, with no evidence of economy-wide displacement. The authors explicitly frame the findings as descriptive rather than causal — a caveat the paper should carry.

### Minor

**N1 — Faros review-time metric ambiguity.** The paper cites "median time in PR review up 441%." Faros publishes several review metrics (median time in review +441.5%; median time to first review +156.6%; average time in code review +199.6%). The paper should name which.

**N2 — GitLab's +91% is 2025 data.** It traces to Faros's 2025 report (10,000 developers), not the 2026 edition. Presented adjacent to 2026 figures without distinction.

**N3 — Missing structural ceiling argument.** DX's explanation for why gains are modest — coding is roughly 14% of a developer's day, so accelerating it has a bounded ceiling, and developers report saving ~3.9 hours/week that does not convert proportionally to output — is the clearest mechanical account of the whole phenomenon and is absent.

**N4 — No uncertainty propagation.** The model runs deterministic point estimates while the underlying evidence carries wide intervals (Microsoft +14.5% to +33.7%). The $96,774 break-even is reported to the dollar; the honest precision is roughly ±$40,000 on the Microsoft CI alone.

---

## 4. What survives, and what the corrected evidence implies

**Survives unchanged:**

- The arithmetic of the model. Recomputed independently; correct in every scenario.
- The +148%/+115.5% parity requirements. Correct, and no source supports lifts of that magnitude.
- The Kim & Koning process/product channel finding and its application. This is the strongest argument in the paper and it validated fully.
- The METR handling. v2.0's correction of the prior chat's figures was right and is now the most defensible treatment of METR I found anywhere in the retrieved material.
- The product management critique (§5.5). Directionally supported, and strengthened by Stanford's rework finding.
- The specification/verification bottleneck thesis.

**Strengthens against Configuration B:**

Correcting M1 and M2 moves the realistic lift band down. A defensible base case using the convergent evidence — Configuration A at roughly +12%, Configuration B at roughly +20% at maximum intensity, consistent with Stanford's net band — yields:

- Configuration A: 4.48 units, cost per unit ≈ $243,300
- Configuration B: 2.40 units, throughput ratio ≈ **53.6%**
- Break-even AI budget ≈ **$21,400**

That is below the paper's own §6.2 operating cost for the configuration. Combined with D1 (the output metric flatters Configuration B) and M3 (the primary source warns the pure form is materially worse), **the corrected evidence supports the paper's conclusion more strongly than the paper's own optimistic base case does.**

**The recommendation should therefore be sharpened, not softened:** on the corrected evidence, Configuration B is not viable at any realistic AI budget except under assumptions drawn from a single conflicted outlier study. The staged measurement approach in §6.1 remains correct and becomes the primary recommendation rather than an alternative.

---

## 5. Required corrections, in priority order

1. Delete the three unverified Uber statistics (C1).
2. Attribute the $36,000/11% calculation to Simon Willison and remove the originality claim (C2).
3. Replace the Stanford summary with the full 2×2 matrix and foreground the net 15–20% after rework (M1).
4. Demote the Microsoft-anchored scenario from base case to upper bound; promote the conservative scenario (M2).
5. Rewrite §4.8 on accounting treatment (M4).
6. Quote and foreground the Faros disclaimer on agentic authoring and human-out-of-loop extrapolation (M3).
7. State that throughput ratios are upper bounds on Configuration B given the PR-count inflation the paper itself documents (D1).
8. Split the GitClear citations; soften the unconfirmed 25% figure; delete the 73.0-per-million figure (D2, register #15).
9. Correct the Uber cap description to a soft ceiling with escalation (D3).
10. Update Stanford Canaries to the August 2026 edition and add the descriptive-not-causal caveat (D4).
11. Add the ~14% coding-share ceiling argument (N3).
12. Add uncertainty ranges to the headline break-even figures (N4).
13. Name the specific Faros review metric (N1); date the GitLab +91% figure to 2025 (N2).
14. Flag the Faros per-task cost figures and the FinOps 73% figure as single-sourced (register #12, #33).

---

## 6. Assessment of method

The paper's stated methodology (§2) claims a preference for first-party operator data over survey aggregation. In practice v2.0 met that standard for roughly two thirds of its citations and failed it for the Uber material specifically, where second-hand summary was presented with the specificity of primary reporting. The failure is instructive: the fabricated figures are precisely the ones that were most quotable and least checked.

The v1.0→v2.0 revision, in which incorporating adversarial evidence reversed the recommendation, is methodologically sound and should be preserved as a visible feature of the document rather than smoothed over.

The remaining structural weakness is that the paper measures a quantity (merged PRs) that its own evidence section establishes is corrupted by the intervention being measured. Until that is resolved — most practically by adopting the paper's own proposed unit of fully-loaded cost per merged change surviving 90 days — the model should be read as an upper bound on Configuration B rather than an estimate of it.

---

*Prepared as an independent review. All sources retrieved 13 August 2026. Where a primary source was gated, verification required three or more independent secondary reports in agreement; claims meeting neither standard are marked ◐ or ❌ above.*
