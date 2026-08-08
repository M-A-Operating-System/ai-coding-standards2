"""Tests for issue #279: release-notes categorization fix.

Realises the Gherkin scenarios in docs/features/release.md:

  Scenario: A pipeline PR is categorized by its classification
  Scenario: release.yml categories match labels that PRs actually carry
  Scenario: Unlabeled hand-authored PRs still appear
  Scenario: A doc-bearing / bug / toil PR lands in the right bucket
"""
import subprocess
import os
from pathlib import Path

import yaml
import pytest

REPO_ROOT = Path(__file__).parent.parent
RELEASE_YML = REPO_ROOT / ".github" / "release.yml"
LINK_SCRIPT = REPO_ROOT / ".github" / "scripts" / "link-pr-to-issue.sh"

CLASSIFICATION_LABELS = {
    "classification: feature",
    "classification: enhancement",
    "classification: bug",
    "classification: toil",
}


def _load_release_yml():
    return yaml.safe_load(RELEASE_YML.read_text())


def _all_category_labels(config):
    """Return all non-catch-all labels across every category."""
    labels = []
    for cat in config["changelog"]["categories"]:
        for lbl in cat.get("labels", []):
            if lbl != "*":
                labels.append(lbl)
    return labels


# ---------------------------------------------------------------------------
# Scenario: release.yml categories match labels that PRs actually carry
# ---------------------------------------------------------------------------

class TestRelaseYmlMatchesPipelineLabels:
    def test_every_non_catchall_label_is_a_classification_label(self):
        """Every non-catch-all category label is a classification: {type} label.

        Realises: Scenario: release.yml categories match labels that PRs actually carry
        """
        config = _load_release_yml()
        non_catchall = _all_category_labels(config)
        assert non_catchall, "Expected at least one non-catch-all label in release.yml"
        for label in non_catchall:
            assert label.startswith("classification: "), (
                f"Label '{label}' is not a classification label — "
                "release.yml references labels that pipeline does not apply to PRs"
            )

    def test_classification_feature_is_in_features_category(self):
        config = _load_release_yml()
        cats = {cat["title"]: cat.get("labels", []) for cat in config["changelog"]["categories"]}
        assert "classification: feature" in cats.get("Features", []), (
            "classification: feature must appear in the Features category"
        )

    def test_classification_enhancement_is_in_features_category(self):
        config = _load_release_yml()
        cats = {cat["title"]: cat.get("labels", []) for cat in config["changelog"]["categories"]}
        assert "classification: enhancement" in cats.get("Features", []), (
            "classification: enhancement must appear in the Features category"
        )

    def test_classification_bug_is_in_fixes_category(self):
        config = _load_release_yml()
        cats = {cat["title"]: cat.get("labels", []) for cat in config["changelog"]["categories"]}
        assert "classification: bug" in cats.get("Fixes", []), (
            "classification: bug must appear in the Fixes category"
        )

    def test_classification_toil_is_in_maintenance_category(self):
        config = _load_release_yml()
        cats = {cat["title"]: cat.get("labels", []) for cat in config["changelog"]["categories"]}
        assert "classification: toil" in cats.get("Maintenance", []), (
            "classification: toil must appear in the Maintenance category"
        )


# ---------------------------------------------------------------------------
# Scenario: Unlabeled hand-authored PRs still appear
# ---------------------------------------------------------------------------

class TestUnlabeledPrsStillAppear:
    def test_catch_all_category_exists(self):
        """The '*' catch-all category is present so unlabeled PRs are not dropped.

        Realises: Scenario: Unlabeled hand-authored PRs still appear
        """
        config = _load_release_yml()
        categories = config["changelog"]["categories"]
        catch_all_found = any(
            "*" in cat.get("labels", []) for cat in categories
        )
        assert catch_all_found, (
            "release.yml must have a category with label '*' so that "
            "unlabeled hand-authored PRs are not silently dropped from release notes"
        )

    def test_catch_all_is_last_category(self):
        """The catch-all category appears last so it does not swallow labelled PRs."""
        config = _load_release_yml()
        categories = config["changelog"]["categories"]
        last_cat = categories[-1]
        assert "*" in last_cat.get("labels", []), (
            "The catch-all ('*') category must be the last one in release.yml "
            "so pipeline PRs match their specific category first"
        )


