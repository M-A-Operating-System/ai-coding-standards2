# Release Flow Migration: GitHub Actions to Orchestrator

## What changed

Before this change the weekly release was cut by the `RELEASE - publish`
GitHub Actions workflow (`.github/workflows/release.yml`) firing on a
Wednesday 09:00 UTC schedule. The `RELEASE - publish` workflow
independently determined the release tag, generated notes, and published the
GitHub Release.

After this change (issue #621) the orchestrator's `weekly-release` flow
(`pipeline/pipeline.json`) is the production release owner. It runs
`scripts/run-release-flow.sh` on its Wednesday cadence and publishes the
GitHub Release. The `RELEASE - publish` workflow's schedule trigger has been
removed so it no longer independently publishes releases.

## Migration steps completed

1. `scripts/run-release-flow.sh` implemented and validated (#620).
2. `scripts/shadow_compare.py` implemented and validated (#603). Shadow-run
   comparison ran via the `RELEASE - publish` workflow to confirm that the
   Python generator's output matches the GitHub-generated notes before cutover.
3. The `weekly-release` flow added to `pipeline/pipeline.json` with a
   Wednesday cron trigger and `scripts/run-release-flow.sh` as the script step.
4. The `schedule` trigger removed from `.github/workflows/release.yml` (this
   change). The workflow still fires on `push: tags: v*` for off-cycle
   releases and on `workflow_dispatch` for emergency manual releases.

## Triggers after cutover

| Trigger | Owner | When |
|---|---|---|
| Weekly Wednesday release | Orchestrator (`weekly-release` flow) | Wednesday, approx. 09:00 Eastern via the pipeline's twice-daily sweep |
| Off-cycle tag push (`v*`) | `RELEASE - publish` workflow | Human pushes an explicit vX.Y.Z tag |
| Emergency manual release | `RELEASE - publish` workflow (`workflow_dispatch`) | Human dispatches via GitHub Actions UI |

## Manual dispatch and retry

To manually trigger the weekly release flow via the orchestrator:

1. In GitHub Actions, run **AI - Orchestrator** (`workflow_dispatch`) -- no
   issue number needed. The orchestrator's `_run_scheduled_flows` function
   evaluates due-ness from the metrics record and runs the `weekly-release`
   flow if it is overdue.

To run `run-release-flow.sh` directly (e.g. in a local debug session):

```bash
REPO=owner/repo GH_TOKEN=<token> bash scripts/run-release-flow.sh
```

The script is idempotent: a re-run with an existing tag exits `skipped`
without creating a duplicate release.

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
