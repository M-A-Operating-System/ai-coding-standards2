# CLAUDE.md — Project-wide coding rules

## ASCII-safe output

Never write emoji or non-ASCII characters inside code, configuration, or
workflow files. This includes Python source files, shell scripts, GitHub
Actions workflow YAML files, and JSON files. Use plain English words or
abbreviations instead.

Markdown documentation files (`.md`) may use emoji only when the user
explicitly requests it.
