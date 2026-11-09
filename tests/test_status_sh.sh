#!/usr/bin/env bash
# Tests status.sh's statuses.json override block (the `while read ... done <
# <(python3 ...)` near the top of the file): every entry in the real
# pipeline/statuses.json must be readable without the python heredoc
# crashing.
#
# Regression test: the heredoc used to read s['description'], but every
# pipeline/statuses.json entry carries its text under 'meaning' instead.
# The KeyError was silently swallowed by the process substitution (bash does
# not propagate a `done < <(...)` command's exit status under `set -e`), so
# STATUS_DESCRIPTIONS quietly kept its hardcoded fallback text instead of the
# real statuses.json content, with no non-zero exit anywhere to surface it.

set -euo pipefail

PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

test_statuses_json_override_loads_without_error() {
  local stderr_file
  stderr_file="$(mktemp)"

  # Sourcing (not executing) status.sh skips its CLI dispatch block (guarded
  # by `[[ "${BASH_SOURCE[0]}" == "${0}" ]]`), so this only runs the
  # top-of-file statuses.json override block, then inspects the array it
  # populates.
  local output
  output="$(
    cd "${REPO_ROOT}" && bash -c '
      source scripts/status.sh
      for s in requested wip complete review blocked failed exhausted skipped approved; do
        printf "%s\t%s\n" "$s" "${STATUS_DESCRIPTIONS[$s]:-__MISSING__}"
      done
    ' 2>"$stderr_file"
  )"

  if grep -q "KeyError" "$stderr_file"; then
    fail "statuses.json override raised KeyError: $(cat "$stderr_file")"
  else
    pass "statuses.json override ran without a KeyError"
  fi

  # Every status in the real pipeline/statuses.json has a long-form
  # 'meaning' field (well over 40 characters); the hardcoded fallback
  # strings declared in status.sh are all short one-liners -- so seeing a
  # long value for every status proves the real JSON was actually loaded,
  # not just that the fallback survived a swallowed crash untouched.
  local short_value=""
  while IFS=$'\t' read -r _status _desc; do
    if [ "${#_desc}" -lt 40 ]; then
      short_value="${_status}=${_desc}"
      break
    fi
  done <<<"$output"

  if [ -z "$short_value" ]; then
    pass "STATUS_DESCRIPTIONS populated from statuses.json's 'meaning' field, not the hardcoded fallback"
  else
    fail "STATUS_DESCRIPTIONS still holds a short/fallback value ($short_value)"
  fi

  rm -f "$stderr_file"
}

test_statuses_json_override_loads_without_error

echo ""
echo "status.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
