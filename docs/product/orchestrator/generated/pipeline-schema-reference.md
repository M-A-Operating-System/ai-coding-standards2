<!-- GENERATED FILE -- DO NOT EDIT.
     Source: docs/product/orchestrator/schema/pipeline.schema.json
     Generator: pipeline/generators/generate_schema_reference.py
     Regenerate: python3 pipeline/generators/generate_schema_reference.py -->

# Target Pipeline Schema

The target shape of pipeline.json, as decided in docs/product/orchestrator/PRODUCT.md (issue #393). Not yet live: pipeline/schemas/pipeline.schema.json governs the current pipeline.json and is unaffected by this file. The two files that compose against each other -- the framework's shipped pipeline/pipeline.json and a repository's own pipeline/pipeline.json -- both validate against this same schema (PRODUCT.md, 'A repository may have its own').

This is the target. `pipeline/schemas/pipeline.schema.json` governs
the pipeline.json that exists today; see
[`gap_analysis.md`](../gap_analysis.md) for the distance between them.

## Top level

| Field | Type | Required | Description |
|---|---|---|---|
| `$schema` | string | no |  |
| `defaults` | object | no | Pipeline-wide defaults merged into every step. Unaffected by the flow work in PRODUCT.md; carried over from the current schema. |
| `budgets` | object | no | Pipeline-wide consumption limits that are not properties of any one step. See PRODUCT.md 'Working on several things at once'. |
| `flows` | object | yes | Every flow the pipeline runs, keyed by a stable flow name. A repository's own pipeline/pipeline.json names the flows it adds or replaces; a flow it does not name is inherited from the shipped default unchanged. Precedence is per flow, not per file (PRODUCT.md, AS-1): a named flow replaces the shipped one wholesale, everything else keeps tracking the default. |

## A flow

| Field | Type | Required | Description |
|---|---|---|---|
| `description` | string | yes | What kind of work this is and why it is its own flow. |
| `trigger` | object (one of) | yes | What makes a work item this flow's, or what makes the flow itself fire. Exactly one shape: item membership (kind, with optional classification and label) for work that produces change or coordinates other work, or a schedule for work with no triggering item (PRODUCT.md, 'Three shapes a flow can take'). Selection is positive: a step or flow with no matching criterion is simply not entered -- there is no exclude_labels or exclude_classifications to forget. |
| `naming` | object | no | What this flow's branches and pull requests are called. Declared here, never computed in orchestrator code (AS-1) -- which is what makes more than one branch or pull request per item expressible, for flows like two-phase design-to-build (04-lifecycle.md) that need it. Absent for a flow whose steps never commit. |
| `steps` | array of object | yes | This flow's steps, in execution order. |

### A flow -- `trigger`

What makes a work item this flow's, or what makes the flow itself fire. Exactly one shape: item membership (kind, with optional classification and label) for work that produces change or coordinates other work, or a schedule for work with no triggering item (PRODUCT.md, 'Three shapes a flow can take'). Selection is positive: a step or flow with no matching criterion is simply not entered -- there is no exclude_labels or exclude_classifications to forget.

Exactly one of the following shapes:

**Shape 1:**

| Field | Type | Required | Description |
|---|---|---|---|
| `kind` | string | yes | Which GitHub object kind this flow processes. One of: `issue`, `pr`. |
| `classification` | array of string | no | Restrict this flow to these classifications. Absent means every classification -- this is the one place classification is allowed to change what runs; see AS-1, 'Selection by classification'. |
| `label` | string | no | Restrict this flow to items carrying this label (e.g. 'epic'). Absent means no label restriction. |

**Shape 2:**

| Field | Type | Required | Description |
|---|---|---|---|
| `schedule` | string | yes | Cron expression. This flow has no triggering work item; it fires on cadence and, if it concludes something is needed, raises one (PRODUCT.md, 'Scheduled work'). Due-ness is derived from the record (when this flow's steps last appended an entry), never stored separately. |

### A flow -- `naming`

What this flow's branches and pull requests are called. Declared here, never computed in orchestrator code (AS-1) -- which is what makes more than one branch or pull request per item expressible, for flows like two-phase design-to-build (04-lifecycle.md) that need it. Absent for a flow whose steps never commit.

| Field | Type | Required | Description |
|---|---|---|---|
| `branch` | string | yes | Token pattern for this flow's primary branch, e.g. 'issue-{number}'. |
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
| `budgets` | object | no | This step's own consumption limits, declared here and nowhere else (AS-1) -- not a module constant applying to every step alike. A step can be exhausted by either wall independently: few turns spent on one slow tool call, or many quick turns inside a short time (the design's 'two budgets' discussion). Required for an agent-type step; a script-type step needs only max_wall_seconds. |
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

### A step -- `trigger`

What makes this step eligible, within a flow its item has already entered. Sequencing (label) and, for a step in a coordinating or self-continuing flow, a condition about the item's own children (PRODUCT.md, 'Coordinating work needs a trigger that can look outward' and 'The same capability lets a step finish its own work in pieces').

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | no | Fires when this label is applied -- ordinarily the previous step's terminal label. |
| `event` | string | no | Fires on a raw GitHub event, for a flow's entry step. |
| `path_filter` | string | no | Glob; modifier on an event trigger. |
| `children` | string | no | all_closed: eligible once every child of this item is closed (the epic wait). any_open: eligible while at least one child remains open (a step re-invoked once per remaining piece, e.g. coder). Both read the same underlying fact about the item's children; which direction a given step needs is the only difference. One of: `all_closed`, `any_open`. |

### A step -- `expected_effect`

What this step is supposed to change, declared explicitly so the orchestrator can compare it against what actually changed (MI-6). A step declaring no commits that produces one disagrees with itself, and the disagreement is surfaced, not buried -- this is also how a read-only step's constraint (PRODUCT.md, 'What a scheduled step may do is declared') becomes checkable rather than a claim in a prompt.

| Field | Type | Required | Description |
|---|---|---|---|
| `commits` | boolean | yes | Whether this step is expected to change tracked files. true implies git_ops.commit_after is meaningful for this step; a step that produces a commit while declaring false is a step disagreeing with itself. |
| `creates_issues` | boolean | no | Whether this step is expected to raise a new work item -- the shape a step that only looks uses to say what it concluded (PRODUCT.md, 'A scheduled flow reviews'). Default: `False`. |

### A step -- `budgets`

This step's own consumption limits, declared here and nowhere else (AS-1) -- not a module constant applying to every step alike. A step can be exhausted by either wall independently: few turns spent on one slow tool call, or many quick turns inside a short time (the design's 'two budgets' discussion). Required for an agent-type step; a script-type step needs only max_wall_seconds.

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
| `scope` | string | yes | One of: `per_issue`, `global`. |
| `id_pattern` | string | no | Optional token pattern for the session ID; the built-in default for the chosen scope is used when omitted. |