# ---------------------------------------------------------------------------
# Scenario: A pipeline PR is categorized by its classification
# Scenario: A doc-bearing / bug / toil PR lands in the right bucket
# (link-pr-to-issue.sh: classification label is copied from issue to PR)
# ---------------------------------------------------------------------------

MOCK_GH_CLASSIFY = r"""#!/usr/bin/env bash
cmd="$*"
case "$cmd" in
  *"--method POST"*"/labels"*)
    echo "LABEL_APPLIED: $*" >&2
    exit 0
    ;;
  *"label create"*)
    exit 0
    ;;
  *"repos/"*"/issues/${ISSUE_NUMBER}"*)
    # Simulate gh api --jq output: plain-text label name only (empty when absent).
    # The real gh CLI applies --jq internally and writes only the matched text.
    if [[ -n "${CLASSIFICATION}" ]]; then
      printf '%s\n' "${CLASSIFICATION}"
    fi
    exit 0
    ;;
  *"repos/"*"/issues/"*)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""


def _run_link_script(tmp_path, classification):
    """Run link-pr-to-issue.sh with a mock gh that returns the given classification."""
    mock_dir = tmp_path / "bin"
    mock_dir.mkdir()
    gh = mock_dir / "gh"
    gh.write_text(MOCK_GH_CLASSIFY)
    gh.chmod(0o755)
    env = {
        "PATH": f"{mock_dir}:/usr/bin:/bin",
        "REPO": "owner/repo",
        "ISSUE_NUMBER": "1",
        "PR_NUMBER": "2",
        "CLASSIFICATION": classification,
    }
    result = subprocess.run(
        ["bash", str(LINK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr, result.returncode


class TestLinkPrToIssueClassification:
    def test_feature_classification_is_applied_to_pr(self, tmp_path):
        """link-pr-to-issue.sh copies classification: feature from issue to PR.

        Realises: Scenario: A pipeline PR is categorized by its classification
        """
        out, rc = _run_link_script(tmp_path, "classification: feature")
        assert rc == 0, f"Script failed: {out}"
        assert "classification: feature" in out

    def test_bug_classification_is_applied_to_pr(self, tmp_path):
        """link-pr-to-issue.sh copies classification: bug from issue to PR.

        Realises: Scenario: A doc-bearing / bug / toil PR lands in the right bucket
        """
        out, rc = _run_link_script(tmp_path, "classification: bug")
        assert rc == 0, f"Script failed: {out}"
        assert "classification: bug" in out

    def test_toil_classification_is_applied_to_pr(self, tmp_path):
        """link-pr-to-issue.sh copies classification: toil from issue to PR.

        Realises: Scenario: A doc-bearing / bug / toil PR lands in the right bucket
        """
        out, rc = _run_link_script(tmp_path, "classification: toil")
        assert rc == 0, f"Script failed: {out}"
        assert "classification: toil" in out

    def test_no_classification_label_does_not_fail(self, tmp_path):
        """link-pr-to-issue.sh succeeds and skips label when issue has none.

        Hand-authored PRs have no classification; the script must not crash or
        apply a label.
        """
        out, rc = _run_link_script(tmp_path, "")
        assert rc == 0, f"Script failed: {out}"
        assert "Applied classification:" not in out, (
            "No classification label should be applied when the issue has none"
        )

    def test_source_issue_label_always_applied(self, tmp_path):
        """source-issue:N is always applied regardless of classification presence."""
        out, rc = _run_link_script(tmp_path, "classification: feature")
        assert rc == 0, f"Script failed: {out}"
        assert "source-issue:1" in out
