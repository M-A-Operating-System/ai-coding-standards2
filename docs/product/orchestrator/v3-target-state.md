# V3 Target-State Runtime Design

## Core design invariants

These invariants are mandatory for V3.

1. **Reuse the existing agent definitions.** V3 executes the same agent definitions already held in the repository. Runtime adapters change invocation mechanics only; they do not create a second behavioral source of truth or fork agent instructions by runtime.

2. **Reuse the existing pipeline process definitions.** V3 uses the same pipeline task definitions, dependencies, ordering, sequencing, gates, retries, review loops, and terminal-state semantics already defined in the repository. Interactive and headless modes resolve the same next eligible step from the same process definition.

3. **Reuse the existing entitlement model.** V3 preserves the current canonical entitlement model for tool and action constraints. Runtime adapters translate resolved entitlements into Claude Code or OpenCode enforcement mechanisms without redefining policy.

4. **Only the model-execution wrapper changes.** V3 does not redesign the AI Agile process. The change is limited to the agent execution wrapper that runs an already-resolved agent against a foundation LLM. Pipeline state, agent behavior, lifecycle rules, standards and ADR selection, deterministic helpers, repository conventions, and workflow semantics remain common.

5. **Metrics logging and analysis continue seamlessly.** Existing metrics collection, logging, aggregation, reporting, and analysis continue across interactive Claude Code and headless OpenCode execution. Historical continuity is preserved and existing measures remain comparable across V2 and V3.

These invariants take precedence over runtime-specific convenience.

## Target architecture

V3 separates the process control plane from the agent execution runtime while preserving the existing repository-driven pipeline.

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
           Claude Code              Azure VM
           runtime/UI          self-hosted GitHub runner
                 |                        |
                 |                        v
                 |                    OpenCode
                 |                   /        \
                 v                  v          v
           Claude model       Anthropic API   Azure model API
```

The orchestrator remains authoritative for process state. Runtime adapters execute the resolved step.

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
Resolved agent step
      |
      v
Claude Code runtime
      |
      v
Claude model through the interactive Claude Code account
```

OpenCode is not inserted into the interactive path.

The operator may continue to use the existing conversational workflow, including requesting the next agent step. The orchestrator resolves the same pipeline state and agent definition used by headless execution, but the agent runs directly in Claude Code.

## Headless execution

Headless execution uses OpenCode as the agent execution runtime.

Long-running coding jobs run on a reusable Azure VM rather than consuming GitHub-hosted Actions minutes for the duration of the workload.

```text
GitHub event / workflow control
              |
              v
short GitHub-hosted bootstrap job
              |
              v
start Azure VM
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
fresh OpenCode execution
          /             \
         v               v
Anthropic API       Azure model API
         |
         v
job completes / host idle
         |
         v
stop/deallocate Azure VM
```

Each resolved pipeline agent step launches as a fresh OpenCode execution. OpenCode session state is not reused across pipeline steps and is never a source of pipeline truth.

The Azure VM is a named reusable host that is normally deallocated. A short GitHub-hosted bootstrap job starts it when work is ready. The VM runs a self-hosted GitHub runner, accepts the long-running coding workload, and is stopped/deallocated automatically after completion or after the configured idle threshold.

Only one coding pipeline job runs on the Azure host at a time. Additional eligible jobs remain queued until the host is available. V3 does not run multiple coding agents concurrently on the same working copy or host.

## Responsibility boundaries

### Pipeline orchestrator

The orchestrator owns process state and determines what happens next.

It remains authoritative for:

- pipeline sequence;
- task dependencies;
- classification;
- issue and PR state;
- human approval gates;
- retries;
- review loops;
- step eligibility;
- lifecycle transitions;
- deterministic pre/post steps;
- expected repository effects;
- agent context assembly;
- entitlement resolution;
- metrics emitted at the process level.

The orchestrator does not contain provider-specific prompting logic.

### Agent definitions

The repository agent definitions remain the authoritative behavioral contract for each role.

The same agent definition is used in both interactive Claude Code and headless OpenCode execution. Runtime adapters may transform packaging or invocation syntax, but they may not alter the behavioral source of truth.

### Runtime adapters

The orchestrator invokes a narrow runtime adapter contract:

