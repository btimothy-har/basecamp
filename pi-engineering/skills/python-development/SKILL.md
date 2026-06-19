---
name: python-development
description: "This skill should be used when writing or modifying .py files, or managing Python dependencies with uv. Keywords: Python script, type hints, uv, pydantic, best practices."
---

# Python Development

Use Python 3.12+ with the `uv` package manager for all Python work.

## Principles

**Workflow**
- **Understand before coding** - Analyze requirements thoroughly before writing code
- **Clarify ambiguity** - Ask questions when specifications are unclear or incomplete
- **Break down complexity** - Decompose complex problems into smaller, focused functions
- **State assumptions** - When requirements are ambiguous, state assumptions explicitly and proceed

**Code Quality**
- **Google Python Style Guide** - Follow it for formatting, naming, and structure
- **Type hints everywhere** - All function signatures, return types, and complex variables
- **Specific exceptions** - Catch and raise specific exception types, never bare `except:`
- **Context managers** - Use `with` for files, connections, locks, and any resource cleanup
- **No mutable defaults** - Never use `[]` or `{}` as default arguments

**Decision Making**
- **Readability over cleverness** - Clear code beats clever code
- **Simple over complex** - Choose straightforward solutions; add complexity only when justified
- **Stdlib first** - Use Python's standard library before adding external dependencies
- **Minimal dependencies** - Every external package must justify its inclusion

## Quick Reference

### Running Python

```bash
uv run script.py           # Run script with inline dependencies
uv run python script.py    # Alternative form
```

### Script Dependencies

```python
# /// script
# dependencies = ["httpx", "pandas"]
# requires-python = ">=3.12"
# ///
```

### Project Setup

```bash
uv init project-name       # Create new project
uv add package-name        # Add dependency
uv add --dev package       # Add dev dependency
uv sync                    # Install all dependencies
```

For CI/CD, Docker, workspaces, and advanced uv patterns — read [UV.md](references/UV.md)

### Code Standards

- **Formatting**: f-strings, `pathlib.Path` for files
- **Docstrings**: Google-style with Args, Returns, Raises
- **Imports**: stdlib → third-party → local; alphabetize
- **Line length**: 88 chars (Black default)
- **Trailing commas**: Always in multi-line structures

---

## Naming — read [NAMING.md](references/NAMING.md)

Names describe **WHAT** something is, not **HOW** or **WHY** it exists.

| Element | Convention | Examples |
|---------|------------|----------|
| Variables | Nouns, no type/process suffixes | `users` not `user_list`, `merged_users` |
| Booleans | Predicates: `is_`, `has_`, `can_` | `is_valid`, `has_permission` |
| Functions | Verbs for actions, questions for bool returns | `fetch_orders()`, `is_expired()` |
| Classes | Nouns, avoid meaningless suffixes | `User` not `UserManager`, `UserHelper` |
| Constants | `SCREAMING_SNAKE_CASE` or `StrEnum` | `MAX_RETRIES`, `Status.ACTIVE` |
| Private | Single underscore prefix | `_helper()`, `_cache` |

```python
# GOOD: Describes WHAT
addresses = merge(billing, shipping)
users = fetch_active_from_db()

# BAD: Describes HOW
merged_addresses = merge(billing, shipping)
active_users_from_db = fetch_active_from_db()
```

---

## Typing — read [TYPING.md](references/TYPING.md)

Use modern Python 3.10+/3.12+ syntax.

```python
# Modern union syntax (not Optional, Union)
def process(value: str | None) -> dict[str, int]: ...

# Built-in generics (not typing.List, Dict)
items: list[str]
mapping: dict[str, int]

# Type aliases (Python 3.12+)
type UserId = int
type Handler = Callable[[Request], Response]
```

| Pattern | Use |
|---------|-----|
| `Literal["a", "b"]` | Constrained string values |
| `Final` | Constants that shouldn't be reassigned |
| `Protocol` | Duck typing interfaces |
| `TypeVar` | Generic functions |
| `Self` | Methods returning same type |

**Annotate**: function signatures, return types, class attributes. **Skip**: obvious locals (`name = "Alice"`).

---

