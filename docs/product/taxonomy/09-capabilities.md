# Capabilities

These are the business outcomes the vocabulary exists to enable. Each is
named in business language and carries a stable kebab-case id; the capability
is the unit referenced from the roadmap and from delivery.

---

## The capability set

| id | Capability | Outcome |
|---|---|---|
| `classify-intended-architecture` | Classify Intended Architecture | An architecture expressed in CALM carries canonical classifications, so its meaning is comparable across systems and teams |
| `classify-observed-infrastructure` | Classify Observed Infrastructure | Discovered runtime topology is normalised into the same canonical classes as intent, whatever provider it came from |
| `compare-intent-with-reality` | Compare Intent With Reality | The difference between designed and running architecture is reported as typed semantic findings rather than a textual diff |
| `classify-source-code` | Classify Source Code | Common source structures receive their engineering role deterministically from static-analysis evidence, without AI in the loop |
| `target-governance-by-classification` | Target Governance By Classification | A standard or decision states what it applies to by classification, and applicability follows inheritance rather than document search |
| `find-approved-building-blocks` | Find Approved Building Blocks | An approved reusable asset is discoverable from architectural intent, so teams build from sanctioned components |
| `deliver-targeted-context` | Deliver Targeted Context | An agent receives the projection bearing on its work — relevant nodes, implementations, patterns, standards, decisions, and symbols — instead of a repository |
| `govern-vocabulary-change` | Govern Vocabulary Change | The vocabulary evolves under review, staying stable enough to be depended on as a contract |

## How they compose

The capabilities are not independent features; they are stations on one
lifecycle. Product intent becomes CALM intended architecture, which
classifies canonically, which drives implementation planning and
reusable-asset selection, which produces code, which static analysis
classifies canonically in turn — while discovery classifies what actually
runs, and review compares the two.

```text
Product intent
    ↓
CALM intended architecture
    ↓
canonical taxonomy classification
    ↓
implementation planner
    ↓
reusable asset selection
    ↓
coder
    ↓
static analysis
    ↓
deterministic code classification
    ↓
discovered CMDB
    ↓
canonical observed classification
    ↓
reviewer
    ↓
intended-versus-observed comparison
```

Standards and decisions are selected through the same identifiers at every
step, which is why `target-governance-by-classification` has no single place
in the sequence — it applies throughout.

## Roadmap alignment

The vocabulary and its enforcement are in place: `taxonomy/` holds the
canonical domains, registries, mappings, rules, schemas, and examples, and
the `validate-taxonomy` workflow gates every change to them.

Each capability above depends on a consumer that reads the vocabulary. Those
consumers — the resolver, deterministic code classification, CALM and CMDB
alignment, governance integration, and context projection — are tracked as a
single decomposable gap in
[#339](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/339),
which is the roadmap entry for this product area. Capability Specifications
and their BDD scenarios are tracked there.

Whether the Taxonomy is distributed to consuming repositories the way
`standards/` is remains an open decision, recorded in
[#329](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/329).
