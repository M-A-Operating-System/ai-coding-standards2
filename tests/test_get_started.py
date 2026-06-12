"""Tests for get_started install helpers and _add_submodules_to_checkout."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import get_started

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agents_src(tmp_path, name="submodule"):
    fake_src = tmp_path / name
    agents_src = fake_src / ".claude" / "agents" / "01_product_docs"
    agents_src.mkdir(parents=True)
    (agents_src / "prd-writer.md").write_text("# prd-writer")
    return fake_src


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

    def test_adrs_json_seeded_on_first_install(self, tmp_path, monkeypatch):
        """adrs.json is created on first install as a project-scoped empty file."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "adrs.json").write_text('{"adrs": []}')
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", "submodule")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_standards(consuming, force=True, dry_run=False)

        dst = consuming / "standards" / "adrs.json"
        assert dst.exists()
        import json
        data = json.loads(dst.read_text())
        assert data["scope"] == "project"
        assert data["adrs"] == []

    def test_adrs_json_not_overwritten_on_sync(self, tmp_path, monkeypatch):
        """adrs.json is never overwritten by --force so project ADRs are preserved."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "adrs.json").write_text('{"adrs": []}')
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        (consuming / "standards").mkdir(parents=True)
        existing_adrs = consuming / "standards" / "adrs.json"
        existing_adrs.write_text('{"scope":"project","adrs":[{"id":"ADR-001"}]}')

        get_started.install_standards(consuming, force=True, dry_run=False)

        assert existing_adrs.read_text() == '{"scope":"project","adrs":[{"id":"ADR-001"}]}'


# ---------------------------------------------------------------------------
# TestInstallAgentsWindows — copy behaviour (simulated via sys.platform == "win32")
# ---------------------------------------------------------------------------

class TestInstallAgentsWindows:
    def test_copies_agent_files_with_subdirs(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_agents(consuming, force=True, dry_run=False)

        assert written == 1
        dst = consuming / ".claude" / "agents" / "01_product_docs" / "prd-writer.md"
        assert dst.exists()
        assert dst.read_text() == "# prd-writer"

    def test_removes_stale_agents(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        stale_dir = consuming / ".claude" / "agents" / "99_retired"
        stale_dir.mkdir(parents=True)
        stale = stale_dir / "old-agent.md"
        stale.write_text("old")

        get_started.install_agents(consuming, force=True, dry_run=False)

        assert not stale.exists()

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / ".claude" / "agents").mkdir(parents=True)
        (fake_src / ".claude" / "agents" / "agent.md").write_text("# agent")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_agents(consuming, force=True, dry_run=True)

        assert written == 1
        assert not (consuming / ".claude" / "agents" / "agent.md").exists()

    def test_skips_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_agents(consuming, force=True, dry_run=False)

        assert written == 0

    def test_direct_copy_helper_writes_files(self, tmp_path):
        """_install_agents_copy called directly (second call site for STD-ARCH-002)."""
        fake_src = _make_agents_src(tmp_path)
        src_dir = fake_src / ".claude" / "agents"
        consuming = tmp_path / "consuming"
        dst_dir = consuming / ".claude" / "agents"

        result = get_started._install_agents_copy(src_dir, dst_dir, force=True, dry_run=False)

        assert result == 1
        assert (dst_dir / "01_product_docs" / "prd-writer.md").exists()


# ---------------------------------------------------------------------------
# TestInstallAgentsLinux — symlink behaviour (default on Linux/macOS)
# ---------------------------------------------------------------------------

class TestInstallAgentsLinux:
    def test_creates_symlink_to_src(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_agents(consuming, force=True, dry_run=False)

        dst = consuming / ".claude" / "agents"
        assert result == 1
        assert dst.is_symlink()
        # Symlink should resolve to the source directory
        assert dst.resolve() == (fake_src / ".claude" / "agents").resolve()

    def test_symlink_uses_relative_target(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_agents(consuming, force=True, dry_run=False)

        dst = consuming / ".claude" / "agents"
        link_target = os.readlink(dst)
        assert not os.path.isabs(link_target), "symlink target should be relative"

    def test_idempotent_correct_symlink_skipped(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_agents(consuming, force=True, dry_run=False)
        result = get_started.install_agents(consuming, force=False, dry_run=False)

        assert result == 0  # already correct, skipped

    def test_force_replaces_wrong_symlink(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        (consuming / ".claude").mkdir(parents=True)
        dst = consuming / ".claude" / "agents"
        os.symlink("/tmp/wrong-target", dst)

        result = get_started.install_agents(consuming, force=True, dry_run=False)

        assert result == 1
        assert dst.resolve() == (fake_src / ".claude" / "agents").resolve()

    def test_force_replaces_existing_directory_with_symlink(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude" / "agents"
        dst.mkdir(parents=True)
        (dst / "stale.md").write_text("stale copy")

        result = get_started.install_agents(consuming, force=True, dry_run=False)

        assert result == 1
        assert dst.is_symlink()

    def test_dry_run_does_not_remove_existing_directory(self, tmp_path, monkeypatch):
        """dry_run + force + existing dir returns 1 but must not delete the directory."""
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude" / "agents"
        dst.mkdir(parents=True)
        (dst / "existing.md").write_text("existing")

        result = get_started.install_agents(consuming, force=True, dry_run=True)

        assert result == 1
        assert dst.is_dir()  # not deleted
        assert (dst / "existing.md").exists()  # contents preserved

    def test_no_force_skips_existing_directory(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude" / "agents"
        dst.mkdir(parents=True)
        (dst / "existing.md").write_text("existing")

        result = get_started.install_agents(consuming, force=False, dry_run=False)

        assert result == 0
        assert not dst.is_symlink()

    def test_dry_run_does_not_create_symlink(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_agents(consuming, force=True, dry_run=True)

        assert result == 1
        assert not (consuming / ".claude" / "agents").exists()

    def test_agents_accessible_through_symlink(self, tmp_path, monkeypatch):
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_agents(consuming, force=True, dry_run=False)

        agent = consuming / ".claude" / "agents" / "01_product_docs" / "prd-writer.md"
        assert agent.exists()
        assert agent.read_text() == "# prd-writer"

    def test_cygwin_msys2_takes_symlink_path(self, tmp_path, monkeypatch):
        """sys.platform != 'win32' is the correct guard; Cygwin has os.name=='posix'."""
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        # Simulate Cygwin: os.name is 'posix' but sys.platform is still 'cygwin'.
        # The guard sys.platform != 'win32' correctly takes the symlink path.
        monkeypatch.setattr(sys, "platform", "cygwin")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_agents(consuming, force=True, dry_run=False)

        dst = consuming / ".claude" / "agents"
        assert result == 1
        assert dst.is_symlink()

    def test_skip_when_agents_path_is_regular_file(self, tmp_path, monkeypatch):
        """shutil.rmtree must not be called on a regular file — skip instead."""
        fake_src = _make_agents_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude" / "agents"
        dst.parent.mkdir(parents=True)
        dst.write_text("i am a file, not a directory")

        result = get_started.install_agents(consuming, force=True, dry_run=False)

        assert result == 0
        assert dst.is_file()  # not deleted

    def test_direct_symlink_helper_creates_link(self, tmp_path):
        """_install_agents_symlink called directly (second call site for STD-ARCH-002)."""
        fake_src = _make_agents_src(tmp_path)
        src_dir = fake_src / ".claude" / "agents"
        consuming = tmp_path / "consuming"
        dst_dir = consuming / ".claude" / "agents"

        result = get_started._install_agents_symlink(src_dir, dst_dir, force=True, dry_run=False)

        assert result == 1
        assert dst_dir.is_symlink()
        assert dst_dir.resolve() == src_dir.resolve()


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
# TestRewritePaths — unit tests for each PATH_REWRITES regex
# ---------------------------------------------------------------------------

class TestRewritePaths:
    """Each PATH_REWRITES rule is tested against a representative input."""

    def _name(self):
        return get_started.SUBMODULE_NAME

    def test_rewrites_status_sh(self):
        src = "bash .github/scripts/status.sh bootstrap-all"
        result = get_started.rewrite_paths(src)
        assert f"{self._name()}/.github/scripts/status.sh" in result
        assert "/.github/scripts/status.sh" not in result.replace(f"{self._name()}/", "")

    def test_no_double_prefix_status_sh(self):
        already = f"bash {self._name()}/.github/scripts/status.sh arg"
        assert get_started.rewrite_paths(already) == already

    def test_rewrites_migrate_labels_py(self):
        src = "python .github/scripts/migrate_labels.py"
        result = get_started.rewrite_paths(src)
        assert f"{self._name()}/.github/scripts/migrate_labels.py" in result

    def test_no_double_prefix_migrate_labels_py(self):
        already = f"python {self._name()}/.github/scripts/migrate_labels.py"
        assert get_started.rewrite_paths(already) == already

    def test_rewrites_claude_agents(self):
        src = "cat .claude/agents/01_product_docs/issue-classifier.md"
        result = get_started.rewrite_paths(src)
        assert f"{self._name()}/.claude/agents/" in result

    def test_no_double_prefix_claude_agents(self):
        already = f"cat {self._name()}/.claude/agents/foo.md"
        assert get_started.rewrite_paths(already) == already

    def test_rewrites_pipeline(self):
        src = "python pipeline/pipeline_orchestrator.py"
        result = get_started.rewrite_paths(src)
        assert f"{self._name()}/pipeline/" in result

    def test_no_double_prefix_pipeline(self):
        already = f"python {self._name()}/pipeline/pipeline_orchestrator.py"
        assert get_started.rewrite_paths(already) == already

    def test_rewrites_agent_todo_standard(self):
        src = "See .claude/agent-todo-standard.md for details."
        result = get_started.rewrite_paths(src)
        assert f"{self._name()}/docs/product/agile/13-todos.md" in result
        assert "agent-todo-standard.md" not in result


# ---------------------------------------------------------------------------
# TestInstallLabelCleanupWorkflow
# ---------------------------------------------------------------------------

class TestInstallLabelCleanupWorkflow:
    def test_copies_workflow_and_injects_submodules(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / ".github" / "workflows").mkdir(parents=True)
        (fake_src / ".github" / "workflows" / "label-cleanup.yml").write_text(
            "steps:\n"
            "  - name: Checkout\n"
            "    uses: actions/checkout@v4\n"
        )
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_label_cleanup_workflow(consuming, force=True, dry_run=False)

        assert result is True
        dst = consuming / ".github" / "workflows" / "label-cleanup.yml"
        assert dst.exists()
        assert "submodules: true" in dst.read_text()

    def test_returns_false_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_label_cleanup_workflow(consuming, force=True, dry_run=False)

        assert result is False

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / ".github" / "workflows").mkdir(parents=True)
        (fake_src / ".github" / "workflows" / "label-cleanup.yml").write_text("steps: []")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_label_cleanup_workflow(consuming, force=True, dry_run=True)

        assert result is True
        assert not (consuming / ".github" / "workflows" / "label-cleanup.yml").exists()


# ---------------------------------------------------------------------------
# TestInstallOrchestratorWorkflows
# ---------------------------------------------------------------------------

class TestInstallOrchestratorWorkflows:
    def _make_src(self, tmp_path):
        fake_src = tmp_path / "submodule"
        wf_dir = fake_src / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "orchestrator-pre-execute.yml").write_text(
            "steps:\n  - uses: actions/checkout@v4\n"
        )
        (wf_dir / "orchestrator-execute.yml").write_text(
            "steps:\n  - name: Checkout\n    uses: actions/checkout@v4\n"
        )
        return fake_src

    def test_copies_both_workflow_files(self, tmp_path, monkeypatch):
        fake_src = self._make_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.install_orchestrator_workflows(consuming, force=True, dry_run=False)

        assert count == 2
        assert (consuming / ".github" / "workflows" / "orchestrator-pre-execute.yml").exists()
        assert (consuming / ".github" / "workflows" / "orchestrator-execute.yml").exists()

    def test_injects_submodules_true_into_both(self, tmp_path, monkeypatch):
        fake_src = self._make_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_orchestrator_workflows(consuming, force=True, dry_run=False)

        for name in ("orchestrator-pre-execute.yml", "orchestrator-execute.yml"):
            content = (consuming / ".github" / "workflows" / name).read_text()
            assert "submodules: true" in content, f"{name} missing submodules: true"

    def test_returns_zero_when_both_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.install_orchestrator_workflows(consuming, force=True, dry_run=False)

        assert count == 0

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = self._make_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.install_orchestrator_workflows(consuming, force=True, dry_run=True)

        assert count == 2
        assert not (consuming / ".github" / "workflows" / "orchestrator-pre-execute.yml").exists()
        assert not (consuming / ".github" / "workflows" / "orchestrator-execute.yml").exists()

    def test_skip_when_force_false_and_file_exists(self, tmp_path, monkeypatch):
        fake_src = self._make_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        wf_dir = consuming / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        existing = wf_dir / "orchestrator-pre-execute.yml"
        existing.write_text("original content")

        get_started.install_orchestrator_workflows(consuming, force=False, dry_run=False)

        assert existing.read_text() == "original content"


# ---------------------------------------------------------------------------
# TestInstallSlashCommands
# ---------------------------------------------------------------------------

class TestInstallSlashCommands:
    def _make_src(self, tmp_path, name="ai-coding-standards2"):
        fake_src = tmp_path / name
        cmd_dir = fake_src / ".claude" / "commands"
        cmd_dir.mkdir(parents=True)
        return fake_src, cmd_dir

    def test_copies_command_files(self, tmp_path, monkeypatch):
        fake_src, cmd_dir = self._make_src(tmp_path)
        (cmd_dir / "my-cmd.md").write_text("# my-cmd\nsome content")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", fake_src.name)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.install_slash_commands(consuming, force=True, dry_run=False)

        assert count == 1
        assert (consuming / ".claude" / "commands" / "my-cmd.md").exists()

    def test_rewrites_status_sh_path(self, tmp_path, monkeypatch):
        fake_src, cmd_dir = self._make_src(tmp_path, "mysubmodule")
        (cmd_dir / "cmd.md").write_text("run .github/scripts/status.sh bootstrap-all")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", "mysubmodule")
        import re
        monkeypatch.setattr(get_started, "PATH_REWRITES", [
            (r"(?<!mysubmodule/)\.github/scripts/status\.sh", "mysubmodule/.github/scripts/status.sh"),
        ])
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_slash_commands(consuming, force=True, dry_run=False)

        content = (consuming / ".claude" / "commands" / "cmd.md").read_text()
        assert "mysubmodule/.github/scripts/status.sh" in content

    def test_removes_stale_commands(self, tmp_path, monkeypatch):
        fake_src, cmd_dir = self._make_src(tmp_path)
        (cmd_dir / "current.md").write_text("# current")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", fake_src.name)
        consuming = tmp_path / "consuming"
        dst_cmd_dir = consuming / ".claude" / "commands"
        dst_cmd_dir.mkdir(parents=True)
        stale = dst_cmd_dir / "old-cmd.md"
        stale.write_text("stale")

        get_started.install_slash_commands(consuming, force=True, dry_run=False)

        assert not stale.exists()
        assert (dst_cmd_dir / "current.md").exists()

    def test_returns_false_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.install_slash_commands(consuming, force=True, dry_run=False)

        assert count == 0

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src, cmd_dir = self._make_src(tmp_path)
        (cmd_dir / "cmd.md").write_text("# cmd")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", fake_src.name)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.install_slash_commands(consuming, force=True, dry_run=True)

        assert count == 1
        assert not (consuming / ".claude" / "commands" / "cmd.md").exists()


# ---------------------------------------------------------------------------
# TestInstallLocalSettings
# ---------------------------------------------------------------------------

class TestInstallLocalSettings:
    def test_writes_valid_json_with_ai_agile_root(self, tmp_path, monkeypatch):
        import json
        fake_src = tmp_path / "submodule"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_local_settings(consuming, force=True, dry_run=False)

        assert result is True
        dst = consuming / ".claude" / "settings.local.json"
        assert dst.exists()
        data = json.loads(dst.read_text())
        assert data["env"]["AI_AGILE_ROOT"] == "."

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_local_settings(consuming, force=True, dry_run=True)

        assert result is True
        assert not (consuming / ".claude" / "settings.local.json").exists()

    def test_skipped_when_exists_and_no_force(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude" / "settings.local.json"
        dst.parent.mkdir(parents=True)
        dst.write_text('{"env":{"AI_AGILE_ROOT":"original"}}')

        result = get_started.install_local_settings(consuming, force=False, dry_run=False)

        assert result is False
        assert '"original"' in dst.read_text()


# ---------------------------------------------------------------------------
# TestAddGitignoreEntries
# ---------------------------------------------------------------------------

class TestAddGitignoreEntries:
    def _make_submodule(self, tmp_path):
        """Minimal submodule with one base standards file."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "architecture.json").write_text("{}")
        (fake_src / "standards" / "adrs.json").write_text("{}")
        (fake_src / "standards" / "pipeline.schema.json").write_text("{}")
        return fake_src

    def test_creates_gitignore_when_absent(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.add_gitignore_entries(consuming, dry_run=False)

        assert count > 0
        gitignore = consuming / ".gitignore"
        assert gitignore.exists()
        text = gitignore.read_text()
        assert ".claude/agents" in text
        assert ".claude/commands/" in text
        assert ".claude/settings.local.json" in text

    def test_includes_base_standards_not_adrs(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert "standards/architecture.json" in text
        assert "standards/adrs.json" not in text
        assert "standards/pipeline.schema.json" not in text

    def test_appends_to_existing_gitignore(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        (consuming / ".gitignore").write_text("*.pyc\n__pycache__/\n")

        get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert "*.pyc" in text
        assert "__pycache__/" in text
        assert ".claude/agents" in text

    def test_idempotent_no_duplicate_entries(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.add_gitignore_entries(consuming, dry_run=False)
        second = get_started.add_gitignore_entries(consuming, dry_run=False)

        assert second == 0
        text = (consuming / ".gitignore").read_text()
        assert text.count(".claude/agents") == 1

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.add_gitignore_entries(consuming, dry_run=True)

        assert count > 0
        assert not (consuming / ".gitignore").exists()

    def test_partial_update_adds_only_missing(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        (consuming / ".gitignore").write_text(".claude/agents\n")

        count = get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert text.count(".claude/agents") == 1
        assert ".claude/commands/" in text
        assert ".claude/settings.local.json" in text
        # count reflects only the newly added pattern lines (not the header/blank)
        new_entries = [l for l in text.splitlines() if l and not l.startswith("#") and l != ".claude/agents"]
        assert count == len(new_entries)


# ---------------------------------------------------------------------------
# TestUntrackManagedPaths
# ---------------------------------------------------------------------------

class TestUntrackManagedPaths:
    """untrack_managed_paths() removes get_started-managed paths from git.

    We cannot run real git operations in tmp_path, so we test the
    git-not-available path and verify the function is a safe no-op.
    """

    def _make_submodule(self, tmp_path):
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "architecture.json").write_text("{}")
        (fake_src / "standards" / "adrs.json").write_text("{}")
        return fake_src

    def test_returns_zero_when_git_unavailable(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        # Monkeypatch subprocess.run to simulate git not found
        import subprocess as sp
        def _raise(*args, **kwargs):
            raise FileNotFoundError("git not found")
        monkeypatch.setattr(sp, "run", _raise)

        result = get_started.untrack_managed_paths(consuming, dry_run=False)

        assert result == 0

    def test_returns_zero_in_non_git_dir(self, tmp_path, monkeypatch):
        """In a non-git directory git ls-files returns non-zero; function is a no-op."""
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        # Run against a real non-git directory; should not raise, returns 0
        result = get_started.untrack_managed_paths(consuming, dry_run=False)

        assert result == 0

    def test_dry_run_does_not_call_git_rm(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        calls = []
        import subprocess as sp
        real_run = sp.run
        def _mock_run(args, **kwargs):
            calls.append(args)
            if args[1] == "ls-files":
                # Simulate a tracked file
                import types
                r = types.SimpleNamespace(returncode=0, stdout=".claude/agents\n", stderr="")
                return r
            return real_run(args, **kwargs)
        monkeypatch.setattr(sp, "run", _mock_run)

        count = get_started.untrack_managed_paths(consuming, dry_run=True)

        rm_calls = [c for c in calls if "rm" in c]
        assert len(rm_calls) == 0
        assert count > 0  # tracked paths are counted in dry_run

    def test_removes_tracked_path_non_dry_run(self, tmp_path, monkeypatch):
        """Non-dry-run: git rm --cached is called for a tracked path and result == 1."""
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        calls = []
        import subprocess as sp
        import types

        def _mock_run(args, **kwargs):
            calls.append(list(args))
            if args[1] == "ls-files":
                stdout = ".claude/agents\n" if args[-1] == ".claude/agents" else ""
                return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
            if "rm" in args:
                return types.SimpleNamespace(returncode=0, stdout="rm '.claude/agents'\n", stderr="")
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", _mock_run)

        result = get_started.untrack_managed_paths(consuming, dry_run=False)

        rm_calls = [c for c in calls if "rm" in c]
        assert result == 1
        assert len(rm_calls) == 1
        assert "--cached" in rm_calls[0]
        assert ".claude/agents" in rm_calls[0]
