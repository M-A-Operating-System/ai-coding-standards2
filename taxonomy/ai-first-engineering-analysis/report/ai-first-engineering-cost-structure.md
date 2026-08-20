# What Does an Equivalent Engineering Team Look Like in an AI-First World?

**13 August 2026**

| | Old team | New team |
|---|---|---|
| Composition | 1 tech lead + 5 developers | supervisors + agents |
| Output | 5 units of work | 5 units of work |
| Quality | baseline | baseline |
| Headcount | 6.0 FTE | **? — the question** |
| Cost | $1,250,000 | **? — the question** |

**A unit of work is one developer-year of merged, delivered output** — so the old team's five developers produce five units by definition, and every other figure is measured against that. Holding output and quality constant is what makes the two teams comparable. The question is therefore: *how many people, in what roles, does it take to deliver the same work to the same standard?*

**Scope.** This paper covers the **engineering function only** — the tech lead and the developers. The same method applies to product management, QA, design and support, and the arithmetic would be similar: each function moves from humans performing the work to agents performing it under human supervision, with the headcount set by how much agent output one person can oversee. Those functions are excluded here to keep the analysis to a single role where the supporting evidence is strongest. **A whole-organisation figure cannot be read off this paper**, and would be larger.

---

## The answer

**An equivalent engineering team is three people rather than six.**

| | FTE | Cost |
|---|---|---|
| Tech lead — supervision, architecture, escalation | 1.00 | $250,000 |
| Supervising engineers — senior rate, $240k | 2.29 | $549,600 |
| **People** | **3.29** | **$799,600** |
| AI — 2,100 Mtok per unit, 5 units | | $31,500 |
| **Total** | **3.29 FTE** | **$831,100** |
| *Old team* | *6.00 FTE* | *$1,250,000* |
| **Change** | **−45%** | **−34%** |

**Supervisors are priced above developers**, at $240,000 against $200,000. The role is senior — specifying, reading, verifying and accepting agent output rather than authoring — and pricing it at developer rates would assume a role change with no compensation change.

**The shape changes more than the size.** The old team was 83% authors and 17% supervisors. The new one is entirely supervisors: the team is exactly **R** people, and nobody writes production code as their main job. **AI is 3.8% of total cost.**

### Why three and not two

If agents author and humans supervise, no human's authoring speed constrains anything. What binds is supervision.

**The anchor is the old team's own tech lead.** That person supervises five developers producing five units — full-time, as the job. So one full-time supervisor covers five units of human-authored work. Agent-authored work costs **R** times as much per unit to supervise, so the same supervisor covers `5 / R` units, and five units need **R supervisors**.

Published data puts **R at approximately 3.29** (§3), giving 3.29 supervisors — the tech lead plus 2.29 more. **That is the whole team.**

| R | Team | Total cost | vs old |
|---|---|---|---|
| 2.0 | 1 lead + 1.00 supervisor | $521,500 | −58% |
| 2.65 | 1 lead + 1.65 | $677,500 | −46% |
| **3.29 — published data** | **1 lead + 2.29** | **$831,100** | **−34%** |
| 4.0 | 1 lead + 3.00 | $1,001,500 | −20% |

**A two-person team is not reachable at any R the evidence supports.** It requires R ≤ 2.0, and every measure available puts R between 2.3 and 5.3.

**Cost is the scoreboard, not the subject.** AI runs about 3% of total cost and is invariant to R: identical output means identical tokens regardless of how many people supervise. All variation is people. A 50% overrun on the AI bill moves total cost by 1.9%; one supervisor either way moves it by 29%.

**The result is a point inside a wide band, not a forecast.** Three parameters carry the answer and none is directly measured: span of control, the maintainability allowance, and the supervisor rate. Compounded, they put the outcome anywhere between +2% and −56% against the old team (§5). The base case is −34%; the direction is robust across most of the band, the magnitude is not.

**Recommendation: adopt AI conventionally; target an engineering team of around three rather than two; commission refactoring explicitly rather than assuming it; measure R locally to size the team.**

---

## 1. What We Set Out to Test, and What the Literature Contains

### 1.1 The hypothesis

**We began with a target state in mind: a conventional team of six — one tech lead and five developers — evolving into an AI-first team of two, one supervisor and one developer, with agents doing the authoring.** That is the shape the AI-first argument is usually made in, and it implies roughly a two-thirds reduction in engineering headcount.

**This analysis suggests that target is not reachable.** A two-person team requires the effort of supervising agent-authored work to be no more than **twice** the effort of supervising a colleague's work. Every measure available puts that ratio between 2.3 and 5.3, and the derivation in §3 puts it near 3.29. At that value two people deliver **61%** of the old team's output, not 100%.

**What the analysis does support is an evolution from six people to around three** — a 45% reduction rather than 67%, with the composition changed more than the size: nobody authoring, everybody supervising.

The gap between the target and the finding is a single quantity: how much agent output one person can actually oversee. That is what the rest of this paper derives, and it is measurable in-house within a quarter. **It also depends on an assumed span of control, and at the upper end of the plausible range the two-person target does become reachable** — §5 sets out how much of the finding is assumption.

### 1.2 What the literature does not contain

**We were unable to find any current research, active study or measured evidence comparing a traditional engineering team with an AI-first team.** That comparison does not exist as of August 2026, this paper does not supply it, and we found no such study announced, in progress or in preprint. Everything here is extrapolation from adjacent evidence, and carries the confidence appropriate to that.

**The distinction matters because the two questions have different answers.** *How much faster does a developer work with AI?* is not *how much output can a team produce if agents do the authoring?* The first measures a multiplier on human authoring; the second measures a ceiling on human supervision. The literature answers the first. The decision requires the second.

**The largest relevant dataset explicitly disclaims the extrapolation.** Faros, reporting telemetry across 22,000 developers, states that agentic authoring accounts for under 1% of pull requests in its data, and warns that removing the human from the loop subjects every metric it publishes to pressure roughly an order of magnitude greater [37].

**Direction of bias.** The output unit is merged delivered work, and AI adoption inflates it — pull requests run 51% larger, 31% more merge unreviewed, and roughly half the gross productivity gain is consumed by rework [23][33][37]. Because the inflation scales with intensity and the agent-primary team is the higher-intensity arm, **every throughput figure here is an upper bound, not an estimate.**

The evidence base, the conflicting productivity estimates and their reconciliation are in **Appendix F**.

---

## 2. The Team, Role by Role

**Tech lead — 1.00 FTE.** Unchanged in count, changed in content. In the old team this person supervised five developers; in the new one they supervise agents, plus the other supervising engineers. Architecture, escalation and final accountability sit here.

**Supervising engineers — 2.29 FTE at the published R.** This is the only line that moves with R, and it moves proportionally: every 0.1 on R is 0.1 of a person. These are senior engineers whose job is specifying, reading, verifying and accepting agent output — not authoring. The role is closer to a staff engineer running code review than to a developer.

**Refactoring is not a role.** Agents do not refactor by default — refactoring line-moves are down 70% against a conventional baseline while duplication is up 81% [26]. But that is a finding about what agents do unprompted, not about what they can do. Directed to consolidate duplication or extract a shared abstraction, an agent produces that work like any other, and it sits inside the target output and is supervised at the same cost R.

What remains human is the *judgement* of what to refactor and when, which belongs to the supervisors alongside every other architectural decision. **Treating it as a separate headcount line would double-count the execution.** It becomes instead an obligation on the team: refactoring must be explicitly commissioned rather than assumed, and duplication and code turnover must be watched to confirm it is happening (§6.2). If those measures degrade, the quality-neutral premise has failed and this comparison no longer applies.

**What is absent: authoring capacity.** No one on this team writes production code as their primary job. That is the substitution, and it is the whole of the saving — 5.0 FTE of authoring replaced by 2.29 FTE of additional supervision and $31,500 of tokens.

**Specification is a practice here, not a headcount line.** Under-specified work is among the largest drivers of R (§3), so whoever supplies specification — a product manager inside or outside the team, or the tech lead — is exerting direct leverage on the supervisor count. Under-resourcing it raises the engineering headcount by more than it saves elsewhere. Where the product function itself moves to AI-led working, the same method in this paper applies to it; that analysis is out of scope here.

---

## 3. Where R Comes From

**R is not directly measured anywhere in the literature, but it is derivable.** Review effort has risen from a pre-AI baseline of 3 to 6.4 hours a week to a median of 11.4 [44][46][48], while output rose only 8–20% and 42% of committed code is now AI-authored [42]. Solving for the premium attaching to that 42% gives **R ≈ 3.29**, in a range of 1.8 to 4.8 depending chiefly on which pre-AI baseline is used.

**Three independent methods corroborate**, using different denominators and none of them clean: elapsed review time against task throughput implies 4.05 [23][37]; senior review at 4.3 minutes per AI suggestion against 1.2 for human-authored code implies 3.58 [39]; and agentic pull request pickup time across 8.1 million PRs implies 5.30 [43]. All four approaches land between 2.3 and 5.3, none below 1.8. Survey evidence agrees on direction: 38% of developers say reviewing AI-generated code takes more effort than reviewing a colleague's, and 81% report spending more time in review since adopting AI [42][45].

**Two cautions on the derived figure, pointing opposite ways.**

The 11.4-hour figure covers "verifying, fixing and debugging" [42]. Fixing and debugging are rework rather than supervision, so a supervision-only R would be lower — nearer 2.1–2.6, which would put the team at roughly 3.1 FTE and a 36% saving rather than 24%.

Against that, **R is derived from teams where 42% of code is AI-authored and applied here to teams where effectively all of it is.** The same dataset that supplies much of the underlying telemetry warns that removing the human from the loop subjects its metrics to pressure roughly an order of magnitude greater (§1.2). If that warning is right, **3.29 is a lower bound on the agent-primary ratio, not a central estimate** — and the honest position is that this paper cannot say which of the two cautions dominates.

**Why R exceeds 1, structurally.** Three mechanisms do not dissolve as models improve. A developer who submits work stakes professional judgement on it, and that stake does verification work — an agent carries no stake, so none of the reviewer's burden is discharged by the submission. Supervising people gets cheaper as trust accumulates; agent competence varies across task type and silently across model versions, so no stable prior forms. And a colleague who attended the design discussion carries shared context, so review checks correctness — an agent has only the prompt, so review checks correctness *and* intent. A better model reduces error rates; it does not acquire a stake, build a reputation, or attend the meeting.

**What moves R is substantially practice, not capability.** Large changes raise it — agent output arrives ~51% larger [23][37] and review effort per line rises with size [41]. Under-specified tasks raise it. Absent machine-checkable gating raises it. Constraining agents to small, well-specified, reversible changes with test-first gating lowers it. **The gap between the derived 3.29 and the 2.0 that would take the team to 2.5 people is closer to a process-discipline gap than a model-capability gap.**

**R should fall over time, but not to 1.** Its capability component declines as models improve; its structural component does not, and where that floor sits is unknown. The available evidence does not yet show R falling: review effort per developer rose 31% year over year [44], and code quality signals worsened continuously from 2023 to 2026 across a period of substantial model improvement [26].

Derivation, assumption register and sensitivity analysis are in **Appendix A**.

---

## 4. What the AI Actually Costs

**The AI bill is built from token consumption, not from a budget.** An agentic coding task in the SWE-bench class consumes 1.0–3.5M tokens including retries and self-correction, input tokens dominate at a 2:1 to 3:1 ratio, and repeated runs of the same task vary by up to 30× [49][50]. Unresolved attempts consume roughly four times the resources of successful ones, so failed runs are a material share of the bill. Combining merged tasks per unit, tokens per task, the share of runs that merge, and a blended price net of caching:

| Case | Tokens per unit | Cost per unit | Per supervisor per year |
|---|---|---|---|
| Low | 250M | $250 | $380 |
| Mid | 750M | $1,500 | $2,280 |
| **High — agent-primary** | **2,100M** | **$6,300** | **$9,574** |

**The result reconciles against observed operator spend**, which is the check a budget-derived figure cannot pass. The mid case lands on Anthropic's published enterprise average of $150–250 per developer per month [6]; the high case lands inside Uber's reported power-user band of $500–2,000 per month [30]. Agent-primary work is power-user work, so the high case is used throughout.

**Tokens per supervisor is the number worth instrumenting.** At the published R, one supervisor oversees roughly **3,200M tokens a year** of agent output, rising to 7,000M at R = 1.5 because fewer supervisors carry the same volume. Unlike R, this is directly measurable from a gateway or CLI wrapper without new instrumentation. **It is a saturation signal rather than a cost signal:** if a supervisor is carrying three billion tokens a year, the question is not the bill — which is under $10,000 — but whether anyone is genuinely reviewing that volume.

---

## 5. How Much of This Is Assumption

Three parameters carry the result and none is directly measured. Their ranges matter more than R does.

| Parameter | Low | Base | High | Basis |
|---|---|---|---|---|
| **Span of control** | 4 → 4.11 FTE, −18% | **5 → 3.29 FTE, −34%** | 7 → 2.35 FTE, −52% | **Assumption.** Engineering spans are commonly cited between 4 and 10; no source is offered for 5 |
| **Supervisor rate** | $200k → −41% | **$240k → −34%** | $275k → −27% | Judgement on how far the role is repriced |
| **Dedicated refactoring role** | none — **base** | — | 0.5 FTE → −24% | Priced for a reader who rejects the argument in §2 that refactoring is supervised agent work |

**Compounded, the band runs from +2% to −56%.** A pessimistic reading — span 4, staff-level pay, and a dedicated 0.5 FTE refactoring role — gives 4.61 FTE at $1,274,250, marginally *more* expensive than the old team. An optimistic reading — span 7, developer pay, no dedicated role — gives 2.35 FTE at $551,500.

**Span of control is the weakest link and the strongest lever.** It moves the answer further than R does, and unlike R it has no derivation behind it at all. **At a span of 7 the two-person target this paper rejects becomes reachable**, which means the central negative finding rests on an assumption rather than on evidence. A reader who believes their supervisors can oversee seven engineers' worth of work should expect a materially different answer.

**What is robust:** the direction, across most of the band, and the structural finding that the team becomes mostly supervisors with an explicit maintainability role. **What is not robust:** the magnitude, and any claim that a specific headcount is correct.

---

## 6. What Follows

### 6.1 The decision

**Adopt AI; restructure engineering toward around three people, not two.** The two moves are separable. Conventional adoption is cheap, well evidenced and returns roughly 9.5% better cost per unit. The restructuring delivers a further 20–58% depending on where R lands locally, inside a wider band on the assumptions in §5 — substantial, but short of the two-thirds a two-person target implies.

**The economics hold across the plausible range of R** — 58% saving at R = 2.0, 34% at the published 3.29, and 20% at R = 4.0 — though §5 shows the band on the surrounding assumptions is wider than the band on R. **Cost is not the deciding factor; three non-financial conditions are.**

1. **Capacity, not capital, must be the thing you can afford to trade.** The restructuring reduces headcount at constant output. If the backlog limits the business, adding capacity beats reducing cost, and this is the wrong move regardless of the saving.
2. **Refactoring must be commissioned and specification resourced.** Agents do not refactor unprompted, and under-specified work drives R up. Neither happens by default: refactoring has to be explicitly tasked to agents and verified, and specification has to come from somewhere.
3. **The team must be able to absorb the concentration risk.** Four people supervising agents have less redundancy than six people sharing authoring and review. A single departure removes a capability rather than degrading it.

**Measure R anyway**, not to decide whether to proceed but to size the team: every 0.1 on R is 0.1 of a supervisor, and the difference between 2.65 and 4.0 is 1.35 people.

**The contrary position.** DORA discourages headcount reduction as an AI strategy, arguing that retention preserves institutional knowledge and that returns come from offloading toil rather than replacing developers [2][3]. That argument bears directly on the third condition above, and it is the strongest case against proceeding even where the arithmetic is favourable.

### 6.2 What to measure

**Measure R first.** It is computable from three months of existing agent history: supervision hours per merged unit surviving 90 days, for agent-authored work divided by the same for human-authored work. Published data puts R at approximately 3.29 (§3), so the local measurement checks whether your practice beats the observed norm — it is not an open question.

**Track review hours separated by authorship.** Only ~38% of organisations track time spent reviewing AI-generated code [45], which is why R is currently derivable only indirectly. Two fields on a timesheet make it a local number rather than an industry estimate.

