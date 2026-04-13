# Agent Todo Standard

Shared instructions for all agents to track progress using persistent todo files.
Any agent definition can reference this file to adopt the standard.

---

## Todo File Location

Each agent maintains its own todo file at:

```
.claude/todos/<agent-name>.todo
```

Example: `.claude/todos/reverse-doc.todo`

## Todo File Format

The file uses a line-oriented format. Each task is a single line:

```
[status] - Raised: MM/DD/YY | <action description> | Completed: MM/DD/YY
```

### Status Markers

| Marker | Meaning |
|--------|---------|
| `[ ]`  | Pending — not yet started |
| `[~]`  | In progress — currently being worked on |
| `[X]`  | Completed |
| `[!]`  | Blocked — cannot proceed, needs attention |
| `[-]`  | Skipped — intentionally not done (with reason) |

### Line Format

```
[X] - Raised: 04/09/26 | Document src/lib/dag-types.ts | Completed: 04/09/26
[X] - Raised: 04/09/26 | Document src/lib/dag-parser.ts | Completed: 04/09/26
[~] - Raised: 04/09/26 | Document src/components/WizardRunner.tsx |
[ ] - Raised: 04/09/26 | Document src/components/DslEditor.tsx |
[!] - Raised: 04/09/26 | Document src/utils/legacy.ts | Blocked: file appears unused, raised issue #12
[-] - Raised: 04/09/26 | Document dist/bundle.js | Skipped: build output, not source
```

### Rules

- **Completed** field is only present when status is `[X]`.
- **Blocked** items append a reason after `Blocked:` instead of `Completed:`.
- **Skipped** items append a reason after `Skipped:` instead of `Completed:`.
- Dates use `MM/DD/YY` format.
- One task per line. No multi-line entries.
- Lines starting with `#` are section headers (not tasks).

## File Structure

The todo file is organized into sections:

```
# <Agent Name> — Task Tracker
# Last updated: MM/DD/YY

## Current Run
[~] - Raised: 04/09/26 | Document src/components/WizardRunner.tsx |
[ ] - Raised: 04/09/26 | Document src/components/DslEditor.tsx |
[ ] - Raised: 04/09/26 | Document src/components/TreeRenderer.tsx |
[ ] - Raised: 04/09/26 | Document src/components/EmbedModal.tsx |
[ ] - Raised: 04/09/26 | Document src/components/PathVisualisation.tsx |

## Completed
[X] - Raised: 04/09/26 | Document src/lib/dag-types.ts | Completed: 04/09/26
[X] - Raised: 04/09/26 | Document src/lib/dag-parser.ts | Completed: 04/09/26
[X] - Raised: 04/09/26 | Document src/lib/dag-engine.ts | Completed: 04/09/26
[X] - Raised: 04/09/26 | Document src/lib/embed-utils.ts | Completed: 04/09/26
[X] - Raised: 04/09/26 | Document src/hooks/useWizard.ts | Completed: 04/09/26

## Backlog
[ ] - Raised: 04/09/26 | Document src/App.tsx |
[ ] - Raised: 04/09/26 | Document backend/file-api.js |

## Issues Raised
[X] - Raised: 04/09/26 | GitHub issue #42: Unused export in embed-utils.ts | Completed: 04/09/26
```

## Agent Workflow

### At the start of each run:

1. **Read** `.claude/todos/<agent-name>.todo` (if it exists).
2. Check for `[~]` in-progress items from a previous interrupted run — resume or reset them.
3. Move completed items from `## Current Run` to `## Completed`.
4. Select the next block of tasks from `## Backlog` and move them to `## Current Run`.
5. If no backlog exists, discover new tasks and populate the backlog.

### During processing:

6. Before starting a task, mark it `[~]` and write the file.
7. After completing a task, mark it `[X]` with today's date and write the file.
8. If a task is blocked, mark it `[!]` with the reason and write the file.
9. If a task should be skipped, mark it `[-]` with the reason and write the file.

### At the end of each run:

