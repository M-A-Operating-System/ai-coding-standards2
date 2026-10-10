# V3 Target-State Runtime Design

## Status

Draft target-state design for V3. This document defines the runtime boundary and operating model only. It does not replace the existing pipeline sequence, agent specifications, entitlement model, standards selection, human gates, or repository-state conventions.

## Core design invariants

These invariants are mandatory for V3. An implementation that violates any of them is not V3-compatible.

1. **Reuse the existing agent definitions.** V3 must execute the same agent definitions already held in the repository. Runtime-specific wrappers may adapt invocation mechanics, but they must not create a second behavioral source of truth or fork agent instructions by runtime.

2. **Reuse the existing pipeline process definitions.** V3 must use the same pipeline task definitions, dependencies, ordering, sequencing, gates, retries, review loops, and terminal-state semantics already defined in the repository. Interactive and headless modes must resolve the same next eligible step from the same process definition.

3. **Reuse the existing entitlement model.** V3 must preserve the current canonical entitlement model for tool and action constraints. Runtime adapters may translate those entitlements into Claude Code or OpenCode enforcement mechanisms, but the policy itself must not be redefined independently by either runtime.

4. **Only the model-execution wrapper changes.** V3 is not a redesign of the AI Agile process. The change is limited to the coding/agent wrapper that executes an already-resolved agent against a foundation LLM. Pipeline state, agent behavior, lifecycle rules, standards and ADR selection, deterministic helpers, and repository conventions remain common.

5. **Metrics logging and analysis must continue seamlessly.** Existing metrics collection, logging, aggregation, reporting, and analysis capabilities must continue across interactive Claude Code and headless OpenCode execution. A runtime change must not break historical continuity, remove existing measures, or require a separate metrics system. Runtime and model-source dimensions may be added, but existing metrics semantics must remain comparable across V2 and V3.

These invariants take precedence over runtime-specific convenience. OpenCode, Claude Code, Azure model mappings, and any future provider integration must conform to them rather than force changes to the existing product model.

## Problem statement

The current implementation is tightly coupled to Claude Code as both an interactive user experience and an agent execution runtime.

That coupling is useful during interactive work because an operator can drive the pipeline from Claude Code and consume Claude Max subscription capacity. It is limiting for unattended execution because headless automation needs a runtime that can select among multiple model sources, including Azure-hosted foundation models, without changing the pipeline or agent definitions.

V3 separates the process control plane from the agent runtime.

## Target operating model

### Interactive mode

Interactive execution remains native to Claude Code.

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
Resolved agent step
      |
      v
Claude Code runtime
      |
      v
Claude model through the interactive Claude Code account
```

OpenCode is not inserted into the interactive path.

This preserves the current conversational workflow, including "next agent step" operation, and preserves the economics of the interactive Claude plan rather than converting every interactive step into metered API inference.

### Headless mode

Headless execution uses OpenCode as the agent runtime abstraction. Long-running coding jobs execute on an Azure-hosted build/agent machine rather than consuming GitHub-hosted Actions minutes for the full duration of the job.

GitHub remains the trigger and workflow control plane. When headless work is required, the Azure execution host is started automatically, accepts the job through the GitHub runner/control path, executes the pipeline step, and is stopped again when the workload is complete or the host becomes idle.

```text
GitHub event / workflow control
              |
              v
      start Azure execution host
              |
              v
Azure VM / self-hosted GitHub runner
              |
              v
      Pipeline orchestrator
              |
              v
       Resolved agent step
              |
              v
           OpenCode
          /        \
         v          v
   Claude source   Azure source
              |
              v
      job completes / idle
              |
              v
       stop Azure host