## Data Structures — read [DATA_STRUCTURES.md](references/DATA_STRUCTURES.md)

**Default to pydantic.** Use dataclass only when you have a specific reason not to.

| Need | Use |
|------|-----|
| **Default choice** | `pydantic.BaseModel` |
| No validation needed, minimal overhead | `dataclass` |
| Immutable + hashable (dict keys) | `NamedTuple` |
| Dict compatibility (legacy APIs) | `TypedDict` |

```python
# Default: pydantic (validates, serializes, coerces types)
class User(BaseModel):
    name: str
    email: str

# Only when you don't need validation
@dataclass
class Point:
    x: float
    y: float

# When you need hashability (dict keys, sets)
class Coordinate(NamedTuple):
    lat: float
    lon: float
```

---

## Code Structure — read [CODE_STRUCTURE.md](references/CODE_STRUCTURE.md)

**Function Design**
- Single responsibility, ≤20 lines
- Limit to 4-5 parameters (use dataclass if more)
- Pure functions when possible

**Guard Clauses**: Exit early to reduce nesting.

```python
# GOOD: Flat structure
def process(order: Order) -> Result:
    if order is None:
        raise ValueError("Order required")
    if order.status != Status.PENDING:
        return Result.skipped("Not pending")
    
    # Main logic at lowest nesting
    return Result.success(calculate(order))
```

**Cyclomatic Complexity**: Target ≤10. Use data-driven dispatch instead of nested conditionals.

---

## Code Smells — read [CODE_SMELLS.md](references/CODE_SMELLS.md)

| Smell | Fix |
|-------|-----|
| Magic numbers/strings | Extract to named constants or `StrEnum` |
| Dead code | Delete it; version control remembers |
| Boolean blindness | Use named arguments or enums |
| Silent failures | Raise specific exceptions |
| `assert` for validation | Use explicit `if`/`raise` (asserts can be disabled) |
| Mutable class attributes | Initialize in `__init__` or use `field(default_factory=...)` |
| Stringly typed code | Use `StrEnum` for type safety |
| God functions | Split by concern into focused functions |
| Unnecessary extraction | Inline trivial one-liners; extract only when it adds clarity |

---

## Error Handling — read [ERROR_HANDLING.md](references/ERROR_HANDLING.md)

Follow [Tryceratops](https://github.com/guilatrova/tryceratops) rules. Enable with `select = ["TRY"]` in Ruff.

| Rule | Requirement |
|------|-------------|
| TRY002 | Custom exceptions, not built-ins (`ValueError`, `Exception`) |
| TRY003 | Message logic in exception class, not at raise site |
| TRY201 | Bare `raise` to re-raise, not `raise e` |
| TRY301 | Use `raise ... from e` for exception chaining |
| TRY400 | Use `logging.exception()` in except blocks |

```python
# Custom exception with encapsulated message
class NotFoundError(Exception):
    def __init__(self, resource: str, id: int) -> None:
        super().__init__(f"{resource} with id={id} not found")

# Chain exceptions with `from e`
try:
    data = json.loads(content)
except json.JSONDecodeError as e:
    raise ValidationError("Invalid JSON") from e
```

**Logging**: Use `logging.exception()` in except blocks, structured `extra={}` elsewhere.

---

## Patterns — read [PATTERNS.md](references/PATTERNS.md)

### Library Preferences

| Use Case | Library |
|----------|---------|
| HTTP | httpx |
| Data | pandas, polars |
| Validation | pydantic |
| CLI | typer, click |
| Paths | pathlib (stdlib) |
| Dates | datetime, zoneinfo (stdlib) |

### Debugging

```bash
uv run --verbose script.py              # Detailed output
uv run python -c "import package"       # Test imports
```

---

## Backend — read [BACKEND.md](references/BACKEND.md)

FastAPI, async SQLAlchemy, PostgreSQL, and Alembic patterns. Covers API design, database operations, N+1 prevention, model design, Pydantic schemas, migrations, pagination, and security.

---

## Testing — read [TESTING.md](references/TESTING.md)

Pytest patterns for test design, fixtures, mocking, parametrization, time control with freezegun, async testing, and FastAPI test clients.