10. Move all `[X]` items from `## Current Run` to `## Completed`.
11. Update the `# Last updated:` timestamp.
12. Write the final state of the file.

## Summary Stats

Agents should print a summary derived from the todo file at the end of each run:

```
Tasks: 5 completed, 0 blocked, 12 remaining
Issues raised: 1
```

---

## Issue Key Standard

All agents MUST generate an **immutable issue key** when raising GitHub issues to prevent duplicates.

### Key Format

```
<AGENT>-<CATEGORY>-<HASH>
```

- `<AGENT>` — uppercase agent name (e.g., `REVDOC`, `FACTORY`, `LINT`)
- `<CATEGORY>` — short category code for the finding type:
  - `DEAD` — dead code / unused export
  - `BUG` — potential bug
  - `SEC` — security concern
  - `PERF` — performance issue
  - `TYPE` — type safety issue
  - `STYLE` — code style / convention
  - `MISS` — missing implementation (error handling, tests, etc.)
  - `STALE` — stale / outdated code
  - `GEN` — general observation
- `<HASH>` — short deterministic hash derived from: `file-path + finding-description`. Use the first 6 characters of a hex-encoded hash. The same file + finding must always produce the same hash.

### Examples

```
REVDOC-DEAD-a3f2c1
REVDOC-BUG-7e9b04
LINT-STYLE-d12f88
```

### GitHub Issue Title Format

```
[<agent-name>] - <KEY> - <short description>
```

Examples:
```
[reverse-doc] - REVDOC-DEAD-a3f2c1 - Unused export `legacyParser` in dag-parser.ts
[reverse-doc] - REVDOC-BUG-7e9b04 - Missing null check in advance() for edge case
[lint-agent] - LINT-STYLE-d12f88 - Inconsistent naming convention in utils/
```

### Duplicate Prevention

Before creating a GitHub issue, the agent MUST:
1. Generate the issue key from the file path and finding description.
2. Search existing issues for that key (use `mcp__github__search_issues` or `Grep` the `## Issues Raised` section of the todo file).
3. If the key already exists — **skip creating the issue**. Optionally add a comment to the existing issue if new context is available.
4. If the key does not exist — create the issue and record the key in the todo file under `## Issues Raised`.

### Recording in Todo File

When an issue is raised, record it with its key:

```
## Issues Raised
[X] - Raised: 04/09/26 | REVDOC-DEAD-a3f2c1 | GitHub #42: Unused export in embed-utils.ts | Completed: 04/09/26
[ ] - Raised: 04/10/26 | REVDOC-BUG-7e9b04 | GitHub #45: Missing null check in advance() |
```

The key column makes it trivial to grep for duplicates before raising a new issue.

---

## Issue Label Standard — Agent Status Tags

All agents MUST maintain a status label on every GitHub issue they own. Labels track which agent raised the issue and its current status.

### Label Format

```
<agent-name>: <status>
```

### Valid Statuses

| Status | Meaning |
|--------|---------|
| `new` | Just created, not yet being worked on |
| `wip` | Work in progress — someone or an agent is actively on it |
| `blocked` | Cannot proceed — waiting on a dependency or external input |
| `review` | Work is done, awaiting review or verification |
| `na` | Not applicable — closed, resolved, or no longer relevant |

### Examples

```
reverse-doc: new
reverse-doc: wip
lint-agent: blocked
test-runner: review
user: na
```

### Rules

1. **On issue creation**: apply `<agent-name>: new`.
2. **When work begins**: replace with `<agent-name>: wip`.
3. **When blocked**: replace with `<agent-name>: blocked`.
4. **When work is done**: replace with `<agent-name>: review`.
5. **On issue close**: replace with `<agent-name>: na`.
6. **Only one status label per agent per issue.** When updating, remove the old status label before adding the new one.
7. **Multiple agents may label the same issue** if they both have a stake. Each agent manages only its own `<agent-name>: <status>` label.
8. **Agents must update their label whenever they interact with the issue** — every audit comment should be accompanied by the correct label state.