```

OpenCode owns the model-facing agent loop in headless mode. The Azure host owns the long-running compute and build environment. The pipeline remains unaware of the implementation details of the selected provider beyond the runtime/model policy required for the step.

For the initial V3 implementation, each resolved pipeline agent step launches as a **fresh OpenCode execution**. OpenCode session state is not a source of pipeline truth and is not reused across pipeline steps.

## Responsibility boundaries

### Pipeline orchestrator

The orchestrator owns process state and decides what happens next.

It remains authoritative for:

- pipeline sequence
- dependencies
- classification
- issue and PR state
- human approval gates
- retries
- review loops
- step eligibility
- lifecycle transitions
- deterministic pre/post steps
- expected repository effects
- metrics emitted at the process level

The orchestrator must not contain provider-specific prompting logic.

### Agent definitions

Agent definitions remain the authoritative behavioral contract for each role.

The same logical agent definition must be usable in interactive Claude Code and headless OpenCode execution. Runtime-specific wrappers may adapt the definition, but they must not fork the behavioral source of truth.

### Entitlements

The existing entitlement model remains canonical.

V3 must preserve the current group-based entitlement structure in `pipeline.json`. Entitlement groups remain an internal policy abstraction used to organize allowed and denied commands. OpenCode does not need to understand those group names.

For each resolved pipeline step, the orchestrator must:

1. resolve defaults and step-specific entitlements;
2. expand referenced allow and deny groups;
3. flatten them into one effective rule list;
4. preserve the allow/deny effect for each rule;
5. pass that resolved list to the selected runtime adapter.

Conceptually:

```text
pipeline.json
  |- default entitlements
  |- step entitlements
  |- allow groups
  `- deny groups
          |
          v
existing entitlement resolver
          |
          v
effective per-step rule list
[
  { action, pattern, effect },
  ...
]
          |
     +----+----+
     |         |
     v         v
Claude Code  OpenCode
renderer     renderer
```

The runtime contract is therefore based on the resolved effective rules, not entitlement group names.

The resolved entitlement handoff should use one normalized internal representation shared by all runtime adapters:

```text
[
  { action, pattern, effect },
  ...
]
```

Rule ordering must be deterministic. Broad allows should be resolved before more specific denies so that the effective policy remains equivalent to the current pipeline semantics when rendered into OpenCode's ordered permission model.

Illustrative resolved policy:

```json
{
  "rules": [
    { "action": "shell", "pattern": "*", "effect": "allow" },
    { "action": "shell", "pattern": "git reset --hard*", "effect": "deny" },
    { "action": "shell", "pattern": "git push --force*", "effect": "deny" },
    { "action": "shell", "pattern": "git config *", "effect": "deny" },
    { "action": "shell", "pattern": "ssh *", "effect": "deny" }
  ]
}
```

OpenCode-specific permission syntax is generated from this flattened list at runtime. The adapter may transform command wrappers or wildcard syntax where OpenCode requires a different representation, but it must not change the policy outcome.

The objective is policy equivalence, not identical runtime syntax.

For V3 MVP, the security goal is **equivalent enforcement to the current Claude Code implementation**, not a redesign of the entitlement/security model. Defense in depth comes from the Azure VM boundary, scoped GitHub credentials, filesystem/OS permissions, and the existing repository controls in addition to runtime command permissions.

### OpenCode

OpenCode is the headless agent execution runtime.

It owns:

- model interaction loop
- local tool execution
- file access
- shell execution
- web search and web fetch where permitted
- MCP tool access where permitted
- subagent/runtime behavior where permitted
- runtime-level permission enforcement
- provider/model invocation for headless execution

OpenCode does not own pipeline sequencing or GitHub lifecycle state.

## Claude Code to OpenCode capability equivalence

In headless mode, OpenCode is expected to provide the agent-side execution capabilities currently supplied by Claude Code. GitHub remains the repository and workflow-control service. For long-running coding jobs, the execution host is an Azure VM running the GitHub self-hosted runner (or equivalent runner integration), rather than a GitHub-hosted runner consuming Actions minutes for the duration of the job. The Azure host supplies the operating system, checked-out working tree, language runtimes, compilers, test frameworks, and build infrastructure.

| Current Claude Code capability | V3 headless equivalent |
|---|---|
| Read repository | OpenCode read / glob / grep capabilities |
| Modify source | OpenCode edit / write capabilities |
| `git status`, `git diff`, `git log` | OpenCode shell execution |
| Commit changes | OpenCode shell execution constrained by the canonical entitlement model |
| Run tests | OpenCode shell execution on the runner/host |
| Compile / build | OpenCode shell execution on the runner/host |
| Linters / formatters | OpenCode shell execution and formatter integrations |
| LSP / code navigation | OpenCode LSP capabilities |
| Web research | OpenCode web search / web fetch capabilities where entitled |
| Agent-specific allowed / denied tools | OpenCode runtime permissions derived from the canonical entitlement model |
| Launch supporting agents | OpenCode subagent capabilities where entitled |
| GitHub CLI / API calls | `gh` through OpenCode shell execution or an approved MCP/tool integration |