```text
execute_agent(
    agent_definition,
    execution_context,
    resolved_entitlements,
    model_selection,
    execution_mode
) -> execution_result
```

The two V3 adapters are:

- Claude Code interactive adapter;
- OpenCode headless adapter.

The orchestrator depends on this contract rather than on Claude Code or OpenCode implementation details.

## Execution context

The orchestrator assembles the complete authoritative execution context before invoking either runtime.

The execution context includes:

- the existing repository agent definition;
- the orchestrator-produced prompt and step instructions;
- issue and PR context required by the step;
- selected standards and ADRs;
- deterministic helper outputs;
- pipeline step metadata;
- repository/worktree context;
- model selection;
- resolved entitlement policy.

OpenCode does not independently rediscover the issue, rebuild the prompt, select alternate standards, or infer pipeline state. It receives the same resolved execution inputs that the interactive Claude Code path uses.

Durable repository and pipeline state remain sufficient to reconstruct the next eligible step in a new invocation.

## Entitlements

The existing group-based entitlement model in `pipeline.json` remains canonical.

Entitlement groups are an internal policy abstraction. OpenCode does not interpret group names.

For each resolved pipeline step, the orchestrator:

1. resolves defaults and step-specific entitlements;
2. expands referenced allow and deny groups;
3. flattens them into one effective rule list;
4. preserves the allow/deny effect for each rule;
5. orders the rules deterministically;
6. passes the resolved rule list to the runtime adapter.

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

The normalized entitlement representation is:

```text
[
  { action, pattern, effect },
  ...
]
```

Broad allows are resolved before more specific denies so that the effective policy remains deterministic when rendered into an ordered runtime permission model.

Example:

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

OpenCode-specific permission syntax is generated from the flattened list at runtime. The adapter may translate command wrappers and wildcard syntax where required by OpenCode, but it may not change the policy outcome.

V3 preserves the current security semantics. Defense in depth is provided by the Azure VM boundary, scoped GitHub credentials, filesystem and OS permissions, repository controls, and runtime command permissions.

## Claude Code to OpenCode capability equivalence

In headless mode, OpenCode provides the agent-side execution capabilities currently supplied by Claude Code.

| Current Claude Code capability | V3 headless equivalent |
|---|---|
| Read repository | OpenCode read / glob / grep capabilities |
| Modify source | OpenCode edit / write capabilities |
| `git status`, `git diff`, `git log` | OpenCode shell execution |
| Commit changes | OpenCode shell execution constrained by canonical entitlements |
| Run tests | OpenCode shell execution on the Azure host |
| Compile / build | OpenCode shell execution on the Azure host |
| Linters / formatters | OpenCode shell execution and formatter integrations |
| LSP / code navigation | OpenCode LSP capabilities |
| Web research | OpenCode web search / web fetch where entitled |
| Agent-specific allowed / denied tools | OpenCode runtime permissions rendered from resolved entitlements |
| Launch supporting agents | OpenCode subagent capabilities where entitled |
| GitHub CLI / API calls | `gh` through OpenCode shell execution or approved tool integration |

## Build and execution host

OpenCode is the headless agent runtime. The Azure VM is the compute and build host.

The Azure host supplies:

- checked-out repository;
- operating system;
- language runtimes;
- compilers and build tools;
- test frameworks;
- linters and formatters;
- local dependencies;
- GitHub self-hosted runner;
- OpenCode runtime.

```text
GitHub repository + workflow control
      |
      v
start / assign job
      |
      v
Azure VM / self-hosted GitHub runner
  |- repository checkout
  |- OS and language runtimes
  |- compilers/build tools
  |- tests/linters
  `- dependencies
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
Anthropic or Azure foundation model
```

GitHub-hosted Actions provide lightweight triggering and bootstrap only. Long-running coding execution occurs on the Azure host.

## Model selection

Existing pipeline model-selection semantics remain authoritative.

V3 does not introduce a separate logical model-class abstraction.

The OpenCode adapter and provider configuration translate the configured model/provider selection into a concrete API endpoint.

```text
Interactive
  Claude Code -> Claude model through interactive account

Headless
  OpenCode -> Anthropic API -> Claude model
  OpenCode -> Azure API     -> Azure-hosted model
