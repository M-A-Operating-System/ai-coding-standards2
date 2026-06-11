# Standards

Machine-readable standards are the enforceable rules that the `coder` and
`pr-reviewer` agents apply to every diff. They are declared in JSON, validated
against a published schema, and referenced by stable IDs in code comments,
commit messages, and PR findings.

---

## Two-tier scope

Standards exist at two scopes. Scope is declared explicitly in the JSON file
header (`"scope": "org"` or `"scope": "project"`).

| Scope | Canonical source | On-disk in a consuming repo | Who owns it | Purpose |
|-------|-----------------|------------------------------|-------------|---------|
| **org** | `ai-coding-standards2/standards/*.json` (submodule) | `{project-root}/standards/` (copied by `get_started.py`; re-seeded daily by `sync-claude.yml`) | Platform / architecture team | Baseline rules that apply across every project that installs AI Agile |
| **project** | `{project-root}/standards/*.json` | `{project-root}/standards/` (same directory) | Project tech lead | Rules specific to this project's stack, domain, or team conventions — always additive |

After `get_started.py` runs, both tiers are co-located in the consuming repo's
`standards/` directory. The `"scope"` field in each file's JSON header is the
authoritative indicator of which tier a file belongs to.

**Rules governing the two tiers:**

- Org standard files are re-seeded by the daily `sync-claude.yml` sync. Do not
  modify them directly in the consuming repo — changes will be overwritten. Add
  project-specific files instead.
- Project standards extend the org set. They may not redeclare an org STD ID
  at a different enforcement level.
- A project that needs to waive an org standard for specific code writes a
  **project ADR** citing the org STD ID. This is the only mechanism for
  per-project exceptions.
- Agents load all standards from `${AI_AGILE_ROOT}/standards/` in one pass.
  Both tiers are enforced — a violation against either raises a finding.

---

## Categories

Each standards file covers exactly one category. The category is declared in
the file header and is part of the STD ID.

| Category | ID prefix | File | `adr_overridable` tendency | What it governs |
|----------|-----------|------|---------------------------|-----------------|
| **Architecture** | `STD-ARCH` | `architecture.json` | true | Code structure, reuse, abstraction, scope creep, function size, deferred defects |
| **Security** | `STD-SEC` | `security.json` | false (most rules) | Injection prevention, secret handling, dependency pinning, auth patterns, input validation |
| **Testing** | `STD-TEST` | `testing.json` | true | Test coverage floors, isolation, naming, forbidden mocking patterns, test-data hygiene |
| **Process** | `STD-PROC` | `process.json` | true | PR scope, commit hygiene, branching conventions, issue lifecycle, documentation requirements |
| **Data** | `STD-DATA` | `data.json` | mixed | Migration safety (false), naming conventions (true), PII handling (false), backward compatibility |
| **UX Design** | `STD-UX` | `ux-design.json` | true | Accessibility, interaction patterns, visual hierarchy, component reuse, responsive behaviour |
| **Documentation** | `STD-DOC` | `documentation.json` | true | Required doc sections, staleness rules, generated vs hand-authored, agent-readable format |

> **Note on `adr_overridable: false`.** Security and data-safety standards that
> are marked non-overridable represent absolute rules — there is no legitimate
> business justification for committing plaintext secrets or disabling RLS, for
> example. These standards always block regardless of any ADR.

---

## Standard object fields

Every entry in a `standards` array must conform to this shape:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | `STD-{CATEGORY}-{NNN}` — stable, never reused. Org standards use `STD-`. |
| `title` | string | yes | Short imperative phrase, ≤80 chars. |
| `description` | string | yes | One or two sentences stating precisely what is required or forbidden. |
| `rationale` | string | yes | One or two sentences explaining why. May cite a source file or section. |
| `acceptance_criteria` | string[] | yes | Concrete, diff-checkable statements. Each starts with a subject and verb. |
| `anti_patterns` | string[] | yes | Specific examples of what violates this rule. |
| `adr_overridable` | boolean | yes | `true` — an ADR can waive a violation for specific code. `false` — always blocks; no exception is possible. |
| `applies_to` | string[] | yes | Which pipeline agents enforce this standard: `coder`, `pr-reviewer`, `issue-classifier`, `prd-writer`. |
| `source` | string | no | Migration provenance, e.g. `"Migrated from CLAUDE.md §Principles"`. |

