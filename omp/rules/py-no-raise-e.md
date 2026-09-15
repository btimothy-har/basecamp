---
description: "Re-raise with bare `raise`, not `raise e`, inside an except handler"
condition: "(?m)^([ \\t]*)except[ \\t]+[\\w.()]+[ \\t]+as[ \\t]+([A-Za-z_]\\w*)[ \\t]*:[^\\n]*\\n(?:\\1[ \\t]+[^\\n]*\\n)*?\\1[ \\t]+raise[ \\t]+\\2[ \\t]*(?:#.*)?$"
scope: "tool:edit(*.py), tool:write(*.py)"
interruptMode: never
---

Inside an `except ... as e:` handler, `raise e` re-raises the caught exception as if it originated at the `raise` line, cluttering the traceback. Bare `raise` re-raises with the original traceback intact.

## Why

```python
# Bad — traceback gains a confusing extra frame
try:
    process()
except ProcessError as e:
    logger.exception("Processing failed")
    raise e

# Good — original traceback preserved exactly
try:
    process()
except ProcessError:
    logger.exception("Processing failed")
    raise
```

## Prefer

- Re-raise the same exception: bare `raise`.
- Raise a different exception: `raise DomainError(...) from e` to preserve the chain explicitly.

## Legitimate uses

`raise e` is necessary outside the active handler — e.g. re-raising an exception object stored earlier, or re-raising from a callback that receives the exception as a value. Inside the handler that caught it, bare `raise` is the right form.
