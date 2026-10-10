# V3 Target-State Runtime Design

## Core design invariants

These invariants are mandatory for V3.

1. **Reuse the existing agent definitions.** V3 executes the same agent definitions already held in the repository. Runtime adapters change invocation mechanics only; they do not create a second behavioral source of truth or fork agent instructions by runtime.

2. **Preserve existing pipeline workflow semantics.** V3 retains the existing pipeline tasks, dependencies, ordering, sequencing, gates, retries, review loops, terminal-state semantics, session semantics, and scripted-step behavior. Interactive and headless modes resolve the same next eligible step from the same process definition. The deliberate pipeline configuration change in V3 is replacement of provider-specific model identifiers with provider-neutral logical model names.

3. **Introduce provider-neutral logical model names.** V3 replaces provider-specific model identifiers in `pipeline.json` with logical model names such as `coding-primary` or `review-fast`. These logical names define the model role required by the pipeline and are resolved through a separate model registry to a concrete model exposed through Claude Code, Anthropic, Azure AI Foundry, Trustbolt, or another supported foundation-model provider or gateway. This allows model providers and gateways to change without altering pipeline workflow semantics or agent definitions.

4. **Reuse the existing entitlement model.** V3 preserves the current canonical entitlement model for tool and action constraints. Runtime adapters translate resolved entitlements into Claude Code or OpenCode enforcement mechanisms without redefining policy.

5. **Only the execution wrapper and model-resolution abstraction change.** V3 does not redesign the AI Agile process. Pipeline state, agent behavior, lifecycle rules, standards and ADR selection, deterministic helpers, repository conventions, session behavior, scripted steps, and workflow semantics remain common. V3 introduces execution adapters, isolated headless sandboxes, and execution placement without changing product behavior.

6. **Metrics logging and analysis continue seamlessly.** Existing metrics collection, logging, aggregation, reporting, and analysis continue across interactive Claude Code and headless OpenCode execution. Historical continuity is preserved and existing measures remain comparable across V2 and V3.

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

V3 separates five concerns:

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
                +--> interactive --> existing deterministic execution path
                |
                `--> headless ----> isolated sandbox --> deterministic script
```

Agent steps invoke a model runtime. Script steps retain their deterministic behavior and do not become OpenCode agents. Every headless pipeline step, whether model-driven or deterministic, executes inside an isolated ephemeral sandbox.

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

The existing orchestrator remains the sole authority for whether work is safe to execute concurrently. Neither OpenCode, the sandbox runtime, GitHub Actions, the placement layer, nor Azure IaaS may introduce an independent process-level concurrency policy.

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

The placement layer does not determine whether pipeline work may run concurrently and does not inspect pipeline dependencies, labels, workflow state, management-task rules, or human gates. It receives only execution requests that the orchestrator has already declared eligible.

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
- one host-level GitHub runner/control process;
- OpenCode runtime image or installation;
- host monitoring and lifecycle control.

Individual sandboxes are execution units, not independent GitHub self-hosted runners. The host-level runner/control process receives work and the orchestrator/placement layer launches isolated sandboxes beneath it.

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

A sandbox cannot inspect or modify another sandbox's files, processes, environment, credentials, repository, or runtime state. Sandboxes are unprivileged and do not receive access to the host container-runtime control socket or other privileged host interfaces.

Sandbox networking is also isolated. A sandbox cannot directly address sibling sandboxes or privileged host-management endpoints. Outbound network access is controlled by the execution environment and limited to the services required by the step's entitlements and runtime configuration.

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

Sandbox-local state is never authoritative and is never reused as the basis for retry or continuation. Retries and re-entry start in a clean sandbox and reconstruct work from durable repository and pipeline state plus explicitly persisted session artifacts where permitted by the session policy.

## Session semantics

V3 preserves the existing session semantics defined in `pipeline.json`, including `per_issue`, `global`, resume behavior, session identity, and retry-specific session behavior.

A fresh OpenCode process does not imply a new logical pipeline session.

Where resume is enabled, the runtime adapter makes the prior logical session context available to the new isolated OpenCode execution. Where resume is disabled, the new execution receives no prior conversational context.

