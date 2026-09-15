# Error Handling and Logging

Follow [Tryceratops](https://github.com/guilatrova/tryceratops) linting rules for clean exception handling, plus Ruff's B904 (flake8-bugbear) for exception chaining. Enable with `select = ["TRY", "B"]` in Ruff.

## Tryceratops Rules

| Rule | Requirement |
|------|-------------|
| TRY002 | Create custom exceptions, don't raise built-ins |
| TRY003 | Keep error messages in exception class, not at raise site |
| B904 | Use `raise ... from e` for exception chaining |
| TRY400 | Use `logging.exception()` in except blocks, not `logging.error()` |

## TRY002: Custom Exceptions

Define domain-specific exceptions instead of raising built-ins like `ValueError` or `Exception`.

```python
# BAD: Raising built-in exceptions (TRY002)
def get_user(user_id: int) -> User:
    user = db.find(user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")  # Too generic
    return user

# GOOD: Custom exception
class NotFoundError(Exception):
    """Raised when a requested resource doesn't exist."""

def get_user(user_id: int) -> User:
    user = db.find(user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user
```

**Why:** Callers can catch specific exception types. `except NotFoundError` is clearer than `except ValueError`.

## TRY003: Message Logic in Exception Class

Avoid repeating message formatting at every raise site. Encapsulate in the exception class.

```python
# BAD: Message logic at raise site (TRY003)
raise NotFoundError(f"User with id={user_id} not found in database")
raise NotFoundError(f"Order with id={order_id} not found in database")

# GOOD: Message logic in exception class
class NotFoundError(Exception):
    def __init__(self, resource: str, id: int) -> None:
        self.resource = resource
        self.id = id
        super().__init__(f"{resource} with id={id} not found")

raise NotFoundError("User", user_id)
raise NotFoundError("Order", order_id)
```

## B904: Exception Chaining with `from`

When raising a new exception from a caught one, use `from e` to preserve the chain. This is Ruff rule B904 (flake8-bugbear `raise-without-from-inside-except`), enabled with `select = ["B"]`.

```python
# BAD: No chaining, original cause is lost (B904)
try:
    data = json.loads(content)
except json.JSONDecodeError:
    raise ValidationError("Invalid JSON")  # Original error hidden

# GOOD: Chain with `from e`
try:
    data = json.loads(content)
except json.JSONDecodeError as e:
    raise ValidationError(f"Invalid JSON at line {e.lineno}") from e
```

## TRY400: Use `logging.exception()` in Except Blocks

In exception handlers, use `logging.exception()` to automatically include the traceback.

```python
# BAD: logging.error loses traceback (TRY400)
try:
    process()
except SomeError as e:
    logging.error("Failed: %s", e)  # No traceback!

# GOOD: logging.exception includes traceback
try:
    process()
except SomeError:
    logging.exception("Failed to process")  # Full traceback logged
```

## Exception Hierarchy

Define a base exception for your application, then specific exceptions.

```python
class AppError(Exception):
    """Base exception for application errors."""

class ValidationError(AppError):
    """Raised when input validation fails."""

class NotFoundError(AppError):
    """Raised when a requested resource doesn't exist."""

class AuthenticationError(AppError):
    """Raised when authentication fails."""

class AuthorizationError(AppError):
    """Raised when user lacks permission."""
```

Callers can catch `AppError` for all application errors, or specific types.

## Actionable Error Messages

Error messages should tell the user what went wrong and how to fix it.

```python
# GOOD: Specific, actionable - tells what's wrong and how to fix it
class InvalidEmailError(ValidationError):
    def __init__(self, email: str) -> None:
        self.email = email
        super().__init__(f"Invalid email format: {email!r}. Expected: user@domain.com")

class ConfigNotFoundError(NotFoundError):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Config file not found: {path}. Create with 'init --config'")

# BAD: Vague, unhelpful - doesn't say what or how to fix
class InvalidEmailError(ValidationError):
    def __init__(self, email: str) -> None:
        super().__init__("Invalid input")  # What input? What's wrong with it?

class ConfigNotFoundError(NotFoundError):
    def __init__(self, path: Path) -> None:
        super().__init__("File not found")  # Which file? What should user do?
```

## Logging

### Structured Logging

Use `extra={}` for structured context.

```python
import logging

logger = logging.getLogger(__name__)

# GOOD: Structured, parseable
logger.info("Order processed", extra={"order_id": order.id, "total": total})
logger.warning("Retry attempt", extra={"attempt": n, "max": MAX_RETRIES})

# Less useful: context is embedded in an unstructured message
logger.info("Processed order %s with total %s", order.id, total)
```

### Log Levels

| Level | Use |
|-------|-----|
| `DEBUG` | Detailed diagnostic info (disabled in production) |
| `INFO` | Normal operations, significant events |
| `WARNING` | Unexpected but handled situations |
| `ERROR` | Failures that affect a single operation |
| `CRITICAL` | System-wide failures |

### What to Log

- **Boundaries**: External API calls, database operations, user actions
- **Context**: IDs, counts, durations
- **Never**: Passwords, tokens, PII
