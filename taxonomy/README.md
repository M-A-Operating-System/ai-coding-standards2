# Taxonomy

Reference analysis about how AI-first engineering work is organized: what the
roles are, what they cost, and what the evidence for each claim actually is.

This folder is a sibling of `standards/`, and the two are deliberately
different in kind. A standard is an enforceable rule, written as a binary
invariant and read by the `coder` and `pr-reviewer` agents against every diff.
Nothing here is enforceable and no agent reads it as a gate. This is the
reasoning an informed human consults when deciding what the rules should be,
or how the work should be staffed -- material that argues a position from
evidence rather than one that polices a diff.

## Contents

`ai-first-engineering-analysis/`: what an equivalent engineering team looks
like when agents author and humans supervise, with output and quality held
constant. A conventional team of six is replaced by roughly three people, all
supervisors, at about 34% lower cost -- not the two-person team the AI-first
argument usually assumes. The result turns on one parameter, the effort to
supervise a unit of agent-authored work relative to a unit of human-authored
work, and the team size is simply that number. The bundle carries a runnable
model that computes every figure in the report, a review pack, and an archive
of audits against a superseded earlier draft.

The bundle is explicit that the direction of its result is robust and the
magnitude is not: the sensitivity band runs from +2% to -56%, and the most
influential parameter is an assumption with no source. Read section 5 of the
report before citing any figure from it.

## Scope of this folder

The charter is seeded by its first entry rather than defined ahead of it. What
is settled: this holds analysis, it is not enforceable, and it is not a home
for rules that belong in `standards/`. What is not yet settled: whether the
folder takes only engineering-organization analysis or reference classification
material more broadly. That question is worth answering when a second entry
arrives, not before -- guessing at it now would be inventing structure for
content that does not exist.

## What an entry looks like

One folder per analysis, holding the whole bundle: the argument, whatever is
needed to check it, and the record of how it was reviewed. A reader should be
able to run the numbers and attack the case without leaving the folder.

Every entry carries a `README.md` stating what the work is, its headline
finding, how confident it is, and the order to read it in.

Claims are marked for provenance, so a sourced fact can be told apart from an
inference or an estimate. Each entry states its own convention; the one in
`ai-first-engineering-analysis/` is set out in Appendix B of its report.

Superseded material is retained rather than deleted, under `archive/`, with a
note saying what it superseded and what it must not be read as. It is kept for
provenance, not for reference.
