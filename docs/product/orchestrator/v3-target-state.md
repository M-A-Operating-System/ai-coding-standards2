# V3 Target-State Runtime Design

## Core design invariants

These invariants are mandatory for V3.

1. **Reuse the existing agent definitions.** V3 executes the same agent definitions already held in the repository. Runtime adapters change invocation mechanics only; they do not create a second behavioral source of truth or fork agent instructions by runtime.

2. **Reuse the existing pipeline process definitions.** V3 uses the same pipeline task definitions, dependencies, ordering, sequencing, gates, retries, review loops, terminal-state semantics, session semantics, and scripted steps already defined in the repository. Interactive and headless modes resolve the same next eligible step from the same process definition.

3. **Reuse the existing entitlement model.** V3 preserves the current canonical entitlement model for tool and action constraints. Runtime adapters translate resolved entitlements into Claude Code or OpenCode enforcement mechanisms without redefining policy.

4. **Only the execution wrapper changes.** V3 does not redesign the AI Agile process. Pipeline state, agent behavior, lifecycle rules, standards and ADR selection, deterministic helpers, repository conventions, session behavior, scripted steps, and workflow semantics remain common. V3 introduces execution adapters, isolated headless sandboxes, and execution placement without changing product behavior.

5. **Metrics logging and analysis continue seamlessly.** Existing metrics collection, logging, aggregation, reporting, and analysis continue across interactive Claude Code and headless OpenCode execution. Historical continuity is preserved and existing measures remain comparable across V2 and V3.

These invariants take precedence over runtime-specific convenience.

## V2 and V3 responsibility model

| Responsibility | V2 | V3 Interactive | V3 Headless |
|---|---|---|---|
| User interaction | Claude Code UI | Claude Code UI | GitHub event, scheduled trigger, or unattended invocation |
| Pipeline definition | Existing `pipeline.json` | Same `pipeline.json` | Same `pipeline.json` |
| Process orchestration | Existing pipeline orchestrator | Same orchestrator | Same orchestrator |
| Step eligibility and dependencies | Orchestrator | Same orchestrator | Same orchestrator |
| Pipeline concurrency rules | Orchestrator | Same orchestrator | Same orchestrator |
| Human gates and review loops | Orchestrator / GitHub state | Same behavior | Same behavior; headless execution stops at gates |
| Agent definitions | Existing repository agent files | Same agent files | Same agent files |
| Deterministic script steps | Existing script execution path | Same script behavior | Same script behavior in the assigned execution environment |
| Agent runtime | Claude Code | Claude Code | OpenCode |
| Model invocation | Claude Code -> Claude | Claude Code -> Claude | OpenCode -> Anthropic API, Azure AI Foundry, or Trustbolt |
| Model selection | Provider-specific model name in current pipeline configuration | Provider-neutral model alias resolved to Claude Code model | Same provider-neutral alias resolved to OpenCode provider/model mapping |
| Model mapping | Not separate | Model registry maps alias to Claude Code model | Model registry maps alias to Anthropic, Azure AI Foundry, or Trustbolt model/deployment |
| Entitlement source | Existing groups and step configuration in `pipeline.json` | Same source | Same source |
| Entitlement enforcement | Claude Code tool permissions | Claude Code tool permissions | Resolved rules rendered into OpenCode permissions |
| Session semantics | Existing `per_issue`, `global`, and resume behavior | Same semantics | Same logical semantics mapped into fresh OpenCode processes |
| Durable workflow state | GitHub / repository / pipeline state | Same | Same |
| Execution compute | User/Claude Code environment | User/Claude Code environment | Azure IaaS execution hosts |
| Workload isolation | Existing interactive execution boundary | Existing interactive execution boundary | Ephemeral isolated sandbox per execution |
| Execution placement | Not required as a separate product concern | Not required | Placement layer chooses Azure IaaS host based on capacity |
| Parallel agent execution | Controlled by orchestrator | Controlled by orchestrator | Controlled by orchestrator; placement runs eligible work concurrently |
| Host capacity management | Not applicable | Not applicable | Execution placement layer |
| Repository working copy | Existing Claude Code working copy/worktree behavior | Same behavior | Independent checkout inside each sandbox |
| Credentials | Existing Claude Code environment | Same | Injected per sandbox and scoped to execution |
| Metrics | Existing metrics pipeline | Same metrics pipeline | Same metrics pipeline plus runtime/host/provider attribution |
| Failure/retry policy | Existing orchestrator | Same orchestrator | Same orchestrator; runtime/host failures normalize into execution results |