**Report cost per merged unit that survives 90 days** — labour, tokens, review hours and incident cost — rather than cost per head. The 90-day filter excludes work merged and then reverted, which would otherwise credit the team for output it did not deliver. Split cohorts on pre-AI performance: heavy AI users out-produce non-users by 4–10×, but most of that gap pre-dated AI [34], and a naive before-and-after comparison will attribute a selection effect to the tooling.

**Watch maintainability directly.** Duplication, refactoring rate and code turnover are the signals that reveal whether the quality-neutral assumption is holding. If they degrade, the team is not delivering the same work to the same standard, and the comparison in this paper no longer applies.

### 6.3 Controls worth having

- **Size work for review.** Keep changes under 400 lines, review below 500 lines per hour, and cap continuous review at 60–90 minutes [41]. Agent output arrives roughly 51% larger [23][37]; splitting it back down is a prerequisite for supervision capacity, not a stylistic preference.
- **Route agent traffic through one control point** — a gateway or CLI wrapper — so spend is attributable per person, per repository and per project. This preserves tool choice and is the precondition for capitalising the spend rather than expensing it.
- **Instrument rework and code turnover from week one**, reported alongside throughput. This is the only signal that detects under-specification before it becomes expensive, and it must be in place before any headcount change, not after.
- **Allow two quarters for the J-curve.** Budget the first six months as transition cost. Withdrawing funding during the dip is the specific failure mode DORA identifies [2][3].

---

## 7. In Closing

An equivalent engineering team in an AI-first world is around three people rather than six, and its composition differs more than its size: nobody authors, everybody supervises, and the team size is simply R.

That is a 45% headcount reduction and a 34% cost saving at constant output and constant quality, inside a band running from +2% to −56% on parameters that are not directly measured (§5). It is not the two-thirds reduction that agent-primary working is often assumed to deliver, and the gap between the two is supervision capacity. The same method applied to the other functions would give a larger organisational figure; this paper does not attempt it.

The parameter that decides it is measurable in-house within a quarter, and is moved more by how work is specified and sized than by which model is used.

---

## References

Numbered references resolve to inline citations throughout. Full extracts, findings relied upon, and per-source caveats are in **Appendix D — Annotated Source Register**.

**[1] Murphy-Hill, E., Butler, J. & Savelieva, A. (2026).** *Adoption and Impact of Command-Line AI Coding Agents: A Study of Microsoft's Early 2026 Rollout of Claude Code and GitHub Copilot CLI.* arXiv:2607.01418, 1 July 2026.
https://arxiv.org/abs/2607.01418 · HTML: https://arxiv.org/html/2607.01418

**[19][20][21] METR — the randomised controlled trial and its withdrawn follow-up.**
https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/ · https://metr.org/blog/2026-02-24-uplift-update/ · https://metr.org/blog/2026-05-11-ai-usage-survey/

**[22] DX (2026).** *AI and Engineering Velocity: A Longitudinal Analysis.*
https://getdx.com/report/ai-and-engineering-velocity-a-longitudinal-analysis/

**[33] Denisov-Blanch, Y. et al.** Stanford Software Engineering Productivity research.
https://softwareengineeringproductivity.stanford.edu

**[23][24][25][37] Faros AI (2026).** *The AI Engineering Report 2026: The Acceleration Whiplash*, and associated cost analyses.
https://www.faros.ai/research/ai-acceleration-whiplash · https://pages.faros.ai/hubfs/AI_Engineering_Report_2026_The_Acceleration_Whiplash_Faros.pdf · https://www.faros.ai/blog/ai-coding-tools-cost · https://www.faros.ai/blog/which-frontier-ai-model-is-worth-the-spend

**[26][34] GitClear (2026)** — two separate studies, frequently conflated.
https://www.gitclear.com/the_ai_code_quality_maintainability_gap · https://www.gitclear.com/industry_stats/ai_code_quality_signal_graphs

**[6] Anthropic (2026).** *Manage costs effectively* — Claude Code documentation.
https://code.claude.com/docs/en/costs

**[7][15e] Larridin (2026).** *Developer Productivity Benchmarks 2026*; *How to Measure Agentic Coding Tool Productivity.*
https://larridin.com/developer-productivity-hub/developer-productivity-benchmarks-2026 · https://larridin.com/blog/measure-agentic-coding-tool-productivity

**[8] Tunguz, T. (2026).** *When AI Costs More Than the Engineer.*
https://tomtunguz.com/ai-spend-breakeven-2029/

**[9] DX (2025).** *How are engineering leaders approaching 2026 AI tooling budgets?*
https://getdx.com/blog/how-are-engineering-leaders-approaching-2026-ai-tooling-budget/

**[4][5] JetBrains (2026).** *Our first moves to get AI spend under control*, and InfoQ coverage.
https://blog.jetbrains.com/ai/2026/08/our-first-moves-to-get-ai-spend-under-control/ · https://www.infoq.com/news/2026/08/jetbrains-ai-spend/

**[30] TechCrunch (2026), reporting Bloomberg.** *Uber caps employee AI spending after blowing through budget in four months*, 2 June 2026. Corroborated by Inc., Yahoo Finance/Stocktwits, The AI Insider.
https://techcrunch.com/2026/06/02/uber-caps-employee-ai-spending-after-blowing-through-budget-in-four-months/

**[10] Janakiram MSV (2026).** *Why Your Engineers' Favorite AI Tools Are Wrecking Your 2026 Budget.* Forbes, 26 May 2026.
https://www.forbes.com/sites/janakirammsv/2026/05/26/why-your-engineers-favorite-ai-tools-are-wrecking-your-2026-budget/

**[16] FinOps Foundation.** *How to build a generative AI cost and usage tracker.*
https://www.finops.org/wg/how-to-build-a-generative-ai-cost-and-usage-tracker/

**[17][18] Operator practice and practitioner survey.**
https://www.aibuilderclub.com/blog/how-to-become-an-ai-native-company · https://newsletter.pragmaticengineer.com/p/the-impact-of-ai-on-software-engineers-2026

**[2][3][32] DORA / Google Cloud.** *The ROI of AI-assisted Software Development* (2026) and *State of AI-assisted Software Development* (2025), with InfoQ coverage.
https://dora.dev/ai/roi/report/ · https://dora.dev/research/2025/dora-report/ · https://www.infoq.com/news/2026/05/dora-roi-ai-assisted-dev-report/ · Calculator: https://dora.dev/ai/roi/calculator

**[11] GitLab (2026).** *Agentic code reviews for $0.25 each*, 19 March 2026.
https://about.gitlab.com/blog/agentic-code-reviews-with-flat-rate-pricing

**[12] Vantage (2026).** *Your Most Expensive Developer Might Be Your Most Efficient in 2026*, 24 April 2026.
https://www.vantage.sh/blog/agentic-coding-efficiency

**[13] Insight Services APAC (2026).** *Token Price Is the Wrong Number: What a Merged Feature Actually Costs Across a Dozen Coding Agents*, 6 July 2026.
https://blog.insight-services-apac.dev/2026/07/06/cost-to-a-merged-feature

**[15d] Futureproofing.dev (2026).** *How to Build an AI-Native Engineering Team in 2026.*
https://www.futureproofing.dev/resources/ai-native-team/how-to-build-an-ai-native-engineering-team

**[41] SmartBear / Cisco Systems (2006).** *Code Review at Cisco Systems* — largest peer code review study conducted; 2,500 reviews, 3.2 million lines, 50 developers, 10 months.
https://static0.smartbear.co/support/media/resources/cc/book/code-review-cisco-case-study.pdf · https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/

**[42] Sonar (2026).** *State of Code Developer Survey*, 8 January 2026; 1,100+ developers globally.
https://www.sonarsource.com/company/press-releases/sonar-data-reveals-critical-verification-gap-in-ai-coding/

**[43] LinearB (2026).** *Software Engineering Benchmarks Report*; 8.1 million pull requests.

**[44] Digital Applied (2026).** Q1 2026 developer survey; 2,847 developers.

**[45] Harness (2026).** *State of Engineering Excellence Report*; 700 practitioners across US, UK, India, France, Germany.

**[46] Bosu, A. & Carver, J. (2013);** JetBrains *State of Developer Ecosystem*.

**[47] CircleCI (2026).** Platform telemetry, reported via https://blog.codacy.com/ai-breaking-code-review-how-engineering-teams-survive-pr-bottleneck

**[48] Anonymous (2026).** *Quo Vadis, Code Review? Exploring the Future of Code Review*. arXiv preprint; 100 respondents.
https://arxiv.org/pdf/2508.06879

**[27][28] Kim, H. (INSEAD) & Koning, R. (HBS).** *AI-Native Firms.* HBS Working Paper 26-090, June 2026.
https://www.hbs.edu/faculty/Pages/item.aspx?num=69077 · PDF: https://www.hbs.edu/ris/download.aspx?name=26-090.pdf · Summary: https://aiinstitute.hbs.edu/less-headcount-more-valuation-how-ai-native-firms-change-the-game/

**[29][36] Brynjolfsson, E., Chandar, B. & Chen, R.** *Canaries in the Coal Mine? Six Facts about the Recent Employment Effects of Artificial Intelligence.* Stanford Digital Economy Lab.
https://digitaleconomy.stanford.edu/publication/canaries-in-the-coal-mine-six-facts-about-the-recent-employment-effects-of-artificial-intelligence/

**[14][15] Cadence (2026)** *Software developer salary guide 2026*; **U.S. Bureau of Labor Statistics**, *Occupational Outlook Handbook*.
https://cadence.withremote.ai/blog/software-developer-salary-2026 · https://www.bls.gov/ooh/computer-and-information-technology/software-developers.htm

**[15a][15b][15c] Product manager compensation.**
https://www.kore1.com/product-manager-salary-guide/ · https://www.recruitingfromscratch.com/blog/product-manager-salary-in-2026-real-data-from-1-9-million-job-postings-5e5dd · https://gusto.com/resources/research/salary/product-manager

**[31][35] EisnerAmper (2026).** *Accounting for AI Data and Consumption Cost*; *Accounting for AI Development Costs Under US GAAP.*
https://www.eisneramper.com/insights/technical-accounting-advisory/accounting-for-ai-data-consumption-cost-0726/ · https://www.eisneramper.com/insights/technical-accounting-advisory/ai-development-cost-under-us-gaap-0726/

**[49] Bai et al. (2026).** *How Do AI Agents Spend Your Money? Analyzing and Predicting Token Consumption in Agentic Coding Tasks.* arXiv:2604.22750.
https://arxiv.org/abs/2604.22750

**[50] Token usage by task type (2026).** Consolidated agentic token-consumption benchmarks.
https://tokenade.net/en/stats/token-usage-by-task-type · https://iternal.ai/token-usage-guide

**[39] Paddo (2026).** *The 10x AI Developer is a Myth.* *The 10x AI Developer is a Myth.*
https://paddo.dev/blog/ai-developer-productivity-myth/

---

## Appendix A — The Model: Anchor, Derivation and Implementation

The arithmetic behind the body. Every figure reported in §2 and §3 is computed by the model in Appendix A and reconciles to its output.

### A.3 The anchor: span of control

Reported spans of control for engineering supervisors cluster between four and seven; five is used throughout. Call that span *S* — the units of human-authored output one supervisor can oversee. Supervising agent-authored output costs R times as much per unit, so:

```
capacity per supervisor  =  S / R
supervisors needed       =  target units × R / S
```

**With S = 5 and a target of 5 units — the old team's output — this reduces to an identity:**

```
supervisors needed  =  R
```

### A.4 The supervision ratio

#### Definition and interpretation

R is the parameter on which this entire comparison turns. It is defined here, before it is used.

**Definition.**

> **R = the effort required to supervise one unit of agent-authored work, divided by the effort required to supervise one unit of human-authored work.**

Formally, with *c_a* and *c_h* the supervision effort per unit of agent- and human-authored output respectively:

```
R = c_a / c_h
```

"Supervision" here means everything a human must do to take responsibility for work they did not write: reading it, checking correctness, checking it does what was intended, and accepting or rejecting it. It excludes writing the specification, which is counted separately (Appendix F.5).

Both terms are denominated in the unit of work defined in Appendix E.2, so R is dimensionless. It is a *ratio*, not a rate — which is what makes it usable, because the absolute cost of reviewing human code is never needed (Appendix A).

**How to interpret a value.**

| R | Meaning | Consequence for Configuration B |
|---|---|---|
| **< 1.0** | Agent output is *cheaper* to supervise than human output — plausible if agents produce more uniform, better-documented, better-tested changes | B beats every alternative decisively |
| **1.0** | Agent output costs the same to check as a colleague's | B delivers 168% of the pre-AI team |
| **1.5** | Half again as costly to check | **Throughput-parity threshold** — B matches Configuration A |
| **2.0** | Twice as costly | B delivers 84% of pre-AI output, still cheaper per unit |
| **2.65** | | **Unit-cost parity with Configuration A** |
| **2.93** | | **Unit-cost parity with the pre-AI team** |
| **3.29** | Roughly three and a third times as costly | **Derived central estimate (Appendix A).** B delivers 51% of pre-AI output at 12.5% more per unit |
| **> 4** | | B fails decisively on both measures |

**What R is not.** Four misreadings are worth heading off:

1. **R is not a measure of AI code quality.** Quality is one input to it. A model producing flawless code that a human still cannot take responsibility for — because there is no accountable author to ask — would still carry R > 1.
2. **R is not a productivity multiplier.** It does not describe how fast anyone works. It describes the cost of a specific activity, and it appears in the model as a divisor on supervision capacity, not as a factor on output.
3. **R is not fixed.** It should be expected to fall as models improve, though only its capability component does (Appendix A).
4. **R is not purely a property of the tooling.** It is substantially a property of *your practices*. Two teams using identical models will have different R if one gates changes with tests and keeps them small and the other does not.

**What moves R, and which levers you control.**

| Raises R | Lowers R |
|---|---|
| Large changes — review effort per line rises with size, and agent PRs run ~51% larger [23][37] | Constraining agents to small, reviewable changes (under 400 lines) [41] |
| Under-specified tasks, forcing intent verification as a second axis of checking | Specification-first workflow; acceptance criteria written before generation |
| No machine-checkable artefacts, throwing all verification onto human reading | Test-first gating, property checks, contract verification |
| Unfamiliar or complex codebase areas | Agents confined to well-understood, reversible work |
| Reviewer unfamiliarity with the intent behind the change | The reviewer having authored the specification |

**This is the practical significance of the parameter.** R is not merely something to measure and accept. Roughly half the entries above are process choices rather than model properties, which means a team can move R deliberately. Configuration B becomes viable at R ≤ 2.65 — and the gap between the derived 3.29 and that threshold is closer to a process-discipline gap than a model-capability gap.

**How to measure R in your own team.** It requires two fields that most teams do not currently record — only ~38% track review time on AI-generated code separately [45]:

```
R  =  (supervision hours per merged agent-authored unit surviving 90 days)
      ÷ (supervision hours per merged human-authored unit surviving 90 days)
```

The 90-day survival filter matters: it excludes work that was merged and then reverted or rewritten, which would otherwise credit the configuration for output it did not really deliver. Three months of history is enough to compute it.

**Where R currently sits.** Not directly measured anywhere in the published literature, but derivable at approximately **3.29**, in a range of 1.8 to 4.8, from the observed inflation in review effort. Four independent approaches corroborate between 2.3 and 5.3. The derivation is set out in full below.

#### Deriving R from review effort

Earlier versions of this analysis treated R as unmeasured. It is not directly measured, but it is **derivable** from published data on review effort, and the derivation converges tightly enough to be decision-relevant.

#### The hard ceiling on human review

Supervision capacity has a cognitive ceiling that is independent of who or what wrote the code. The SmartBear study of Cisco's peer review process — 2,500 reviews covering 3.2 million lines by 50 developers, still the largest of its kind — established boundaries that have held up across two decades [41]:

- Defect detection is highest at **200–400 lines per review**; beyond 400 LOC reviewers are overwhelmed and detection drops sharply.
- Inspection rates **below 300 LOC/hour** give best detection; **above 500 LOC/hour** a significant share of defects is missed.
- Detection **collapses after 60–90 minutes** of continuous review, at a fairly constant ~15 defects/hour.

