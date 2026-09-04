#!/usr/bin/env bash
# commit-agent-work.sh — stages, commits, and pushes agent-written files to
# the issue branch.  Invoked as a post_steps entry in pipeline.json after a
# commit_after agent signals complete.
#
# Required env:
#   AGENT_NAME   — fully-qualified agent name (e.g. 03_execute/coder)
#   ISSUE_NUMBER — issue number
#   AI_AGILE_BRANCH — the branch to commit to, resolved by the orchestrator
#                     from the step's flow naming in pipeline.json (issue #406).
#                     Never derived here: a branch name is declared, not computed.
#   GITHUB_TOKEN or GH_TOKEN — for git auth (contents:write scope)
#
# Optional env:
#   AI_AGILE_BOT_TOKEN — classic PAT with repo+workflow scopes;
#                        required when the agent wrote .github/workflows/ files.

set -euo pipefail

AGENT_NAME="${AGENT_NAME:?AGENT_NAME is required}"
ISSUE_NUMBER="${ISSUE_NUMBER:?ISSUE_NUMBER is required}"
BRANCH="${AI_AGILE_BRANCH:?AI_AGILE_BRANCH is required -- the branch declared by this step flow naming}"

# ---------------------------------------------------------------------------
# Git auth — set GIT_CONFIG env vars so every git operation in this process
# authenticates with GITHUB_TOKEN (contents:write scope). The token is never
# embedded in a URL, keeping it out of `git remote -v`, `ps`, and CI logs.
# GitHub git transport uses HTTP Basic auth; format: base64("x-access-token:TOKEN").
# ---------------------------------------------------------------------------
_GITHUB_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [[ -z "$_GITHUB_TOKEN" ]]; then
    echo "WARNING: no GITHUB_TOKEN or GH_TOKEN — git push may fail" >&2
else
    # base64 -w 0 (GNU) suppresses line-wrapping; macOS base64 has no -w flag.
    _ENCODED=$(printf 'x-access-token:%s' "$_GITHUB_TOKEN" \
        | base64 -w 0 2>/dev/null \
        || printf 'x-access-token:%s' "$_GITHUB_TOKEN" | base64)
    # Remove any extraHeader written by actions/checkout into .git/config.
    # Without this, git collects both entries and sends two Authorization
    # headers, causing HTTP 400.
    git config --local --unset-all "http.https://github.com/.extraHeader" 2>/dev/null || true
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0="http.https://github.com/.extraHeader"
    export GIT_CONFIG_VALUE_0="Authorization: Basic ${_ENCODED}"
fi

# ---------------------------------------------------------------------------
# Check for working-tree changes
# ---------------------------------------------------------------------------
DIRTY=$(git status --porcelain)
if [[ -z "$DIRTY" ]]; then
    echo "commit-agent-work: no working-tree changes — skipping commit for ${AGENT_NAME} on issue #${ISSUE_NUMBER}"
    exit 0
fi

# ---------------------------------------------------------------------------
# Git identity
# ---------------------------------------------------------------------------
git config user.email "github-actions[bot]@users.noreply.github.com"
git config user.name "github-actions[bot]"

# ---------------------------------------------------------------------------
# Save current branch; restore it on exit even if an error fires midway.
# ---------------------------------------------------------------------------
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
STASHED=0

_cleanup() {
    git checkout "${CURRENT_BRANCH}" 2>/dev/null || true
    # Preserve the stash on failure so agent work is not silently lost.
    # If STASHED is still 1 here, an intermediate step failed before STASHED=0
    # was reached (line after stash pop). The stash entry holds the agent's
    # uncommitted work; drop it only on clean success (STASHED set to 0 by caller).
    if [[ "${STASHED}" -eq 1 ]]; then
        echo "commit-agent-work: WARNING: exiting with stash entry preserved — agent work is in stash 'commit_after:${AGENT_NAME}:${BRANCH}'. Inspect with 'git stash list'; drop manually after investigation." >&2
    fi
}
trap _cleanup EXIT

# ---------------------------------------------------------------------------
# Stash all working-tree changes (staged + unstaged + untracked)
# ---------------------------------------------------------------------------
git stash push --include-untracked -m "commit_after:${AGENT_NAME}:${BRANCH}"
STASHED=1

# ---------------------------------------------------------------------------
# Switch to issue branch, resetting to remote state so the push is always
# a fast-forward (prevents non-fast-forward rejections from a stale local ref).
# ---------------------------------------------------------------------------
git fetch origin "${BRANCH}"
git checkout -B "${BRANCH}" "origin/${BRANCH}"

# Capture which files the agent wrote before popping the stash, so we add
# only those files rather than any unrelated working-tree noise.
_stash_show_out=$(git stash show --name-only -u 2>/dev/null)
_stash_show_rc=$?
STASH_FILES="$_stash_show_out"
if [[ $_stash_show_rc -ne 0 && -z "$STASH_FILES" ]]; then
    echo "commit-agent-work: WARNING: git stash show failed (rc=$_stash_show_rc) — falling back to git add -A" >&2
fi

git stash pop
STASHED=0