The defining V3 principle is that **process semantics remain common while execution mechanics differ by mode**.

## Target architecture

V3 separates four concerns:

- **process control** — the pipeline orchestrator determines what work is eligible and whether work may run concurrently;
- **execution placement** — the headless execution layer determines where each eligible execution runs based on available Azure IaaS capacity;
- **execution isolation** — each headless execution runs inside its own ephemeral sandbox;
- **model selection** — `pipeline.json` references a provider-neutral logical model alias, resolved through a separate model registry;
- **model inference** — OpenCode invokes the provider/model resolved by that registry through Anthropic direct, Azure AI Foundry, or Trustbolt.

```text
                         GitHub repository
                               |
                         pipeline.json
                               |
                               v
                     Pipeline orchestrator
                     /                  \
                    /                    \
             Interactive              Headless
                 |                        |
                 v                        v
           Claude Code          Execution placement layer
           runtime/UI                    |
                 |                        v
                 |                  Azure IaaS
                 |               VM execution host(s)
                 |                        |
                 |             +----------+----------+
                 |             |          |          |
                 |             v          v          v
                 |         sandbox A  sandbox B  sandbox C
                 |             |          |          |
                 |             v          v          v
                 |          OpenCode   OpenCode   OpenCode
                 |             |          |          |
                 v             +----------+----------+
           Claude model                   |
                                  +-----------+-----------+
                                  |           |           |
                                  v           v           v
                            Anthropic API  Azure AI    Trustbolt
                                           Foundry
```

The orchestrator remains authoritative for process semantics. The placement layer determines execution location only. The sandbox provides isolation. OpenCode provides the headless agent loop. Model providers provide inference only.

## Pipeline step execution

The pipeline contains both model-driven agent steps and deterministic script steps. V3 preserves both as first-class pipeline step types.

```text
resolved pipeline step
        |
        +--> agent step
        |       |
        |       +--> interactive --> Claude Code
        |       |
        |       `--> headless ----> isolated sandbox --> OpenCode
        |
        `--> script step
                |
                `--> assigned execution environment --> deterministic script
```

Agent steps invoke a model runtime. Script steps retain their deterministic behavior and do not become OpenCode agents.

## Interactive execution

Interactive execution runs natively inside Claude Code.

```text
Human operator
      |
      v
Claude Code UI
      |
      v
Pipeline orchestrator
      |
      v
Resolved pipeline step
      |
      +--> agent step --> Claude Code runtime --> Claude model
      |
      `--> script step --> existing deterministic execution path
```

OpenCode is not inserted into the interactive path.

## Headless execution

Headless execution uses Azure IaaS for compute and OpenCode for model-driven agent execution.

GitHub provides durable repository/workflow state and lightweight triggering. Long-running execution runs on Azure IaaS rather than consuming GitHub-hosted Actions minutes for the duration of the workload.

```text
GitHub event / workflow control
              |
              v
short GitHub-hosted bootstrap
              |
              v
ensure Azure IaaS capacity
              |
              v
Pipeline orchestrator
              |
              v
eligible pipeline executions
              |
              v
Execution placement layer
              |
        +-----+------+
        |            |
        v            v
 Azure VM A      Azure VM B
   |   |            |
   v   v            v
  SB1 SB2          SB3
   |   |            |
   v   v            v
  OC  OC           OC
```