The canonical policy remains in the repository. Entitlement groups are resolved and flattened before OpenCode is invoked. OpenCode receives only the effective per-step allow/deny rule list. OpenCode-specific permission syntax is an adapter concern and must not become a second entitlement source of truth.

### Build and execution host boundary

OpenCode does not itself provide the underlying build machine. For long-running headless coding work, it executes on an Azure host that is started and stopped automatically around the workload.

```text
GitHub repository + workflow control
      |
      v
start / assign job
      |
      v
Azure VM / self-hosted GitHub runner
  |- checked-out repository
  |- operating system
  |- Python / Node / Java / other runtimes
  |- compilers and build tools
  |- test frameworks
  `- local dependencies
      |
      v
OpenCode
  |- reads and edits files
  |- runs git commands
  |- executes builds and tests
  |- invokes tools subject to entitlements
  `- manages the headless agent loop
      |
      v
Claude or Azure foundation model
      |
      v
job completes / runner becomes idle
      |
      v
stop Azure VM
```

GitHub Actions may still provide lightweight orchestration and triggering, but the target design does not use GitHub-hosted runner minutes as the primary compute for long-running coding agents.

For the V3 MVP, a **short GitHub-hosted bootstrap job** starts the Azure VM before the long-running job is assigned. The Azure VM runs a self-hosted GitHub runner and accepts the actual coding workload once available. When the workload completes or the host reaches its configured idle threshold, the VM is stopped/deallocated automatically.

The initial design uses **one named reusable Azure VM that is normally deallocated**, rather than provisioning a disposable VM for every pipeline step. Disposable/ephemeral hosts may be introduced later without changing the OpenCode adapter contract.

For V3, "OpenCode runtime" therefore means the headless **agent execution runtime**, while the Azure VM is the underlying compute/build host.

## Azure

Azure is a model source, not the agent runtime.

Azure-hosted foundation models receive model requests from OpenCode in headless mode. They do not own the pipeline, tool loop, repository lifecycle, or internet runtime.

## Runtime selection

Runtime selection is based first on execution mode.

```text
execution_mode = interactive
    runtime = claude-code

execution_mode = headless
    runtime = opencode
```

Within the headless OpenCode runtime, model source is independently selectable:

```text
runtime = opencode
model_source = claude | azure
```

This separation prevents provider choice from becoming embedded in the pipeline definition.

## Model selection

V3 does not introduce a new logical model-class abstraction as part of the initial implementation.

Existing pipeline model-selection semantics remain authoritative. The OpenCode adapter and provider configuration are responsible for translating the configured model/provider choice into the concrete Anthropic or Azure endpoint required at runtime.

In headless mode:

```text
OpenCode
  |- Anthropic API -> Claude model
  `- Azure API     -> Azure-hosted model
```

Claude Code is **not** nested underneath OpenCode. Claude Code remains the interactive runtime only; when a headless OpenCode step uses Claude, it reaches Claude through the Anthropic API/provider path.

This keeps model-provider selection behind the runtime boundary and avoids changing pipeline definitions solely for V3.

## Research and content agents

V3 is not limited to software-development agents.

The same runtime model supports:

- research agents
- blog-post agents
- technical white-paper agents
- technical reviewers
- editors
- humanizer agents
- metadata/SEO agents
- other human-readable artifact workflows

In headless mode, OpenCode provides the execution environment around the model, including web and file tools where the entitlement policy permits them.

A foundation model is not considered "web enabled" merely because it is hosted in Azure. Web access is a runtime capability supplied by OpenCode or another explicitly configured tool service.

Example:

```text
research agent
    |
    v
OpenCode
  |- web search
  |- web fetch
  |- local files
  |- repository access
  `- model call
        |
        v
      Azure model
```

## State continuity

The repository and pipeline state remain the durable source of truth across runtimes.

Interactive Claude Code and headless OpenCode must not depend on private conversational state to determine pipeline progress.

A new invocation must be able to reconstruct the next eligible action from durable repository and pipeline state.

## Interactive "next agent step"

The current interactive experience should remain conceptually unchanged.

An operator in Claude Code requests the next agent step. The orchestrator resolves the next eligible pipeline action and the resolved agent executes natively in the Claude Code runtime.

```text
operator
   |
   v
"next agent step"
   |
   v
orchestrator
   |
   v
resolve next step
   |
   v
execute inside Claude Code
```

