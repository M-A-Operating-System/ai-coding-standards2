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
   Python generator's output matched the GitHub-generated notes before
   cutover. Removed after cutover, once that parity was confirmed — the thing
   it validated against (the old scheduled run) no longer exists to compare
   against.
3. The `weekly-release` flow added to `pipeline/pipeline.json` with a
   Wednesday cron trigger and `scripts/run-release-flow.sh` as the script step.
4. `.github/workflows/release.yml` removed entirely (issue #695), once the
   orchestrator's `weekly-release` flow was verified in production. Its
   off-cycle `push: tags: v*` and emergency `workflow_dispatch` paths were
   retired along with it, not retained.

## Triggers after cutover

| Trigger | Owner | When |
|---|---|---|
| Weekly Wednesday release | Orchestrator (`weekly-release` flow) | Wednesday, approx. 09:00 Eastern via the pipeline's twice-daily sweep |
| PR merge to `main` (PATCH bump) | Orchestrator (`05_continuous/pr/patch-tag` step) | Immediately on `pull_request.closed` with `merged: true`; `scripts/push-patch-tag.sh` bumps the PATCH version; skipped if HEAD is already tagged |
| Off-cycle or emergency release | None | `RELEASE - publish` workflow removed (issue #695); the orchestrator's `weekly-release` flow is the sole remaining path |

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

To revert production release ownership back to a GitHub Actions workflow:

1. Restore `.github/workflows/release.yml` from the commit that removed it
   (issue #695), with its `schedule` trigger re-added:
   ```yaml
   schedule:
     - cron: '0 9 * * 3'  # 09:00 UTC on Wednesdays
   ```
2. Remove or disable the `weekly-release` flow from `pipeline/pipeline.json`
   by deleting its entry from the `flows` object.
3. Open and merge the change. The restored workflow resumes the Wednesday
   cadence on the next tick.

No data migration is needed: both paths read the latest published GitHub
Release to determine the window start, so switchover and rollback are
window-boundary safe.
