# Adversarial Review Brief

Paste the block below into a **new conversation**. Do not paste anything else from this
session — no summary, no context, no list of known concerns. The value of the review
depends on the reviewer finding defects independently.

Attach or reference these two files from your outputs:
- `ai-first-engineering-cost-structure.md`
- `ai_team_cost_model.py`

---

````text
Perform an adversarial review of the attached report and its companion model.

YOUR ROLE

You are a reviewer whose job is to find errors, not to confirm the work. Assume the
report is wrong somewhere and find where. A review that returns "looks sound" has
failed. Approach it as if you had been asked to argue against its conclusion in front
of the people who commissioned it.

WHAT THE REPORT CLAIMS

Read it and establish this yourself. Do not take the summary tables at face value.

MANDATORY CHECKS

1. ARITHMETIC. Run the model. Independently verify every number in the report against
   model output. Report any figure that does not reconcile, including rounding.

2. CIRCULARITY. Trace each parameter to its origin. Flag any figure derived from a
   quantity that itself depends on the thing being computed.

3. PROVENANCE. Every claim should carry a citation or be labelled as an author's
   derivation, estimate or reasoning. Find claims that carry neither. Check that cited
   sources actually say what is claimed — retrieve them, do not trust the report's
   characterisation.

4. LOAD-BEARING ASSUMPTIONS. Identify which parameters the conclusion is most sensitive
   to. For each, ask whether it is sourced or assumed. Rank them by how far they move
   the answer. Flag any case where an unsourced parameter moves the result further than
   a sourced one.

5. INTERNAL CONSISTENCY. Read the whole document in one pass. Find claims in one section
   contradicted by another, stale figures left behind by revisions, and cross-references
   that point to the wrong place.

6. SCOPE AND FRAMING. Ask whether the comparison is fair. Are both sides costed on the
   same basis? Are roles priced consistently with how they are described? Is anything
   excluded from one side but not the other?

7. THE CONCLUSION. Ask whether it follows from the evidence, whether it would survive
   plausible alternative parameter choices, and whether a reader acting on it would be
   misled about the confidence it deserves.

OUTPUT

A defect register. For each defect: what it is, where, severity (critical / major /
moderate / minor), and what it does to the conclusion if corrected. Order by severity.

State separately: which parts of the argument you consider sound and why. Do not pad
this section — if little survives, say so.

Do not fix anything. Report only.
````

---

## After the review

Bring the defect register back here. I have written my own known-issues list to
`self-assessment-sealed.md` **before** seeing the review, so the two can be compared:

- Defects the reviewer found that I had not flagged → my blind spots.
- Defects I flagged that the reviewer missed → the review was not adversarial enough,
  and it is worth re-running with a sharper brief.
- Defects both found → high confidence these are real.

Do not open the sealed file until the review is back, and do not show it to the reviewer.