Session state remains non-authoritative. Every invocation re-derives its current situation from durable artifacts.

Persisted session material is scoped to the logical session and exposed only to the sandbox executing that session.

Conversational session state is runtime-specific and optional. A Claude Code conversational session is not translated into an OpenCode session, and an OpenCode session is not translated into Claude Code. When execution changes runtime, the next invocation reconstructs its context from durable repository and pipeline state plus the resolved execution inputs. This preserves pipeline/session semantics without making runtime-specific conversation formats part of the product contract.

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

### Execution adapters

All pipeline execution crosses one explicit execution boundary. The orchestrator does not invoke Claude Code, OpenCode, provider APIs, containers, or host-specific commands directly.

For model-driven agent steps:

```text
execute_agent(
    agent_definition,
    resolved_execution_input,
    resolved_entitlements,
    session_policy,
    logical_model,
    execution_mode,
    execution_metadata
) -> execution_result
```

For deterministic script steps:

```text
execute_script(
    script_definition,
    resolved_execution_input,
    resolved_entitlements,
    execution_mode,
    execution_metadata
) -> execution_result
```

The adapter layer is the only component permitted to translate pipeline execution into runtime-specific invocation.

V3 provides:

- Claude Code interactive agent execution;
- OpenCode headless agent execution;
- deterministic script execution in the assigned interactive or headless environment.

The orchestrator depends only on these contracts and never on Claude Code CLI syntax, OpenCode CLI syntax, provider APIs, container commands, or Azure IaaS implementation details.

## Execution contract

V3 preserves the existing ownership of execution-context resolution.

Whatever the current pipeline resolves before invoking Claude Code remains resolved before invoking either runtime. The interactive and headless runtimes receive semantically equivalent resolved inputs, even where runtime-specific packaging differs.

The normalized execution input contains, at minimum:

- pipeline execution ID;
- flow and step identity;
- issue/PR/work-item identity;
- agent or script definition;
- resolved prompt/context;
- selected standards and ADRs;
- deterministic helper outputs;
- resolved entitlements;
- logical model name for model-driven steps;
- session policy and logical session identity where applicable;
- repository/branch context;
- execution mode.

OpenCode does not independently infer pipeline state, choose alternate standards, reconstruct issue intent, or create a second process model.

Every execution returns a normalized machine-readable result containing, at minimum:

```text
status
execution_id
step
execution_mode
execution_runtime
execution_host
logical_model
model_provider
model
model_deployment
started_at
completed_at
elapsed_time
usage
commits
artifacts
repository_effects
failure_class
retryable
diagnostics
```

Fields that do not apply to a deterministic script step are null/omitted according to the execution-result schema.

This normalized result is the only runtime-facing outcome consumed by the orchestrator. Runtime/provider-specific metadata may be retained as diagnostics but cannot become a pipeline-state dependency.

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

V3 deliberately introduces **logical model names** to abstract pipeline behavior from concrete foundation-model providers and model gateways. A logical model name represents the role or capability expected by the pipeline, while the model registry resolves that logical name to the concrete provider, model, and deployment used in a given execution mode.

Each model-driven pipeline step references a provider-neutral logical model name:

```json
{
  "agent": "03_execute/coder",
  "model": "coding-primary"
}
```

