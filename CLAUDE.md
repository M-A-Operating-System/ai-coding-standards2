# CLAUDE.md — Project-wide coding rules

## ASCII-safe output

Never write emoji or non-ASCII characters inside code, configuration, or
workflow files. This includes:

- Python source files (`.py`)
- Shell scripts (`.sh`)
- GitHub Actions workflow YAML files (`.yml` / `.yaml`)
- JSON files (`.json`)
- Any file that a Windows developer or CI runner may read with a default
  (non-UTF-8) encoding

Use plain ASCII equivalents instead:

| Instead of | Use |
|---|---|
| `✓` / `✅` | `OK:` |
| `⚠️` / `⚠` | `WARNING:` |
| `❌` / `✗` | `ERROR:` / `FAIL:` |
| `→` | `->` |
| `—` (em dash) | `--` |
| Any other symbol or emoji | A plain English word or abbreviation |

Markdown documentation files (`.md`) may use emoji only when the user
explicitly requests it — the default is still no emoji.
