# Data Structures

**Default to pydantic.** Use dataclass only when you have a specific reason not to.

## Decision Matrix

| Need | Use |
|------|-----|
| **Default choice** | `pydantic.BaseModel` |
| Minimal overhead, no validation needed | `dataclass` |
| Immutable, hashable (dict keys, set members) | `NamedTuple` |
| Dict compatibility (legacy APIs, JSON passthrough) | `TypedDict` |

## pydantic BaseModel (Default)

Use pydantic for data structures. It provides validation, serialization, and excellent IDE support.

```python
from pydantic import BaseModel, Field

class User(BaseModel):
    name: str = Field(min_length=1)
    email: str
    age: int = Field(ge=0)

# Validates on construction
user = User(name="Alice", email="alice@example.com", age=30)

# Serialization built-in
data = user.model_dump()  # {"name": "Alice", ...}
json_str = user.model_dump_json()

# From dict (with validation)
user = User.model_validate({"name": "Bob", "email": "bob@example.com", "age": 25})
```

**Why pydantic by default:**
- Validates data at construction (catches bugs early)
- Type coercion (string "123" → int 123)
- Built-in serialization (`.model_dump()`, `.model_dump_json()`)
- JSON Schema generation
- Excellent IDE autocomplete and type checking
- Immutability option with `frozen=True`

### Validation

```python
from pydantic import BaseModel, EmailStr, Field, field_validator

class User(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    age: int = Field(ge=0, le=150)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        return v.strip().title()

# Invalid data raises ValidationError with clear messages
# User(name="", email="not-an-email", age=-5)
```

### Immutability

```python
from pydantic import BaseModel, ConfigDict

class Point(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    x: float
    y: float

p = Point(x=1.0, y=2.0)
# p.x = 3.0  # Error: instance is frozen
```

### Settings/Config

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    api_key: str
    debug: bool = False

    model_config = {"env_prefix": "APP_"}

# Reads from environment: APP_DATABASE_URL, APP_API_KEY
settings = Settings()
```

## dataclass (When You Don't Need Validation)

Use dataclass only when:
- You don't need validation (you control all inputs)
- You need minimal overhead (tight loops, many instances)
- You want to avoid external dependencies

```python
from dataclasses import dataclass, field

@dataclass
class Point:
    x: float
    y: float

@dataclass(slots=True)  # Memory efficient
class Coordinate:
    x: float
    y: float
    z: float

@dataclass
class Config:
    name: str
    values: list[str] = field(default_factory=list)  # Mutable default
```

**Limitations (why pydantic is preferred):**
- No validation: `Point(x="not a float", y=None)` silently accepts bad data
- No serialization: need `asdict()` for dict conversion
- No type coercion: string "1.5" won't become float 1.5

### dataclass ↔ dict

```python
from dataclasses import asdict

point = Point(x=1.0, y=2.0)
data = asdict(point)  # {"x": 1.0, "y": 2.0}
point = Point(**data)  # From dict (no validation!)
```

## NamedTuple (Immutable + Hashable)

Use when you need immutability AND hashability (dict keys, set members).

```python
from typing import NamedTuple

class Point(NamedTuple):
    x: float
    y: float

p = Point(1.0, 2.0)

# Immutable
# p.x = 3.0  # Error

# Hashable - can use as dict key
cache: dict[Point, float] = {p: 1.5}

# Tuple unpacking
x, y = p
```

**Use NamedTuple over frozen pydantic/dataclass when:**
- You need to use instances as dict keys or set members
- You want tuple operations (unpacking, indexing)

### NamedTuple with Defaults

```python
class Config(NamedTuple):
    host: str
    port: int = 8080
    debug: bool = False

config = Config(host="localhost")  # port=8080, debug=False
```

## TypedDict (Dict Compatibility)

Use when you must work with dicts (legacy APIs, JSON passthrough).

```python
from typing import TypedDict, NotRequired

class UserDict(TypedDict):
    name: str
    email: str
    age: NotRequired[int]

user: UserDict = {"name": "Alice", "email": "alice@example.com"}
```

**Limitations:**
- No runtime validation (type hints only)
- No methods or computed properties
- Prefer pydantic with `.model_dump()` when possible

## Anti-Patterns

### Don't Use dict When You Know the Shape

```python
# BAD: Stringly typed, no IDE support
def process_user(user: dict) -> None:
    name = user["name"]  # No type info, KeyError risk
    
# GOOD: Use pydantic
def process_user(user: User) -> None:
    name = user.name  # Type checked, autocomplete works
```

### Don't Use dataclass for External Data

```python
# BAD: No validation, bad data silently accepted
@dataclass
class ApiResponse:
    status: int
    data: dict

response = ApiResponse(status="200", data=None)  # No error!

# GOOD: Pydantic validates
class ApiResponse(BaseModel):
    status: int
    data: dict

# ApiResponse(status="200", data=None)  # Raises ValidationError
```

### Don't Use dataclass "Because It's Simpler"

```python
# "Simpler" but fragile
@dataclass
class User:
    name: str
    email: str

# Same effort, but validates and serializes
class User(BaseModel):
    name: str
    email: str
```

The pydantic version catches bugs, provides `.model_dump()`, and has the same definition effort.
