# Project Standards

Machine-readable standards (`scope: "project"`) for this repository, read by the
`coder` agent during implementation and the `pr-reviewer` agent against every diff.
One JSON file per category: `architecture`, `security`, `data`, `ux-design`,
`testing`, `process`, `documentation`.

## Authoring convention

A standard documents a **timeless rule**, not the current state of the codebase.
Known violations, migrations in flight, and naming drifts are **git issues**, not
standards — never describe them here.

### Make it enforceable

A standard is enforceable when a reviewer (human or agent) can return a yes/no
verdict from the **diff alone** — no runtime, no external state, no judgment.

- **Rule (`title` + `description`):** one binary, imperative invariant —
  "Never X", "Every Y must Z". Avoid soft language ("prefer", "where
  appropriate", "clean", "reasonable", "consider").
- **`acceptance_criteria`:** each item is a diff-checkable predicate —
  *subject + verb + observable condition* visible in the changed code. Avoid
  criteria about reviewer behaviour, runtime outcomes, or whole-codebase state.
- **`anti_patterns`:** concrete code snippets that would fail the check.
- **Scope:** what appears in a PR diff.

If a rule genuinely cannot be made diff-checkable (e.g. "domains model subjects,
not roles"), keep it `adr_overridable: true` and write its criteria as the
closest observable proxy — it must not masquerade as a deterministic gate behind
vague criteria.

### `adr_overridable`

- **`false`** — absolute invariants where no business reason could ever justify a
  violation: secrets, RLS, injection/sanitisation, fail-closed, migration safety,
  PII. Worded with no exception clause.
- **`true`** — firm rules a documented business reason could waive **once**, via a
  repo-local ADR in that repository's own `adrs/adrs.json` whose
  `authorises_exception_to` cites the STD ID. Never inside `standards/`: this
  folder is the universal set, identical in every repository and read verbatim. The standard is still worded as a hard rule; the ADR is the only escape
  hatch, not soft language in the standard.

### Object shape

```json
{
  "id": "STD-<AREA>-NNN",
  "title": "Short imperative title",
  "description": "Precisely what is required or forbidden.",
  "rationale": "Why, citing the source doc/section.",
  "acceptance_criteria": ["Diff-checkable statement.", "..."],
  "anti_patterns": ["A specific violation.", "..."],
  "adr_overridable": true,
  "applies_to": ["coder", "pr-reviewer"],
  "instantiates": "STD-ARCH-001",
  "related": ["STD-ARCH-022", "STD-DATA-012"],
  "source": "Migrated from <file> — <section>"
}
```

`instantiates` and `related` are optional (see *Avoiding duplication* below).

ID prefixes: `STD-ARCH`, `STD-SEC`, `STD-DATA`, `STD-UX`, `STD-TEST`, `STD-PROC`,
`STD-DOC`. Next ID per category = highest existing number + 1. IDs are never
reused or renumbered (gaps are fine).

## Avoiding duplication

Apply DRY to the standards themselves: a principle has exactly **one canonical
home**, and everything else **references it rather than restating it**. Duplicated
*gates* drift and conflict; a reference cannot.

**The rules**

- **One principle, one owner.** A principle is stated as a rule in exactly one
  standard. Elsewhere, cite its ID — never re-encode the rule, rationale, or
  generic acceptance criteria.
- **Org principle ← project instance.** A generic principle lives at `scope: "org"`
  only; the project file holds *only the binding*. A project standard that applies
  an org principle declares `"instantiates": "<org-id>"` and owns only the
  project-specific criteria/anti-patterns. (e.g. `STD-ARCH-010` instantiates
  `STD-ARCH-001`.) The same rule never appears as a full standard at both scopes.
- **Family = umbrella + facets.** When several standards are facets of one concern,
  one is the umbrella and the others own only their distinct facet, linked with
  `related`. (e.g. output-encoding umbrella `STD-SEC-003` with sinks `STD-SEC-008/009/012`;
  the database-naming umbrella `STD-DATA-014` with facets `STD-DATA-008` (surrogate key)
  and `STD-DATA-009` (role-named foreign keys).)
- **Thin parents.** An umbrella/value standard (e.g. "prefer the simplest solution")
  carries no gate of its own — its acceptance is delegated to the concrete facets it
  points to, so it cannot duplicate them.

**Relationship fields**

- `instantiates`: string — the parent (usually org) standard ID this standard is a
  concrete binding of. The instance must not restate the parent's rule.
- `related`: string[] — sibling standards that are facets of the same concern.

**Dedup gate** (run in the migrator's conflict filter and the consistency pass):
flag any two standards whose acceptance criteria substantially overlap **without** an
`instantiates`/`related` link — that is an undeclared duplicate; either link them or
remove one. Promote duplication-prone principles to org scope so project standards
shrink to bindings.

> Note: if the JSON Schema sets `additionalProperties: false`, it must be extended to
> permit `instantiates` and `related` (a platform-team change). Validation degrades to
> JSON-only when the schema is absent.