**This ceiling does not rise because an agent wrote the code.** It is a property of human attention. An agent fleet can generate output at arbitrary volume; a supervisor still reads at 300–500 LOC/hour for 60–90 productive minutes at a stretch. That asymmetry is the entire structural problem with AI-first staffing, and no tooling improvement addresses it.

#### Deriving R from review-effort inflation

**How R is derived.** Review effort splits between human- and agent-authored work. Since the pre-AI team's effort was entirely on human-authored output, and the post-AI team's splits by the agent-authored share *f*, the observed inflation in effort *per unit of output* pins down the premium attaching to the agent share:

```
R = ( I − 1 + f ) / f     where I = (E_post / E_pre) / volume_uplift
```

Every term is published. With review hours rising from a pre-AI baseline of 5.0 per week — published estimates span 3 to 6.4 [46][48] — to a post-AI median of 11.4 [44], an agent-authored share of 42% [42], and output up 16.2% [23]:

```
effort ratio  = 11.4 / 5.0    = 2.28
per unit (I)  = 2.28 / 1.162  = 1.96    ← effort per unit rose 96%
R             = (1.96 − 1 + 0.42) / 0.42 = 3.29
```

Read plainly: **effort per unit of output rose 96%, but only 42% of that output is agent-authored — so the agent share must carry a premium of roughly 3.3× to account for it.**

Two assumptions bias the result in opposite directions and are of comparable size. Treating review effort as linear in volume **overstates** R, since effort per line rises with change size and agent PRs run ~51% larger. Treating review thoroughness as unchanged **understates** it, since 31% more PRs now merge with no review at all — so observed effort is what teams spend, not what adequate review would cost. Full derivation, the assumption register and the sensitivity grid are in **Appendix A.2**.

Solving across the plausible ranges of each input:

**Central estimate R ≈ 3.3, with a plausible range of roughly 1.8 to 4.8.** Only the most generous assumption available — the highest published pre-AI baseline of 6.4 hours combined with a 2027-projected AI share — brings R below the 2.65 unit-cost threshold, and even that does not approach the 1.50 throughput threshold.

#### Independent corroboration

Three further measures, using different methods and different denominators, land in the same region:

| Method | Implied R | Caveat |
|---|---|---|
| Faros: review time +441.5% against task throughput +33.7% [23][37] | **4.05** | Elapsed time, includes queueing |
| Senior review: 4.3 min per AI suggestion vs 1.2 min human [39] | **3.58** | Per suggestion, not per unit |
| LinearB: agentic PR pickup time, 8.1M PRs [43] | **5.30** | Queue time, not effort |

None is a clean measurement of R. All four independent approaches nonetheless cluster between 2.3 and 5.3, and none falls below 1.82.

Survey evidence agrees on direction: **38% of developers say reviewing AI-generated code takes more effort than reviewing a colleague's**, and 61% agree AI produces code that looks correct but is not reliable [42]. Harness found **81% of developers spend more time in review since adopting AI**, with 28% reporting increases of 30% or more [45].

#### The sharpest single datapoint

CircleCI's 2026 data reports **feature branch throughput up 59% year over year while main branch throughput for the median team fell** [47]. More work entering the pipeline; less work coming out of it. That is what a binding supervision constraint looks like in production telemetry, and it is the clearest available evidence that agent capacity has already outrun the ability to supervise it.

#### What this means for the comparison

| | Threshold | Estimated R | Verdict |
|---|---|---|---|
| Throughput parity | R ≤ 1.50 | ~3.3 | **Fails** by a wide margin |
| Unit-cost parity | R ≤ 2.65 | ~3.3 | **Fails**, though within range of the most favourable assumptions |

At R = 3.3, two supervisors carry 6.72 / 3.3 = **2.04 units** — about **45%** of Configuration A's output — at a cost per unit of roughly **$303,000** against Configuration A's $243,304.

**This moves the paper's central claim from reasoning to derivation.** The case against Configuration B no longer rests on a structural argument about accountability and trust, though that argument stands and explains *why* R is high. It rests on four independent published measures of review effort that converge on an R comfortably above both thresholds.

**The estimate remains an extrapolation.** It is derived from teams where AI authored 42% of code, not 100%; the mechanisms below suggest R rises rather than falls as that share approaches unity, since the human-authored work that currently anchors reviewer context disappears. Local measurement (§6.2) remains the right course — but a team should now expect to find R near 3, not near 1.

#### Why R exceeds 1, and what moves it

The derivation in the derivation below puts R at roughly 3.3 empirically. A structural argument explains *why* it sits above 1, and it matters because most of it does not dissolve as models improve.

- **No accountability transfer.** A developer who submits work stakes professional judgement on it, and that stake does real verification work — it is why a reviewer can accept "I've tested this thoroughly" as partial evidence rather than re-deriving it. An agent carries no stake, so none of the reviewer's burden is discharged by the submission itself.
- **No trust accumulation.** Supervising people gets cheaper over time: a lead learns who is reliable on concurrency and reads lightly there. Agent competence varies across task type, context length and silently across model versions, so no stable prior forms and vigilance must stay uniform.
- **Intent verification is a second axis.** A colleague who attended the design discussion carries shared context, so review checks *correctness*. An agent has only the prompt, so review checks correctness **and** whether the thing built is the thing meant.

**None of these is a capability deficit.** A better model reduces error rates; it does not acquire a stake in its output, build a reputation a reviewer can rely on, or attend the design meeting. They therefore set a **floor** under R that model improvement does not remove — and if that floor exceeds 1.50, an AI-first team of this size never matches the throughput of the team it replaces, however good the models become.

Three effects push the other way and deserve weight: machine-checkable gating moves verification from human reading to automated checks; agent output is stylistically uniform, which genuinely speeds reading; and cheap regeneration changes the economics of rejection in a way that has no human analogue. A team with strong specification discipline and test-first gating could plausibly hold R well below the derived figure.

*The model implementation is documented in Appendix A; Appendix B gives an agent specification for reproducing this analysis against current sources.*

---

### A.1 Model implementation

A runnable, strictly-typed Python implementation of the §2 model is provided as the companion file `ai_team_cost_model.py`. It accepts the parameters in Appendix F.3 as typed inputs, computes throughput, cost per unit, break-even AI budget and the sensitivity table below, and validates inputs at construction. Substituting local compensation figures and an observed productivity lift will regenerate the analysis for any team composition.

Product management is modelled as fractional FTE (`product_managers: Decimal`), bearing payroll and tooling cost but contributing no output units, per the proxy limitation in §1. This is enforced structurally: `output_units` derives from `engineering_headcount` while `payroll_annual` and `ai_spend_annual` derive from `total_fte`. Readers who wish to model a specification-capacity effect on throughput should not do so by adding PM FTE to the output term — the published evidence does not support a coefficient — but by reducing the engineering `productivity_lift` parameter to reflect degraded specification quality, and running the result against the sensitivity band below.

All monetary arithmetic uses `Decimal` rather than binary floating point, since the break-even solve divides one derived quantity by another and float error would accumulate across the sensitivity sweep.

The model exposes four named scenarios via the `SCENARIOS` mapping — `realistic` (the convergent DX/Stanford/Faros band, and the default), `optimistic` (Microsoft telemetry, an upper bound rather than a base case), `conservative` (DX panel and Faros telemetry) and `adverse` (METR RCT floor) — each documented inline with its provenance. A `breakeven_range()` function propagates a credible interval on the baseline lift through to the break-even budget, so headline figures need not be reported to a false precision. The module docstring records that all throughput ratios are upper bounds on Configuration B. Running the module reports all three plus the sensitivity sweep. Substituting a locally measured within-person lift for these published parameters is the intended use; per §6.2, that local measurement is what should decide the question.

---

*Prepared 13 August 2026. All sources retrieved on that date. Figures denominated in USD. Model capability, pricing and vendor terms in this domain change on a timescale of weeks; the quantitative conclusions should be re-derived against current sources before use in a funding decision.*

---

### A.2 Full derivation of the supervision ratio R

**The derivation, from first principles.**

Recall that R is the ratio of supervision effort per unit, with *c_h* for human-authored and *c_a* for agent-authored output:

```
R = c_a / c_h
```

Before AI adoption, all output is human-authored, so total review effort is volume times unit cost:

```
E_pre = V_pre × c_h
```

After adoption, a fraction *f* of output is agent-authored and (1 − *f*) remains human-authored. Total effort is the volume-weighted sum of the two unit costs:

```
E_post = V_post × [ (1 − f)·c_h + f·c_a ]
```

Factor out *c_h*, and substitute R for *c_a / c_h*:

```
E_post = V_post × c_h × [ (1 − f) + f·R ]
```

Dividing the two, ***c_h* cancels**:

```
E_post / E_pre  =  (V_post / V_pre) × [ (1 − f) + f·R ]
                =  volume_uplift × [ (1 − f) + f·R ]
```

**This cancellation is what makes the derivation possible.** We never need to know the absolute cost of reviewing a unit of human code — a figure nobody publishes and which would vary by language, domain and team. Only the *ratio* survives, and every remaining term is published.

Rearranged for R, writing *I* for the observed inflation in effort per unit:

```
I = (E_post / E_pre) / volume_uplift        ← effort per unit, post vs pre
R = ( I − 1 + f ) / f
```

**Worked example.** Pre-AI review 5.0 hours per week, post-AI 11.4, agent-authored share 42%, output up 16.2%:

```
E_post / E_pre = 11.4 / 5.0            = 2.280   (effort more than doubled)
I              = 2.280 / 1.162         = 1.962   (per unit of output)
R              = (1.962 − 1 + 0.42) / 0.42 = 3.29
```

Read plainly: **review effort per unit of output rose 96%, but only 42% of that output is agent-authored — so the agent-authored share must be carrying an effort premium of roughly 3.3× to account for it.**

**The assumptions, and which way each biases the result.**

| # | Assumption | Bias on R |
|---|---|---|
| A1 | Review effort scales linearly with volume. It does not — SmartBear [41] shows effort per line rising as changes grow, and AI-assisted PRs run ~51% larger [23][37]. | **Overstates**, if PR size is treated as separate from authorship. But larger PRs are a *consequence* of agent authoring, so this arguably belongs inside R rather than beside it. |
| A2 | Review thoroughness is unchanged before and after. It is not — 31% more PRs now merge with no review at all [23][37], and only 48% of developers always verify AI output [42]. | **Understates**, and materially. The observed *E_post* is what teams actually spend, not what adequate supervision would cost. |
| A3 | *E_pre* and *E_post* are comparable populations. They are not — different surveys, samples, instruments and years. | **Uncertain.** This is the largest source of error and the reason a range is reported rather than a point. |
| A4 | *f* is the agent-authored share of *output units*. The published figure is the share of *committed code* [42]. | **Uncertain**, likely small. |
| A5 | All output units are equivalent. | Same limitation as the merged-PR proxy throughout (§1). |

A1 and A2 push in opposite directions and are of comparable magnitude, which is part of why the derivation is reported as a range rather than a point estimate.

#### Two constraints, and only one of them moves

It is worth separating the two quantities in the model, because they behave differently and conflating them produces bad forecasts.

**Supervision capacity (*S*) is fixed.** It is a property of human cognition — 200–400 lines per review session, 300–500 lines per hour, detection collapsing after 60–90 minutes [41]. It does not improve because the tooling improved. A supervisor in 2030 will read at approximately the rate a supervisor read in 2006, because the constraint is attention, not technology. **Nothing in the AI trajectory raises *S*.**

**R is a property of the output being supervised, and it moves.** R is the effort premium attaching to agent-authored work relative to human-authored work, and it is a function of how good the agent output is. As models improve — fewer plausible-but-wrong constructions, fewer confabulated dependencies, fewer silently dropped edge cases — the effort required to verify a unit of their output falls. **R should be expected to decline over time.**

This is the correct reading of the current estimate. R ≈ 3.3 is a **measurement of the present**, not a constant of nature. The same derivation run in 2028 should be expected to return a lower number.

**But R does not decline to 1, and the floor matters more than the trajectory.** The mechanisms above divide into two kinds:

| Component | Behaviour over time | Why |
|---|---|---|
| **Capability-driven** — defect rates, plausible-but-wrong code, hallucinated APIs, missed edge cases, rework | **Declines** as models improve | These are quality deficits, and quality is what is improving |
| **Structural** — no accountability transfer, no trust accumulation, intent alignment as a second axis of checking | **Does not decline** | These follow from the relationship, not from capability. A better model does not acquire a stake in its output, build a reputation a reviewer can rely on, or attend the design discussion |

So `R(t) = R_structural + R_capability(t)`, where the second term trends toward zero and the first does not.

**This turns the staffing question into a timing question.** The thresholds are fixed by arithmetic: R ≤ 2.65 for unit-cost parity, R ≤ 1.50 for throughput parity. If R is 3.3 today and falling, Configuration B is not viable now but becomes viable at some future date — *provided R_structural sits below the relevant threshold*. If R_structural is above 1.50, throughput parity is never reachable no matter how good models become, and the ceiling on an AI-first team of this size is permanently below the conventional team it replaces.

**What R_structural is, nobody knows.** It is not derivable from the data assembled here, because published measurements capture the sum rather than the components. Identifying it would require comparing supervision effort on agent output against supervision effort on output of *equivalent measured quality* from a human — separating the trust and accountability effects from the defect-rate effects. No such study exists.

**The available evidence does not yet show R falling.** Three observations, all imperfect:

- Review effort per developer rose **31% year over year** to 11.4 hours weekly [44] — though this is volume-confounded and may reflect more agent output rather than costlier agent output.
- GitClear's quality signals **worsened continuously from 2023 to 2026** — duplication up 81%, refactoring down 70% [26] — across a period of substantial model improvement.
- Security analysis reports that newer models produce cleaner syntax without producing safer code, which would mean at least one component of R is not improving with capability.

None of this establishes that R is flat. All of it counsels against assuming a decline steep enough to change a staffing decision inside a planning horizon.

**The practical consequence for the decision.** Do not treat R ≈ 3.3 as permanent, and do not treat it as about to collapse. Re-derive it annually from your own review telemetry (§6.2). The signal to watch is not the model release notes but whether your own effort per supervised unit is falling — and Configuration B becomes worth revisiting when your measured R approaches 2.65, not when a vendor announces a better model.

Solving across the plausible ranges:

| *E_pre* | *E_post* | *f* | Output uplift | **R** |
|---|---|---|---|---|
| 6.4 | 11.4 | 0.42 | +16.2% | **2.27** |
| 5.0 | 11.4 | 0.42 | +16.2% | **3.29** |
| 4.0 | 11.4 | 0.42 | +16.2% | **4.46** |
| 3.0 | 11.4 | 0.42 | +16.2% | **6.41** |
| 5.0 | 15.0 (heavy users) | 0.42 | +16.2% | **4.77** |
| 6.4 | 11.4 | 0.65 | +16.2% | **1.82** |
| 5.0 | 11.4 | 0.42 | +8% | **3.65** |

