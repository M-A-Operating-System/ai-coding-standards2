Read atlas.hcl to find the active environment. Then run:

1. `atlas schema validate --env <env>` to verify schema files are valid
2. `atlas migrate diff --env <env> "$ARGUMENTS"`
3. `atlas migrate lint --env <env> --latest 1`
4. If lint passes, show the generated SQL. If it fails, fix and re-lint.