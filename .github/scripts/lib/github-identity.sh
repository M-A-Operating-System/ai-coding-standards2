#!/usr/bin/env bash
# lib/github-identity.sh -- the identity every headless system action uses.
#
# Sourced, never executed. One line near the top of a script that talks to
# GitHub:
#
#     . "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/github-identity.sh"
#
# WHY (PRODUCT.md, MI-7): "Everything the system does on GitHub acts as a
# dedicated identity of its own, never a person's account or the generic
# identity a CI run gets by default -- the default is the trap, since it makes
# system actions indistinguishable from unrelated CI." Before issue #407 only
# three PR-writing scripts and commit-agent-work.sh were handed
# AI_AGILE_BOT_TOKEN; everything else fell back to the Actions-default
# GITHUB_TOKEN, so the same logical actor appeared on an issue as two different
# identities depending on which step wrote.
#
# WHAT: AI_AGILE_BOT_TOKEN when the repository has one configured, otherwise
# whatever token was already there. Resolved in ONE place so no script decides
# its own identity, and applied to both names a script might read:
#   GH_TOKEN     -- what the `gh` CLI authenticates with
#   GITHUB_TOKEN -- what the git-auth preambles build their Basic header from
# A repository that has not configured the PAT is unchanged: the fallback is
# exactly the token it used before.
#
# TRADEOFF, stated rather than hidden: this widens what a script could do with
# the credential it holds. The PAT is the broadest credential the orchestrator
# has (classic, repo+workflow), and STD-SEC-022 previously kept it away from
# steps that had no demonstrated need. MI-7 needs decidability -- "a person
# applied this label" has to be a fact, not a guess -- and that requires one
# identity for every system write, not most of them. The narrowing that
# survives is which VARIABLES a script is handed at all (the env allowlists in
# pipeline_orchestrator.py) and what each script is written to do.
#
# OUT OF SCOPE, deliberately: interactive-session identity. In a chat session
# the GitHub MCP server authenticates through session/environment
# configuration outside this repository, so no code change here can unify it.
# It is a separate, infrastructure-level question -- not something this file
# silently glosses over.
#
# AI_AGILE_GH_IDENTITY names which source won, for the logs.

if [[ -n "${AI_AGILE_BOT_TOKEN:-}" ]]; then
    export GH_TOKEN="${AI_AGILE_BOT_TOKEN}"
    export GITHUB_TOKEN="${AI_AGILE_BOT_TOKEN}"
    export AI_AGILE_GH_IDENTITY="AI_AGILE_BOT_TOKEN"
elif [[ -n "${GH_TOKEN:-}" ]]; then
    export GITHUB_TOKEN="${GH_TOKEN}"
    export AI_AGILE_GH_IDENTITY="GH_TOKEN"
elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
    export GH_TOKEN="${GITHUB_TOKEN}"
    export AI_AGILE_GH_IDENTITY="GITHUB_TOKEN"
else
    export AI_AGILE_GH_IDENTITY="none"
fi
