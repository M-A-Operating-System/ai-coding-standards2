#!/usr/bin/env bash
# append-metrics-record.sh -- append one record to the metrics ledger.
#
# Usage: append-metrics-record.sh <path-to-record-line>
#
# <path-to-record-line> holds the record EXACTLY as it should appear in
# records.jsonl: one compact JSON object, newline-terminated. Deciding what
# goes in a record is the orchestrator's business -- it knows the step, the
# outcome and the timing. Writing it to the ledger is not, so the git plumbing
# that does the writing lives here (AS-2, issue #407); it was inline Python in
# pipeline_orchestrator.py (_append_metrics_record) until then.
#
# NOT a pipeline step -- does not emit AI_AGILE_STATUS:.
#
# Plain git plumbing rather than the GitHub Contents API: some restricted
# sessions (e.g. an interactive Claude Code session) 403 on a direct Contents
# API PUT even though `git push` over the same HTTPS credential helper
# succeeds. Object and ref operations never touch the working tree or the real
# index -- a scratch GIT_INDEX_FILE is used -- so this is safe to run while
# another branch is checked out.
#
# The append IS the compare-and-swap the scheduled-flow mutex relies on: the
# commit is built on the fetched tip and pushed, so a concurrent writer's push
# rejects rather than clobbers. A rejection is retried against the new tip.
#
# Required env:
#   AI_AGILE_METRICS_BRANCH          -- the orphan branch holding the ledger
#   AI_AGILE_METRICS_FILE            -- the ledger path on that branch
#   AI_AGILE_METRICS_COMMIT_MESSAGE  -- the commit message for this append
#
# Optional env:
#   AI_AGILE_METRICS_RETRIES         -- push retries on rejection (default 2)

set -euo pipefail

RECORD_FILE="${1:?usage: append-metrics-record.sh <path-to-record-line>}"
BRANCH="${AI_AGILE_METRICS_BRANCH:?AI_AGILE_METRICS_BRANCH is required}"
RECORDS_FILE="${AI_AGILE_METRICS_FILE:?AI_AGILE_METRICS_FILE is required}"
COMMIT_MESSAGE="${AI_AGILE_METRICS_COMMIT_MESSAGE:?AI_AGILE_METRICS_COMMIT_MESSAGE is required}"
RETRIES="${AI_AGILE_METRICS_RETRIES:-2}"

if [[ ! -f "$RECORD_FILE" ]]; then
    echo "append-metrics-record: ERROR: no record at ${RECORD_FILE}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Git auth: a url.insteadOf rewrite embeds the credential in the remote URL
# before git attempts username resolution, so git never reaches the credential
# subsystem (issue #717 -- http.extraHeader was silently bypassed because git
# resolves a username before it checks any extra headers). The credential lives
# only in GIT_CONFIG_* env vars, never written to .git/config on disk.
# Which token is the identity question, and lib/github-identity.sh answers it
# once for every script (MI-7). When no token is set at all the checkout's
# own credential helper is left to do the work.
# ---------------------------------------------------------------------------
# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"
echo "append-metrics-record: identity source: ${AI_AGILE_GH_IDENTITY:-unset}" >&2

# Author/committer identity for `git commit-tree` below -- without this, a
# runner with no global git config set fails every append with "Author
# identity unknown" (git commit-tree, unlike git push, has no credential
# helper to fall back on). Same identity create-pr.sh already uses for its
# own commits, so every system write is attributed consistently (MI-7).
export GIT_AUTHOR_NAME="github-actions[bot]"
export GIT_AUTHOR_EMAIL="github-actions[bot]@users.noreply.github.com"
export GIT_COMMITTER_NAME="${GIT_AUTHOR_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_AUTHOR_EMAIL}"

if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    # Remove any extraHeader actions/checkout wrote into .git/config to avoid
    # interference with the url.insteadOf rewrite below.
    git config --local --unset-all "http.https://github.com/.extraHeader" 2>/dev/null || true
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0="url.https://x-access-token:${GITHUB_TOKEN}@github.com/.insteadOf"
    export GIT_CONFIG_VALUE_0="https://github.com/"
fi

CONTENT=$(mktemp)
INDEX=$(mktemp)
trap 'rm -f -- "$CONTENT" "$INDEX"' EXIT

attempt=0
while :; do
    parent_sha=""
    parent_arg=""
    if git fetch origin "$BRANCH" >/dev/null 2>&1; then
        parent_sha=$(git rev-parse "origin/${BRANCH}")
        parent_arg="-p ${parent_sha}"
    fi

    # The whole ledger, plus this record. A missing file on the branch is an
    # empty ledger, not an error: the first append creates it. A missing branch
    # is also treated as an empty ledger -- this run creates the orphan commit.
    if [[ -n "${parent_sha}" ]] && git show "${parent_sha}:${RECORDS_FILE}" > "$CONTENT" 2>/dev/null; then
        :
    else
        : > "$CONTENT"
    fi
    cat -- "$RECORD_FILE" >> "$CONTENT"

    blob_sha=$(git hash-object -w --stdin < "$CONTENT")

    # A scratch index, so nothing here can disturb the checkout this tick is
    # running in.
    export GIT_INDEX_FILE="$INDEX"
    if [[ -n "${parent_sha}" ]]; then
        git read-tree "$parent_sha"
    else
        git read-tree --empty
    fi
    git update-index --add --cacheinfo "100644,${blob_sha},${RECORDS_FILE}"
    tree_sha=$(git write-tree)
    unset GIT_INDEX_FILE
    : > "$INDEX"

    # shellcheck disable=SC2086
    commit_sha=$(git commit-tree "$tree_sha" $parent_arg -m "$COMMIT_MESSAGE")

    if push_err=$(git push origin "${commit_sha}:refs/heads/${BRANCH}" 2>&1); then
        echo "append-metrics-record: appended to ${BRANCH}:${RECORDS_FILE}"
        exit 0
    fi

    # Fail closed (STD-ARCH-014): a rejected push means the record is NOT in
    # the ledger. Retry against the new tip; when the retries are gone, say so
    # and exit non-zero rather than reporting a success-shaped result.
    if (( attempt < RETRIES )); then
        attempt=$(( attempt + 1 ))
        echo "append-metrics-record: push rejected (concurrent writer?), retrying (attempt ${attempt}): ${push_err}" >&2
        sleep 1
        continue
    fi
    echo "append-metrics-record: ERROR: git push to ${BRANCH} failed: ${push_err}" >&2
    exit 1
done
