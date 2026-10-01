#!/usr/bin/env bash
# epic-closer.sh
#
# Closes a coordinating work item (an epic) once every one of its children is
# closed: posts the epic-complete comment, then closes the issue.
#
# This is an ordinary declared step of the epic-completion flow, not a special
# case in the orchestrator (issue #406). Its eligibility is the flow's own
# declaration -- trigger.children: all_closed -- evaluated by the same
# per-item, per-tick machinery every other step's trigger goes through, so a
# flow that wants a review of the whole before the epic closes simply declares
# that step ahead of this one, with no orchestrator change.
#
# Environment (set by orchestrator):
#   REPO                     - owner/repo
#   ISSUE_NUMBER             - the epic being closed
#   AI_AGILE_CHILDREN_TOTAL  - how many children the epic has
#   AI_AGILE_CHILDREN_OPEN   - how many of them are still open (0 to be here)
#   GITHUB_TOKEN or GH_TOKEN - for the gh calls

set -euo pipefail

# The identity every headless system action on GitHub uses (MI-7): the
# dedicated bot when the repository configures one, otherwise exactly the token
# this script used before. Resolved in one place, never here.
# shellcheck source=lib/github-identity.sh
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"

: "${REPO:?REPO must be set}"
: "${ISSUE_NUMBER:?ISSUE_NUMBER must be set}"
: "${AI_AGILE_CHILDREN_TOTAL:?AI_AGILE_CHILDREN_TOTAL must be set}"

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: ISSUE_NUMBER is not a valid integer: ${ISSUE_NUMBER}" >&2
  exit 1
fi

# Defensive: the orchestrator only makes this step eligible when every child is
# closed. If that is somehow not the case, do nothing and say so, rather than
# closing a parent whose work is still running.
if [[ "${AI_AGILE_CHILDREN_OPEN:-0}" != "0" ]]; then
  echo "Epic #${ISSUE_NUMBER} still has ${AI_AGILE_CHILDREN_OPEN} open child issue(s) -- not closing." >&2
  echo "AI_AGILE_STATUS: blocked"
  exit 0
fi

COMMENT_BODY="$(printf '%s\n%s\n\n%s' \
  "<!-- ai-agile/announcement/v1 by orchestrator -->" \
  "## Epic complete" \
  "All ${AI_AGILE_CHILDREN_TOTAL} sub-issue(s) have been closed. Closing this epic.")"

gh api "repos/${REPO}/issues/${ISSUE_NUMBER}/comments" \
  --method POST -f "body=${COMMENT_BODY}" >/dev/null

gh api "repos/${REPO}/issues/${ISSUE_NUMBER}" \
  --method PATCH -f "state=closed" -f "state_reason=completed" >/dev/null

echo "Epic #${ISSUE_NUMBER}: all ${AI_AGILE_CHILDREN_TOTAL} sub-issue(s) closed -- closed the epic."
echo "AI_AGILE_STATUS: complete"
