"""Tests for get_started install helpers and _add_submodules_to_checkout."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import get_started


# ---------------------------------------------------------------------------
# TestInstallStandards
# ---------------------------------------------------------------------------

class TestInstallStandards:
    def test_copies_json_not_schema(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "base.json").write_text('{"standards": []}')
        (fake_src / "standards" / "pipeline.schema.json").write_text("{}")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_standards(consuming, force=True, dry_run=False)

        assert written == 1
        assert (consuming / "standards" / "base.json").exists()
        assert not (consuming / "standards" / "pipeline.schema.json").exists()

    def test_rewrites_schema_ref_path(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "s.json").write_text(
            '{"$schema": "../pipeline/schemas/standards.schema.json"}'
        )
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", "submodule")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_standards(consuming, force=True, dry_run=False)

        result = (consuming / "standards" / "s.json").read_text()
        assert "../submodule/pipeline/schemas/standards.schema.json" in result
        assert '"../pipeline/schemas/standards.schema.json"' not in result

    def test_preserves_project_specific_standards(self, tmp_path, monkeypatch):
        """Standards not in the submodule (project-specific) are never deleted."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "base.json").write_text("{}")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        (consuming / "standards").mkdir(parents=True)
        project_specific = consuming / "standards" / "myapp.json"
        project_specific.write_text("{}")

        get_started.install_standards(consuming, force=True, dry_run=False)

        assert (consuming / "standards" / "base.json").exists()
        assert project_specific.exists()  # must not be deleted

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "base.json").write_text("{}")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_standards(consuming, force=True, dry_run=True)

        assert written == 1
        assert not (consuming / "standards" / "base.json").exists()


# ---------------------------------------------------------------------------
# TestInstallAgents
# ---------------------------------------------------------------------------