Each `SB` is an ephemeral isolated execution sandbox. Each `OC` is an OpenCode execution for one agent step.

Azure VM hosts are reusable IaaS capacity and are normally deallocated when no executable work remains. The placement layer may place multiple sandboxes on one VM when sufficient capacity exists or start/use additional VMs when needed.

## Concurrency

The existing orchestrator remains the sole authority for whether work is safe to execute concurrently.

It continues to enforce:

- task dependencies;
- conflicting code/work ownership;
- mutually exclusive management operations;
- review and lifecycle sequencing;
- human gates;
- other existing pipeline concurrency restrictions.

Once the orchestrator declares multiple executions eligible concurrently, the placement layer may run them in parallel subject to Azure IaaS capacity.

Host capacity constrains placement only; it does not change pipeline semantics.

## Execution placement

The execution placement layer determines where each eligible headless execution runs.

It:

- discovers available Azure IaaS execution hosts;
- evaluates host CPU, memory, storage, and configured execution limits;
- places new sandboxes on hosts with capacity;
- starts additional Azure VM capacity when no suitable host is available;
- prevents new placement on hosts that are draining or shutting down;
- deallocates hosts when there are no active executions, no queued executable work, and the configured idle threshold has been reached.

The placement layer does not determine whether pipeline work may run concurrently.

## Azure IaaS execution infrastructure

Azure IaaS provides the headless execution infrastructure.

An execution host supplies:

- operating system;
- container runtime;
- CPU and memory capacity;
- local storage;
- language runtimes;
- compilers and build tools;
- test frameworks;
- linters and formatters;
- Git tooling;
- GitHub runner/control integration;
- OpenCode runtime image or installation;
- host monitoring and lifecycle control.

The Azure IaaS VM is a capacity and placement boundary, not the isolation boundary between agent executions.

## Ephemeral execution sandboxes

Every concurrent headless execution runs inside its own ephemeral sandbox.

Each sandbox has its own:

- process namespace;
- writable filesystem;
- repository checkout;
- working directory;
- `HOME`;
- temporary and scratch storage;
- environment variables;
- runtime state;
- credentials;
- OpenCode process;
- CPU and memory limits.

A sandbox cannot inspect or modify another sandbox's files, processes, environment, credentials, repository, or runtime state. Agent sandboxes are unprivileged and do not receive access to the host container-runtime control socket or other privileged host interfaces.

The sandbox is destroyed after execution completes or fails.

## Repository and persistence model

Sandbox-local state is disposable.

Durable state leaves the sandbox only through existing sanctioned mechanisms:

```text
code state       -> Git commits / pushed branches
workflow state   -> GitHub issues / PRs / labels / comments / pipeline state
design artifacts -> repository commits or existing artifact mechanisms
metrics          -> existing metrics log and analysis path
```

Retries and re-entry start in a clean sandbox and reconstruct work from durable repository and pipeline state.

## Session semantics

V3 preserves the existing session semantics defined in `pipeline.json`, including `per_issue`, `global`, resume behavior, session identity, and retry-specific session behavior.

A fresh OpenCode process does not imply a new logical pipeline session.

Where resume is enabled, the runtime adapter makes the prior logical session context available to the new isolated OpenCode execution. Where resume is disabled, the new execution receives no prior conversational context.

Session state remains non-authoritative. Every invocation re-derives its current situation from durable artifacts.

Persisted session material is scoped to the logical session and exposed only to the sandbox executing that session.

## Responsibility boundaries

### Pipeline orchestrator

The orchestrator owns:

- pipeline sequence;
- task dependencies;
- step eligibility;
- concurrency eligibility;
- issue and PR state;
- human approval gates;
- retries and review loops;
- lifecycle transitions;
- deterministic pre/post steps;
- script-step semantics;
- existing context resolution;
- entitlement resolution;
- session identity and resume policy;
- process-level metrics.

