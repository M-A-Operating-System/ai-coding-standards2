#!/usr/bin/env bash
# new-branch-pr.sh
#
# Opens an issue's branch and its draft PR by hand, the same way the pipeline
# does it: this is an adapter onto create-pr.sh, not a second implementation of
# it. `/maos-new-branch-pr` names this script and passes the issue number
# through (AS-3); the branch name, the base branch, and whether the PR closes
# the issue come from the flow's naming in pipeline.json (issue #406), read
# through the orchestrator's own loader so nothing is re-derived here.
#
# Everything create-pr.sh already guarantees still holds when it is reached
# this way: it is idempotent (an existing branch and PR are reported, never
# recreated), it truncates the issue title to 60 characters for the PR title,
# it applies source-issue:{N}, and it posts the announcement comment once.
#
# Usage: new-branch-pr.sh <issue-number>
#
# Required env:
#   REPO         -- owner/repo
#   GITHUB_TOKEN or GH_TOKEN -- passed straight through to create-pr.sh
#
# Optional env:
#   AI_AGILE_STEP -- the pipeline step to resolve naming from
#                   (default 01_product_docs/create-pr)

set -euo pipefail

ISSUE_NUMBER="${1:?usage: new-branch-pr.sh <issue-number>}"
: "${REPO:?REPO must be set (owner/repo)}"

STEP="${AI_AGILE_STEP:-01_product_docs/create-pr}"
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "${HERE}/../.." && pwd)

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: issue number is not an integer: ${ISSUE_NUMBER}" >&2
    exit 1
fi

# Ask the orchestrator what this step's flow names things. Resolving it here
# from a pattern would be a second copy of the naming rules (P-2), and the
# whole point of issue #406 is that a branch name is declared, not computed.
NAMING=$(
    ISSUE_NUMBER="${ISSUE_NUMBER}" python3 - "${ROOT}" "${STEP}" <<'PY'
import os
import sys

root, step = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(root, "pipeline"))
import pipeline_orchestrator as po  # noqa: E402

agents, _ = po.load_pipeline(po.PIPELINE_PATH)
agent_def = po.pipeline_by_name(agents).get(step)
if agent_def is None:
    sys.exit(f"ERROR: {step} is not declared in pipeline.json")

work_item = po.WorkItem(
    number=int(os.environ["ISSUE_NUMBER"]), kind="issue", title="",
    labels=set(), url="",
)
env = po._flow_context_env(agent_def, work_item)
if "AI_AGILE_BRANCH" not in env:
    sys.exit(f"ERROR: flow {agent_def.flow!r} declares no naming.branch for {step}")
env.setdefault("PR_CLOSES_ISSUE", "true")
for key in ("AI_AGILE_BRANCH", "AI_AGILE_BASE_BRANCH", "PR_CLOSES_ISSUE"):
    if key in env:
        print(f"{key}={env[key]}")
PY
)

# shellcheck disable=SC2163
while IFS= read -r assignment; do
    [[ -n "$assignment" ]] && export "${assignment?}"
done <<< "$NAMING"

echo "new-branch-pr: issue #${ISSUE_NUMBER} -> branch ${AI_AGILE_BRANCH} (via ${STEP})"

export REPO ISSUE_NUMBER
exec bash "${HERE}/create-pr.sh"
