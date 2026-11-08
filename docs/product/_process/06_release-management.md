# Release Management

Release management follows [AI-Agile implementation](04_ai-agile-implementation.md).
It takes approved, merged changes and publishes an eligible set as a versioned
GitHub Release. The release notes connect what shipped to the merged pull
requests and associated issues.

## Inputs, checks, and outputs

The weekly flow starts from the most recent published GitHub Release and finds
merged pull requests and their associated closed issues since that release.
It applies the configured exclusions and coverage threshold. A run with no
eligible changes records that outcome. An existing release tag is skipped,
and a failed publication check is recorded for review.

When the checks pass, the flow generates Markdown release notes and publishes
a GitHub Release. It records the release metadata and run outcome so a
maintainer can trace what was published or see why publication stopped.

## Release paths

| Release path | Owner | Trigger |
| --- | --- | --- |
| Scheduled weekly release | AI Agile orchestrator, `weekly-release` | Wednesday schedule in [`pipeline/pipeline.json`](../../../pipeline/pipeline.json) |
| Off-cycle tagged release | [RELEASE - publish](../../../.github/workflows/release.yml) | A maintainer pushes an explicit `vX.Y.Z` tag |
| Emergency manual release | [RELEASE - publish](../../../.github/workflows/release.yml) | A maintainer dispatches the workflow manually |

## Manual dispatch and retry

To request a run of the standard release process, dispatch **AI - Orchestrator**
in GitHub Actions without an issue number. The orchestrator checks whether the
weekly flow is due before running it.

For local debugging, set `GH_TOKEN` to an authorized GitHub token and run
the release script from the repository root.

```bash
REPO=owner/repo bash scripts/run-release-flow.sh
```

A retry with an existing release tag skips publication, so rerunning the
flow does not create a duplicate release.

## Migration history

The weekly schedule moved from `RELEASE - publish` to the orchestrator in
[#621](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/621).
The cutover followed implementation of the release script in
[#620](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/620)
and a shadow comparison of generated notes in
[#603](https://github.com/M-A-Operating-System/ai-coding-standards2/issues/603).
The legacy workflow retains its explicit-tag and emergency manual paths.

## Rollback plan

To revert production release ownership back to the GitHub Actions workflow:

1. Re-add the `schedule` trigger to `.github/workflows/release.yml`:
   ```yaml
   schedule:
     - cron: '0 9 * * 3'  # 09:00 UTC on Wednesdays
   ```
2. Remove or disable the `weekly-release` flow from `pipeline/pipeline.json`
   by deleting its entry from the `flows` object.
3. Open and merge the change. The `RELEASE - publish` workflow resumes the
   Wednesday cadence on the next tick.

No data migration is needed: both paths read the latest published GitHub
Release to determine the window start, so switchover and rollback are
window-boundary safe.