class TestInstallAgents:
    def test_copies_agent_files_with_subdirs(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        agents_src = fake_src / ".claude" / "agents" / "01_product_docs"
        agents_src.mkdir(parents=True)
        (agents_src / "prd-writer.md").write_text("# prd-writer")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_agents(consuming, force=True, dry_run=False)

        assert written == 1
        dst = consuming / ".claude" / "agents" / "01_product_docs" / "prd-writer.md"
        assert dst.exists()
        assert dst.read_text() == "# prd-writer"

    def test_removes_stale_agents(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        agents_src = fake_src / ".claude" / "agents" / "01_product_docs"
        agents_src.mkdir(parents=True)
        (agents_src / "prd-writer.md").write_text("# prd-writer")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        stale_dir = consuming / ".claude" / "agents" / "99_retired"
        stale_dir.mkdir(parents=True)
        stale = stale_dir / "old-agent.md"
        stale.write_text("old")

        get_started.install_agents(consuming, force=True, dry_run=False)

        assert not stale.exists()

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        agents_src = fake_src / ".claude" / "agents"
        agents_src.mkdir(parents=True)
        (agents_src / "agent.md").write_text("# agent")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_agents(consuming, force=True, dry_run=True)

        assert written == 1
        assert not (consuming / ".claude" / "agents" / "agent.md").exists()


# ---------------------------------------------------------------------------
# TestInstallSyncWorkflow
# ---------------------------------------------------------------------------

class TestInstallSyncWorkflow:
    def test_copies_workflow_and_injects_submodules(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / ".github" / "workflows").mkdir(parents=True)
        (fake_src / ".github" / "workflows" / "sync-claude.yml").write_text(
            "steps:\n"
            "  - uses: actions/checkout@v4\n"
            "  - run: echo hi\n"
        )
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_sync_workflow(consuming, force=True, dry_run=False)

        assert result is True
        dst = consuming / ".github" / "workflows" / "sync-claude.yml"
        assert dst.exists()
        assert "submodules: true" in dst.read_text()

    def test_returns_false_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_sync_workflow(consuming, force=True, dry_run=False)

        assert result is False


# ---------------------------------------------------------------------------
# TestInstallBootstrapLabelsWorkflow
# ---------------------------------------------------------------------------

class TestInstallBootstrapLabelsWorkflow:
    def test_copies_workflow_and_injects_submodules(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / ".github" / "workflows").mkdir(parents=True)
        (fake_src / ".github" / "workflows" / "bootstrap-labels.yml").write_text(
            "steps:\n"
            "  - name: Checkout\n"
            "    uses: actions/checkout@v4\n"
        )
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_bootstrap_labels_workflow(consuming, force=True, dry_run=False)

        assert result is True
        dst = consuming / ".github" / "workflows" / "bootstrap-labels.yml"
        assert "submodules: true" in dst.read_text()

    def test_returns_false_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_bootstrap_labels_workflow(consuming, force=True, dry_run=False)

        assert result is False


# ---------------------------------------------------------------------------
# TestAddSubmodulesToCheckout
# ---------------------------------------------------------------------------

class TestAddSubmodulesToCheckout:
    def test_named_form_inserts_submodules(self):
        content = (
            "    steps:\n"
            "      - name: Checkout\n"
            "        uses: actions/checkout@abc123\n"
            "      - name: Setup Python\n"
        )
        result = get_started._add_submodules_to_checkout(content)
        assert "        with:\n          submodules: true\n" in result

    def test_shorthand_form_inserts_submodules(self):
        content = (
            "    steps:\n"
            "      - uses: actions/checkout@abc123\n"
            "      - uses: actions/setup-python@def456\n"
        )
        result = get_started._add_submodules_to_checkout(content)
        assert "with:\n" in result
        assert "submodules: true\n" in result

    def test_already_expanded_form_left_untouched(self):
        content = (
            "    steps:\n"
            "      - name: Checkout\n"
            "        uses: actions/checkout@abc123\n"
            "        with:\n"
            "          fetch-depth: 0\n"
        )
        result = get_started._add_submodules_to_checkout(content)
        # submodules: true must NOT be injected when with: already present
        assert result.count("with:") == 1
        assert "submodules: true" not in result

    def test_already_expanded_shorthand_left_untouched(self):
        content = (
            "    steps:\n"
            "      - uses: actions/checkout@abc123\n"
            "        with:\n"
            "          submodules: true\n"
        )
        result = get_started._add_submodules_to_checkout(content)
        assert result.count("submodules: true") == 1

    def test_non_checkout_uses_not_modified(self):
        content = (
            "    steps:\n"
            "      - uses: actions/setup-python@abc123\n"
        )
        result = get_started._add_submodules_to_checkout(content)
        assert "submodules" not in result
        assert result == content


# ---------------------------------------------------------------------------
# QA-002: TestRewritePaths
# ---------------------------------------------------------------------------

class TestRewritePaths:
    """Tests for get_started.rewrite_paths() path-rewrite rules."""

    def test_bare_github_scripts_path_rewritten(self):
        """Bare .github/scripts/status.sh is prefixed with the submodule name."""
        content = "bash .github/scripts/status.sh set-wip prd-writer 42"
        result = get_started.rewrite_paths(content)
        # The rewritten path should start with the submodule name, not a bare dot
        assert result.startswith(f"bash {get_started.SUBMODULE_NAME}/"), (
            f"Expected path to start with submodule prefix; got {result!r}"
        )
        assert f"{get_started.SUBMODULE_NAME}/.github/scripts/status.sh" in result

    def test_bare_pipeline_path_rewritten(self):
        """Bare pipeline/ prefix is rewritten to <submodule>/pipeline/."""
        content = "python pipeline/validate.py --pipeline pipeline/pipeline.json"
        result = get_started.rewrite_paths(content)
        submodule = get_started.SUBMODULE_NAME
        assert f"{submodule}/pipeline/validate.py" in result
        assert f"{submodule}/pipeline/pipeline.json" in result

    def test_bare_claude_agents_path_rewritten(self):
        """Bare .claude/agents/ prefix is rewritten to <submodule>/.claude/agents/."""
        content = "Read .claude/agents/01_product_docs/prd-writer.md"
        result = get_started.rewrite_paths(content)
        submodule = get_started.SUBMODULE_NAME
        assert f"{submodule}/.claude/agents/01_product_docs/prd-writer.md" in result
        # The result must not start with the bare .claude/ prefix (no unqualified dot-paths)
        assert not result.startswith("Read .claude/"), (
            f"Bare .claude/ path should have been rewritten; got {result!r}"
        )

    def test_double_prefix_prevention_github_scripts(self):
        """Already-prefixed .github/scripts path is NOT double-prefixed."""
        submodule = get_started.SUBMODULE_NAME
        content = f"bash {submodule}/.github/scripts/status.sh"
        result = get_started.rewrite_paths(content)
        assert result == content, (
            f"rewrite_paths should not double-prefix an already-qualified path; "
            f"got {result!r}"
        )

    def test_double_prefix_prevention_pipeline(self):
        """Already-prefixed pipeline/ path is NOT double-prefixed."""
        submodule = get_started.SUBMODULE_NAME
        content = f"python {submodule}/pipeline/pipeline_orchestrator.py"
        result = get_started.rewrite_paths(content)
        assert result == content, (
            f"rewrite_paths should not double-prefix an already-qualified path; "
            f"got {result!r}"
        )

    def test_schema_path_rewritten_in_standards_file(self, tmp_path, monkeypatch):
        """install_standards rewrites the $schema URL in installed standards JSON files."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "s.json").write_text(
            '{"$schema": "../pipeline/schemas/standards.schema.json", "standards": []}'
        )
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", "submodule")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_standards(consuming, force=True, dry_run=False)

        text = (consuming / "standards" / "s.json").read_text()
        assert '"../pipeline/schemas/standards.schema.json"' not in text
        assert '"../submodule/pipeline/schemas/standards.schema.json"' in text
