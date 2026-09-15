---
description: "Remove try/except wrappers whose handler only bare-reraises; call the code directly"
condition: "(?m)^([ \\t]*)except\\b[^\\n]*:[^\\n]*\\n\\1[ \\t]+raise[ \\t]*(?:#[^\\n]*)?(?=\\n(?!\\1[ \\t]+\\S)|(?![\\s\\S]))"
scope: "tool:edit(*.py), tool:write(*.py)"
interruptMode: never
---

A `try`/`except` whose handler does nothing but bare `raise` adds a frame of noise without changing behavior. Delete the wrapper.

## Why

```python
# Bad — the except clause accomplishes nothing
def process(data: bytes) -> Result:
    try:
        return transform(data)
    except TransformError:
        raise

# Good — identical behavior, less code
def process(data: bytes) -> Result:
    return transform(data)
```

## Prefer

Keep the `try` only when the handler adds something: logging with `logger.exception()`, converting to a domain exception with `raise ... from e`, or cleanup. For cleanup that runs either way, use `finally` or a context manager instead of catch-and-reraise.

## Legitimate uses

A placeholder handler during active development, or an explicit `raise` kept to satisfy a type checker or document intent, is fine temporarily — but it should not survive review.
