<!-- GENERATED FILE -- DO NOT EDIT.
     Source: docs/product/orchestrator/schema/pipeline.schema.json
     Generator: pipeline/generators/generate_schema_reference.py
     Regenerate: python3 pipeline/generators/generate_schema_reference.py -->

# Target Pipeline Schema

The target shape of a COMPLETE pipeline definition, as decided in docs/product/orchestrator/PRODUCT.md (issue #393). Not yet live: pipeline/schemas/pipeline.schema.json governs the current pipeline.json and is unaffected by this file. This schema's required-ness (flows present and non-empty, budgets present and complete) describes the framework's shipped pipeline/pipeline.json, and the EFFECTIVE result of composing a repository's own pipeline/pipeline.json over it. A repository's file is a fragment by design (PRODUCT.md, 'A repository may have its own') and is not expected to satisfy this schema's required-ness on its own -- how a bare fragment is validated before composition, as opposed to after, is not yet decided; tracked on issue #393.

This is the target. `pipeline/schemas/pipeline.schema.json` governs
the pipeline.json that exists today; the build plan closing that
distance is sequenced on issue #393.

## Top level

| Field | Type | Required | Description |
|---|---|---|---|
| `$schema` | string | no |  |
| `defaults` | object | no | Pipeline-wide entitlement and lifecycle defaults merged into every step. Unaffected by the flow work in PRODUCT.md; carried over from the current schema. Step budgets are a separate, sibling concern -- see the top-level budgets key -- so a repository overriding one does not have to restate the other. |
| `budgets` | object | yes | Consumption limits. Two shapes live here: a pipeline-wide cap with no step-level equivalent, and the default turn/wall-clock budget every step gets unless it declares its own -- the same two-level shape as extra_allowedTools (a global value declared once and visible, overridable per step where a step genuinely needs to differ), applied to budgets instead of entitlements. max_turns and max_wall_seconds are required so every step has an effective budget even when it declares none itself; a hidden constant asserted to fit every step alike is exactly what this replaces (AS-1). |
| `flows` | object | yes | Every flow the pipeline runs, keyed by a stable flow name. A repository's own pipeline/pipeline.json names the flows it adds or replaces; a flow it does not name is inherited from the shipped default unchanged. Precedence is per flow, not per file (PRODUCT.md, AS-1): a named flow replaces the shipped one wholesale, everything else keeps tracking the default. |

### Top level -- `defaults`

Pipeline-wide entitlement and lifecycle defaults merged into every step. Unaffected by the flow work in PRODUCT.md; carried over from the current schema. Step budgets are a separate, sibling concern -- see the top-level budgets key -- so a repository overriding one does not have to restate the other.

| Field | Type | Required | Description |
|---|---|---|---|
| `extra_allowedTools` | array of string | no | Tools granted to every step in every flow. A step's effective permission is exactly this plus its own extra_allowedTools (AS-1) -- nothing else contributes. |
| `agent_lifecycle` | object | no | Scripts the orchestrator runs around every agent-type step to prepare and tear down its environment. Not steps themselves: no outcome, no label, and a non-zero exit is logged rather than failing the run. |

#### Top level -- `defaults` -- `agent_lifecycle`

Scripts the orchestrator runs around every agent-type step to prepare and tear down its environment. Not steps themselves: no outcome, no label, and a non-zero exit is logged rather than failing the run.

| Field | Type | Required | Description |
|---|---|---|---|
| `before` | array of string | no | Run immediately before each invocation, including retries. Must be idempotent: a run killed mid-flight leaves state behind, and re-running setup is what clears it. |
| `after` | array of string | no | Run once after the final retry, on every outcome. |

### Top level -- `budgets`

Consumption limits. Two shapes live here: a pipeline-wide cap with no step-level equivalent, and the default turn/wall-clock budget every step gets unless it declares its own -- the same two-level shape as extra_allowedTools (a global value declared once and visible, overridable per step where a step genuinely needs to differ), applied to budgets instead of entitlements. max_turns and max_wall_seconds are required so every step has an effective budget even when it declares none itself; a hidden constant asserted to fit every step alike is exactly what this replaces (AS-1).

| Field | Type | Required | Description |
|---|---|---|---|
| `max_turns` | integer | yes | Default turn budget for every agent-type step, unless the step declares its own. A person's starting judgement, not a formula -- a wrong number is not silently wrong: it surfaces as exhausted, naming the wall a step hit, and gets revised the same way any other config value is revised when the evidence says so. |
| `max_wall_seconds` | integer | yes | Default wall-clock budget for every step, agent or script, unless the step declares its own. |
| `max_launches_per_tick` | integer | no | How much work a single tick will start before it stops, so a burst of eligible work (a hundred issues becoming eligible at once) does not consume everything available in one pass. Not a concurrency limit -- concurrent execution is governed by component: label claiming, the decided target design (PRODUCT.md, 'Working on several things at once'), independently of how many of those starts can run together. This is the target-schema name for the current PIPELINE_MAX_CONCURRENT constant, moved out of orchestrator code and given its true meaning. Pipeline-wide only -- no per-step equivalent, since it bounds a tick rather than an invocation. |

## A flow

| Field | Type | Required | Description |
|---|---|---|---|
| `description` | string | yes | What kind of work this is and why it is its own flow. |
| `trigger` | object (one of) | yes | What makes a work item this flow's, or what makes the flow itself fire. Exactly one shape: item membership (kind, with optional type and labels) for work that produces change or coordinates other work, or a schedule for work with no triggering item (PRODUCT.md, 'Three shapes a flow can take'). Selection is positive: a step or flow with no matching criterion is simply not entered -- there is no exclude_labels or exclude_classifications to forget. |
| `naming` | object | no | What this flow's branches and pull requests are called. Declared here, never computed in orchestrator code (AS-1) -- which is what makes more than one branch or pull request per item expressible, for flows like two-phase design-to-build (lifecycle.md) that need it. Absent for a flow whose steps never commit. |
| `steps` | array of object | yes | This flow's steps, in execution order. |

### A flow -- `trigger`

What makes a work item this flow's, or what makes the flow itself fire. Exactly one shape: item membership (kind, with optional type and labels) for work that produces change or coordinates other work, or a schedule for work with no triggering item (PRODUCT.md, 'Three shapes a flow can take'). Selection is positive: a step or flow with no matching criterion is simply not entered -- there is no exclude_labels or exclude_classifications to forget.

Exactly one of the following shapes:

**Shape 1:**

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | string | yes | Which GitHub object kind this flow processes. One of: `issue`, `pr`. |
| `type` | array of string | no | Restrict this flow to work items carrying any one of these type: labels (OR within the dimension -- a work item carries exactly one type, never two, so this is 'any of', never 'all of'). Absent means every type. See AS-1, 'Selection by classification'. |
| `labels` | array of string | no | Every label listed must be present for a work item to enter this flow -- an AND combination, general to any dimension (e.g. ['size: L'], or ['type: enhancement', 'priority: high'] if a flow ever needed to key off more than type and size). Combines with `type` above, which is AND'd in as its own dimension when present. Absent means no additional label restriction. `priority:` labels are deliberately never used here -- priority orders pickup, never eligibility (lifecycle.md, 'Priority'). |

**Shape 2:**

| Field | Type | Required | Description |
|---|---|---|---|
| `schedule` | string | yes | Cron expression. This flow has no triggering work item; it fires on cadence and, if it concludes something is needed, raises one (PRODUCT.md, 'Scheduled work'). Due-ness is derived from the record (when this flow's steps last appended an entry), never stored separately. |

### A flow -- `naming`

What this flow's branches and pull requests are called. Declared here, never computed in orchestrator code (AS-1) -- which is what makes more than one branch or pull request per item expressible, for flows like two-phase design-to-build (lifecycle.md) that need it. Absent for a flow whose steps never commit.

| Field | Type | Required | Description |
|---|---|---|---|
| `branch` | string | yes | Token pattern for this flow's primary branch, e.g. 'issue-{number}'. |
| `base` | string | no | Token pattern for the branch this flow's primary branch is created from, e.g. 'feature-{parent_number}'. Defaults to the repository's default branch when omitted, and falls back to it when the computed branch does not exist. |
| `pull_requests` | array of object | no | One entry per pull request this flow opens. A flow needing only its primary branch and one PR may omit this; a flow needing more (a design PR merged ahead of a code PR) declares each here. |

## A step

| Field | Type | Required | Description |
|---|---|---|---|
| `agent` | string | yes | Stable step name in the form {phase}/{short-name}. For an agent-type step this matches the prompt at .claude/agents/{phase}/{short-name}.md and its frontmatter name field. Unaffected by which flow the step lives in -- phase governs where the prompt file sorts, not what work the step is for. |
| `phase` | string | yes | Must equal the agent field's phase prefix. One of: `00_ondemand`, `01_product_docs`, `02_design`, `03_execute`, `04_evaluate`, `05_continuous`. |
| `trigger` | object | yes | What makes this step eligible, within a flow its item has already entered. Sequencing (label) and, for a step in a coordinating or self-continuing flow, a condition about the item's own children (PRODUCT.md, 'Coordinating work needs a trigger that can look outward' and 'The same capability lets a step finish its own work in pieces'). |
| `unit` | string | no | What one invocation of this step addresses. 'item' (default): the work item itself. 'sub_item': one of the item's open children -- the orchestrator selects one and tells the step which via SUB_ITEM_NUMBER. Pairs with trigger.children: any_open: the step stays eligible, one sub-issue per invocation, so a step that exhausts mid-item has already committed the pieces it finished (PRODUCT.md, 'The unit of work shrinks; the contract does not change'). Default: `item`. One of: `item`, `sub_item`. |
| `dependencies` | array of string | yes | Other steps in this flow that must be complete first. |
| `type` | string | no | 'agent' invokes the Claude CLI with this step's prompt. 'script' runs the file at 'script' directly. The step contract binds both; a script meets most of it by construction and must still return one outcome and report honestly when it did nothing (PRODUCT.md, 'The step contract'). Default: `agent`. One of: `agent`, `script`. |
| `script` | string | no | Repo-relative path. Required when type is 'script'. |
| `model` | string | no | Which model this step runs on, chosen when the step was declared -- a step does not choose its own model, any more than it chooses its own permissions (AS-1). Agent-type steps only. |
| `expected_effect` | object | yes | What this step is supposed to change, declared explicitly so the orchestrator can compare it against what actually changed (MI-6). A step declaring no commits that produces one disagrees with itself, and the disagreement is surfaced, not buried -- this is also how a read-only step's constraint (PRODUCT.md, 'What a scheduled step may do is declared') becomes checkable rather than a claim in a prompt. |
| `budgets` | object | no | Overrides the top-level budgets default for this step only, field by field: a step declaring only max_turns still inherits max_wall_seconds from the default, and vice versa. Absent entirely means this step uses the default for both. A step can be exhausted by either wall independently: few turns spent on one slow tool call, or many quick turns inside a short time (the design's 'two budgets' discussion) -- which is why an override can target one wall without touching the other. |
| `extra_allowedTools` | array of string | no | Additional entitlements for this step beyond defaults.extra_allowedTools. Together these are this step's complete allowed-commands set; an action outside it is refused, not merely discouraged. |
| `git_ops` | object | no | Declares that this step produces file output the orchestrator commits. Absent means it does not. |
| `human_gate_after` | boolean | yes | Whether a named gate label is required before downstream steps see this one as satisfied. |
| `human_gate_label` | string | no | Required when human_gate_after is true. |
| `auto_approve_on_complete` | boolean | no | When true and this step completes, the orchestrator applies human_gate_label itself without a human acting. Default: `False`. |
| `self_gates` | boolean | no | When true, the orchestrator trusts this step's own outcome (review vs complete) instead of forcing complete to review. Default: `False`. |
| `review_gate` | boolean | no | Set true only on the step that is the final automated review gate before human merge approval. |
| `review_loop` | object | no | Automatic retry loop: when this step emits review, the orchestrator re-invokes a target step (up to max_cycles) before escalating to human sign-off. |
| `max_retries` | integer | no | How many times the orchestrator retries this step after failed before giving up. Never retries exhausted -- the same step against the same wall is deterministic, so a retry there is waste that costs a full budget to learn nothing. Default: `0`. |
| `session` | object | no | Session management for an agent-type step. |
| `post_steps` | array of string | no | Ordered repo-relative script paths the orchestrator runs after this step's result is recorded. A non-zero exit transitions the step from complete to failed. |
| `description` | string | yes | What this step does, for a person reading pipeline.json. |

**Conditional requirements:**

- When `human_gate_after` is `true`: requires `human_gate_label`.
- When `type` is `"script"`: requires `script`.

### A step -- `trigger`

What makes this step eligible, within a flow its item has already entered. Sequencing (label) and, for a step in a coordinating or self-continuing flow, a condition about the item's own children (PRODUCT.md, 'Coordinating work needs a trigger that can look outward' and 'The same capability lets a step finish its own work in pieces').

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | no | Fires when this label is applied -- ordinarily the previous step's terminal label. |
| `event` | string | no | Fires on a raw GitHub event, for a flow's entry step. |
| `path_filter` | string | no | Glob; modifier on an event trigger. |
| `children` | string | no | all_closed: eligible once every child of this item is closed (the epic wait). any_open: eligible while at least one child remains open (a step re-invoked once per remaining piece, e.g. coder). Both read the same underlying fact about the item's children; which direction a given step needs is the only difference. One of: `all_closed`, `any_open`. |
| `labels` | array of string | no | Additional labels that must all be present for this step to be eligible, beyond whatever fires it (label/event) and whatever its dependencies require -- an AND combination, general to any dimension. This is what lets steps inside one flow vary by a dimension like size without becoming a separate flow: architect declares labels: ['size: L'] so it is eligible only on a large item, even though large-decomposer, the combiner, and every M-only step share the same flow and the same sequencing. `priority:` labels are deliberately never used here -- priority orders pickup, never eligibility (lifecycle.md, 'Priority'). |

### A step -- `expected_effect`

What this step is supposed to change, declared explicitly so the orchestrator can compare it against what actually changed (MI-6). A step declaring no commits that produces one disagrees with itself, and the disagreement is surfaced, not buried -- this is also how a read-only step's constraint (PRODUCT.md, 'What a scheduled step may do is declared') becomes checkable rather than a claim in a prompt.

| Field | Type | Required | Description |
|---|---|---|---|
| `commits` | boolean | yes | Whether this step is expected to change tracked files. true implies git_ops.commit_after is meaningful for this step; a step that produces a commit while declaring false is a step disagreeing with itself. |
| `creates_issues` | boolean | no | Whether this step is expected to raise a new work item -- the shape a step that only looks uses to say what it concluded (PRODUCT.md, 'A scheduled flow reviews'). Default: `False`. |

### A step -- `budgets`

Overrides the top-level budgets default for this step only, field by field: a step declaring only max_turns still inherits max_wall_seconds from the default, and vice versa. Absent entirely means this step uses the default for both. A step can be exhausted by either wall independently: few turns spent on one slow tool call, or many quick turns inside a short time (the design's 'two budgets' discussion) -- which is why an override can target one wall without touching the other.

| Field | Type | Required | Description |
|---|---|---|---|
| `max_turns` | integer | no | Bounds how much back-and-forth this step's invocation is allowed, regardless of how long any of it takes. Agent-type steps only. |
| `max_wall_seconds` | integer | no | Bounds how long this step's invocation may hold the pipeline, regardless of how many turns it took. Reclaims a stranded :wip: a lock older than this cannot still be legitimately running, so the orchestrator takes it back and records failed (PRODUCT.md, 'A step can vanish'). |

### A step -- `git_ops`

Declares that this step produces file output the orchestrator commits. Absent means it does not.

| Field | Type | Required | Description |
|---|---|---|---|
| `commit_after` | boolean | yes | When true the orchestrator stages, commits and pushes after this step's result is recorded. The orchestrator is the only committer in every case -- a step never runs git itself. |
| `commits_to` | string | no | Which of the flow's naming.pull_requests entries this step commits to. Required when the flow declares more than one; omitted when the flow has only its primary branch. |

### A step -- `review_loop`

Automatic retry loop: when this step emits review, the orchestrator re-invokes a target step (up to max_cycles) before escalating to human sign-off.

| Field | Type | Required | Description |
|---|---|---|---|
| `re_invoke` | string | yes | The step to re-invoke. Must be an earlier step in the same flow. |
| `max_cycles` | integer | yes | Retry cycles before escalating to human sign-off. |
| `also_clear` | array of string | no | Other steps whose complete label is also cleared when the loop fires, so intermediate steps re-run. |

### A step -- `session`

Session management for an agent-type step.

| Field | Type | Required | Description |
|---|---|---|---|
| `scope` | string | yes | per_issue -- a distinct session for each work item; default ID ais-v1-{safe_agent}-issue-{number}. global -- one persistent session shared across every invocation of this agent; default ID ais-v1-{safe_agent}. Use global for agents that benefit from context accumulated across issues (e.g. a doc reviewer). One of: `per_issue`, `global`. |
| `id_pattern` | string | no | Optional token pattern for the session ID; the built-in default for the chosen scope is used when omitted. Available tokens: {agent}, {safe_agent}, {phase}, {safe_phase}, {number}, {kind}, {owner}, {repo_name}, {safe_repo} -- only bare {identifier} placeholders are accepted, not attribute or index access. {title} and {url} are deliberately excluded: titles are human-authored and change over time, and both contain characters unsafe in a session ID. On a retry the orchestrator appends -r{attempt} to the seed before deriving the session's UUID, giving each retry attempt a distinct session. |
