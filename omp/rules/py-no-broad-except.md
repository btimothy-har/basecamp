---
description: "Catch specific exception types; reserve `except Exception` for explicit boundaries"
condition: "(?m)^[ \\t]*except[ \\t]+\\(?[ \\t]*(?:Exception|BaseException)\\b"
scope: "tool:edit(*.py), tool:write(*.py)"
interruptMode: never
---

Catching broad `Exception` (or worse, `BaseException`) deep inside program logic masks failures you did not anticipate. Prefer catching the specific types the try block can raise.

## Why

- Broad catches hide programming errors (`NameError`, `TypeError`, `AttributeError`) that should crash loudly during development.
- `BaseException` additionally swallows `KeyboardInterrupt` and `SystemExit`.
- A specific `except` clause documents the contract of the code it guards.

## Prefer

```python
# Bad — masks unrelated bugs
try:
    data = json.loads(payload)
except Exception:
    return None

# Good — names the expected failure
try:
    data = json.loads(payload)
except json.JSONDecodeError as e:
    raise ValidationError(f"Invalid payload: {e}") from e
```

## Legitimate uses

Broad catches belong at top-level boundaries — the `main()` entry point, a web-framework request handler, a background-job wrapper — where the handler has explicit behavior: log with traceback, return a 500, mark the job failed, or exit with a status code. A boundary catch without explicit behavior is just a silent failure.
