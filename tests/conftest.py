# pytest session configuration


import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))


@pytest.fixture(autouse=True)
def no_real_metrics_push(monkeypatch):
    """Keep unit tests off the real `ai-agile/metrics` branch.

    Several tests drive `process_work_item` for real with a mocked GitHubClient
    but an unmocked subprocess layer. `_post_cycle_metrics` then reaches the
    ledger append, which fetches and pushes against whatever remote the working
    copy has -- so running the suite in a real checkout appends test records to
    the real branch and, when the push stalls on credentials, hangs the run.

    The call site is patched, not the transport: production code looks the
    function up on the module, so this fixture neutralises it there, while the
    tests that exercise the append itself hold their own direct reference
    (`from pipeline_orchestrator import _append_metrics_record`) or patch it
    themselves, and are unaffected.
    """
    import pipeline_orchestrator as po

    calls = []

    def _refuse(gh, repo, record, **kwargs):
        calls.append((repo, record))

    monkeypatch.setattr(po, "_append_metrics_record", _refuse)
    return calls
