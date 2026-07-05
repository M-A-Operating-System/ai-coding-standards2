"""Tests for get_started install helpers and _add_submodules_to_checkout."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import get_started

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claude_src(tmp_path, name="submodule"):
    """A minimal submodule .claude tree: an agent, a command, and settings.json."""
    fake_src = tmp_path / name
    claude = fake_src / ".claude"
    (claude / "agents" / "01_product_docs").mkdir(parents=True)
    (claude / "agents" / "01_product_docs" / "prd-writer.md").write_text("# prd-writer")
    (claude / "commands").mkdir(parents=True)
    (claude / "commands" / "run-agent.md").write_text("# run-agent")
    (claude / "settings.json").write_text('{"env": {"AI_AGILE_ROOT": "."}}')
    return fake_src


# ---------------------------------------------------------------------------
# TestInstallStandards
# ---------------------------------------------------------------------------

class TestInstallStandards:
    def test_symlinks_whole_standards_dir(self, tmp_path, monkeypatch):
        """On Linux/macOS, standards/ is a single directory symlink into the
        submodule (sole, live source -- no drift)."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "base.json").write_text('{"standards": []}')
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_standards(consuming, force=True, dry_run=False)

        assert written == 1
        std = consuming / "standards"
        assert std.is_symlink()
        assert std.resolve() == (fake_src / "standards").resolve()
        assert not os.path.isabs(os.readlink(std))
        # Files resolve through the symlink.
        assert (std / "base.json").read_text() == '{"standards": []}'

    def test_windows_copies_whole_tree(self, tmp_path, monkeypatch):
        """On Windows (no unprivileged symlinks) standards/ is copied verbatim."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "s.json").write_text('{"a": 1}')
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_standards(consuming, force=True, dry_run=False)

        dst = consuming / "standards" / "s.json"
        assert not (consuming / "standards").is_symlink()
        assert dst.read_text() == '{"a": 1}'

    def test_force_replaces_old_per_file_dir_with_symlink(self, tmp_path, monkeypatch):
        """Migrating a pre-existing copied/per-file install: --force replaces the
        real standards/ directory with a whole-folder symlink."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "base.json").write_text("{}")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        old = consuming / "standards"
        old.mkdir(parents=True)
        (old / "base.json").write_text("{}")  # a real dir from an older install

        get_started.install_standards(consuming, force=True, dry_run=False)

        assert old.is_symlink()

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "base.json").write_text("{}")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_standards(consuming, force=True, dry_run=True)

        assert written == 1
        assert not (consuming / "standards").exists()

    def test_skips_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        assert get_started.install_standards(consuming, force=True, dry_run=False) == 0


# ---------------------------------------------------------------------------
# TestInstallAdrs — project ADRs live in a local adrs/ folder, not standards/
# ---------------------------------------------------------------------------