```

Claude Code is not nested beneath OpenCode.

## Research and content agents

The same V3 runtime model applies to coding and non-coding agents, including:

- research agents;
- blog-post agents;
- technical white-paper agents;
- technical reviewers;
- editors;
- humanizer agents;
- metadata and SEO agents;
- other human-readable artifact workflows.

In headless mode, OpenCode supplies runtime capabilities such as web search, web fetch, local files, repository access, shell execution, and other entitled tools around the selected foundation model.

Web capability belongs to the runtime/tool layer, not to the Azure-hosted foundation model itself.

## Human approval gates

Existing human gates remain authoritative and behave identically across runtimes.

When headless execution reaches a human approval gate:

1. the orchestrator persists pipeline state;
2. the current headless run exits normally;
3. no approval is synthesized, inferred, or bypassed;
4. the Azure host may stop/deallocate;
5. the recorded human approval triggers or enables a subsequent invocation;
6. the orchestrator resumes from durable state and resolves the next eligible step.

## State continuity

Repository and pipeline state remain the durable source of truth.

Neither Claude Code conversational state nor OpenCode session state is required to determine pipeline progress.

A new interactive or headless invocation reconstructs the next eligible action from durable repository and pipeline state.

## Failure and recovery

Runtime failures are normalized into the execution result returned to the orchestrator.

This includes:

- OpenCode process failure;
- foundation model API timeout or provider error;
- Azure VM loss;
- self-hosted runner disconnect;
- tool permission failure;
- agent budget exhaustion;
- build or test process failure.

The runtime adapter records the failure classification and available diagnostic metadata. The existing orchestrator owns process-level retry, re-entry, terminal-state handling, and escalation.

OpenCode does not maintain a separate retry state machine.

## Execution result

Each runtime adapter returns a normalized execution result containing:

- completion status;
- runtime used;
- execution host;
- model provider;
- concrete model identity where available;
- elapsed time;
- token and usage metrics where available;
- tool or permission failure classification;
- produced artifacts or repository effects;
- retryable versus terminal failure indication.

Provider-specific diagnostic fields may be retained as optional metadata but do not become process-state dependencies.

## Metrics continuity

The existing metrics log, aggregation, reporting, and analysis pipeline remains unchanged as the canonical telemetry path.

V3 adds runtime attribution dimensions to the existing records:

```text
execution_runtime = claude-code | opencode
execution_host    = interactive | azure
model_provider    = anthropic | azure
model             = concrete model identifier
```

Existing metrics retain their current definitions and historical comparability. V3 does not create a separate telemetry store or analysis path.

The additional dimensions allow existing reports and analysis to compare execution duration, cost, failures, model usage, and quality outcomes across interactive and headless execution.

## V3 scope

V3 introduces the runtime abstraction required to support interactive Claude Code and headless OpenCode execution without changing the existing AI Agile product model.

The target design does not include:

- Trustbolt integration;
- replacement of the existing pipeline state machine;
- redesign of agent prompts;
- redesign of standards or ADR selection;
- routing interactive Claude Code sessions through OpenCode;
- replacement of GitHub as the durable workflow and repository state;
- a new model-class taxonomy;
- a separate entitlement policy system;
- a separate metrics system.

## Target-state acceptance criteria

V3 is complete when:

- an existing pipeline definition runs without a separate interactive/headless fork;
- the same existing agent definition executes through Claude Code interactively and OpenCode headlessly;
- the same canonical entitlement policy is enforced through both runtime adapters;
- entitlement groups are flattened into the same normalized per-step rule list before runtime invocation;
- the orchestrator resolves the same next eligible step regardless of runtime;
- each headless pipeline step executes in a fresh OpenCode process;
- long-running headless work runs on the reusable auto-start/stop Azure self-hosted runner VM;
- only one coding pipeline job executes on that Azure host at a time;
- headless OpenCode can use either the Anthropic API or an Azure-hosted foundation model according to existing model selection;
- the same orchestrator-produced execution context is supplied to both runtime paths;
- human approval gates are preserved without bypass;
- runtime failures return to the orchestrator for existing retry and lifecycle handling;
- repository and pipeline state are sufficient to resume work in a new session;
- existing metrics logging, aggregation, reporting, and analysis continue without interruption;
- runtime, host, provider, and model attribution are captured in the existing metrics stream.
