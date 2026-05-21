#!/usr/bin/env python3
"""
pipeline_orchestrator.py

Reads pipeline.json and orchestrates agent execution by inspecting GitHub
issue and PR labels of the form:

    {agent-name}:complete     — agent finished successfully
    {agent-name}:wip          — agent is currently running
    {agent-name}:review       — agent completed work and requests formal human
                                review/approval; remove label once approved
    {agent-name}:blocked      — agent cannot proceed (ambiguous spec, missing
                                data, conflict); remove label once resolved
    {agent-name}:failed       — agent exited with an error
    {agent-name}:skipped      — agent was bypassed by a human

For each open issue or PR, the orchestrator:
  1. Reads current labels to determine which agents have completed.
  2. Identifies agents whose dependencies are all complete (including any
     required human gate labels).
  3. Triggers eligible agents via the Claude CLI, applying {agent-name}:wip.
  4. Skips agents that are complete, wip, review, blocked, failed, or
     skipped, or whose dependencies are unmet.
  5. On blocked: posts a comment requesting human intervention and halts.
  6. On review: posts a comment requesting formal approval and waits for
     the label to be removed before the pipeline advances.

Usage:
    python pipeline_orchestrator.py [--repo OWNER/REPO] [--issue N] [--dry-run]

Requirements:
    pip install requests
    gh CLI authenticated
    ANTHROPIC_API_KEY set in environment (for agent execution; in CI
        this comes from a secret on the consuming repo, not this repo)
    GITHUB_TOKEN set in environment (or gh CLI authenticated)
"""