It does not own model-provider inference logic or Azure IaaS host placement.

### Execution placement layer

The placement layer owns infrastructure placement and capacity only.

It does not own pipeline dependencies, work-conflict rules, human gates, retry policy, agent behavior, or entitlements.

### Runtime adapters

Runtime adapters execute already-resolved model-driven agent steps.

```text
execute_agent(
    agent_definition,
    resolved_execution_input,
    resolved_entitlements,
    session,
    model_selection,
    execution_mode
) -> execution_result
```

V3 provides:

- Claude Code interactive execution;
- OpenCode headless execution.

## Execution input

V3 preserves the existing ownership of execution-context resolution.

Whatever the current pipeline resolves before invoking Claude Code remains resolved before invoking either runtime.

The interactive and headless runtimes receive semantically equivalent resolved inputs, even where runtime-specific packaging differs.

OpenCode does not independently infer pipeline state, choose alternate standards, reconstruct issue intent, or create a second process model.

## Entitlements

The existing group-based entitlement model in `pipeline.json` remains canonical.

For each resolved pipeline step, the existing entitlement resolution process:

1. resolves defaults and step-specific entitlements;
2. expands referenced allow and deny groups;
3. produces the effective per-step allow/deny rules;
4. passes those resolved rules to the selected runtime renderer.

```text
pipeline.json
  |- defaults
  |- step entitlements
  |- allow groups
  `- deny groups
          |
          v
existing entitlement resolver
          |
          v
effective per-step allow/deny rules
          |
     +----+----+
     |         |
     v         v
Claude Code  OpenCode
renderer     renderer
```

OpenCode receives resolved rules, not entitlement group names. Runtime-specific translation may change syntax but may not change policy meaning. V3 does not introduce a second canonical entitlement model.

## Headless security model

Security controls operate at multiple layers:

```text
pipeline entitlements
        +
sandbox isolation
        +
per-sandbox credentials
        +
Azure IaaS host controls
        +
repository protections
```

Credentials are injected per sandbox and scoped to the execution. Sandboxes do not inherit broad shared host credentials or another execution's credentials.

## Provider-neutral model selection

Pipeline definitions must not contain provider-specific model or deployment names.

Each model-driven pipeline step references a provider-neutral logical model alias:

```json
{
  "agent": "03_execute/coder",
  "model": "coding-primary"
}
```

A separate model registry owns the mapping from that alias to the concrete runtime, provider, and model/deployment used in each execution mode.

The canonical registry is held outside `pipeline.json`, for example:

```text
config/model-providers.json
```

Conceptually:

```text
pipeline.json
  model = coding-primary
          |
          v
model-providers.json
          |
     +----+------------------+
     |                       |
     v                       v
interactive               headless
     |                       |
     v                       v
Claude Code               OpenCode
     |                 /       |        \
     v                v        v         v
Claude model      Anthropic   Azure     Trustbolt
                    direct    AI Foundry
```

The registry allows provider/model assignments to change without changing pipeline process definitions or agent definitions.

Example:

```json
{
  "models": {
    "coding-primary": {
      "interactive": {
        "runtime": "claude-code",
        "model": "claude-sonnet-4-6"
      },
      "headless": {
        "runtime": "opencode",
        "provider": "azure-ai-foundry",
        "model": "kimi-k2",
        "deployment": "kimi-k2-prod"
      }
    },
    "review-fast": {
      "interactive": {
        "runtime": "claude-code",
        "model": "claude-haiku-4-5"
      },
      "headless": {
        "runtime": "opencode",
        "provider": "anthropic",
        "model": "claude-haiku-4-5"
      }
    }
  }
}
```

The logical alias is the pipeline contract. Provider names, API endpoints, deployment names, and provider-specific credentials remain runtime configuration.

## Model inference

Model inference is separate from Azure IaaS.

### Interactive

```text
provider-neutral model alias
          |
          v