*[Author's derivation from sourced inputs.]*

---

## Appendix B — Method, Evidential Standard and Provenance

This is a synthesis of published sources retrieved in August 2026, not original empirical research. Sources were selected against three criteria: (i) first-party operator data preferred over survey aggregation; (ii) large-sample or telemetry-based evidence preferred over self-report; (iii) 2026 publication date preferred, given the rate of change in both model capability and pricing.

**This is an extrapolation, and is structured as one.** Appendix F reports what has been measured — productivity and cost effects on conventional teams adopting AI. §4 projects from that evidence to the agent-primary case and is explicitly labelled as projection throughout. §4 states what would have to hold for the projection to favour the substitution, and what to measure to find out. The boundary between measurement and projection falls at the start of §4 and is not crossed silently anywhere.

**Evidential standard.** Every cited claim was retrieved and checked against primary material or, where the primary source is gated, against three or more independent secondary reports in agreement. Claims meeting neither standard are either omitted or explicitly flagged at the point of use as single-sourced or uncorroborated. Widely-circulated figures that could not be traced to a primary source are not relied upon in any conclusion.

**Conventions.** The provenance and citation conventions governing every assertion — the five classes each claim is marked with, and the scope of a citation within a passage — are set out at the head of the Sources section.

The cost model in §4 is a deterministic parametric model. All parameters are drawn from the sources catalogued there, and a runnable implementation is provided as a companion artefact (`ai_team_cost_model.py`, documented in Appendix A).

---

## Appendix C — Agent Specification for Reproduction

This appendix is an executable prompt, not a description of one. Copy everything inside the block below into Claude, replace the five bracketed inputs at the end, and it will run the same sequence that produced this report against current sources.

Two notes before use. **Enable web search** — the specification is built around retrieval and will fail without it. And expect it to take several exchanges: the two review gates are adversarial by design and are the point of the exercise, so approving the first draft defeats it.

The output will not match this report exactly. Sources move, and the specification deliberately anchors on whatever the evidence supports at run time rather than on any conclusion reached here.

---

````text
# ROLE

You are an evidence analyst producing a research synthesis on a contested
quantitative question — or, where the evidence to answer it does not exist, a
clearly-labelled extrapolation from whatever adjacent evidence does. Your
output must be defensible to someone who disagrees with your conclusion and
checks your sources.

If the literature does not contain the comparison being asked for, say so as
your primary finding, then extrapolate with the boundary between measurement
and projection marked explicitly in the document. Do not present projection in
the register of measurement.

You are not writing an essay. You are assembling an auditable evidence base,
computing a result from it, and then attacking your own work twice before
presenting it.

# GOVERNING PRINCIPLES

P1  EVIDENCE BEFORE ASSERTION. Never write a claim before retrieving its
    source. Do not draft from memory and source afterwards.
P2  PRIMARY BEFORE SECONDARY. Source each claim to the primary publication, or
    to 3+ independent secondary reports in agreement. One secondary report is
    never sufficient.
P3  RELAYED FIGURES ARE UNVERIFIED FIGURES. Any number arriving via a summary,
    an earlier conversation, another agent, or your own recall is unsourced
    until you retrieve it yourself. This is where errors concentrate.
P4  CONVERGENCE OVER STRENGTH. When large studies disagree, anchor your base
    case on the band where independent datasets converge — not on the most
    rigorous or most favourable single study. Outliers become bounds.
P5  DECLARE THE DIRECTION OF BIAS. If your measurement unit or method
    systematically favours one conclusion, say so at every point of use.
P6  ABSENCE IS A FINDING. If the literature does not contain the comparison
    asked for, that is your primary result — stated in the introduction, the
    abstract and the conclusion. Never substitute adjacent evidence silently.
P7  ARITHMETIC LIVES IN CODE. Every computed figure comes from an executable
    model you write. Never calculate inline in prose.
P8  DECLARE CONFLICTS AT POINT OF USE. Vendor and self-interested sources are
    usable, but label them where their finding is cited — especially where the
    publisher sells the thing being measured.
P9  NO ORPHAN CLAIMS. A claim with neither a citation nor a declared
    derivation is a defect, not a style choice.

# PROVENANCE CLASSES

Every assertion you write carries exactly one class. Mark them in the text.

  sourced          [n] resolves to a reference; the source says this.
  single-sourced   [n] + explicit note. One source only. Indicative.
  uncorroborated   In circulation, untraceable to a primary. Record it,
                   never rely on it.
  derivation       *[Author's derivation]* Arithmetic from sourced inputs.
  estimate         *[Author's estimate]* Judgement, no published basis.

No conclusion may rest on an uncorroborated or estimate claim.

# SEQUENCE

Run these in order. Do not skip ahead.

PHASE 1 — SCOPE
  State the question, the options being compared, the output unit, and what is
  out of scope. Name any known bias in the output unit now, not later.

PHASE 2 — RETRIEVE
  Search per named entity, never in combination — combined queries return
  shallow results for everything. Retrieve the primary source for every figure
  that will carry weight. Record publication and retrieval dates.
  Search until every part of your eventual answer is grounded in something you
  retrieved. Typically 8-20 searches. If you planned to look something up and
  haven't, do it now.

PHASE 3 — EXTRACT
  For each source record: population, design, central estimate, date, declared
  conflicts, and a short verbatim extract where exact wording is material.

PHASE 4 — RECONCILE
  Tabulate every estimate side by side: population, design, central estimate.
  Do NOT average them. Do NOT pick the best one.
  Explain the spread mechanically — sample composition, unit of analysis,
  tool or product generation, self-report vs telemetry.
  Identify the outlier and the convergent band. Per P4 the band is your base
  case; the outlier becomes a bound.
  Check whether any source disclaims the extrapolation you are about to make.
  If one does, that disclaimer is a headline finding, not a footnote.

PHASE 5 — PARAMETERISE
  Define each model parameter and name the claim justifying it. Any parameter
  with no supporting claim is an estimate and must NOT enter the model — it
  may appear only in supporting tables, individually labelled.

PHASE 6 — COMPUTE
  Write a runnable model (Python; strict typing; Decimal for money).
  Implement named scenarios as parameter sets, each with its evidential anchor
  in a comment. Include a function that propagates published confidence or
  credible intervals through to your headline outputs.
  Run it. Every figure you later report must come from its output.

PHASE 7 — DRAFT
  Structure:
    1  Standfirst: what this is, date, source cut-off
    2  Abstract — OPENING with the absence statement if P6 applies
    3  Introduction: motivation, questions, THE ABSENCE STATEMENT IN FULL,
       scope, limitations, declared direction of bias
    4  Method: evidential standard, provenance convention, citation scope
    5  Findings: the measured quantity — principal study, reconciliation of
       conflicting estimates, moderators
    6  Findings: cost or impact structure — levels, then structural shifts
    7  Analysis: options, parameters, scenarios, sensitivity, uncertainty
    8  Recommendation: conditions, staged course, controls
    9  Conclusion — RESTATING the absence as the governing conclusion
   10  Sources: numbered; citation, URL, extract, findings, caveats together
   11  Appendix: the model

PHASE 8 — GATE 1: SOURCE VALIDATION
  Adopt an adversarial stance. Your job is to find errors, not confirm work.
  Re-retrieve every cited source independently. Do not trust your Phase 3
  notes.
  For each claim verify: figure, population, date, design.
  Hunt specifically for: misattributed derivations (did you claim someone
  else's published calculation as your own?); compressed findings that dropped
  a material qualifier; superseded editions; conflated studies; and every
  figure that reached you via relay (P3).
  Produce a defect register with severities. Apply corrections.

PHASE 9 — GATE 2: TRACEABILITY AUDIT
  Different question: does every claim have a source AT ALL, and does the
  document contradict itself?
  Check every reference cited resolves, and every reference listed is cited.
  Check every sentence containing a number carries a citation, a provenance
  marking, or sits in a passage governed by a preceding citation.
  Read the WHOLE document in one pass for internal contradiction.
  EXPECT TO FIND CONTRADICTIONS INTRODUCED BY YOUR PHASE 8 FIXES. Correcting
  section by section does not produce a consistent document. Check that
  parameter tables still match result tables, that cross-references still
  point to the right sections, and that section counts match their lists.
  Verify every reported figure against model output.
  Apply corrections. Re-run both checks until clean.

PHASE 10 — REPORT
  Present the report, the model, and the defect register from both gates.
  State plainly what remains uncorroborated or estimated.

# STOP CONDITIONS

Done only when ALL hold:
  1. Every quantitative assertion has a resolvable citation or a provenance
     class marking.
  2. No unresolved and no orphaned references.
  3. Every reported figure reconciles to model output.
  4. No internal contradiction between any two sections.
  5. Where the literature lacks the requested comparison, that absence is
     stated in introduction, abstract and conclusion.
  6. No conclusion rests on an uncorroborated or estimate claim.

Any failure returns you to the phase that owns it. Repeat Phases 7-9 until
clean or five cycles. At five cycles, stop, report which conditions remain
unmet, and recommend PUBLISH / EXTEND / WITHDRAW. Do not continue without
approval.

# PROHIBITIONS

- Never carry a figure from an earlier conversation, summary, other agent, or
  your own recall into the report without retrieving it yourself.
- Never claim another analyst's published derivation as your own work.
- Never style an estimate to look like sourced data.
- Never mix estimates with sourced inputs inside one computation.
- Never report a figure to a precision the evidence does not carry; propagate
  the interval instead.
- Never resolve disagreement between studies by picking the most rigorous one.
- Never narrate the document's drafting history in the report body.
- Never soften an absence-of-evidence finding into a limitation.
- Never present a throughput or benefit figure as an estimate when your method
  makes it an upper bound.

# TASK

Question:       [THE QUANTITATIVE QUESTION YOU NEED ANSWERED]
Options:        [THE CONFIGURATIONS OR CHOICES TO COMPARE]
Output unit:    [UNIT OF DELIVERED VALUE, AND ANY BIAS YOU KNOW OF]
Locale:         [CURRENCY, COMPENSATION BASIS, JURISDICTION]
Cut-off:        [HOW RECENT SOURCES MUST BE]

Begin at Phase 1. Show your work at each phase. Both gates are mandatory —
do not skip them because the draft looks sound.
````

---

### D.1 Worked invocation

The task block that produced this report:

````text
Question:       If AI performs the majority of code production under human
                oversight, can engineering headcount be reduced, and by how
                much, at equivalent delivery throughput?
Options:        A: 1 engineering lead + 3 developers + 1 product manager
                B: 1 engineering lead + 1 developer + 0.5 product manager
                   + a discretionary AI budget
Output unit:    Merged pull requests. Known bias: AI adoption inflates PR
                counts, and the inflation scales with intensity, so this unit
                flatters the higher-intensity option.
Locale:         USD, US fully-loaded compensation, US GAAP
Cut-off:        2026 sources preferred; this field moves in weeks
````

### D.2 What to expect

The specification is deliberately slow. Phases 2–4 dominate, and Phase 4 is
where most of the value sits — the reconciliation step is what prevents the
common failure of anchoring on whichever study is most quotable.

Both gates reliably find defects. In producing this report, Gate 1 found
fourteen and Gate 2 found twenty-one, four of the latter created by Gate 1's
own corrections. If a gate returns nothing, it was not run adversarially.

The specification does not guarantee a particular answer, and should not. If
current evidence supports a different conclusion than the one reached here,
a correct run will say so.

---

## Appendix D — Annotated Source Register

Each entry gives the citation, a short verbatim extract where exact wording is material, the findings relied upon in this paper, and any caveat affecting how the source should be weighted. Extracts are kept short and the substance paraphrased; the analysis in the body is this author's, not the sources'.

**[1] Murphy-Hill, E., Butler, J. & Savelieva, A. (2026).** *Adoption and Impact of Command-Line AI Coding Agents: A Study of Microsoft's Early 2026 Rollout of Claude Code and GitHub Copilot CLI.* arXiv:2607.01418, 1 July 2026.
https://arxiv.org/abs/2607.01418 · HTML: https://arxiv.org/html/2607.01418

*Extract:* "adopters merged roughly 24% more pull requests than they would have otherwise"

- Synthetic-control estimate: +24.0% lift in PRs per engineer per day, 95% CI [+14.5%, +33.7%], posterior tail-area p < 0.001. Tens of thousands of engineers over a sixteen-week window.
- Within-person dose-response: +15.0% at three tool-use days per week, rising to +50.1% at five or more.
- Persistence: February +29.4% [+17.7%, +44.4%]; March–April +20.0% [+7.4%, +35.9%]. Intervals overlap; no detectable decay.
- Tool comparison among single-tool users: Copilot CLI +24.9% [+23.0%, +26.8%] versus Claude Code +11.4% [+9.4%, +13.6%].
- Adoption is socially transmitted: engineers whose skip-level peers used the tool had +216% higher odds of trying it; a manager using it raised odds by +82%.
- Accompanying survey of 609 attendees at an internal agentic engineering event: tools described as suited to experienced developers who can decompose work into reviewable chunks, with explicit scepticism about junior effectiveness.
- Placebo test at 2025-10-06 returned −1.1% [−10.6%, +8.6%].
- Authors state the open question is quality, not throughput, and that the field lacks agreed measures for it.

*Caveat — declared conflict.* The authors disclose Microsoft employment, and that Microsoft sells AI tools and owns GitHub, maker of the better-performing tool in their comparison. The design is the most rigorous in this set; the result is nonetheless the outlier among large studies, and this paper treats it as an upper bound rather than a base case.

---

**[19][20][21] METR — the randomised controlled trial and its withdrawn follow-up.**
https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/ · https://metr.org/blog/2026-02-24-uplift-update/ · https://metr.org/blog/2026-05-11-ai-usage-survey/

*Extract [19]:* "when developers use AI tools, they take 19% longer than without"

- [19] Randomised controlled trial; 16 experienced open-source developers, 246 tasks, repositories where they averaged around five years of prior experience. Tooling was Cursor Pro with Claude 3.5/3.7 Sonnet. Data collected February–June 2025.
- The three-way divergence: developers forecast a 24% speedup beforehand, self-assessed a 20% speedup afterwards, and were measured 19% slower.
- METR frames the result as a snapshot of early-2025 capabilities and states on the original page that these historical results no longer reflect current impact.
- [20] The February 2026 update reports that the follow-up experiment, begun August 2025 with a larger and more diverse pool (57 developers, 143 repositories, 800+ tasks), produced an unreliable signal — the stated cause being that developers declined to participate rather than work without AI, which biases the speedup estimate downward.
- METR's stated position is that developers are likely more sped up in early 2026, but that their data constitutes only very weak evidence for the size of that increase.
- [21] METR's May 2026 survey work attempts to distinguish "value" from "speed" uplift and cautions that survey instruments — including those used by AI vendors — may lead respondents to overestimate productivity through task-selection framing.

*Note on miscitation.* Specific 2026 point estimates (−18% returning, −4% newly recruited) are sometimes attributed to METR. These correspond to compromised raw data that METR itself declines to present as findings. This paper cites −19% as an early-2025 result and attributes no current point estimate to METR.

---

**[22] DX (2026).** *AI and Engineering Velocity: A Longitudinal Analysis.*
https://getdx.com/report/ai-and-engineering-velocity-a-longitudinal-analysis/

- Panel of 400+ companies, November 2024 to February 2026.
- AI usage rose 65% across the period while median PR throughput rose 7.76%; mean 13.1%; approximately 44% at the 90th percentile. Most organisations land in the 5–15% range.
- Figure filtered for gamification by excluding teams that set PR-throughput targets for individual engineers.
- Structural explanation offered: developers report saving ~3.9 hours per week, but coding is only around 14% of a developer's day, so acceleration has a bounded ceiling. Saved time is consumed by review burden, unscaled downstream processes, and the learning curve.
- Organisation-level medians include non-adopters and therefore dilute relative to within-person designs.

---

**[33] Denisov-Blanch, Y. et al.** Stanford Software Engineering Productivity research.
https://softwareengineeringproductivity.stanford.edu

- ~100,000 software engineers across 600+ companies, tens of millions of commits, analysed on private repositories using functionality-based measurement rather than commit or line counts.
- Task matrix: low-complexity greenfield 30–40%; high-complexity greenfield 10–15%; low-complexity brownfield 15–20%; high-complexity brownfield 0–10%, and capable of being negative.
- **Headline result:** gross delivered output rises roughly 30–40%, but after netting off rework the average net gain across industries is **15–20%**.
- Gains are further moderated by programming-language popularity, being weakest in less common languages.

*Note on citation practice.* This study is commonly cited second-hand and compressed to "35–40% greenfield, ≤10% complex legacy," which drops the net-of-rework figure. The net 15–20% is its most decision-relevant number and anchors the base case in §3.

---

**[23][24][25][37] Faros AI (2026).** *The AI Engineering Report 2026: The Acceleration Whiplash*, and associated cost analyses.
https://www.faros.ai/research/ai-acceleration-whiplash · https://pages.faros.ai/hubfs/AI_Engineering_Report_2026_The_Acceleration_Whiplash_Faros.pdf · https://www.faros.ai/blog/ai-coding-tools-cost · https://www.faros.ai/blog/which-frontier-ai-model-is-worth-the-spend

- Telemetry across approximately 22,000 developers and 4,000+ teams, comparing low and high AI-adoption periods within the same organisations.
- Throughput: tasks per developer +33.7%, epics per developer +66.2%, PRs merged per developer +16.2%.
- Quality and process: median time in review +441.5%, PR size +51%, bugs per developer +54% (from 9% in the 2025 edition), incidents per PR +242.7%, 31% more PRs merged with no review, code churn +861%. Lead time commit-to-production +480.4% and time in progress +225.2% among organisations instrumenting those metrics.
- Review metrics are multiple and easily conflated: median time in review +441.5%; median time to first review +156.6%; average time in code review +199.6%. The 2025 edition (10,000 developers) reported +91%, which is the figure GitLab cites.
- No evidence found that organisations with strong pre-AI engineering practices are insulated from quality degradation.
- Human review characterised as the largest hidden cost, falling disproportionately on senior engineers.
- [24][25] Route benchmarking against 30 of Faros's own merged pull requests: $1.14 per task for the cheapest competitive route against $3.66 projected ($4.60 billed) for the most expensive, at statistically indistinguishable quality; at 30,000 agent tasks per month, worth roughly $900,000 annually. **Single-sourced; not independently corroborated.**

***Critical scope statement.*** The primary PDF states that agentic authoring accounts for under 1% of PRs in this dataset, characterises its findings as describing AI used as a primary authoring tool *with humans still in the loop*, and states that removing that human entirely subjects every metric to pressure roughly an order of magnitude greater — adding that the industry is not ready for that transition. This is the single most important limitation on this paper's extrapolation and is set out in §1.

*Caveat.* Vendor source selling engineering-intelligence tooling. The methodology — benchmarking routes against your own merged work with real cost accounting — is nonetheless the most directly reusable in the literature. A figure of $150,000–$300,000 per senior departure is associated with this analysis but could not be independently corroborated and is not relied upon.

---

**[26][34] GitClear (2026)** — two separate studies, frequently conflated.
https://www.gitclear.com/the_ai_code_quality_maintainability_gap · https://www.gitclear.com/industry_stats/ai_code_quality_signal_graphs

*[26] The Maintainability Gap* (623 million analysed changes, 2023–2026, with GitKraken; AI-assisted commits approximately one quarter of all commits):
- Block duplication (five or more consecutive repeated meaningful lines) up 81%; within-commit copy/paste up 41%; error-masking constructs up 47%; two-week code churn up 15%.
- Refactoring line moves down 70%; cross-file function calls down 35%; long-term legacy maintenance down 74%.
- Refactored ("moved") code as a share of changed lines: roughly a quarter in 2020–21, 9.5% in 2024, 3.8% in the 2026 edition.
- Pre-AI two-week churn baseline of 3.3% (2021).

*[34] AI Coding Tools Attract Top Performers — But Do They Create Them?* (January 2026) — the source of the selection finding:
- Heavy AI users out-produce non-users by a factor of 4–10, but most of that gap pre-dated AI adoption. Measured against their own prior output the gain is substantially more modest.
- A specific within-person figure of roughly 25% circulates in secondary commentary but **could not be confirmed against the primary** and is not relied upon. The direction is confirmed; the magnitude is not.

*Note on commonly-conflated figures.* A figure of "refactored code falling from 21% of changed lines in 2022" appears in circulation but does not match GitClear's published series. A figure of "73.0 duplicated blocks per million changed lines" could not be located in any GitClear material and is not used here.

*Caveat.* GitClear is a commercial code-analysis firm; the data is correlational and the methodology proprietary. What gives the series weight is directional consistency across three consecutive annual editions.

---

### Cost structure and governance

---

**[6] Anthropic (2026).** *Manage costs effectively* — Claude Code documentation.
https://code.claude.com/docs/en/costs

*Extract:* "average cost is around $13 per developer per active day"

- $150–250 per developer per month across enterprise deployments; 90% of users below $30 per active day.
- Per-developer cost varies widely with model selection, codebase size, and usage patterns such as running multiple instances or automation.
- Anthropic's own guidance is to pilot with a small group and establish a baseline before wider rollout.

---

**[7][15e] Larridin (2026).** *Developer Productivity Benchmarks 2026*; *How to Measure Agentic Coding Tool Productivity.*
https://larridin.com/developer-productivity-hub/developer-productivity-benchmarks-2026 · https://larridin.com/blog/measure-agentic-coding-tool-productivity

*Extract:* "$200-$2,000+ per engineer per month"

- Inline completion tools cost $20–60 per engineer per month; agentic tools introduce usage-based token costs at the figure quoted above. Blended total $200–600 per engineer per month.
- ROI calculations using only seat licence as the denominator produce misleadingly high results. Healthy ROI stated as 2.5–3.5× average, 4–6× top quartile, only when the denominator includes actual token cost.
- Code turnover thresholds: above 18% at 30 days warrants an audit; above 25% is critical.
- A 2026 study of eight frontier models on SWE-bench Verified found agentic coding tasks consumed roughly 1,000× the tokens of code reasoning and chat in that setup, with runs on the same task varying by as much as 30×, and higher token use not consistently improving accuracy.

*Caveat.* Vendor-adjacent; treat as directional.

---

**[8] Tunguz, T. (2026).** *When AI Costs More Than the Engineer.*
https://tomtunguz.com/ai-spend-breakeven-2029/

*Extract:* "The median spends $137."

- Top 1% of companies spend approximately $89,000 per engineer per year on AI, around 40% of a fully-loaded $224,000 senior engineer.
- Anthropic itself estimated at roughly 2.3× payroll in compute spend.
- The stated gap: 2.3× at the frontier, 0.4× at the top of the software market, near zero at the median.

---

**[9] DX (2025).** *How are engineering leaders approaching 2026 AI tooling budgets?*
https://getdx.com/blog/how-are-engineering-leaders-approaching-2026-ai-tooling-budget/

*Extract:* "1-3% of their total engineering budgets for AI tools"

- Survey of 50 engineering budget holders; nearly half reported the allocation quoted above.
- Companion poll of 275 engineering leaders on 2025 spend: 38.4% at $101–500 per developer per year; 10.5% at $501–1,000; 10.5% above $1,000.
- $1,000 per developer per year emerged as a common 2026 target; stated planning range $500 to $3,000+ where multiple tools cover multiple use cases.
- Multi-vendor procurement is near-universal because no single tool covers chat, autocomplete, agentic IDE and background agents.

---

**[4][5] JetBrains (2026).** *Our first moves to get AI spend under control*, and InfoQ coverage.
https://blog.jetbrains.com/ai/2026/08/our-first-moves-to-get-ai-spend-under-control/ · https://www.infoq.com/news/2026/08/jetbrains-ai-spend/

- Development-related AI spending rose roughly tenfold in six months. Most developers used three to five AI tools per month; token consumption rose sharply from January 2026 alongside more capable frontier models.
- Initial response was four days of manual spreadsheet collation, subsequently automated via provider APIs and internal dashboards.
- Visibility alone proved insufficient: dashboards showed spend but offered no intervention point, since requests went directly from tools to providers.
- Remedy was Central CLI, a wrapper routing requests through the internal AI platform, creating a shared control point permitting per-developer, per-team and per-group limits.
- JetBrains deliberately rejected standardising on one or two tools, on the grounds that relative tool capability changes too fast to predict.
- Over 1,000 developers adopted Central CLI within weeks; terminal agents and personal subscriptions remain outside the managed path.

---

**[30] TechCrunch (2026), reporting Bloomberg.** *Uber caps employee AI spending after blowing through budget in four months*, 2 June 2026. Corroborated by Inc., Yahoo Finance/Stocktwits, The AI Insider.
https://techcrunch.com/2026/06/02/uber-caps-employee-ai-spending-after-blowing-through-budget-in-four-months/

- Cap of $1,500 per month per employee per agentic coding tool, applied separately to each tool (Claude Code, Cursor), so exhausting one does not consume the other's budget.
- Usage tracked on an internal per-employee dashboard. **The cap can be exceeded with permission** — a soft ceiling with an escalation path, not a hard stop.
- CTO Praveen Neppalli Naga disclosed in April 2026 (via The Information) that Uber had exhausted its entire planned 2026 AI coding budget within the first four months.
- Prior to the caps, individual engineers were generating $500–$2,000 per month in token consumption.
- Context: Uber had encouraged staff to use AI as much as possible and ranked internal usage competitively on leaderboards, with no ceiling attached.
- CEO Dara Khosrowshahi reported as saying around 10% of Uber's code was AI-created. COO Andrew Macdonald reported as saying it remains difficult to draw a direct line from the spend to shipped consumer features.
- **The $36,000/year and 11%-of-package calculation is Simon Willison's**, published and widely reported: two tools at the cap against a typical Uber software engineer package of roughly $330,000.

*Note on commonly-miscited figures.* Three statistics are widely attributed to Uber that could not be traced to any source: an adoption ramp of 32% to 84% between February and March 2026; approximately 70% of committed code originating from agentic tools; and around 11% of live backend updates being agent-written with no human in the loop. The 70% figure is contradicted by the CEO's reported ~10%. None are used in this paper.

---

**[10] Janakiram MSV (2026).** *Why Your Engineers' Favorite AI Tools Are Wrecking Your 2026 Budget.* Forbes, 26 May 2026.
https://www.forbes.com/sites/janakirammsv/2026/05/26/why-your-engineers-favorite-ai-tools-are-wrecking-your-2026-budget/

*Extract:* "only 15% of companies forecast AI costs within 10% of actual"

- Mavvrik/Benchmarkit 2025 study of 372 enterprises; a majority miss by 11–25%, nearly one in four by more than 50%.
- The article notes Mavvrik sells AI cost-governance tooling and characterises the survey as relevant evidence rather than neutral academic data.
- Microsoft wound down most internal Claude Code licences in its Experiences and Devices division roughly six months after a December pilot launch, with access ending 30 June — coinciding with fiscal year end. Stated rationale was toolchain unification; reporting also points to cost control.
- Mechanism identified: flat licences kept token spend invisible because price did not move with usage.

---

**[16] FinOps Foundation.** *How to build a generative AI cost and usage tracker.*
https://www.finops.org/wg/how-to-build-a-generative-ai-cost-and-usage-tracker/

- Describes generative AI as a growing part of the FinOps remit and recommends centralised approaches to tracking AI usage and costs.

*Caveat.* The widely-circulated "73% of enterprises exceed AI cost projections" figure could not be confirmed against this source and is not relied upon here.

---

**[17][18] Operator practice and practitioner survey.**
https://www.aibuilderclub.com/blog/how-to-become-an-ai-native-company · https://newsletter.pragmaticengineer.com/p/the-impact-of-ai-on-software-engineers-2026

- Pragmatic Engineer survey: around 15% of respondents raised AI tool cost as a concern; employers fund more expensive packages than individuals buy personally; "max" plans at roughly $100–200 per engineer per month are common employer purchases.
- UK and EU respondents report materially more budget resistance than US-based ones, including pushback on $30–50 per engineer per month.
- Personal subscriptions and terminal agents outside the managed path are a recurring shadow-spend gap.

---

### Delivery process and unit economics

---

**[2][3][32] DORA / Google Cloud.** *The ROI of AI-assisted Software Development* (2026) and *State of AI-assisted Software Development* (2025), with InfoQ coverage.
https://dora.dev/ai/roi/report/ · https://dora.dev/research/2025/dora-report/ · https://www.infoq.com/news/2026/05/dora-roi-ai-assisted-dev-report/ · Calculator: https://dora.dev/ai/roi/calculator

*Extract:* "the tuition cost of transformation"

- The J-curve: a temporary productivity dip precedes long-term gain, caused by the learning curve, the verification tax on reviewing AI-generated code, and the need to adapt downstream testing and change-approval processes to higher code volume.
- Illustrative model for a 500-person engineering organisation at $176,000 fully-loaded per head: first-year return ~$11.6m against ~$8.4m investment; 39% ROI; ~8-month payback. The authors describe these as high-uncertainty estimates intended to start a conversation.
- Instability tax: the sample calculator shows a negative downtime impact of $344,000 on an assumed change failure rate rising from 5% to 6% post-adoption.
- Inference costs fell by a factor of 280 between November 2022 and October 2024 per the Stanford AI Index, shifting the true burden of adoption to governance.
- [32] The 2025 report found AI adoption associated with increasing delivery instability even as its relationship with throughput turned positive.
- The report discourages headcount reduction as a strategy, arguing retention and training preserve institutional knowledge, and reframes ROI as unlocking human capacity rather than replacing developers.
- The current model measures change lead time, deployment frequency, failed deployment recovery time, change fail rate, and deployment rework rate — the last being most sensitive to specification quality.
- Recommends running conservative, realistic and optimistic scenarios.

---

**[11] GitLab (2026).** *Agentic code reviews for $0.25 each*, 19 March 2026.
https://about.gitlab.com/blog/agentic-code-reviews-with-flat-rate-pricing

*Extract:* "Code review times have jumped 91% on teams using AI coding tools."

- Median engineer at a large company waits 13 hours for a PR to merge; 44% of engineering teams cite slow code review as their single biggest delivery blocker.
- Token-based agentic review tools stated to cost $15–25 per review depending on change size; GitLab's own Code Review Flow is priced at a flat $0.25 per review.

*Caveat.* Vendor source announcing its own product; the comparison figures are its own. The +91% figure traces to Faros's 2025 report, not the 2026 edition.

---

**[12] Vantage (2026).** *Your Most Expensive Developer Might Be Your Most Efficient in 2026*, 24 April 2026.
https://www.vantage.sh/blog/agentic-coding-efficiency

- Recommends defining a unit — PRs merged or tickets closed — and dividing attributed AI spend by that count.
- Token consumption between long multi-turn agentic sessions and autocomplete-style use differs by orders of magnitude before model choice is considered; characterised as a pattern to understand rather than a problem to fix.
- A developer routing to a more capable model is not necessarily wasteful if fewer turns and retry loops lower cost per outcome.

---

**[13] Insight Services APAC (2026).** *Token Price Is the Wrong Number: What a Merged Feature Actually Costs Across a Dozen Coding Agents*, 6 July 2026.
https://blog.insight-services-apac.dev/2026/07/06/cost-to-a-merged-feature

- One real feature given to a dozen models across three coding CLIs, each held to the same automated production review gate.
- The same feature cost between roughly $7 and $70 to merge.
- Fastest arm reached a mergeable PR in 26 minutes and one cycle at around $30, using a frontier model — expensive per token but converging in a single cycle. Mid-tier models 36–107 minutes; open-weight arms 69–176 minutes.
- Conclusion: no single best combination, only a cost axis and a time axis.

*Caveat.* Practitioner blog; single-feature sample, so directional rather than generalisable.

---

**[15d] Futureproofing.dev (2026).** *How to Build an AI-Native Engineering Team in 2026.*
https://www.futureproofing.dev/resources/ai-native-team/how-to-build-an-ai-native-engineering-team

*Extract (attributing Larridin CTO Ameya Kanitkar):* "the bottleneck is no longer writing code"

- The stated inversion: agents write first-draft code, humans build the system that verifies it. Teams are AI-native when AI is the default mode of development rather than a layer on an existing process.
- Explicit guidance to spend more time on planning and specification and less on coding, with tests written first in end-to-end, integration, then unit order.
- A "Delegate, Review, Own" framing: mechanical, well-specified, reversible tasks are delegated; correctness and intent alignment are reviewed; architecture, strategy and ambiguous requirements remain human-owned.

*Caveat.* Practitioner and vendor commentary rather than controlled study. Cited as convergent expert opinion on where the constraint sits, not as measurement of its magnitude.

---

### Supervision capacity and review effort

---

**[41] SmartBear / Cisco Systems (2006).** *Code Review at Cisco Systems* — largest peer code review study conducted; 2,500 reviews, 3.2 million lines, 50 developers, 10 months.
https://static0.smartbear.co/support/media/resources/cc/book/code-review-cisco-case-study.pdf · https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/

*Extract:* "LOC under review should be under 200, not to exceed 400."

- Defect detection highest at 200–400 LOC per review; beyond 400 reviewers are overwhelmed and detection drops.
- Inspection rates under 300 LOC/hour give best detection; under 500 still acceptable; above 450–500 defect density is below average in 87% of cases.
- Detection collapses after 60–90 minutes of continuous review. Defect rate roughly constant at ~15/hour, and under 20/hour in 94% of reviews regardless of review size.
- Review of 200–400 LOC over 60–90 minutes yields 70–90% defect discovery.
- Author annotation of changes materially reduces defects found.

*Relevance.* Establishes a supervision ceiling grounded in human attention rather than in tooling. The ceiling does not rise because an agent wrote the code, which is the structural asymmetry underlying Appendix F.4 and Appendix A.

---

**[42] Sonar (2026).** *State of Code Developer Survey*, 8 January 2026; 1,100+ developers globally.
https://www.sonarsource.com/company/press-releases/sonar-data-reveals-critical-verification-gap-in-ai-coding/

- AI accounts for **42% of all committed code**, expected to reach 65% by 2027. 72% of AI users use it daily.
- **38% say reviewing AI-generated code requires more effort than reviewing code written by human colleagues.**
- 96% do not fully trust AI output, yet only 48% always verify it before committing.
- 61% agree AI produces code that looks correct but is not reliable.
- Developers spend roughly 24% of the work week verifying, fixing and debugging AI-generated code.

*Caveat.* Sonar sells code review and verification tooling. Self-report survey.

---

**[43] LinearB (2026).** *Software Engineering Benchmarks Report*; 8.1 million pull requests.
Reported via https://blog.codacy.com/ai-breaking-code-review-how-engineering-teams-survive-pr-bottleneck

- Agentic AI pull requests have **pickup time 5.3× longer** than unassisted PRs; AI-assisted PRs wait 2.47× longer.
- AI-assisted PRs run roughly 2.5× larger.

*Caveat.* Pickup time is queue time, not reviewer effort; it measures reviewer avoidance rather than cost per unit. Accessed via secondary reporting.

---

**[44] Digital Applied (2026).** Q1 2026 developer survey; 2,847 developers.
Reported via https://antoniopagano.com/blog/ai-verification-bottleneck/

- Reviewing AI-generated code has **overtaken writing as the single largest time sink**, at a median of **11.4 hours per week**, up 31% year over year.
- Heavy agentic users report review loads of **14–16 hours weekly** while writing hours stayed flat.

*Caveat.* Accessed via secondary reporting; primary not located.

---

**[45] Harness (2026).** *State of Engineering Excellence Report*; 700 practitioners across US, UK, India, France, Germany.
Reported via https://dev.to/harsh2644/the-review-tax-why-81-of-developers-are-buried-in-ai-code-review-9k6

- **81% of developers spend more time in code review since their teams adopted AI**; 28% report review time up 30% or more.
- AI tools cut time-to-PR by roughly 58%, but those PRs then sit in review substantially longer.
- Only ~38% of organisations track time spent reviewing AI-generated code specifically.

*Caveat.* Vendor survey, accessed via secondary reporting.

---

**[46] Bosu, A. & Carver, J. (2013);** JetBrains *State of Developer Ecosystem*.
Cited in https://arxiv.org/pdf/2311.02489

- Developers spend approximately **6.4 hours per week** reviewing code — close to 20% of a 40-hour week. Microsoft Research places the figure at 6–12 hours for larger organisations.
- Stack Overflow survey data puts the median at 4–5 hours per week, with ~75% of developers at 5 hours or under.

*Relevance.* The pre-AI baseline against which review-effort inflation is measured in Appendix A. The spread across sources is the dominant source of uncertainty in the derived R.

---

**[47] CircleCI (2026).** Platform telemetry, reported via https://blog.codacy.com/ai-breaking-code-review-how-engineering-teams-survive-pr-bottleneck

- **Feature branch throughput up 59% year over year, while main branch throughput for the median team fell.**

*Relevance.* The clearest available signal of a binding supervision constraint: more work entering the pipeline, less work leaving it.

---

**[48] Anonymous (2026).** *Quo Vadis, Code Review? Exploring the Future of Code Review*. arXiv preprint; 100 respondents.
https://arxiv.org/pdf/2508.06879

- Median self-reported code review time approximately **3 hours per week** (IQR 2–6); most respondents under 5 hours, a subset up to 16.
- 47% expect to spend more time on review over five years; 30% about the same; 23% less.

*Caveat.* Small sample, self-reported perceptions.

---

### Firm structure and labour market

---

**[27][28] Kim, H. (INSEAD) & Koning, R. (HBS).** *AI-Native Firms.* HBS Working Paper 26-090, June 2026.
https://www.hbs.edu/faculty/Pages/item.aspx?num=69077 · PDF: https://www.hbs.edu/ris/download.aspx?name=26-090.pdf · Summary: https://aiinstitute.hbs.edu/less-headcount-more-valuation-how-ai-native-firms-change-the-game/

*Extract:* "AI-native startups are 25% smaller, half a seniority level flatter, and substantially more expert-dense"

- Sample: 2,900+ Y Combinator startups (2020–2024) linked to workforce data, plus the broader universe of US venture-backed firms, matched on industry and cohort.
- AI-native firms ~25% smaller in the YC sample and ~12% smaller in the PitchBook sample. Raw averages: approximately 13 employees against 42. Around half as many people three years after founding.
- Flatter by roughly half a seniority level; engineers a larger share of the team; fewer entry-level roles and fewer managers, each layer around 15% lower.
- Valuations comparable or higher despite smaller headcount; ~30% more funding per employee and ~30% higher valuation per head controlling for cohort and industry, rising to 76% higher valuation per employee in the PitchBook sample.
- **The mechanism:** the authors separate a process channel (staff using tools such as Claude or Cursor to work faster) from a product channel (AI embedded in what the firm sells). AI-native firms name specific coding tools in job postings at roughly 2.6× the rate of peers, but *that measure does not predict smaller headcount once other variables are controlled*. Firms embedding AI in their products employ roughly 10 fewer staff than comparable peers.
- The effect concentrates in services businesses that previously scaled by hiring, where AI-native firms run at roughly 30% of peers' headcount.

*Caveat.* Working paper, not yet peer-reviewed. Observational and correlational; the channel separation is an identification argument rather than an experiment.

---

**[29][36] Brynjolfsson, E., Chandar, B. & Chen, R.** *Canaries in the Coal Mine? Six Facts about the Recent Employment Effects of Artificial Intelligence.* Stanford Digital Economy Lab.
https://digitaleconomy.stanford.edu/publication/canaries-in-the-coal-mine-six-facts-about-the-recent-employment-effects-of-artificial-intelligence/

- August 2025 edition: early-career workers (22–25) in the most AI-exposed occupations show a 13% relative employment decline, controlling for firm-level shocks. Data from ADP payroll records.
- **August 2026 update, data through June 2026: the gap stands at 19% and has widened steadily.** Experienced workers show no comparable gap.
- The mechanism operates primarily through reduced hiring rather than increased separations. No evidence of widespread economy-wide displacement.
- Declines concentrate where AI usage substitutes for human tasks; where it complements, employment is flat or rising.

*Caveat.* Authors explicitly frame these as early descriptive indicators rather than causal estimates. Patterns attenuate when controlling for education and are more pronounced in the ADP sample than in national survey benchmarks. The superseded 13% figure remains in wide circulation.

---

### Compensation baselines

---

**[14][15] Cadence (2026)** *Software developer salary guide 2026*; **U.S. Bureau of Labor Statistics**, *Occupational Outlook Handbook*.
https://cadence.withremote.ai/blog/software-developer-salary-2026 · https://www.bls.gov/ooh/computer-and-information-technology/software-developers.htm

*Extract (Cadence):* "Fully-loaded year-one cost (benefits, equipment, recruiter, ramp time) runs 1.5-1.8x base salary."

- BLS median software developer wage: $133,080 (May 2024 release, most recent published). Lowest decile below $79,850; top decile above $211,450.
- Levels.fyi total compensation median reported at approximately $192,000 mid-2026 — a different population and measure to BLS base wage.
- Benefits and employer payroll taxes add roughly 30–40% per BLS Employer Costs for Employee Compensation.
- Fully-loaded US senior figure of $220,000–280,000 in year one including recruiter fees and onboarding.

---

**[15a][15b][15c] Product manager compensation.**
https://www.kore1.com/product-manager-salary-guide/ · https://www.recruitingfromscratch.com/blog/product-manager-salary-in-2026-real-data-from-1-9-million-job-postings-5e5dd · https://gusto.com/resources/research/salary/product-manager

*Extract (KORE1):* "Product managers in the United States earn between $119,000 and $194,000 in base salary as of 2026"

- KORE1 places the national average around $150,000, noting dispersion driven by what the title covers rather than measurement error.
- Recruiting from Scratch reports a 2026 median of $192,000 from 1,000 recent job postings (25th percentile $163,000; 75th $225,000). Posting-derived medians typically read high.
- Gusto reports a median of $132,000 with 80% of salaries between $75,000 and $190,000.
- BLS has no dedicated occupation code; the closest proxies are management occupations ($122,090 median, May 2024) and project management specialists ($100,750).
- The $150,000 base figure adopted in Appendix F.3 sits at the convergent centre of these estimates.

---

### Accounting treatment

---

**[31][35] EisnerAmper (2026).** *Accounting for AI Data and Consumption Cost*; *Accounting for AI Development Costs Under US GAAP.*
https://www.eisneramper.com/insights/technical-accounting-advisory/accounting-for-ai-data-consumption-cost-0726/ · https://www.eisneramper.com/insights/technical-accounting-advisory/ai-development-cost-under-us-gaap-0726/

- US GAAP contains no AI-specific guidance; entities apply existing software cost standards by analogy.
- For a customer in a SaaS arrangement, implementation cost follows ASC 350-40 and ASU 2018-15, while ongoing subscription and usage fees are typically expensed as incurred.
- **ASC 350-40-30-1 allows direct costs incurred during the software development phase to be capitalised**, and the source explicitly identifies AI tokens used for model training, cloud compute for model interface, and coding or functionality creation as capable of being capitalised on that basis.
- Internally generated data is generally expensed; purchased data with alternative future use may be capitalised as an intangible under ASC 350-30.
- R&D-purposed development is expensed under ASC 730 with no capitalisation pathway. Externally marketed software follows ASC 985-20, expensed until technological feasibility.
- ASU 2025-06 (September 2025) updates internal-use software guidance.
- Practitioner commentary adds the operational point: capitalisation requires tagging token requests with project and resource identifiers.

*Common misreading.* It is frequently asserted that substituting metered consumption for capitalisable labour necessarily front-loads cost recognition and reduces the capitalised asset base. That is directionally wrong: the pathway exists, and the binding constraint is per-project attribution.

*Caveat.* Accounting-firm advisory publications, not authoritative standard-setter guidance, and US GAAP-specific. Confirm with whoever prepares the accounts, in the applicable jurisdiction and framework.

---

### Single-sourced

---

**[49][50] Agentic token consumption.**
https://arxiv.org/abs/2604.22750 · https://tokenade.net/en/stats/token-usage-by-task-type

- Agentic coding tasks in the SWE-bench class consume 1.0–3.5M tokens per task including retries and self-correction loops.
- Input tokens dominate at a 2:1 to 3:1 ratio; 80%+ of input is typically cache reads.
- Repeated runs of the same task differ by up to 30× in total tokens, and higher token usage does not translate into higher accuracy — accuracy peaks at intermediate budgets.
- Unresolved attempts consume roughly four times the resources of successful ones.
- Agentic tasks consume ~1000× the tokens of single-turn code reasoning or chat.

*Caveat.* Benchmark conditions, not production. Per-task variance is large enough that any single figure is indicative only; the paper uses a range and reconciles it against operator spend.

---

**[39] Paddo (2026).** *The 10x AI Developer is a Myth.*
https://paddo.dev/blog/ai-developer-productivity-myth/

- Practitioner analysis; sole located source for the 30–50% participation-refusal figure attributed to METR's 2026 update, and for the $50/hour incentive detail.
- Also reports juniors seeing 27–39% speed gains against seniors at 8–16%, with seniors spending 4.3 minutes reviewing per AI suggestion versus 1.2 minutes for human code. These secondary figures are not relied upon in this paper.

*Caveat.* Single-sourced and not corroborated elsewhere. Cited only where the text says so explicitly.

---

## Appendix E — Cost Levels, Budget and Governance

AI spend is a small share of total cost in every configuration examined (§2), so this material is supporting rather than decisive. It is retained because budget-setting, forecasting and capitalisation still require it, and because the published record on AI cost governance is widely misread.

### E.1 What AI actually costs per engineer

#### Published per-engineer spend

Anthropic's own product documentation provides the most authoritative first-party figure:

> "average cost is around $13 per developer per active day"
> — Claude Code documentation, *Manage costs effectively*

The same source gives $150–250 per developer per month across enterprise deployments, with 90% of users below $30 per active day. Note the distribution shape: the mean is driven by a minority of heavy users, so a team-level budget built on the mean will be wrong for any team whose members are all heavy users — which is precisely the AI-first case.

Independent benchmarking [7] places realistic all-in cost higher once agentic token consumption is included, at $200–600 per engineer per month on average, with agentic power users at:

> "$200-$2,000+ per engineer per month"
> — Larridin, *Developer Productivity Benchmarks 2026*

Reported operator figures cluster at the upper end of that band. Before Uber introduced its caps, individual engineers were reported generating $500–$2,000 per month in token consumption [30]. The $150–250 band is Anthropic's cross-enterprise average [6] and is not an Uber-specific figure; the two are commonly conflated.

At the extreme, Tunguz's analysis of frontier and top-quartile firms [8] places the top 1% of software companies at approximately $89,000 per engineer per year — around 40% of a fully-loaded $224,000 senior engineer — against a market median that is effectively nil:

> "The median spends $137."
> — Tomasz Tunguz, *When AI Costs More Than the Engineer*

#### Budget-setting practice

DX's survey of 50 engineering budget holders [9] found:

> "1-3% of their total engineering budgets for AI tools"
> — DX, *How are engineering leaders approaching 2026 AI tooling budgets?*

The same source reports $1,000 per developer per year emerging as a common 2026 target, with a plausible range of $500 to $3,000+ where developers receive access to multiple tools.

This band is materially below the operator data in Appendix E.1. The gap is the central budgeting hazard: **budgets are being set from seat-licence intuition while costs are being incurred on consumption.**

#### Structural shift — — fixed to variable, with no natural ceiling

Under seat licensing, cost did not move with usage. Under token metering it moves with exactly the thing that makes the tool valuable. A more capable agent performs more work per task and therefore costs more per task; there is no equilibrium point at which the bill self-limits.

JetBrains' engineering organisation documented this directly [4][5], reporting that development-related AI spending rose roughly tenfold over six months as token consumption accelerated from January 2026 alongside more capable frontier models, with most developers using three to five AI tools each month. Notably, JetBrains' remedy was not tool restriction but a centralised access and accounting layer — a shared control point between developers and providers, permitting per-developer and per-team limits while preserving tool choice.

#### Structural shift — — forecast error becomes the dominant financial risk

> "only 15% of companies forecast AI costs within 10% of actual"
> — Forbes, reporting a Mavvrik/Benchmarkit survey of 372 enterprises

A majority missed by 11–25%, and nearly one in four by more than 50%. The source is vendor-originated and should be weighted accordingly. A FinOps Foundation figure of 73% of enterprises exceeding AI cost projections circulates widely; it could not be confirmed against the primary [16] in this pass and is noted rather than relied upon.

**Uber is the best-documented case and the most useful for calibration** [30]. It capped spend at $1,500 per month per employee *per tool* after exhausting its entire planned annual AI coding budget in four months, having previously encouraged maximum use and ranked engineers on usage leaderboards. Power users were running $500–$2,000 per month.

**The cap is a soft ceiling, not a hard stop** — exceedable with permission, tracked on a per-employee dashboard. That escalation path is the more important half of the design: it preserves the ability to spend where justified while making the decision explicit rather than invisible.

**The calibration point** was computed by Simon Willison [30]: two tools at the cap is roughly $36,000 per year, approximately **11%** of a typical Uber engineer's $330,000 package. That is the right order of magnitude for agent-primary operation, and an order of magnitude above the seat-licence figures in Appendix E.1. For scale on the output side, Uber's CEO is reported as saying around 10% of the company's code was AI-created, and its COO as saying it remains hard to draw a line from the spend to shipped features.

For a small team the absolute exposure is smaller; the governance lesson is not. A 50% overrun on a $58,000 budget is $29,000, which for a small business is a material and unbudgeted expense.

#### Structural shift — — the accounting treatment changes

This shift is absent from most of the engineering literature and is material for a small business. It is also frequently stated backwards.

Under Configuration A, most product development cost is engineering labour, a portion of which is typically capitalised as internally-developed software under ASC 350-40 and amortised. The intuitive assumption is that substituting metered AI consumption destroys that treatment. **It does not, necessarily.** ASC 350-40-30-1 permits direct costs incurred during the application development stage to be capitalised, and EisnerAmper's 2026 advisory [31][35] identifies tokens consumed for coding and functionality creation as capable of falling within that window. The distinction is purpose, not form: ongoing SaaS usage fees are typically expensed, while tokens consumed to build a durable software asset have a defensible capitalisation pathway. R&D-purposed development is expensed under ASC 730 regardless; externally marketed software follows ASC 985-20.

**The binding constraint is substantiation, not eligibility.** Capitalisation requires demonstrating which token spend built which asset at which stage — per-project, per-resource attribution that most teams do not have, and which is the same instrumentation §6.3 requires for cost control. Build it once, get both.

Three consequences, none arguing against the substitution but all worth testing with whoever prepares the accounts *before* the decision: treating token spend as undifferentiated operating expense when a capitalisation pathway exists depresses reported margin unnecessarily; claiming capitalisation without attribution is not defensible under audit; and R&D credit eligibility may be affected, since qualifying-expenditure definitions were drafted around labour rather than metered compute. The sources are accounting-firm advisory publications, not standard-setter guidance, and treatment is jurisdiction-specific.

### E.2 The cost trade, and the recommended budget

Let one engineer operating without agentic tooling produce 1.0 output units.

Let one engineer operating without agentic tooling produce 1.0 output units. Payroll is identical across scenarios; only the lift parameters vary.

**Configuration A payroll:** $1,075,000 (lead $250k + developers $600k + PM $225k) + AI $15,000 = **$1,090,000**
**Configuration B payroll:** $562,500 (lead $250k + developer $200k + PM $112.5k) + AI budget *X*

Per Appendix F.1, the published estimates disagree widely enough that a single point estimate would misrepresent the evidence. Four scenarios are therefore reported.

**The trade, stated plainly.** Configuration B removes two developers and half a product manager, saving **$512,500** in fully-loaded payroll. Running it agent-primary costs $44,400–64,800 in AI against Configuration A's ~$15,000, so the additional tooling spend is $29,400–49,800. **The net cash saving is therefore roughly $463,000–483,000 a year — and it buys 46% less delivery.**

Expressed per unit of output, that trade is negative. At a mid-range $55,000 AI budget, Configuration B costs $617,500 for 2.40 units, or **$257,292 per unit against Configuration A's $243,304 — 5.7% more expensive per unit delivered.** *[Author's derivation from the model.]* The saving is real cash; it is simply buying less than it costs.

This is the number that matters for the decision. A firm that is capital-constrained and not delivery-constrained may rationally accept it: $463,000–483,000 of runway in exchange for roughly half the output. A firm that needs the output should not.

Under the supervision model the same trade reads differently depending on R. At **R = 1.5** Configuration B matches Configuration A's output for $617,500 against $1,090,000 — a saving of $472,500 at equal delivery, which would make it clearly correct. At **R = 2.80** it delivers 53.6% and costs 5.7% more per unit. The cash saving is identical in both cases; what changes is what it buys.

| Layer | Monthly | Annual |
|---|---|---|
| Committed subscription floor (2 engineering seats, top tier) *(derived, [6])* | $400 | $4,800 |
| Product management tooling (0.5–1.0 FTE) *(derived, [6])* | $100–200 | $1,200–2,400 |
| Metered agentic headroom (engineering) *(derived, [6][7][30])* | $2,400–3,600 | $28,800–43,200 |
| Automated PR review and eval gating *(derived, [11])* | $200–400 | $2,400–4,800 |
| CI / compute uplift from higher PR volume *(author's estimate)* | $300–500 | $3,600–6,000 |
| Model and harness evaluation reserve *(author's estimate)* | $300 | $3,600 |
| **Total** | **$3,700–5,400** | **$44,400–64,800** |

**Provenance of this table.** The subscription floor and metered headroom lines are derived from the published per-engineer bands in Appendix E.1 (Anthropic [6], Larridin [7], Uber operator figures [30]). The automated review line derives from GitLab's published per-review pricing [11]. **The CI/compute uplift and evaluation reserve lines are the present author's estimates and are not sourced**; no published dataset quantifies either for a team of this size. They are included because omitting them would understate the total, and flagged because including them should not lend them false authority.

**If Configuration A is retained with an elevated budget (the recommended course), plan $58,000 per annum.**

**If the substitution proceeds despite §6.1, the break-even ceiling is $21,429** on the realistic base case — below this table's floor. That is the arithmetic statement of why the substitution is not recommended: there is no budget at which it is both affordable to run and cheaper per unit than the incumbent. Only if local measurement demonstrates a sustained lift at or above +35% does the ceiling rise to roughly $94,000 and the configuration become fundable.

Per engineer, the table above is approximately $2,300–2,700 per month — consistent with the published power-user band and with the Uber calibration in Appendix E (roughly 11% of a fully-loaded package), but well above the seat-licence figures that dominate budget-setting practice (Appendix E.1). Note that the product manager should be funded for agentic tooling too; specification, research and acceptance-criteria work benefit from it, and whoever carries the specification load needs the leverage more than anyone on the team.

---

## Appendix F — Extended Analysis

Supporting detail removed from the body for length. Nothing here is omitted from the argument; it is the evidence and parameter work behind it.

### F.1 What has been measured, and why it answers a different question

#### F.1.1 The principal field study

The strongest available evidence is Murphy-Hill, Butler and Savelieva's study [1] of Microsoft's early-2026 rollout of Claude Code and GitHub Copilot CLI, published July 2026. It is the first field study to use developer-level telemetry to analyse both adoption and pull-request impact for agentic command-line tools, and it covers tens of thousands of engineers over a sixteen-week window.

Its central result, estimated via a Bayesian structural time-series synthetic control:

> "adopters merged roughly 24% more pull requests than they would have otherwise"
> — Murphy-Hill, Butler & Savelieva (2026), arXiv:2607.01418

The point estimate is +24.0% with a 95% credible interval of [+14.5%, +33.7%]. A placebo intervention at an earlier date returned −1.1% [−10.6%, +8.6%], passing the falsification check.

Two secondary results matter more for the substitution question than the headline.

**The effect is dose-dependent and monotone.** Within-person analysis, where each engineer serves as their own control across weeks of differing tool use, yields a lift of +15.0% at three tool-use days per week rising to **+50.1% at five or more days per week**. This is the ceiling the literature currently supports for an individual engineer operating at maximum intensity — which is, definitionally, the AI-first operating mode.

**The effect does not decay.** February's estimate (+29.4%) and the March–April estimate (+20.0%) have substantially overlapping credible intervals and both exclude zero. This contradicts earlier open-source findings of a lift that faded by month three [1], and the authors attribute the difference to tool generation and to their within-person design being immune to compositional drift.

#### F.1.2 Reconciling the conflicting estimates

The Microsoft result does not stand alone, and the other large studies disagree with it substantially. The disagreement is not measurement noise; it tracks sample composition, tool generation, and unit of analysis in an interpretable way.

| Study | Population | Design | Central estimate |
|---|---|---|---|
| METR (2025) | 16 experienced OSS developers, 246 tasks, own repositories | Randomised controlled trial | **−19%** (slower) |
| DX (Nov 2024–Feb 2026) | 400+ organisations | Longitudinal panel | **+7.76%** median PR throughput (mean +13.1%; ~+44% at p90) |
| Stanford (Denisov-Blanch) | ~100,000 engineers, 600+ companies | Commit-level functional analysis | **+15–20% net of rework** (gross +30–40%) |
| Faros AI (2026) | 22,000 developers, 4,000 teams | Telemetry | **+16.2%** PRs merged/developer (+33.7% tasks, +66.2% epics) |
| Microsoft (2026) | Tens of thousands of engineers | Telemetry, within-person + synthetic control | **+24%** pooled [CI +14.5%, +33.7%]; **+50%** at 5+ tool-days/week |

**Three of the five converge; one is an outlier.** DX, Stanford and Faros cluster between roughly +8% and +20%. Microsoft sits well above them. That matters because Microsoft is also the study with the most disclosed conflict: its authors state that Microsoft sells AI tools and owns GitHub, the maker of Copilot CLI — the tool their data finds outperforms the alternative by 2.2×. The authors handle this openly and their design is the most rigorous in the set, but a single outlier with a structural interest is the wrong anchor for a headcount decision.

**This paper accordingly treats the convergent band as the base case and the Microsoft figures as an upper bound.**

**The METR result deserves particular weight and particular care.** It is the only randomised controlled trial in the set, and it found that experienced open-source developers took 19% longer with AI tools while believing they had been sped up by 20% — a roughly 39-point gap between perception and measurement, against an initial forecast of a 24% speedup. That perception gap is the single strongest argument against self-reported productivity data anywhere in this literature.

It must be read with its limitations stated: early-2025 tooling (autocomplete-and-chat rather than agentic), n=16, and experienced developers working in mature repositories they knew well — close to the worst case for AI assistance per the Stanford task-type finding.

**METR's own follow-up neither confirmed nor refuted the result.** Its February 2026 methodology update reports an unreliable signal, because developers declined to participate rather than work without AI, biasing the estimate downward [20]. METR's position is that developers are likely more sped up in early 2026, but that its data is only very weak evidence for the size of that increase. Its separate survey work cautions that self-report instruments — including those used by AI vendors — may lead respondents to overestimate gains [21].

The correct reading: **−19% is a valid finding about early-2025 tooling in mature codebases, not a current estimate, and METR has explicitly declined to publish one.** This paper retains it as a stress-test floor, not a forecast.

**Why the gradient runs upward across the table.** Tool generation explains much of it: METR tested autocomplete-era tools, Microsoft tested agentic CLI tools eighteen months later. Unit of analysis explains more: DX measures organisation-level medians, which include non-adopters and dilute toward zero, while Microsoft's within-person design conditions on the same engineer and is immune to that dilution. Sample composition explains the remainder.

**Why the ceiling is low regardless.** DX [22] offers the clearest mechanical account, and it is structural rather than about tool quality. Developers report saving an average of 3.9 hours per week, but coding is only around 14% of a developer's day — so accelerating it has a bounded ceiling no matter how good the tool becomes. The saved time is then consumed by increased review burden for AI-generated output, by downstream processes that have not scaled with code velocity, and by the learning curve. This is the same mechanism Stanford quantifies from the other direction: gross +30–40% collapsing to net +15–20% once rework is netted off.

For planning purposes, **the defensible central band for a team at high adoption intensity is roughly +12% to +20%, with +50% reachable only at maximum dose on favourable work under the outlier study.** §4 runs all of these.

#### F.1.3 The selection effect that invalidates most internal claims

GitClear's January 2026 study *AI Coding Tools Attract Top Performers — But Do They Create Them?* [34] identifies the trap that catches nearly every organisation attempting to measure its own AI return: heavy AI users out-produce non-users by a factor of 4–10, but most of that gap pre-dated AI adoption. Measured against their own prior output, the gain is substantially more modest. (A specific figure of roughly 25% for the within-person gain circulates in secondary commentary; it could not be confirmed against the primary source and should not be relied on. The direction of the finding is confirmed; the magnitude is not.)

Note that this is a **different GitClear study** from the *Maintainability Gap* analysis [26] cited in Appendix F.1 — the two are frequently conflated.

This matters directly for anyone assessing Configuration B. The engineers who remain after a two-thirds reduction will be the strongest performers, and they will out-produce the departed average by a wide margin *for reasons unrelated to AI*. A naive before-and-after comparison will therefore attribute a selection effect to the tooling and conclude the substitution succeeded when it did not.

The methodological implication is that only within-person or cohort-matched designs are trustworthy here — which is precisely why the Microsoft within-person dose-response is weighted more heavily in Appendix F.1 than its cross-sectional peers, and why any internal measurement must split cohorts on pre-AI performance.

#### F.1.4 Task-mix dependency and the verification constraint

The single most important moderator is the nature of the work. Stanford's Software Engineering Productivity research (Denisov-Blanch et al.) [33] analysed roughly 100,000 engineers across 600+ companies and tens of millions of commits, using functional analysis of what code accomplishes rather than raw counts. It reports a two-dimensional matrix on task complexity and codebase maturity:

| | **Greenfield** | **Brownfield (existing codebase)** |
|---|---|---|
| **Low complexity** | 30–40% | 15–20% |
| **High complexity** | 10–15% | 0–10%, and sometimes negative |

**The study's headline result is the one most often dropped in citation.** Gross delivered output rises roughly 30–40%, but a substantial share of that is rework — modifying recently committed code to fix what the AI produced. Netting rework off, **the average productivity gain across all industries and task types is 15–20%.**

Two implications follow. First, the perceived-versus-actual gap that METR found in a controlled setting reappears here at scale: the 30–40% figure is what a dashboard shows, and the 15–20% figure is what the organisation gets. Second, a team maintaining a mature, interdependent production system should plan against the bottom-right cell — 0–10%, possibly negative — not the top-left.

Microsoft's accompanying survey of 609 attendees at an internal agentic engineering event [1] found respondents describing the tools as well suited to experienced developers capable of decomposing work into reviewable chunks, with explicit scepticism about junior effectiveness. The quantitative data agrees in part: junior individual contributors were less likely to try the tools, though those who used them showed larger lifts.

**The constraint under AI-first operation is human verification capacity, not human authoring capacity.** Any restructuring that removes verification capacity while increasing generated volume moves against it.

---

#### F.1.5 Cost migrates from authoring to verification

DORA's 2026 report *The ROI of AI-assisted Software Development* [2][3] models a J-curve of value realisation: a temporary productivity dip before long-term gain, driven by the learning curve, the verification tax on reviewing AI-generated code, and the need to adapt downstream testing and approval processes to higher code volume — a framing consistent with DORA's 2025 finding that AI adoption is associated with increased delivery instability [32]. The report characterises this period as:

> "the tuition cost of transformation"
> — DORA (2026), via InfoQ

The report's illustrative calculator makes the cost of the accompanying instability explicit, showing a negative downtime impact of $344,000 on the assumption that change failure rate rises from 5% to 6% following adoption.

Downstream, review becomes the bottleneck. GitLab [11] cites a 91% increase in code review times on teams using AI coding tools — a figure that traces to Faros's **2025** report (10,000 developers), and which the 2026 edition supersedes with larger numbers.

**The quantified cost transfer.** Faros's 2026 telemetry across 22,000 developers [23][37] puts numbers on where the offsetting cost lands, and the magnitudes exceed the gains they offset: median time in review up 441.5%, PR size up 51%, bugs per developer up 54%, incidents per PR up 242.7%, code churn up 861%, and 31% more pull requests merging with no review at all.

GitClear's *Maintainability Gap* analysis [26] — 623 million changes, 2023 to 2026 — points the same direction on code structure: duplication up 81%, error-masking constructs up 47%, refactoring line moves down 70%, cross-file function calls down 35%, legacy maintenance down 74%. Full figures and caveats for both sources are in Sources.

Two implications follow. First, **the cost curve does not flatten, it relocates** — from generation, which is cheap and metered, to verification, rework and incident response, which are expensive, senior and human. Faros characterises human review as the largest hidden cost, falling on senior engineers [23]. A figure of $150,000–$300,000 per senior departure is associated with this analysis but **could not be independently corroborated** and is not relied upon here. Second, and critically for anyone assuming engineering maturity is protective: Faros reports no evidence that organisations with strong pre-AI engineering practices are insulated from the quality degradation. The pattern appears regardless of baseline maturity, because the processes in question were sized for a lower-throughput world.

**Second-order infrastructure costs.** Higher merged-PR volume propagates into CI minutes, build infrastructure, artefact storage, environment provisioning and automated review spend. Faros reports lead time from commit to production up 480.4% and time in progress up 225.2% among organisations instrumenting those metrics [23]. **No published source quantifies the resulting infrastructure spend increase**, and this paper does not assert one; the Appendix E budget line for CI and compute uplift is the author's estimate and is flagged as such there.

---

### F.2 The unit of work

Every headline figure in this paper is denominated in "units of work". Because the entire comparison rests on that denominator, it is defined here explicitly rather than left implicit.

**Definition.**

> **One unit of work = the merged, delivered output that one competent engineer produces in one year, working without AI assistance, on this team's codebase.**

Configuration 0 therefore produces exactly **4.00 units** by construction: four engineers, no AI, one year. This is a definition, not a measurement — the pre-AI team defines the yardstick, and every other configuration is measured against it.

**Why the unit is defined this way.** Three alternatives were considered and rejected:

- **Lines of code.** Rewards verbosity, and AI adoption inflates it directly — the worst possible denominator here.
- **Story points.** Not comparable across teams, and re-baselined by teams whenever velocity changes, which would absorb precisely the effect being measured.
- **Merged pull requests, counted raw.** The proxy used by the underlying literature [1], but AI adoption inflates PR counts and PR size simultaneously (Appendix F.1), so raw counts drift against delivered value.

Defining the unit against *one engineer-year of pre-AI output* sidesteps all three. It is self-normalising: whatever mix of features, fixes and refactoring a team actually delivers, one engineer-year of it is one unit.

**What a unit costs, and why the figures look large.** Cost per unit divides *total* configuration cost by units produced, so it carries the full overhead of producing that output — lead, product management and tooling included, not just the producing engineer's salary:

```
Configuration 0:  $1,075,000 / 4.00 units  =  $268,750 per unit
```

This is why unit costs exceed a developer's salary. A unit is not "what one developer costs"; it is **what the organisation pays, all in, for one engineer-year of delivered work.** That is the correct basis for comparing configurations with different shapes, since Configuration B's economics depend precisely on carrying fewer producers under the same overhead.

**How the other configurations map onto it.**

| | Derivation | Units |
|---|---|---|
| Configuration 0 | 4 engineers × 1.00 (definitional) | **4.00** |
| Configuration A | 4 engineers × 1.12 (authoring team, AI-assisted) | **4.48** |
| Agent-primary team | *n* supervisors × span / R (Appendix A) | **5*n* / R** |

The two configurations use different functional forms, and deliberately so: Configuration A is an authoring team whose humans are made faster; the agent-primary team is a supervisory one whose humans are made responsible for more. Applying the authoring form to a supervisory team is the common error this paper avoids.

**Four limitations of the unit, stated plainly.**

1. **It measures delivered volume, not delivered value.** A unit of well-chosen work and a unit of misdirected work count the same. This matters most for Configuration B, where reduced specification capacity (Appendix F.5) raises the risk that output is volume without value.
2. **It assumes units are fungible across configurations.** A unit of agent-authored work carries different downstream properties — higher duplication, less refactoring, higher churn (Appendix F.1) — than a unit of human-authored work. The model treats them as equivalent; the evidence says they are not.
3. **It inherits the merged-PR proxy's bias.** The productivity lifts feeding Configuration A come from studies counting merged PRs [1], so the +12% is only as good as that proxy.
4. **It is annualised.** All costs are annual, so all output is annual. The model says nothing about latency, and a configuration delivering the same annual units in a burstier pattern is not distinguished.

Limitations 1 and 2 both flatter Configuration B, which is why every throughput figure for it is reported as an upper bound.

**Practical translation.** To apply this model locally, do not attempt to count units directly. Take the delivered output of your team in its last full pre-AI year, divide by the number of engineers, and call that 1.0. Everything else follows from ratios.

### F.3 Configurations and parameters

| | **Configuration 0** (pre-AI) | **Configuration A** (AI-assisted) | **Configuration B** (AI-first) |
|---|---|---|---|
| Engineering lead | 1 | 1 | 1 |
| Developers | 3 | 3 | 1 |
| Product manager | 1.0 FTE | 1.0 FTE | 0.5 FTE |
| Total FTE | 5.0 | 5.0 | 2.5 |
| Output-producing engineers | 4 | 4 | 2 |
| Operating mode | No AI tooling | AI-assisted (moderate) | AI-first (maximum intensity) |
| AI budget posture | None | Standard tooling | Elevated, metered, capped |
| Governing model | — | Augmentation | Supervision-bound (Appendix F.4) |

**Configuration 0 exists to separate two effects that are otherwise conflated.** Moving 0 → A measures what adopting AI does to a conventional team — the only thing the published literature actually studies. Moving A → B measures what restructuring around agents does, which nothing in the literature studies. Reporting only A and B would credit the restructuring with gains that belong to adoption.

#### Parameters

Fully-loaded cost is used throughout. Cadence's 2026 salary guide [14] places fully-loaded year-one cost at 1.5–1.8× base salary once benefits, employer taxes, equipment, recruiting and ramp are included. Against the BLS median software developer wage of $133,080 (May 2024 release, the most recent published) [15], this yields a fully-loaded developer figure of approximately $200,000 and a lead figure of approximately $250,000. Tunguz's independent anchor of $224,000 fully-loaded for a senior engineer sits inside this range and is used as a cross-check.

Product manager compensation is less consistently reported than engineering compensation [15a], with published 2026 medians spanning roughly $132,000 (Gusto [15c]) to $192,000 (Recruiting from Scratch, job-posting analysis [15b]), reflecting genuine dispersion in what the title covers rather than measurement noise. A national base figure of approximately $150,000 is used, consistent with the convergent estimate across aggregators, giving a fully-loaded figure of $225,000 at the same 1.5× loading applied to engineering.

| Parameter | Value | Source basis |
|---|---|---|
| Fully-loaded lead | $250,000 / yr | *Derivation:* BLS median [15] × loading [14], upper band |
| Fully-loaded developer | $200,000 / yr | *Derivation:* BLS median [15] × loading [14], mid band |
| Fully-loaded product manager | $225,000 / yr | *Derivation:* ~$150k convergent base [15a][15b][15c] × 1.5 loading [14] |
| Config A AI spend | $250 / FTE / month | Anthropic enterprise average, upper bound |
| Config B AI spend | variable — solved for | — |
| Config 0 productivity lift | 0% by definition | One unassisted engineer produces 1.0 units; this defines the unit |
| Config A productivity lift | **+12% (base case)** | Convergent band, DX [22] / Stanford [33] / Faros [23] — see Appendix F.1 |
| Config B productivity lift | **+20% (base case)** | Upper end of Stanford net-of-rework band [33] at maximum intensity |
| Alternative lift scenarios | +24% / +50%; +7.76% / +16.2%; −19% | Microsoft [1]; DX [22] / Faros [23]; METR [19] — see Appendix F.4 |
| Output unit | one engineer-year of pre-AI merged output | Defined in Appendix F.2 |
| Supervision ratio R | 3.29 central; 1.8–4.8 range | Defined and derived in Appendix A |
| PM output contribution | zero (by proxy definition) | See §1 |

### F.4 The binding constraint is supervision, not authoring speed

**The ceiling on an AI-first team is not how fast its humans write code with AI assistance. It is how much agent output those humans can supervise.** This section builds the model on that basis. The alternative form — treating each human as a producer whom AI makes faster — is retained below for comparison, but it does not fit the configuration and is not the primary analysis.

**Why the constraint sits there.** In Configuration B no human authors production code. Authoring speed is therefore not a constraint on anything; the agents' capacity is effectively unbounded relative to the team's ability to consume it, and cost of tokens is a budget question rather than a throughput one. What limits delivery is the rate at which two people can specify work, read what comes back, verify it does what was meant, and accept it. Every published productivity figure measures the wrong quantity for this purpose.

**The anchor is span of control:** an engineering supervisor oversees roughly five developers, so one supervisor covers five units of human-authored output and `5 / R` units of agent-authored output.

**The model.**

```
output_B = supervisors × S / R

  v = share of the working week a supervisor spends reviewing, at quality
      = 3.36, anchored on the Configuration A lead
  R = the supervision ratio, as defined in Appendix A
```

Configuration B has two supervisors, giving a human-equivalent capacity of **6.72 units**, divided by R.

Note that applying the lead's demonstrated rate to *both* humans is deliberately generous — a developer does not demonstrably supervise at a lead's rate — so every figure below is an upper bound on Configuration B.

**Results.** Configuration A produces 4.48 units at $243,304 per unit. Configuration B carries $562,500 of payroll plus an AI budget taken here at $55,000.

| R | B output | % of A | % of pre-AI | B cost/unit | vs A | vs pre-AI | Basis |
|---|---|---|---|---|---|---|---|
| **1.0** | 6.72 | 150.0% | 168.0% | $91,890 | cheaper | −65.8% | agent output as cheap to check as human |
| **1.5** | 4.48 | 100.0% | 112.0% | $137,835 | cheaper | −48.7% | throughput-parity threshold |
| **2.0** | 3.36 | 75.0% | 84.0% | $183,780 | cheaper | −31.6% | midpoint |
| **2.65** | 2.54 | 56.6% | 63.4% | $243,494 | ≈ parity | −9.4% | unit-cost crossover vs A (exactly 2.648) |
| 2.80 | 2.40 | 53.6% | 60.0% | $257,292 | dearer | −4.3% | *implied by the augmentation form* |
| **3.29** | **2.04** | **45.6%** | **51.1%** | **$302,252** | **dearer** | **+12.5%** | **derived central estimate** |
| 3.6 | 1.87 | 41.7% | 46.7% | $330,745 | dearer | +23.1% | corroborating datapoint |

**Note the second crossover.** Configuration B stops being cheaper per unit than *Configuration A* at R ≈ 2.65. It stops being cheaper per unit than the **pre-AI team** at R ≈ 2.93. At the derived R of 3.29 it has passed both: **the AI-first restructuring delivers work at 12.5% more per unit than the same team would have managed with no AI tooling at all.**

*[Author's derivation; see `supervision_model()` and `solve_r_thresholds()`.]*

**The two thresholds.**

- **R ≤ 1.50** — Configuration B matches Configuration A's *throughput*.
- **R ≈ 2.65** — Configuration B matches Configuration A's *cost per unit* (crossover at 2.648).
- **Above 2.65** — it fails on both.

**This is the whole question.** Every other parameter in this paper — compensation, AI spend, productivity lift, task mix — moves the thresholds by a few percentage points. R moves the answer from *Configuration B delivers half again as much as the incumbent* to *Configuration B delivers two fifths of it*. Nothing else in the analysis has that leverage.

**And R is unmeasured.** No study in the literature reports the cost of supervising agent-authored output relative to human-authored output. The sole located proxy — senior review at 4.3 minutes per AI suggestion against 1.2 minutes for human code, implying R ≈ 3.6 [39] — is single-sourced and uses a denominator (per suggestion) that does not match the one required here (per unit of delivered output). It indicates direction, not magnitude.

### F.5 The specification constraint and the product manager reduction

The cost model treats the 0.5 FTE product manager as a saving of $112,500 per annum. The literature suggests this is the least defensible line in the configuration, and for a reason that the merged-PR proxy structurally cannot capture.

**The bottleneck moves outward, not away.** The consistent finding across the 2026 literature is that agentic tooling does not remove the delivery bottleneck; it relocates it [15d][15e]. DORA's framing [2][3] is that returns come not from the tools but from the surrounding organisational system — the quality of the internal platform, the clarity of workflows, and team alignment. Practitioner accounts converge on the same structure from the other direction: with generation cheap, the binding constraints become *what to build* (specification, upstream) and *whether it is correct* (verification, downstream). Guidance for AI-native teams [15d] states the inversion plainly — agents produce first-draft code, humans build the system that verifies it, and more time is spent on planning and specification rather than less.

**Configuration B reduces capacity on both sides of the constraint simultaneously.** It removes two-thirds of developer capacity, which is where verification review happens, and half of product management capacity, which is where specification happens. Meanwhile the per-engineer lift it depends on — +20% in the base case, +50% under the optimistic upper bound (Appendix F.4) — is, definitionally, more generated code per remaining person. The configuration therefore increases throughput demand on two functions while reducing the staffing of both.

**The asymmetry with the developer reduction matters.** The developer reduction is at least *compensated* by a documented effect: the Microsoft dose-response shows a remaining engineer at maximum intensity producing +50%. **No published field evidence was located** that a product manager operating with AI assistance produces proportionally more specification throughput, and none at the +100% that a halving would require to hold specification capacity constant. *[Absence of located evidence, not a positive finding that no such effect exists.]* The developer cut trades against a measured effect; the product manager cut trades against an assumption.

**The failure mode is not slower delivery — it is faster delivery of the wrong thing**, which is why the merged-PR proxy conceals it. Under-specified work still merges, at normal or elevated rates; the cost surfaces later as rework, churn and abandoned features. Larridin [7] treats 30-day code turnover above 18% as warranting an audit and above 25% as critical, against a pre-AI two-week baseline of 3.3% [26]. A team that has halved its specification capacity should expect the wrong end of that distribution and should instrument for it from the outset.

**Mitigations, in order of evidential support:** retain full product management capacity and take the saving elsewhere — the $112,500 is roughly **twice** the Appendix E AI budget, so the reduction is not needed to fund the tooling *[author's derivation]*; failing that, move specification into the engineering lead's remit explicitly and fund the time, accepting that this consumes lead capacity Configuration B also needs for review; and instrument specification quality directly through rework rate and feature abandonment rather than velocity, which is why DORA measures deployment rework rate [15e][32].

**The verification paradox.** Configuration B reduces developer-level review capacity by two-thirds (3 developers to 1) while raising generated code volume. This runs directly against the constraint identified in Appendix F.1 and against DORA's instability finding in Appendix F.1, and compounds with the specification reduction in Appendix F.5 — the two constraints sit either side of the same widened pipe. Two mitigations are available and both cost money that must sit inside the AI budget:

1. **Automated review gating.** Flat-rate agentic review is now commercially available at low unit cost — GitLab prices Code Review Flow at $0.25 per merge request, against token-metered alternatives it identifies as running $15–25 per review on larger changes [11]. (GitLab is the vendor of the priced product; the comparison figure is its own.)
2. **Verification-first process discipline.** Test-first sequencing and specification-before-implementation, which shift human effort upstream of generation rather than downstream of it.

### F.6 The firm-level headcount evidence

The most directly relevant study for a headcount-substitution decision is Kim (INSEAD) and Koning (HBS), *AI-Native Firms*, HBS Working Paper 26-090, June 2026 [27][28]. It links workforce data for over 2,900 Y Combinator startups (2020–2024) plus the broader universe of US venture-backed firms, comparing AI-native firms against matched non-AI peers by industry and cohort.

**The headline appears to support the substitution.** AI-native startups are ~25% smaller in the Y Combinator sample and ~12% smaller in the broader PitchBook sample, controlling for industry and cohort — flatter by around half a seniority level, more engineer-dense, with fewer entry-level roles and managers — yet carry comparable or higher valuations per employee.

**The mechanism is the problem.** The authors distinguish a **process channel** (staff using tools such as Claude or Cursor to work faster) from a **product channel** (AI capability embedded in what the firm sells). AI-native firms name specific coding tools in job postings at roughly 2.6× the rate of peers, but **that measure does not predict smaller headcount once other variables are controlled.** What does predict it is the product channel: firms embedding AI in their products employ roughly 10 fewer staff than comparable peers, concentrated in services businesses that previously scaled by hiring.

**This is the single most important finding in the paper for the question posed.** The best available firm-level evidence attributes lean AI-native headcount to *selling* AI, not to *coding with* it. Configuration B is a pure process-channel intervention: the same product, built by fewer people using better tools. The firm-level evidence does not support the expectation that this yields a durable structural headcount reduction.

The corollary is more useful than the caution. If the objective is to operate at materially lower headcount, the evidence points toward changing what the product does — moving work customers currently perform, or that the firm performs on their behalf, into AI capability inside the product — rather than toward reducing the team that builds it. Those are different decisions with different risk profiles, and only the second is being modelled here.

**Adjacent evidence on the entry-level rung.** Stanford's Digital Economy Lab, using ADP payroll microdata [29][36], documents employment effects concentrated in early-career workers in AI-exposed occupations. The August 2025 edition reported a 13% relative decline for workers aged 22–25; the **August 2026 update, with data through June 2026, puts the gap at 19% and finds it has widened steadily.** Experienced workers in the same occupations show no comparable gap. The mechanism is primarily reduced hiring rather than increased separations, and the authors find no evidence of widespread economy-wide displacement.

The authors explicitly frame these as early descriptive indicators rather than causal estimates, and note the patterns attenuate when controlling for education. Combined with Kim and Koning's finding of ~15% lower entry-level and management layers at AI-native firms, this describes a redesign rather than a proportional shrink: junior work is absorbed into senior workflows or automated. That is consistent with the verification-capacity constraint in Appendix F.1, but poor news for anyone relying on a junior pipeline to backfill the roles Configuration B removes.

