"""Tests for get_started._add_submodules_to_checkout."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import get_started


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
