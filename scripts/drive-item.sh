#!/usr/bin/env bash
# drive-item.sh
#
# Runs orchestrator ticks against one work item until it halts, so a person
# driving the pipeline in a chat session does not hand-repeat the loop.
# `/maos-run` names this script and passes the issue number through (AS-3).
#
# What this does is mechanical: invoke a tick, look at what the tick changed,
# invoke another one. What it deliberately does NOT do is cross a gate. A gate
# is crossed only by a person's own label, or by the orchestrator recording a
# confirmation a driver relayed (MI-7) -- so when a step lands on :review, or a
# gated step is waiting for its {agent}:approved label, this script stops and
# says so. Deciding is the person's; relaying the decision is the driver's;
# writing the label is the orchestrator's, via --confirm-gate.
#
# The orchestrator is what advances state. This script never applies a label,
# never posts a comment, and never runs an agent prompt: hand-mirroring any of
# that drifts the labels and artefacts the pipeline depends on.
#
# Usage: drive-item.sh <issue-number> [extra orchestrator args...]
#
# Required env:
#   REPO -- owner/repo
#
# Optional env:
#   AI_AGILE_MAX_TICKS -- stop after this many ticks (default 20), so a
#                        misconfigured pipeline cannot spin forever.
#
# Exit codes:
#   0  the item reached a state with nothing left for a tick to advance
#   2  a halt needing a person: :review, :blocked, :failed, or a gate
#   1  the run could not proceed (missing prerequisite, orchestrator error)

set -euo pipefail

ISSUE_NUMBER="${1:?usage: drive-item.sh <issue-number> [orchestrator args...]}"
shift || true
: "${REPO:?REPO must be set (owner/repo)}"

MAX_TICKS="${AI_AGILE_MAX_TICKS:-20}"

if [[ ! "${ISSUE_NUMBER}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: issue number is not an integer: ${ISSUE_NUMBER}" >&2
    exit 1
fi

# Standalone checkout first, then the submodule layout a consuming repo has.
SCRIPT=pipeline/pipeline_orchestrator.py
[ -f "$SCRIPT" ] || SCRIPT=ai-coding-standards2/pipeline/pipeline_orchestrator.py
if [[ ! -f "$SCRIPT" ]]; then
    echo "ERROR: no orchestrator found at pipeline/pipeline_orchestrator.py or ai-coding-standards2/pipeline/pipeline_orchestrator.py." >&2
    echo "Run this from the repository root of a checkout that has one." >&2
    exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "ERROR: the gh CLI is not on PATH; the pipeline's scripts and agents call 'gh api'." >&2
    exit 1
fi

_labels() {
    gh api "repos/${REPO}/issues/${ISSUE_NUMBER}/labels" --jq '.[].name' 2>/dev/null | sort
}

_halting_labels() {
    _labels | grep -E ':(review|blocked|failed)$' || true
}

_initial_labels=$(_labels)

# Epic mode: when the item carries both "epic" and "blocked" labels and has a
# non-empty native sub-issue list, drive each child in sub-issue order and stop
# at the first child that halts for a human decision.
if echo "$_initial_labels" | grep -qx "epic" && echo "$_initial_labels" | grep -qx "blocked"; then
    _sub_issue_err=$(mktemp)
    if ! _sub_issue_numbers=$(gh api "repos/${REPO}/issues/${ISSUE_NUMBER}/sub_issues" \
        --paginate --jq '.[].number' 2>"${_sub_issue_err}"); then
        echo "drive-item: WARNING: could not fetch sub-issues for epic #${ISSUE_NUMBER}" \
            "(gh api failed: $(head -1 "${_sub_issue_err}")); falling back to the" \
            "single-issue path." >&2
        _sub_issue_numbers=""
    fi
    rm -f "${_sub_issue_err}"
    if [[ -n "$_sub_issue_numbers" ]]; then
        echo "drive-item: #${ISSUE_NUMBER} is an epic; driving children in sub-issue order"
        while IFS= read -r _child_num; do
            [[ -z "$_child_num" ]] && continue
            if [[ ! "$_child_num" =~ ^[0-9]+$ ]]; then
                echo "drive-item: WARNING: skipping non-numeric child '${_child_num}'" \
                    "from epic #${ISSUE_NUMBER}'s sub-issue list" >&2
                continue
            fi
            if [[ "$_child_num" == "${ISSUE_NUMBER}" ]]; then
                echo "drive-item: WARNING: skipping child #${_child_num} -- an epic cannot" \
                    "be its own sub-issue" >&2
                continue
            fi
            _child_state=$(gh api "repos/${REPO}/issues/${_child_num}" --jq '.state' 2>/dev/null || echo "")
            if [[ "$_child_state" == "closed" ]]; then
                echo "drive-item: child #${_child_num} already closed; skipping."
                continue
            fi
            echo "drive-item: child #${_child_num} of epic #${ISSUE_NUMBER}"
            _child_rc=0
            # Deliberate full ambient-environment inheritance (STD-SEC-022):
            # this is the script invoking itself, not a new trust boundary --
            # the child runs under the exact same interactive session, the
            # same already-authenticated gh identity, and the same REPO this
            # invocation itself received. There is nothing to allowlist
            # because no new environment is being constructed; it is the
            # same one this process is already running in, same as every
            # other subprocess call in this script (gh, python3) makes.
            REPO="${REPO}" bash "$0" "${_child_num}" "$@" || _child_rc=$?
            if [[ $_child_rc -ne 0 ]]; then
                echo "drive-item: child #${_child_num} halted (exit ${_child_rc}); stopping epic drive."
                exit $_child_rc
            fi
        done <<< "$_sub_issue_numbers"
        echo "drive-item: all children of epic #${ISSUE_NUMBER} completed."
        exit 0
    fi
fi

tick=0
_pending_before="${_initial_labels}"
while (( tick < MAX_TICKS )); do
    tick=$(( tick + 1 ))
    if [[ -n "${_pending_before+x}" ]]; then
        before="${_pending_before}"
        unset _pending_before
    else
        before=$(_labels)
    fi

    echo "drive-item: tick ${tick} on #${ISSUE_NUMBER}"
    # No shell `timeout` around this: agent-heavy steps legitimately take
    # minutes and the orchestrator enforces its own per-step wall clock. A
    # short cap here would kill ticks that were about to finish.
    if ! python3 "$SCRIPT" --repo "$REPO" --issue "$ISSUE_NUMBER" "$@"; then
        echo "drive-item: the orchestrator exited non-zero on tick ${tick}; stopping." >&2
        exit 1
    fi

    halts=$(_halting_labels)
    if [[ -n "$halts" ]]; then
        echo "drive-item: halted on #${ISSUE_NUMBER} after tick ${tick}:"
        printf '  %s\n' $halts
        echo "drive-item: a person decides what happens next. A :review is a gate --"
        echo "  relay the person's approval by running the orchestrator with"
        echo "  --agent {step} --issue ${ISSUE_NUMBER} --confirm-gate, which is what"
        echo "  writes the gate label. A :blocked or :failed is cleared by fixing the"
        echo "  cause and removing the label."
        exit 2
    fi

    after=$(_labels)
    if [[ "$before" == "$after" ]]; then
        echo "drive-item: tick ${tick} advanced nothing on #${ISSUE_NUMBER}; stopping."
        exit 0
    fi
done

echo "drive-item: stopped after ${MAX_TICKS} ticks without reaching a halt or a settled state." >&2
echo "Raise AI_AGILE_MAX_TICKS if this item legitimately needs more." >&2
exit 1
