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

Headless execution uses OpenCode as the agent runtime abstraction.

```text
GitHub Actions / unattended invocation
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
```

OpenCode owns the model-facing agent loop in headless mode. The pipeline remains unaware of the implementation details of the selected provider beyond the runtime/model policy required for the step.

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

Runtime adapters translate the canonical entitlement set into the enforcement mechanism supported by the selected runtime.

Conceptually:

```text
canonical entitlement policy
          |
     +----+----+
     |         |
     v         v
Claude Code  OpenCode
adapter      adapter
```

The objective is policy equivalence, not identical runtime syntax.

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

#
## Claude Code to OpenCode capability equivalence

In headless mode, OpenCode is expected to provide the agent-side execution capabilities currently supplied by Claude Code. GitHub remains the repository service, and the GitHub Actions runner or other execution host remains responsible for the operating system, checked-out working tree, language runtimes, compilers, test frameworks, and build infrastructure.

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

The canonical policy remains in the repository. OpenCode-specific permission syntax is an adapter concern and must not become a second entitlement source of truth.

### Build and execution host boundary

OpenCode does not itself provide the underlying build machine. It executes inside the environment supplied to it.

```text
GitHub repository
      |
      v
GitHub Actions runner / execution host
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
```

For V3, "OpenCode runtime" therefore means the headless **agent execution runtime**, not the underlying compute or build sandbox.

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

## Model policy

Pipeline and agent definitions should refer to logical model classes rather than provider deployment identifiers where practical.

Examples:

```text
frontier-coding
fast-review
research
writing
reasoning
economy
```

A runtime/provider configuration resolves those logical classes to a concrete model source and deployment.

For example:

```text
frontier-coding -> Azure deployment A
research        -> Azure deployment B
fast-review     -> Claude model C
```

The mapping may evolve without changing the logical agent or process definition.

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
3. Add a headless OpenCode adapter.
4. Map the existing entitlement model into OpenCode permissions.
5. Support at least one Azure-hosted model through OpenCode.
6. Run an existing pipeline agent unchanged through both execution modes.
7. Verify equivalent pipeline-state transitions and repository effects.
8. Add runtime/model telemetry without changing existing process semantics.

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
