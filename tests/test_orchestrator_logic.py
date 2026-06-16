"""Tests for core pipeline-state logic in pipeline_orchestrator.py."""
import sys, os
import subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest
from pipeline_orchestrator import (
    ALL_STATUSES,
    STATUS_COMPLETE, STATUS_FAILED, STATUS_SKIPPED,
    STATUS_REVIEW, STATUS_BLOCKED, STATUS_WIP, STATUS_REQUESTED,
    PIPELINE_MAX_CONCURRENT,
    agent_status,
    _apply_failed,
    _count_running,
    _handle_review_loop,
    _make_audit_event,
    write_audit_log,
    promote_gated_agents,
    AgentDef, AgentRunResult, ConcurrencyState, WorkItem,
    parse_frontmatter,
    process_work_item,
    _compute_agent_session_id,
    main,
)


def _make_agent_def(name: str = "03_execute/coder") -> AgentDef:
    """Build a minimal AgentDef for tests."""
    return AgentDef(
        agent=name,
        phase=name.split("/")[0],
        objects=["issue"],
        trigger={},
        dependencies=[],
        human_gate_after=False,
        human_gate_label=None,
        description="test agent",
    )


def _make_work_item(number: int = 42) -> MagicMock:
    wi = MagicMock()
    wi.number = number
    wi.kind = "issue"
    wi.title = "Test issue"
    wi.url = f"https://github.com/test/repo/issues/{number}"
    return wi


pass