---

## File header fields

Every standards file (`StandardsFile`) carries:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `$schema` | string | no | Path to `standards.schema.json`. |
| `version` | string | yes | Schema version, e.g. `"1.0"`. |
| `scope` | string | yes | `"org"` or `"project"`. Must match the file's location. |
| `category` | string | yes | One of the seven category names above. |
| `description` | string | no | Human-readable summary of what this file covers. |
| `standards` | Standard[] | yes | The enforceable rules. |

---

## ADR scope

ADRs follow the same two-tier pattern.

| Scope | Location | Can waive |
|-------|----------|-----------|
| **org** | `ai-coding-standards2/standards/adrs.json` | Org `adr_overridable: true` standards only |
| **project** | `{project-root}/standards/adrs.json` | Org or project `adr_overridable: true` standards |

Every ADR entry requires:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | `ADR-NNN` — zero-padded, sequential within the file's scope. |
| `title` | string | Short description of the decision. |
| `authorises_exception_to` | string[] | The STD IDs this ADR waives (e.g. `["STD-ARCH-002"]`). |
| `rationale` | string | Why this exception is justified. |
| `approved_by` | string | Optional. Name or GitHub handle of the approver. |
| `approved_at` | string | Optional. ISO 8601 date of approval. |

---

## Enforcement model

The pr-reviewer raises a finding for every standard violated in a diff. The
finding's outcome depends solely on `adr_overridable` and whether a covering
ADR exists:

| `adr_overridable` | Covering ADR exists? | Outcome |
|-------------------|----------------------|---------|
| `false` | n/a | **Always blocks** — REQUEST_CHANGES regardless of ADR |
| `true` | No | **Blocks** — REQUEST_CHANGES |
| `true` | Yes | **Informational** — noted in findings, does not block APPROVE |

The pr-reviewer verdict rule: **APPROVE if and only if zero unwaived findings.**

---

## Agent load paths

Agents load all standards from a single directory at startup.

```bash
# All standards — org copies and project additions are co-located.
# AI_AGILE_ROOT = consuming repo root (set by the orchestrator as $GITHUB_WORKSPACE).
find "${AI_AGILE_ROOT}/standards" -name "*.json" ! -name "adrs.json" | sort

# ADRs (project-owned; org ADR entries are in adrs.json at scope: "org")
cat "${AI_AGILE_ROOT}/standards/adrs.json" 2>/dev/null || true
```

`AI_AGILE_ROOT` is the consuming repo root — where `standards/` lives after
`get_started.py` installation. In standalone dev mode (running inside
ai-coding-standards2 directly), it equals the submodule root.

`AI_AGILE_CONTEXT` (also set by the orchestrator) is the absolute path to
`AGENTS.md` inside the submodule. Agents that need to locate the schema
validator can derive the submodule root from it:
```bash
SUBMODULE_ROOT="$(dirname "$(dirname "$AI_AGILE_CONTEXT")")"
```

---

## Adding a new standard

Use the `09_gap_assessment/standards-migrator` agent. It scans existing
knowledge files (CLAUDE.md, `*_knowledge*`, markdown guides) in the consuming
repo and proposes each rule as a structured standard for human approval before
writing. Each proposed standard is presented one at a time — the human decides
which rules become enforceable.

New org-wide standards are PRd against `ai-coding-standards2`. New
project-specific standards are PRd against the consuming project repo.

---

## Evolving existing standards

Standards are evolved by the `07_evaluate/standards-evolver` agent (roadmap
item — not yet active in MVP). When active, it runs after each retrospective,
identifies recurring violations, and drafts proposals as GitHub issues for
Standards Owner approval. Approved proposals are merged as PRs against the
relevant standards file.

A change to an existing standard's `acceptance_criteria` or `adr_overridable`
flag requires Standards Owner approval before merge.