A separate model registry owns the mapping from that logical name to the concrete provider/gateway and model/deployment used in each execution mode. Runtime selection is fixed elsewhere by execution mode: interactive execution uses Claude Code and headless execution uses OpenCode. The registry does not select or configure runtimes.

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
        "provider": "claude-code",
        "model": "claude-sonnet-4-6"
      },
      "headless": {
        "provider": "azure-ai-foundry",
        "model": "kimi-k2",
        "deployment": "kimi-k2-prod"
      }
    },
    "review-fast": {
      "interactive": {
        "provider": "claude-code",
        "model": "claude-haiku-4-5"
      },
      "headless": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5"
      }
    }
  }
}
```

The logical model name is the pipeline contract. Provider names, concrete model identifiers, and deployment names belong to the model registry. API endpoints, tenant/resource identifiers, authentication mechanisms, secrets, and provider-specific credentials belong to provider/runtime configuration and are not stored in the model registry.

Each logical model name also represents a functional capability contract for the pipeline role it serves, such as required tool use, structured-output support, or minimum context capability. A provider mapping must satisfy that contract.

Model resolution returns one configured target. Provider or model failure is returned to the orchestrator as an execution failure; V3 does not silently substitute another provider or model.

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

V3 must distinguish the model target selected by pipeline/runtime configuration from the concrete model actually used by the provider for each inference request. This distinction is required for routed providers and gateways such as Azure AI Foundry Model Router and Trustbolt, where the configured target may select a different underlying model at request time.

Execution-level attribution includes:

```text
execution_mode          = interactive | headless
execution_runtime       = claude-code | opencode
execution_host          = interactive | azure-iaas

logical_model           = provider-neutral pipeline model name

configured_provider     = claude-code | anthropic | azure-ai-foundry | trustbolt
configured_model        = configured provider model or router target
configured_deployment   = configured deployment identifier where applicable

actual_providers_used   = distinct providers reported across inference requests
actual_models_used      = distinct concrete models reported across inference requests
primary_actual_model    = dominant/primary concrete model where meaningful
model_switch_count      = number of actual-model changes during the execution
```

Each individual model inference request is also recorded with request-level attribution:

```text
execution_id
request_id
sequence
logical_model

configured_provider
configured_model
configured_deployment

actual_provider
actual_model
actual_deployment

input_tokens
output_tokens
latency
cost
provider_request_id
```

For direct, non-routed model calls, configured and actual model attribution will normally be identical. For provider-side routing, the configured model may be a router or gateway target while `actual_model` records the concrete underlying model reported for that request.

If the provider does not expose the concrete model actually used, the actual-model fields remain unavailable rather than being inferred.

Existing metrics retain their definitions and historical comparability. These additional fields extend attribution without creating a separate telemetry path.

## Target-state acceptance criteria

V3 is complete when:

- existing pipeline definitions execute without interactive/headless forks;
- existing agent definitions execute unchanged through Claude Code interactively and OpenCode headlessly;
- all pipeline execution crosses the execution-adapter boundary rather than calling runtime/provider/infrastructure implementations directly;
- agent and script executions both return the normalized execution-result contract;
- deterministic script steps retain their existing semantics and run inside isolated sandboxes when headless;
- the orchestrator retains all existing dependency and concurrency controls;
- multiple eligible headless executions may run concurrently;
- each concurrent headless execution runs in an isolated ephemeral sandbox;
- one sandbox cannot affect another sandbox;
- execution placement can use multiple sandboxes per Azure IaaS VM and multiple Azure IaaS VMs without inspecting pipeline semantics;
- Azure IaaS capacity management does not change pipeline semantics;
- session scope and resume semantics remain compatible with the existing pipeline, while conversational state remains runtime-specific and non-authoritative;
- canonical entitlements are resolved once and rendered into the selected runtime;
- Azure IaaS is used only for execution infrastructure;
- pipeline model references are provider-neutral logical model names introduced specifically to abstract foundation-model providers and gateways and to define the capability contract required by each model role;
- the model registry resolves each logical model name to provider/model/deployment mappings without duplicating runtime selection;
- Azure AI Foundry is used only as a model inference provider;
- Trustbolt is a parallel headless model-access provider;
- headless OpenCode can use Anthropic direct, Azure AI Foundry, or Trustbolt according to the model registry, with no silent provider/model fallback;
- human approval gates remain unchanged;
- retries run in clean sandboxes and recover only from durable state and explicitly persisted session artifacts;
- sandbox network access prevents direct sibling or privileged host-management access;
- the Azure IaaS host uses a host-level runner/control process rather than one GitHub runner per sandbox;
- metrics capture the logical model name, configured provider/model/deployment, and the actual provider/model/deployment reported for each inference request;
- execution-level metrics aggregate the distinct actual models used and model switches for routed executions;
- existing metrics logging, aggregation, reporting, and analysis continue without interruption.