# ---------------------------------------------------------------------------
# Remove gitignored files that were inadvertently tracked on this branch.
# Runs after stash pop so the full index state is visible. Silently no-ops
# when no such files exist.
# ---------------------------------------------------------------------------
GITIGNORED_TRACKED=$(git ls-files --cached -i --exclude-standard 2>/dev/null || true)
if [[ -n "$GITIGNORED_TRACKED" ]]; then
    echo "commit-agent-work: removing gitignored tracked files"
    while IFS= read -r ignored_file; do
        [[ -n "$ignored_file" ]] && git rm --cached -- "$ignored_file"
    done <<< "$GITIGNORED_TRACKED"
fi

# ---------------------------------------------------------------------------
# Stage agent-written files
# ---------------------------------------------------------------------------
if [[ -n "$STASH_FILES" ]]; then
    # Read file list line-by-line to handle names with spaces correctly.
    while IFS= read -r stash_file; do
        [[ -n "$stash_file" ]] && git add -- "$stash_file"
    done <<< "$STASH_FILES"
else
    git add -A
fi

# ---------------------------------------------------------------------------
# Refuse to commit a NEW file at the repo root (issue #321).
#
# The scratch convention tells agents to write working files under
# $AI_AGILE_SCRATCH, and every agent prompt carries the rule. Instruction is
# not enforcement: a bare filename still resolves against the repo root,
# because that is the working directory, so a leak is always one invented
# filename away. That is how pr_review_328.txt reached a commit on issue-316,
# and how artefact_comment.txt and closing_comment.txt reached d0471f1.
#
# This is the enforcement half, and it does not depend on agent compliance:
# a newly-added file at depth 0 is unstaged before the commit is written.
# Modifications to files already tracked at the root are untouched -- CLAUDE.md,
# README.md and .gitignore are legitimate edit targets. The file is left on
# disk rather than deleted, so nothing an agent produced is destroyed and the
# violation stays visible.
# ---------------------------------------------------------------------------
ROOT_ADDITIONS=$(git diff --cached --name-only --diff-filter=A -- ':(top)*' \
    | grep -v '/' || true)
if [[ -n "$ROOT_ADDITIONS" ]]; then
    echo "commit-agent-work: ERROR: ${AGENT_NAME} created new file(s) at the repo root." >&2
    echo "commit-agent-work: working files belong under \$AI_AGILE_SCRATCH (see .claude/AGENTS.md)." >&2
    echo "commit-agent-work: unstaging them; they are left on disk, not committed:" >&2
    while IFS= read -r root_file; do
        [[ -n "$root_file" ]] || continue
        echo "commit-agent-work:   $root_file" >&2
        git restore --staged -- "$root_file" 2>/dev/null || git rm --cached -- "$root_file" >/dev/null
    done <<< "$ROOT_ADDITIONS"
fi

# Everything the agent legitimately wrote may now be gone from the index.
if [[ -z "$(git diff --cached --name-only)" ]]; then
    echo "commit-agent-work: nothing left to commit after the root-file guard -- skipping"
    exit 0
fi

# ---------------------------------------------------------------------------
# Detect .github/workflows/ files — GITHUB_TOKEN cannot push them.
# AI_AGILE_BOT_TOKEN (classic PAT with repo+workflow scopes) is used instead.
# ---------------------------------------------------------------------------
WORKFLOW_FILES=$(git diff --cached --name-only -- .github/workflows/ 2>/dev/null || true)
_BOT_TOKEN="${AI_AGILE_BOT_TOKEN:-}"
if [[ -n "$WORKFLOW_FILES" ]]; then
    if [[ -z "$_BOT_TOKEN" ]]; then
        echo "ERROR: agent wrote .github/workflows/ files but AI_AGILE_BOT_TOKEN is not set." >&2
        echo "GITHUB_TOKEN cannot push workflow files — add AI_AGILE_BOT_TOKEN as a classic PAT with repo+workflow scopes." >&2
        exit 1
    fi
    echo "commit-agent-work: workflow files staged — using AI_AGILE_BOT_TOKEN for push"
fi

# Guard: if the staging area is empty after stash pop, there is nothing to
# commit (agent found no changes to write).
if git diff --cached --quiet; then
    echo "commit-agent-work: staging area empty after stash pop — skipping commit for ${AGENT_NAME}"
    exit 0
fi

# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------
COMMIT_MSG="[agent] ${AGENT_NAME} — issue #${ISSUE_NUMBER}"
git commit -m "${COMMIT_MSG}"

# ---------------------------------------------------------------------------
# Push — use AI_AGILE_BOT_TOKEN when workflow files are staged (requires the
# workflow scope that GITHUB_TOKEN lacks), otherwise use the default auth set
# up above.
# ---------------------------------------------------------------------------
if [[ -n "$WORKFLOW_FILES" ]] && [[ -n "$_BOT_TOKEN" ]]; then
    _PUSH_ENCODED=$(printf 'x-access-token:%s' "$_BOT_TOKEN" \
        | base64 -w 0 2>/dev/null \
        || printf 'x-access-token:%s' "$_BOT_TOKEN" | base64)
    GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="http.https://github.com/.extraHeader" \
    GIT_CONFIG_VALUE_0="Authorization: Basic ${_PUSH_ENCODED}" \
    git push origin "${BRANCH}"
else
    git push origin "${BRANCH}"
fi

echo "commit-agent-work: pushed commit to ${BRANCH}"
