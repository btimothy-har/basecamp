---
description: "Do not extract one-return functions that only wrap an expression — inline them"
astCondition:
  - "def $F($$$P): return $E"
  - "def $F($$$P) -> $T: return $E"
  - "async def $F($$$P): return $E"
  - "async def $F($$$P) -> $T: return $E"
scope: "tool:edit(*.py), tool:write(*.py)"
interruptMode: never
---

Inline functions whose whole body is a single `return` of an expression, unless the name creates a durable contract.

## Why

- One-line wrappers add no behavior; readers jump to the definition to confirm triviality.
- A signature freezes the shape too early and invites call-site coupling.
- Inline expressions read better in search results and type inference.

## Prefer

```python
# Bad — pure rename, no behavior added
def get_user_email(user: User) -> str:
    return user.email

def is_empty(items: list[Item]) -> bool:
    return len(items) == 0

# Good — use the language directly
email = user.email
if not items:
    ...
```

## Allowed tiny functions

- Public or otherwise durable contract: the name is a stable API or domain concept.
- `@property`, overrides, and protocol/interface implementations where the shape is mandated.
- Callback identity matters: the function object itself is registered, compared, or passed.
- DI boundary or test seam that needs an indirection point.
- Type guards and narrowing helpers (`TypeIs`/`TypeGuard`).
- Three or more call sites need lockstep behavior behind one name.
- The name documents a non-obvious formula or domain computation the bare expression would not explain.

If none apply, inline it.
