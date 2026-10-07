#!/usr/bin/env bash
# commit-report.sh -- write a file to a persistent git branch.
#
# Usage: commit-report.sh <source-file> <dest-path>
#
# Writes the binary or text file at <source-file> to <dest-path> on the
# branch named by AI_AGILE_REPORT_BRANCH. If the branch does not yet exist
# an orphan (parentless) first commit is created. If it does exist, the
# file is added or replaced at <dest-path>.
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
# Required env:
#   AI_AGILE_REPORT_BRANCH         -- the branch to write to (e.g. ai-agile/reports)
#   AI_AGILE_REPORT_COMMIT_MESSAGE -- the commit message
#
# Optional env:
#   AI_AGILE_REPORT_RETRIES        -- push retries on rejection (default 2)

set -euo pipefail

SOURCE_FILE="${1:?usage: commit-report.sh <source-file> <dest-path>}"
DEST_PATH="${2:?usage: commit-report.sh <source-file> <dest-path>}"
BRANCH="${AI_AGILE_REPORT_BRANCH:?AI_AGILE_REPORT_BRANCH is required}"
COMMIT_MESSAGE="${AI_AGILE_REPORT_COMMIT_MESSAGE:?AI_AGILE_REPORT_COMMIT_MESSAGE is required}"
RETRIES="${AI_AGILE_REPORT_RETRIES:-2}"

if [[ ! -f "$SOURCE_FILE" ]]; then
    echo "commit-report: ERROR: source file not found: ${SOURCE_FILE}" >&2
    exit 1
fi

# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    _ENCODED=$(printf 'x-access-token:%s' "${GITHUB_TOKEN}" \
        | base64 -w 0 2>/dev/null \
        || printf 'x-access-token:%s' "${GITHUB_TOKEN}" | base64)
    git config --local --unset-all "http.https://github.com/.extraHeader" 2>/dev/null || true
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0="http.https://github.com/.extraHeader"
    export GIT_CONFIG_VALUE_0="Authorization: Basic ${_ENCODED}"
fi

INDEX=$(mktemp)
trap 'rm -f -- "$INDEX"' EXIT

attempt=0
while :; do
    # Fetch the branch if it exists; treat a non-existent branch as an empty tree.
    parent_arg=""
    if git fetch origin "$BRANCH" >/dev/null 2>&1; then
        parent_sha=$(git rev-parse "origin/${BRANCH}")
        parent_arg="-p ${parent_sha}"

        export GIT_INDEX_FILE="$INDEX"
        git read-tree "$parent_sha"
    else
        # Branch does not exist yet -- start with an empty index.
        export GIT_INDEX_FILE="$INDEX"
        git read-tree --empty
    fi

    blob_sha=$(git hash-object -w --stdin < "$SOURCE_FILE")

    git update-index --add --cacheinfo "100644,${blob_sha},${DEST_PATH}"
    tree_sha=$(git write-tree)
    unset GIT_INDEX_FILE
    : > "$INDEX"

    # shellcheck disable=SC2086
    commit_sha=$(git commit-tree "$tree_sha" $parent_arg -m "$COMMIT_MESSAGE")

    if push_err=$(git push origin "${commit_sha}:refs/heads/${BRANCH}" 2>&1); then
        echo "commit-report: committed ${DEST_PATH} to ${BRANCH}"
        exit 0
    fi

    if (( attempt < RETRIES )); then
        attempt=$(( attempt + 1 ))
        echo "commit-report: push rejected (concurrent writer?), retrying (attempt ${attempt}): ${push_err}" >&2
        sleep 1
        continue
    fi
    echo "commit-report: ERROR: git push to ${BRANCH} failed: ${push_err}" >&2
    exit 1
done
