# Enhancement: Reduce CI Log Verbosity

In `pipeline/pipeline_orchestrator.py`, inside `invoke_agent()`, replace the stderr write block in the stdout read loop:

```python
# BEFORE
try:
    _ev = json.loads(line)
    if _ev.get("type") != "system":
        sys.stderr.write(line)
except (json.JSONDecodeError, AttributeError):
    sys.stderr.write(line)  # non-JSON lines always shown
```

```python
# AFTER
try:
    _ev = json.loads(line)
    if args.verbose or _ev.get("type") == "result":
        sys.stderr.write(line)
except (json.JSONDecodeError, AttributeError):
    sys.stderr.write(line)
```

`args` is not in scope inside `invoke_agent()` — pass it as a parameter or use a module-level flag. The simplest approach is a module-level bool set in `main()`:

```python
# at module level
_VERBOSE = False

# in main(), after parse_args()
global _VERBOSE
_VERBOSE = args.verbose
```

Then in the read loop:

```python
if _VERBOSE or _ev.get("type") == "result":
    sys.stderr.write(line)
```

**Result:** Normal CI runs log one summary JSON line per agent invocation. Full stream-json output is only shown when the orchestrator is invoked with `--verbose` / `-v`.