class TestInstallAdrs:
    def test_seeds_project_adrs_in_adrs_folder(self, tmp_path, monkeypatch):
        import json
        fake_src = tmp_path / "submodule"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(get_started, "SUBMODULE_NAME", "submodule")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_adrs(consuming, dry_run=False)

        assert result is True
        dst = consuming / "adrs" / "adrs.json"
        assert dst.exists()
        # Lives OUTSIDE standards/ so standards/ can be a whole-folder symlink.
        assert not (consuming / "standards" / "adrs.json").exists()
        data = json.loads(dst.read_text())
        assert data["scope"] == "project"
        assert data["adrs"] == []

    def test_never_overwritten(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        (consuming / "adrs").mkdir(parents=True)
        existing = consuming / "adrs" / "adrs.json"
        existing.write_text('{"scope":"project","adrs":[{"id":"ADR-001"}]}')

        result = get_started.install_adrs(consuming, dry_run=False)

        assert result is False
        assert existing.read_text() == '{"scope":"project","adrs":[{"id":"ADR-001"}]}'

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_adrs(consuming, dry_run=True)

        assert result is True
        assert not (consuming / "adrs" / "adrs.json").exists()


# ---------------------------------------------------------------------------
# TestInstallClaudeWindows — copy behaviour (simulated via sys.platform == "win32")
# ---------------------------------------------------------------------------

class TestInstallClaudeWindows:
    def test_copies_whole_claude_tree(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_claude(consuming, force=True, dry_run=False)

        assert written == 3  # agent + command + settings.json
        assert (consuming / ".claude" / "agents" / "01_product_docs" / "prd-writer.md").read_text() == "# prd-writer"
        assert (consuming / ".claude" / "commands" / "run-agent.md").read_text() == "# run-agent"
        # Non-.md files (settings.json) are copied too.
        assert (consuming / ".claude" / "settings.json").exists()

    def test_removes_stale_files(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        stale = consuming / ".claude" / "agents" / "99_retired" / "old.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("old")

        get_started.install_claude(consuming, force=True, dry_run=False)

        assert not stale.exists()

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        written = get_started.install_claude(consuming, force=True, dry_run=True)

        assert written == 3
        assert not (consuming / ".claude").exists()

    def test_skips_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "win32")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        assert get_started.install_claude(consuming, force=True, dry_run=False) == 0

    def test_direct_copy_helper_copies_non_md_too(self, tmp_path):
        """_copy_dir_tree copies all files, not just *.md (e.g. settings.json)."""
        fake_src = _make_claude_src(tmp_path)
        src_dir = fake_src / ".claude"
        dst_dir = tmp_path / "consuming" / ".claude"

        result = get_started._copy_dir_tree(src_dir, dst_dir, force=True, dry_run=False)

        assert result == 3
        assert (dst_dir / "settings.json").exists()


# ---------------------------------------------------------------------------
# TestInstallClaudeLinux — whole-folder symlink (default on Linux/macOS)
# ---------------------------------------------------------------------------

class TestInstallClaudeLinux:
    def test_creates_symlink_to_claude(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_claude(consuming, force=True, dry_run=False)

        dst = consuming / ".claude"
        assert result == 1
        assert dst.is_symlink()
        assert dst.resolve() == (fake_src / ".claude").resolve()

    def test_symlink_uses_relative_target(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_claude(consuming, force=True, dry_run=False)

        assert not os.path.isabs(os.readlink(consuming / ".claude"))

    def test_idempotent_correct_symlink_skipped(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_claude(consuming, force=True, dry_run=False)
        assert get_started.install_claude(consuming, force=False, dry_run=False) == 0

    def test_force_replaces_wrong_symlink(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        dst = consuming / ".claude"
        os.symlink("/tmp/wrong-target", dst)

        result = get_started.install_claude(consuming, force=True, dry_run=False)

        assert result == 1
        assert dst.resolve() == (fake_src / ".claude").resolve()

    def test_force_replaces_existing_directory(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude"
        dst.mkdir(parents=True)
        (dst / "stale.md").write_text("stale")

        result = get_started.install_claude(consuming, force=True, dry_run=False)

        assert result == 1
        assert dst.is_symlink()

    def test_dry_run_does_not_remove_existing_directory(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude"
        dst.mkdir(parents=True)
        (dst / "existing.md").write_text("existing")

        result = get_started.install_claude(consuming, force=True, dry_run=True)

        assert result == 1
        assert dst.is_dir()  # not deleted
        assert (dst / "existing.md").exists()

    def test_no_force_skips_existing_directory(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        dst = consuming / ".claude"
        dst.mkdir(parents=True)
        (dst / "existing.md").write_text("existing")

        result = get_started.install_claude(consuming, force=False, dry_run=False)

        assert result == 0
        assert not dst.is_symlink()

    def test_dry_run_does_not_create_symlink(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_claude(consuming, force=True, dry_run=True)

        assert result == 1
        assert not (consuming / ".claude").exists()

    def test_everything_accessible_through_symlink(self, tmp_path, monkeypatch):
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_claude(consuming, force=True, dry_run=False)

        assert (consuming / ".claude" / "agents" / "01_product_docs" / "prd-writer.md").read_text() == "# prd-writer"
        assert (consuming / ".claude" / "commands" / "run-agent.md").read_text() == "# run-agent"
        assert (consuming / ".claude" / "settings.json").exists()

    def test_cygwin_takes_symlink_path(self, tmp_path, monkeypatch):
        """sys.platform != 'win32' is the correct guard; Cygwin has os.name=='posix'."""
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        monkeypatch.setattr(sys, "platform", "cygwin")
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_claude(consuming, force=True, dry_run=False)

        assert result == 1
        assert (consuming / ".claude").is_symlink()

    def test_skip_when_claude_path_is_regular_file(self, tmp_path, monkeypatch):
        """shutil.rmtree must not be called on a regular file — skip instead."""
        fake_src = _make_claude_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        dst = consuming / ".claude"
        dst.write_text("i am a file, not a directory")

        result = get_started.install_claude(consuming, force=True, dry_run=False)

        assert result == 0
        assert dst.is_file()  # not deleted

    def test_direct_symlink_helper_creates_link(self, tmp_path):
        """_symlink_dir called directly."""
        fake_src = _make_claude_src(tmp_path)
        src_dir = fake_src / ".claude"
        dst_dir = tmp_path / "consuming" / ".claude"

        result = get_started._symlink_dir(src_dir, dst_dir, force=True, dry_run=False)

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
# TestInstallOperationalWorkflows -- emergency-stop / restart
# ---------------------------------------------------------------------------

class TestInstallOperationalWorkflows:
    """The stop/restart workflows read nothing from the submodule, so unlike
    the other installers they must NOT get 'submodules: true' injected --
    otherwise a private submodule that cannot be fetched would break the very
    workflow meant to stop the pipeline."""

    def test_emergency_stop_copied_without_submodule_injection(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / ".github" / "workflows").mkdir(parents=True)
        (fake_src / ".github" / "workflows" / "pipeline-emergency-stop.yml").write_text(
            "steps:\n"
            "  - name: Checkout\n"
            "    uses: actions/checkout@v4\n"
        )
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_emergency_stop_workflow(consuming, force=True, dry_run=False)

        assert result is True
        dst = consuming / ".github" / "workflows" / "pipeline-emergency-stop.yml"
        assert dst.exists()
        assert "submodules: true" not in dst.read_text()

    def test_restart_copied_without_submodule_injection(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "submodule"
        (fake_src / ".github" / "workflows").mkdir(parents=True)
        (fake_src / ".github" / "workflows" / "pipeline-restart.yml").write_text(
            "steps:\n"
            "  - name: Checkout\n"
            "    uses: actions/checkout@v4\n"
        )
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        result = get_started.install_restart_workflow(consuming, force=True, dry_run=False)

        assert result is True
        dst = consuming / ".github" / "workflows" / "pipeline-restart.yml"
        assert dst.exists()
        assert "submodules: true" not in dst.read_text()

    def test_returns_false_when_src_missing(self, tmp_path, monkeypatch):
        fake_src = tmp_path / "empty"
        fake_src.mkdir()
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        assert get_started.install_emergency_stop_workflow(consuming, force=True, dry_run=False) is False
        assert get_started.install_restart_workflow(consuming, force=True, dry_run=False) is False


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
        # Indentation is load-bearing: wrong indent = invalid YAML. The dash
        # sits at 6 spaces, so with: must be at 8 and submodules: at 10.
        assert (
            "      - uses: actions/checkout@abc123\n"
            "        with:\n"
            "          submodules: true\n"
        ) in result
        # The non-checkout step below must remain untouched (no with: injected).
        assert "      - uses: actions/setup-python@def456\n" in result

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
        assert f"{self._name()}/docs/product/orchestrator/13-todos.md" in result
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
        (wf_dir / "orchestrator.yml").write_text(
            "steps:\n  - name: Checkout\n    uses: actions/checkout@v4\n"
        )
        return fake_src

    def test_copies_workflow_file(self, tmp_path, monkeypatch):
        fake_src = self._make_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.install_orchestrator_workflows(consuming, force=True, dry_run=False)

        assert count == 1
        assert (consuming / ".github" / "workflows" / "orchestrator.yml").exists()

    def test_injects_submodules_true(self, tmp_path, monkeypatch):
        fake_src = self._make_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.install_orchestrator_workflows(consuming, force=True, dry_run=False)

        content = (consuming / ".github" / "workflows" / "orchestrator.yml").read_text()
        assert "submodules: true" in content, "orchestrator.yml missing submodules: true"

    def test_returns_zero_when_src_missing(self, tmp_path, monkeypatch):
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

        assert count == 1
        assert not (consuming / ".github" / "workflows" / "orchestrator.yml").exists()

    def test_skip_when_force_false_and_file_exists(self, tmp_path, monkeypatch):
        fake_src = self._make_src(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        wf_dir = consuming / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        existing = wf_dir / "orchestrator.yml"
        existing.write_text("original content")

        get_started.install_orchestrator_workflows(consuming, force=False, dry_run=False)

        assert existing.read_text() == "original content"


# TestInstallSlashCommands / TestInstallLocalSettings retired: slash commands and
# settings now arrive via the whole-.claude symlink, and there is no generated
# local config file (the consuming repo owns only its adrs/ folder).


# ---------------------------------------------------------------------------
# TestAddGitignoreEntries
# ---------------------------------------------------------------------------

class TestAddGitignoreEntries:
    def _make_submodule(self, tmp_path):
        """Minimal submodule with a standards dir."""
        fake_src = tmp_path / "submodule"
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "architecture.json").write_text("{}")
        return fake_src

    def test_creates_gitignore_with_symlinked_folders(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        count = get_started.add_gitignore_entries(consuming, dry_run=False)

        assert count == 2
        text = (consuming / ".gitignore").read_text()
        # Whole-folder symlinks are gitignored (force-committed by the setup job).
        assert ".claude" in text
        assert "standards" in text
        # Retired per-entry patterns must not appear.
        assert ".claude/agents" not in text
        assert ".claude/commands/" not in text
        assert ".claude/settings.local.json" not in text
        assert "standards/architecture.json" not in text

    def test_excludes_project_owned_adrs(self, tmp_path, monkeypatch):
        """The adrs/ folder is project-owned and stays committed (not gitignored)."""
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert "adrs" not in text.split()

    def test_seed_mode_omits_standards(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.add_gitignore_entries(consuming, dry_run=False, include_standards=False)

        lines = (consuming / ".gitignore").read_text().splitlines()
        assert ".claude" in lines
        assert "standards" not in lines

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
        assert ".claude" in text.splitlines()

    def test_no_leading_blank_line_when_gitignore_absent(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert not text.startswith("\n")
        first_line = text.splitlines()[0]
        assert first_line == (
            "# Managed by get_started.py -- do not commit these paths manually; "
            "sync-claude.yml is the authoritative committer"
        )

    def test_single_separator_newline_before_header(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        (consuming / ".gitignore").write_text("*.pyc\n__pycache__/\n")

        get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert (
            "__pycache__/\n"
            "\n"
            "# Managed by get_started.py -- do not commit these paths manually; "
            "sync-claude.yml is the authoritative committer"
        ) in text

    def test_appends_without_duplicate_header_when_header_present(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        header = (
            "# Managed by get_started.py -- do not commit these paths manually; "
            "sync-claude.yml is the authoritative committer"
        )
        # Seed with header + one managed pattern (.claude) already present.
        (consuming / ".gitignore").write_text(
            "*.pyc\n\n" + header + "\n.claude\n"
        )

        count = get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert text.count(header) == 1          # no duplicate header
        assert "standards" in text.splitlines()  # the missing pattern was appended
        assert text.split().count(".claude") == 1  # not re-added
        assert count == 1

    def test_idempotent_no_duplicate_entries(self, tmp_path, monkeypatch):
        fake_src = self._make_submodule(tmp_path)
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)
        consuming = tmp_path / "consuming"
        consuming.mkdir()

        first = get_started.add_gitignore_entries(consuming, dry_run=False)
        second = get_started.add_gitignore_entries(consuming, dry_run=False)

        assert first == 2  # .claude + standards
        assert second == 0
        text = (consuming / ".gitignore").read_text()
        assert text.split().count(".claude") == 1

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
        (consuming / ".gitignore").write_text(".claude\n")

        count = get_started.add_gitignore_entries(consuming, dry_run=False)

        text = (consuming / ".gitignore").read_text()
        assert text.split().count(".claude") == 1
        assert "standards" in text.splitlines()
        assert count == 1  # only 'standards' was missing


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
                stdout = ".claude\n" if args[-1] == ".claude" else ""
                return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
            if "rm" in args:
                return types.SimpleNamespace(returncode=0, stdout="rm '.claude'\n", stderr="")
            return types.SimpleNamespace(returncode=1, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", _mock_run)

        result = get_started.untrack_managed_paths(consuming, dry_run=False)

        rm_calls = [c for c in calls if "rm" in c]
        assert result == 1
        assert len(rm_calls) == 1
        assert "--cached" in rm_calls[0]
        assert ".claude" in rm_calls[0]


# ---------------------------------------------------------------------------
# TestPrintFollowup
# ---------------------------------------------------------------------------

class TestPrintFollowup:
    """print_followup emits the load-bearing setup guidance. We assert stable
    substrings rather than whole-line matches so wording tweaks don't break."""

    def test_emits_load_bearing_guidance(self, tmp_path, capsys):
        get_started.print_followup(tmp_path)
        out = capsys.readouterr().out

        assert "ANTHROPIC_API_KEY" in out
        assert "AI_AGILE_BOT_TOKEN" in out
        assert "2. Commit the seed files" in out
        assert "3. Open a test issue" in out

    def test_references_single_orchestrator_workflow(self, tmp_path, capsys):
        """A SINGLE orchestrator.yml workflow is installed — the old split
        pre-execute/execute files no longer exist and must not be referenced."""
        get_started.print_followup(tmp_path)
        out = capsys.readouterr().out

        assert "orchestrator.yml" in out
        # The retired split workflow filenames must not appear.
        assert "pre-execute" not in out
        assert "execute.yml" not in out

    def test_emits_requirements_txt_in_git_add(self, tmp_path, capsys):
        """requirements.txt must appear in the git add list so the first
        pipeline run's 'pip install -r requirements.txt' does not fail."""
        get_started.print_followup(tmp_path)
        out = capsys.readouterr().out

        assert "requirements.txt" in out


# ---------------------------------------------------------------------------
# TestParseArgsAndMain
# ---------------------------------------------------------------------------

class TestParseArgsAndMain:
    def test_parse_args_defaults(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["get_started.py"])
        args = get_started.parse_args()
        assert args.force is False
        assert args.dry_run is False

    def test_parse_args_flags(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["get_started.py", "--force", "--dry-run"])
        args = get_started.parse_args()
        assert args.force is True
        assert args.dry_run is True

    def test_main_runs_dry_run_end_to_end(self, tmp_path, monkeypatch, capsys):
        """main() in --dry-run wires the consuming repo without writing files."""
        # A minimal submodule with one of every source the installers read.
        fake_src = tmp_path / "submodule"
        wf = fake_src / ".github" / "workflows"
        wf.mkdir(parents=True)
        for name in (
            "orchestrator.yml",
            "bootstrap-labels.yml",
            "label-cleanup.yml",
            "sync-claude.yml",
            "pipeline-emergency-stop.yml",
            "pipeline-restart.yml",
        ):
            (wf / name).write_text("steps:\n  - uses: actions/checkout@v4\n")
        (fake_src / "standards").mkdir(parents=True)
        (fake_src / "standards" / "architecture.json").write_text("{}")
        (fake_src / ".claude" / "agents").mkdir(parents=True)
        (fake_src / ".claude" / "agents" / "agent.md").write_text("# agent")
        (fake_src / ".claude" / "commands").mkdir(parents=True)
        (fake_src / ".claude" / "commands" / "cmd.md").write_text("# cmd")
        monkeypatch.setattr(get_started, "SUBMODULE_ROOT", fake_src)

        consuming = tmp_path / "consuming"
        consuming.mkdir()
        monkeypatch.setattr(
            get_started, "find_consuming_repo_root", lambda: consuming
        )
        monkeypatch.setattr(sys, "argv", ["get_started.py", "--dry-run"])

        rc = get_started.main()

        assert rc == 0
        out = capsys.readouterr().out
        assert "dry run" in out
        # Dry-run must not have written anything into the consuming repo.
        assert not (consuming / ".github").exists()
        assert not (consuming / "standards").exists()
        assert not (consuming / ".gitignore").exists()


# ---------------------------------------------------------------------------
# TestFindConsumingRepoRoot
# ---------------------------------------------------------------------------

class TestFindConsumingRepoRoot:
    def test_returns_superproject_path(self, tmp_path, monkeypatch):
        """Success path: git reports a superproject working tree."""
        import subprocess as sp
        import types

        super_dir = tmp_path / "super"
        super_dir.mkdir()

        def _mock_run(args, **kwargs):
            return types.SimpleNamespace(
                returncode=0, stdout=str(super_dir) + "\n", stderr=""
            )

        monkeypatch.setattr(sp, "run", _mock_run)

        result = get_started.find_consuming_repo_root()

        assert result == super_dir.resolve()

    def test_exits_when_superproject_empty(self, monkeypatch):
        """Empty superproject output => not installed as a submodule => sys.exit."""
        import subprocess as sp
        import types

        def _mock_run(args, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout="\n", stderr="")

        monkeypatch.setattr(sp, "run", _mock_run)

        with pytest.raises(SystemExit) as exc:
            get_started.find_consuming_repo_root()
        # Non-zero / message exit (SystemExit carries the error string).
        assert "submodule" in str(exc.value)

    def test_exits_when_git_missing(self, monkeypatch):
        """git binary missing => FileNotFoundError => sys.exit with guidance."""
        import subprocess as sp

        def _raise(*args, **kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(sp, "run", _raise)

        with pytest.raises(SystemExit) as exc:
            get_started.find_consuming_repo_root()
        assert "git" in str(exc.value)


# ---------------------------------------------------------------------------
# TestDryRunStaleRemoval — the "WOULD REMOVE" branch
# ---------------------------------------------------------------------------

class TestDryRunStaleRemoval:
    def test_copy_dir_tree_dry_run_would_remove(self, tmp_path, capsys):
        """_copy_dir_tree (Windows path) in dry_run prints WOULD REMOVE for
        stale files instead of deleting them."""
        fake_src = _make_claude_src(tmp_path)
        src_dir = fake_src / ".claude"
        dst_dir = tmp_path / "consuming" / ".claude"
        stale = dst_dir / "agents" / "99_retired" / "old-agent.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("old")

        get_started._copy_dir_tree(src_dir, dst_dir, force=True, dry_run=True)

        out = capsys.readouterr().out
        assert "WOULD REMOVE" in out
        assert stale.exists()  # dry-run must not delete


# ---------------------------------------------------------------------------
# TestGuardExistingClaude — refuse to clobber a consuming repo's own .claude
# ---------------------------------------------------------------------------

class TestGuardExistingClaude:
    def test_fails_on_foreign_claude_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AI_AGILE_REPLACE_CLAUDE", raising=False)
        consuming = tmp_path / "consuming"
        (consuming / ".claude").mkdir(parents=True)
        (consuming / ".claude" / "settings.json").write_text("{}")  # parent's own config

        with pytest.raises(SystemExit) as exc:
            get_started._guard_existing_claude(consuming)
        assert ".claude" in str(exc.value)

    def test_passes_when_missing(self, tmp_path):
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        get_started._guard_existing_claude(consuming)  # no exception

    def test_passes_when_already_symlink(self, tmp_path):
        """A re-run where .claude is already the framework's symlink is fine."""
        consuming = tmp_path / "consuming"
        consuming.mkdir()
        target = tmp_path / "submodule" / ".claude"
        target.mkdir(parents=True)
        os.symlink(os.path.relpath(target, consuming), consuming / ".claude")
        get_started._guard_existing_claude(consuming)  # no exception

    def test_passes_for_prior_managed_install(self, tmp_path):
        """An old-style managed .claude (real dir with a .claude/agents symlink)
        is safe to convert, so the guard allows it."""
        consuming = tmp_path / "consuming"
        (consuming / ".claude").mkdir(parents=True)
        agents_target = tmp_path / "submodule" / ".claude" / "agents"
        agents_target.mkdir(parents=True)
        os.symlink(agents_target, consuming / ".claude" / "agents")
        get_started._guard_existing_claude(consuming)  # no exception

    def test_bypass_env_allows_replacement(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_AGILE_REPLACE_CLAUDE", "1")
        consuming = tmp_path / "consuming"
        (consuming / ".claude").mkdir(parents=True)
        (consuming / ".claude" / "settings.json").write_text("{}")
        get_started._guard_existing_claude(consuming)  # no exception
