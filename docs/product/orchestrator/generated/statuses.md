<!-- GENERATED FILE -- DO NOT EDIT.
     Source: pipeline/statuses.json
     Generator: pipeline/generators/generate_docs.py
     Regenerate: python3 pipeline/generators/generate_docs.py -->

# Status Model

Canonical status definitions for all pipeline agents. Every agent uses exactly these statuses. Labels are applied in the form {agent-name}:{status}. This file is the single source of truth -- colours, semantics, and behaviour rules are defined here and referenced by all agents, the orchestrator, and the setup scripts.

Labels take the form `{agent-name}:{status}`.

## Statuses

| Status | Meaning | Terminal | Blocks | Needs a human | Cleared by |
|---|---|---|---|---|---|
| `:requested` | A human (or upstream automation) has explicitly requested this agent to run on this item. The orchestrator will pick it up on its next tick, apply :wip, remove :requested, and invoke the agent. Useful as a manual ad-hoc trigger for agents that are not in the standard dependency chain. | no | no | no | orchestrator |
| `:wip` | Agent is actively running. Applied by the orchestrator at the moment the agent is invoked. Removed and replaced with the outcome status when the agent finishes. | no | yes | no | orchestrator |
| `:complete` | Agent completed its work successfully. All automated checks passed. If the agent has a human_gate_label configured, the pipeline still waits for that gate before the next agent fires. | yes | no | no | never |
| `:review` | Agent has completed its automated work and is explicitly requesting formal human review and approval before the pipeline advances. Used when the agent produces an artefact (PRD, design doc, test spec, build plan) that must be read and signed off by a person. Distinct from human_gate_label in pipeline.json -- this is raised by the agent itself, not pre-configured. | no | yes | yes | orchestrator (on gate-label application) or human (removes label to reject) |
| `:blocked` | Agent cannot proceed without human intervention. Applied when the agent encounters something it cannot resolve autonomously: ambiguous or contradictory requirements, missing data, a hard dependency that is unresolved, or a decision that exceeds its authority. The agent must post a comment explaining exactly what is blocking it and what information or decision is needed. | no | yes | yes | human |
| `:failed` | Agent exited with an error -- a technical failure, not a business decision. The agent output or CI logs should contain the error detail. This is distinct from blocked: failed means the agent crashed or returned a non-zero exit code, not that it encountered an unresolvable decision. | yes | yes | yes | human |
| `:skipped` | Agent was intentionally bypassed by a human. Treated as equivalent to complete for the purposes of dependency resolution -- downstream agents will proceed. Use when the agent's work is not applicable to this ticket or has been done manually. | yes | no | no | never |
| `:approved` | A human has reviewed and approved the agent's output at a configured human gate. Applied by a human to advance the pipeline past the gate. Only meaningful on agents that declare human_gate_label in pipeline.json. | yes | no | no | never |

## Orchestrator behaviour

| Status | Set by | Behaviour |
|---|---|---|
| `:requested` | human | Treat as an eligible trigger regardless of the agent's configured trigger conditions. Apply :wip and invoke the agent. |
| `:wip` | orchestrator | Skip -- another process is already handling this agent on this item. Do not trigger again. |
| `:complete` | orchestrator | Treat as a satisfied dependency for downstream agents. |
| `:review` | orchestrator | Halt pipeline for this item. Do not trigger any further agents until the label is removed by a human. |
| `:blocked` | orchestrator | Halt pipeline for this item. Post a comment tagging the owner. Do not trigger any further agents until the label is removed by a human. |
| `:failed` | orchestrator | Halt pipeline for this item. Do not retry automatically -- require a human to remove the label. |
| `:skipped` | human | Treat as a satisfied dependency. Do not trigger this agent. |
| `:approved` | human | Treat as a satisfied human gate. Allow downstream agents whose trigger depends on this label to proceed. |

## Standalone labels

| Label | Meaning |
|---|---|
| `human-review-pending` | The orchestrator applies this label when the pr-reviewer emits :complete but unresolved human REQUEST_CHANGES reviews exist on the PR. It signals the coder agent for a free re-invoke (Mode B without advancing the review-cycle counter). Removed once the pr-reviewer APPROVEs a second time after the coder addresses the human feedback. Guards against repeated free re-invokes (once-only). |
| `classification: security` | Applied by issue-classifier when the issue body describes a concrete security vulnerability (injection, auth bypass, credential exposure, SSRF, path traversal, insecure deserialization, missing access control, or known-vulnerable dependency with exploit path). Security items are scheduled by the orchestrator before all other work items -- the highest priority tier. Expedited scheduling does not skip review gates: pr-reviewer and human gates still run. |

## Priority ordering

Work items carrying these labels are evaluated first, in order:

1. `classification: security`
2. `priority`