model registry
          |
          v
Claude Code
          |
          v
Claude model through the interactive Claude Code account
```

### Headless

```text
provider-neutral model alias
          |
          v
model registry
          |
          v
OpenCode
   /          |          \
  v           v           v
Anthropic   Azure AI    Trustbolt
 direct     Foundry
  |           |           |
  v           v           v
Claude      Kimi /      routed
models      other       models
            models
```

Claude Code is not nested beneath OpenCode.

OpenCode is the headless model-access abstraction. It invokes the provider/model resolved by the registry.

## Model provider responsibilities

### Anthropic direct

Anthropic direct is a headless model-provider path used by OpenCode with provider credentials such as an Anthropic API key.

It provides direct access to configured Claude models.

### Azure AI Foundry

Azure AI Foundry is a model inference provider, not the execution host.

It provides model deployments, inference endpoints, model credentials, and provider/model usage telemetry. Its deployed model portfolio may include Kimi and other supported model families.

It does not own pipeline sequencing, OpenCode execution, repository state, sandbox lifecycle, Azure IaaS placement, GitHub workflow state, or entitlement policy.

### Trustbolt

Trustbolt is a parallel model-access provider behind OpenCode.

The same provider-neutral logical model aliases may be mapped to Trustbolt rather than Azure AI Foundry or Anthropic direct without changing `pipeline.json` or agent definitions.

Trustbolt may route to underlying model providers while preserving the same OpenCode-facing provider boundary.

## Human approval gates

Existing human gates remain authoritative.

When headless execution reaches a human approval gate, pipeline state is persisted, no approval is inferred or bypassed, the current execution ends, and a later invocation resumes from durable state after approval.

## Failure and recovery

Runtime and infrastructure failures are returned to the orchestrator as normalized execution results.

This includes OpenCode process failure, model-provider errors, Azure IaaS host loss, sandbox failure, runner disconnect, tool permission failure, budget exhaustion, build failure, and test failure.

The existing orchestrator owns retry, re-entry, terminal-state handling, and escalation.

A failed sandbox is discarded. Retries start in a clean sandbox and reconstruct from durable state.

## Metrics continuity

The existing metrics pipeline remains canonical.

V3 adds attribution dimensions:

```text
execution_mode     = interactive | headless
execution_runtime  = claude-code | opencode
execution_host     = interactive | azure-iaas
model_provider     = claude-code | anthropic | azure-ai-foundry | trustbolt
model              = concrete model/deployment identifier
```

Existing metrics retain their definitions and historical comparability.

## Target-state acceptance criteria

V3 is complete when:

- existing pipeline definitions execute without interactive/headless forks;
- existing agent definitions execute unchanged through Claude Code interactively and OpenCode headlessly;
- deterministic script steps retain their existing semantics;
- the orchestrator retains all existing dependency and concurrency controls;
- multiple eligible headless executions may run concurrently;
- each concurrent headless execution runs in an isolated ephemeral sandbox;
- one sandbox cannot affect another sandbox;
- execution placement can use multiple sandboxes per Azure IaaS VM and multiple Azure IaaS VMs;
- Azure IaaS capacity management does not change pipeline semantics;
- session scope and resume semantics remain compatible with the existing pipeline;
- canonical entitlements are resolved once and rendered into the selected runtime;
- Azure IaaS is used only for execution infrastructure;
- pipeline model references are provider-neutral logical aliases;
- the model registry resolves each alias to the concrete runtime/provider/model mapping;
- Azure AI Foundry is used only as a model inference provider;
- Trustbolt is a parallel headless model-access provider;
- headless OpenCode can use Anthropic direct, Azure AI Foundry, or Trustbolt according to the model registry;
- human approval gates remain unchanged;
- retries run in clean sandboxes and recover from durable state;
- existing metrics logging, aggregation, reporting, and analysis continue without interruption.
