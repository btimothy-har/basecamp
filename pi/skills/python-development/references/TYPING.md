# Type Annotations

Use modern Python 3.12+ typing syntax throughout.

## Modern Syntax

```python
# GOOD: Python 3.10+ union syntax
def process(value: str | None) -> dict[str, int]: ...

# BAD: Legacy typing module imports
from typing import Optional, Dict, List
def process(value: Optional[str]) -> Dict[str, int]: ...
```

## Built-in Generics

```python
# Use lowercase built-in types (Python 3.9+)
items: list[str]
mapping: dict[str, int]
unique: set[int]
pair: tuple[str, int]
callback: Callable[[int, str], bool]
```

## Type Aliases

```python
# Simple alias with type statement (Python 3.12+)
type UserId = int
type Coordinates = tuple[float, float]
type Handler = Callable[[Request], Response]

# Or TypeAlias for compatibility
from typing import TypeAlias
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
```

## Constraining Values

```python
from typing import Literal, Final

# Literal for specific allowed values
def set_mode(mode: Literal["read", "write", "append"]) -> None: ...

# Final for constants that shouldn't be reassigned
MAX_CONNECTIONS: Final = 100
```

## Class Attributes

```python
from typing import ClassVar

class Counter:
    instances: ClassVar[int] = 0  # Class-level, not instance
    value: int                     # Instance attribute
```

## Protocols for Duck Typing

```python
from typing import Protocol

# Define interface by behavior, not inheritance
class Closable(Protocol):
    def close(self) -> None: ...

def cleanup(resource: Closable) -> None:
    resource.close()  # Works with any object that has close()
```

## Generics

```python
from typing import TypeVar

T = TypeVar("T")

def first(items: list[T]) -> T | None:
    return items[0] if items else None

# Bounded generics
from typing import SupportsFloat
N = TypeVar("N", bound=SupportsFloat)

def average(values: list[N]) -> float:
    return sum(float(v) for v in values) / len(values)
```

## Self Type

```python
from typing import Self

class Builder:
    def with_name(self, name: str) -> Self:
        self.name = name
        return self  # Returns same type, even in subclasses
```

## When to Annotate

- Always: function signatures, return types, class attributes
- Usually: variables where type isn't obvious from assignment
- Skip: locals where type is obvious (`name = "Alice"`)
