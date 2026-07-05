# Standards

Machine-readable standards are the enforceable rules that the `coder` and
`pr-reviewer` agents apply to every diff. They are declared in JSON, validated
against a published schema, and referenced by stable IDs in code comments,
commit messages, and PR findings.

---

## Scope

Standards are **defined centrally**: the framework (the ai-coding-standards2
submodule) owns them, and a consuming repo inherits them via the whole-folder
`standards/` symlink.

| Scope | Canonical source | On-disk in a consuming repo | Who owns it | Purpose |
|-------|-----------------|------------------------------|-------------|---------|
| **org** | `ai-coding-standards2/standards/*.json` (submodule) | `{project-root}/standards` — a whole-folder symlink into the submodule (copied on Windows), kept live by `sync-claude.yml` | Platform / architecture team | Baseline rules that apply across every project that installs AI Agile |

A consuming repo does **not** add its own standards files. `standards/` is a
symlink into the submodule, so there is nowhere project-local to put one, and
the sync would not preserve it. The single per-project mechanism is a **project
ADR** (see below), which records an exception to a centrally-defined standard.

> The schema's `scope` field still permits `"project"`, and older installs may
> carry project standards files. Retiring the project-standards tier from the
> schema and validator — and cleaning the central `standards/` contents — is
> tracked in #216. Under the whole-folder symlink model, **only org standards
> are supported**; project-specific needs are expressed as project ADRs.

**Rules:**

- Org standard files are owned by the framework and live in the submodule. The
  symlink points at the submodule, so there is nothing local to edit — change a
  standard by opening a PR against ai-coding-standards2.
- A project that needs to waive an org standard for specific code writes a
  **project ADR** citing the org STD ID. This is the only mechanism for
  per-project exceptions.
- Agents load all standards from `${AI_AGILE_ROOT}/standards/` in one pass; a
  violation of any of them raises a finding.

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
| `title` | string | yes | Short imperative phrase, ≤100 chars. |
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

ADRs exist at two scopes: org ADRs live in the submodule, project ADRs in the
consuming repo's local `adrs/` folder.

| Scope | Location | Can waive |
|-------|----------|-----------|
| **org** | `ai-coding-standards2/standards/adrs.json` | Org `adr_overridable: true` standards |
| **project** | `{project-root}/adrs/adrs.json` (local folder, outside the symlinked `standards/`) | Org `adr_overridable: true` standards (there are no project standards to waive under the whole-folder model) |

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
# Standards live in the symlinked standards/ folder (framework-owned).
# AI_AGILE_ROOT = consuming repo root (set by the orchestrator as $GITHUB_WORKSPACE).
find "${AI_AGILE_ROOT}/standards" -name "*.json" ! -name "adrs.json" | sort

# Project ADRs live in the local adrs/ folder, OUTSIDE the symlinked standards/.
cat "${AI_AGILE_ROOT}/adrs/adrs.json" 2>/dev/null || true
```

`AI_AGILE_ROOT` is the consuming repo root — where the `standards/` symlink and
the local `adrs/` folder live after `get_started.py` installation. In standalone
dev mode (running inside ai-coding-standards2 directly), it equals the submodule
root.

`AI_AGILE_CONTEXT` (also set by the orchestrator) is the absolute path to
`AGENTS.md` inside the submodule. Agents that need to locate the schema
validator can derive the submodule root from it:
```bash
SUBMODULE_ROOT="$(dirname "$(dirname "$AI_AGILE_CONTEXT")")"
```

---

## Adding a new standard

Use the `00_ondemand/standards-migrator` agent. It scans existing
knowledge files (CLAUDE.md, `*_knowledge*`, markdown guides) in the consuming
repo and proposes each rule as a structured standard for human approval before
writing. Each proposed standard is presented one at a time — the human decides
which rules become enforceable.

New org-wide standards are PRd against `ai-coding-standards2`. New
project-specific standards are PRd against the consuming project repo.

---

## Evolving existing standards

Standards are evolved by the `04_evaluate/standards-evolver` agent.
It runs after each retrospective,
identifies recurring violations, and drafts proposals as GitHub issues for
Standards Owner approval. Approved proposals are merged as PRs against the
relevant standards file.

A change to an existing standard's `acceptance_criteria` or `adr_overridable`
flag requires Standards Owner approval before merge.
