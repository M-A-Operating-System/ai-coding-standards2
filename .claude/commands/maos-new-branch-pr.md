# maos-new-branch-pr

Create the shared issue branch and open a draft PR for an issue, linking it via `Closes #N`.

This mirrors `.github/scripts/create-pr.sh` (the `01_product_docs/create-pr` scripted
pipeline step, which normally runs right after `prd-writer:approved`) for interactive use.
That script depends on the `gh` CLI, which isn't available in this environment — the
steps below do the same thing with `git` and the GitHub MCP tools instead.

Idempotent: if a branch/PR already exists for the issue, this skips straight to
verifying the announcement comment rather than recreating anything.

## Input

`$ARGUMENTS` — the issue number (e.g. `42`)

## Instructions

1. **Determine the repo.** Use the repo already in scope for this session (or derive
   `owner/repo` from `git remote get-url origin` if ambiguous).

2. **Check for an existing PR first.** Call `mcp__github__list_pull_requests` filtered
   by `head: "{owner}:issue-{N}"` and `state: open`. If one is already open, skip to
   step 7 (comment check) — do not create a second branch or PR for the same issue
   (STD-PROC-001/002: one issue = one branch = one draft PR).

3. **Create the branch from the default branch, with a placeholder commit.**
   ```bash
   git fetch origin <default-branch>
   git checkout <default-branch>
   git pull origin <default-branch>
   git checkout -b issue-{N}
   git commit --allow-empty -m "chore: open branch for issue-{N}"
   git push -u origin issue-{N}
   ```
   Determine `<default-branch>` from the repo (normally `main`). If `issue-{N}` already
   exists locally or on the remote, do not overwrite it — that likely means an earlier
   run left agent work on it; stop and tell the user rather than force-pushing.

4. **Get the issue title** (via `mcp__github__issue_read`, method `get`) to build the PR
   title: `issue-{N}: {title}`, where `{title}` is truncated to its first 60 characters
   *before* the `"issue-{N}: "` prefix is added — matching `create-pr.sh`'s exact
   `${ISSUE_TITLE:0:60}` behavior. The prefix is not counted against the 60, so the final
   title is longer than 60 characters once it's prepended.

5. **Open the draft PR** via `mcp__github__create_pull_request`:
   - `title`: from step 4
   - `head`: `issue-{N}`
   - `base`: `<default-branch>`
   - `draft`: `true`
   - `body`: `Closes #{N}` (this is what creates GitHub's Development-sidebar link
     between the PR and the issue)

6. **Apply the `source-issue:{N}` label to the PR**, matching `link-pr-to-issue.sh`.
   The GitHub MCP toolset has no label-creation tool — if `source-issue:{N}` doesn't
   already exist as a repo label, skip this step and say so rather than failing; don't
   invent a workaround.

7. **Post the announcement comment on the issue** (idempotent — check via
   `mcp__github__issue_read` method `get_comments` whether a comment containing
   `01_product_docs/create-pr` already exists before posting):
   ```
   <!-- ai-agile/announcement/v1 by 01_product_docs/create-pr -->
   Draft PR opened for this issue: [#{PR_NUMBER}](https://github.com/{owner}/{repo}/pull/{PR_NUMBER})
   ```

8. **Report the result** to the user: PR number, URL, and branch name.

## Fallback

If GitHub MCP tools are not available, inform the user:
```
GitHub MCP tools are not connected. To create branches and PRs, ensure the GitHub MCP
server is configured in your Claude Code settings.
```
