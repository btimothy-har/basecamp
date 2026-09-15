---
description: "Avoid mutable list/dict/set defaults in function signatures; use None or immutable sentinels"
condition: "(?ms)^(?=[ \\t]*(?:async[ \\t]+)?def\\b)(?:(?!\\)\\s*(?:->[^:\\n]*)?:)[\\s\\S])*?(?:\\(|,)\\s*\\*{0,2}[A-Za-z_]\\w*(?:\\s*:[^=\\n]+)?\\s*=\\s*(?:\\[[^\\]\\n]*\\]|\\{[^}\\n]*\\}|(?:list|dict|set)\\(\\s*\\))"
scope: "tool:edit(*.py), tool:write(*.py)"
interruptMode: never
---

A mutable default argument (`=[]`, `={}`, `=set()`) is evaluated once at function-definition time and shared across every call. Mutations leak between invocations.

## Why

```python
# Bad — the same list object is reused on every call
def append_tag(tag: str, tags: list[str] = []) -> list[str]:
    tags.append(tag)
    return tags

append_tag("a")  # ["a"]
append_tag("b")  # ["a", "b"] — surprising!
```

## Prefer

```python
# Good — fresh list per call
def append_tag(tag: str, tags: list[str] | None = None) -> list[str]:
    tags = [] if tags is None else tags
    tags.append(tag)
    return tags
```

Immutable alternatives (`()`, `frozenset()`, `MappingProxyType`) are also safe defaults when the function only reads the value.

## Legitimate uses

Intentionally shared state — a memoization cache or registry — can live in a default, but that is a deliberate design choice: name it clearly and document that it persists across calls. Dataclass and pydantic fields are unaffected; this concern is about plain function signatures.