The command surface may be refactored, but the process semantics must remain identical to headless operation.

## Headless execution

For unattended operation, the orchestrator resolves exactly the same next step and delegates agent execution to the OpenCode adapter.

```text
scheduler / GitHub event
        |
        v
orchestrator
        |
        v
resolve next step
        |
        v
OpenCode adapter
        |
        v
OpenCode
        |
        +--> Claude model source
        |
        `--> Azure model source
```

The outcome must be written back through the same repository-state and pipeline-state mechanisms used today.

When headless execution reaches an existing human approval gate, it must **stop normally and persist state**. It must never synthesize, infer, or bypass the approval. The Azure host may then shut down. Once the human approval is recorded, a subsequent invocation resumes from the durable pipeline state and launches the next eligible step.

## Runtime adapter contract

V3 should introduce a narrow runtime abstraction rather than embedding OpenCode logic directly throughout the orchestrator.

Illustrative contract:

```text
execute_agent(
    agent,
    context,
    entitlements,
    model_policy,
    execution_mode
) -> execution_result
```

The initial adapters are:

- Claude Code interactive adapter
- OpenCode headless adapter

The orchestrator should depend on the adapter contract, not on Claude CLI or OpenCode implementation details.

## Execution result contract

Each runtime adapter should return a normalized result containing, at minimum:

- completion status
- runtime used
- model source/model identity where available
- elapsed time
- token/usage metrics where available
- tool/permission failure classification
- produced artifacts or repository effects
- retryable vs terminal failure indication

Provider-specific fields may be retained as optional diagnostic metadata but must not become process-state dependencies.

## Remaining open questions

The following items remain intentionally unresolved and should be answered during the next design/implementation pass:

1. **Concurrency and work isolation.** If multiple issues are eligible simultaneously, determine whether a single Azure host may run multiple agent jobs concurrently, whether separate worktrees are sufficient, or whether V3 initially serializes work per host.

2. **Execution-context assembly.** Define the exact authoritative payload passed to the runtime adapter from the existing orchestrator: agent definition, resolved prompt/context, standards/ADRs, issue/PR context, and other deterministic inputs. OpenCode must not independently rediscover or reconstruct pipeline context.

3. **Metrics attribution dimensions.** Preserve the existing metrics pipeline while deciding which additional runtime dimensions are required, such as execution runtime, execution host, model provider, and concrete model.

4. **Runtime failure and recovery.** Define the normalized handling for OpenCode failure, VM loss, API timeout, runner disconnect, and budget exhaustion, while keeping process-level retry policy in the existing orchestrator.

## Out of scope for this design

The following are deliberately out of scope for the initial V3 target state:

- Trustbolt integration
- replacing the existing pipeline state machine
- redesigning agent prompts
- redesigning standards or ADR selection
- moving interactive Claude Code sessions through OpenCode
- replacing GitHub as the durable workflow/repository state
- defining the final Azure model portfolio
- selecting detailed provider fallback algorithms
- changing existing product workflows solely to fit OpenCode

## Initial implementation direction

The minimum V3 implementation should prove runtime portability with the smallest possible change surface:

1. Introduce the runtime adapter boundary.
2. Preserve the current interactive Claude Code path behind the Claude adapter.
3. Add a headless OpenCode adapter that launches a fresh OpenCode execution per resolved pipeline step.
4. Resolve and flatten the existing entitlement groups into the normalized per-step rule list and render it into OpenCode permissions.
5. Add the short GitHub-hosted bootstrap that starts the reusable Azure self-hosted runner VM and stops/deallocates it after completion or idle.
6. Support the existing configured model selection through either the Anthropic API or an Azure-hosted model via OpenCode.
7. Run an existing pipeline agent unchanged through both execution modes.
8. Verify equivalent pipeline-state transitions, human gates, repository effects, and metrics continuity.

## Acceptance criteria for the V3 foundation

The V3 foundation is successful when:

- an existing pipeline definition requires no fork between interactive and headless operation;
- an existing agent definition can execute through Claude Code interactively and OpenCode headlessly;
- the same canonical entitlement policy is enforced in both paths;
- the orchestrator resolves the same next step regardless of runtime;
- headless OpenCode can execute against an Azure-hosted foundation model;
- repository and pipeline state remain sufficient to resume work in a new session;
- runtime/provider selection is observable in metrics;
- no existing human gate, dependency, or review-loop behavior is weakened by the runtime abstraction.
