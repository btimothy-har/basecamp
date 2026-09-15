---
description: "Prefer explicit exception types over a bare `except:` clause"
condition: "(?m)^[ \\t]*except[ \\t]*:[ \\t]*(?:#[^\\n]*)?$"
scope: "tool:edit(*.py), tool:write(*.py)"
interruptMode: never
---

A bare `except:` catches every exception, including `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit`. Prefer naming the exceptions you actually handle.

## Why

- Bare `except:` intercepts Ctrl+C and interpreter shutdown, making processes hard to stop.
- It hides programming errors (`NameError`, `TypeError`) that should surface during development.
- Naming the exception type documents which failures the handler expects.

## Prefer

```python
# Bad — swallows everything, including interrupts
try:
    process()
except:
    recover()

# Good — handles the expected failure
try:
    process()
except TransientError:
    recover()
```

If the intent is genuinely "any application failure", `except Exception:` still lets system-level signals propagate.

## Legitimate uses

A bare `except:` can be right at a process boundary when the handler re-raises after cleanup or logs unconditionally — e.g. a worker loop that must record every outcome before exiting. Keep those rare and deliberate.
