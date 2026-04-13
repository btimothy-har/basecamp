---
name: code-documentation
description: This skill should be used when writing or improving code documentation—docstrings, READMEs, ADRs, or inline comments. Keywords: docstring, README, ADR, documentation, comments.
---

# Code Documentation

Write documentation that helps future developers (including yourself) understand and use code effectively.

## Principles

**Philosophy**
- **Document why, not what** - Code shows what happens; docs explain why it exists and when to use it
- **Close to code** - Keep docs near the code they describe; external docs go stale faster
- **Audience-aware** - Docstrings for developers using the code; READMEs for those evaluating or setting up
- **Update with code** - Documentation changes are part of the code change, not a follow-up task

**What to Document**
- **All public APIs** - Every public function, class, and method gets a docstring
- **Complex logic** - Non-obvious algorithms, business rules, and workarounds
- **Decisions and tradeoffs** - Why this approach over alternatives
- **Skip the obvious** - Don't document `i += 1` or self-evident code

**Style**
- **Google style docstrings** - Consistent with python-development skill
- **Imperative mood** - "Return the user" not "Returns the user"
- **Examples over explanation** - Show usage when behavior isn't obvious
- **Keep it current** - Wrong documentation is worse than no documentation

## Python Docstrings (Google Style)

### Functions

```python
def fetch_user(user_id: int, include_deleted: bool = False) -> User | None:
    """Fetch a user by ID from the database.

    Retrieves the user record, optionally including soft-deleted users.
    Returns None if no matching user exists.

    Args:
        user_id: The unique identifier of the user.
        include_deleted: If True, return soft-deleted users. Defaults to False.

    Returns:
        The User object if found, None otherwise.

    Raises:
        DatabaseError: If the database connection fails.

    Example:
        >>> user = fetch_user(123)
        >>> user.email
        'user@example.com'
    """
```

### Classes

```python
class RateLimiter:
    """Token bucket rate limiter for API endpoints.

    Implements a token bucket algorithm that allows bursting while enforcing
    an average rate limit. Tokens regenerate at a fixed rate up to a maximum.

    Attributes:
        rate: Tokens added per second.
        capacity: Maximum tokens in the bucket.

    Example:
        >>> limiter = RateLimiter(rate=10, capacity=100)
        >>> if limiter.acquire():
        ...     process_request()
    """

    def __init__(self, rate: float, capacity: int) -> None:
        """Initialize the rate limiter.

        Args:
            rate: Tokens to add per second.
            capacity: Maximum bucket size.
        """
```

### Modules

```python
"""User authentication and session management.

This module provides authentication utilities including password hashing,
token generation, and session validation. It integrates with the User model
and requires Redis for session storage.

Typical usage:
    from auth import authenticate, create_session

    user = authenticate(email, password)
    if user:
        session = create_session(user)
"""
```

### Short Docstrings

```python
def is_valid_email(email: str) -> bool:
    """Check if email matches a valid email pattern."""


def get_current_timestamp() -> datetime:
    """Return the current UTC timestamp."""
```

## Inline Comments

### When to Comment

```python
# GOOD: Explain why, not what
# Use binary search here because the list is always sorted and can have 100k+ items
index = bisect.bisect_left(sorted_items, target)

# GOOD: Clarify non-obvious behavior
# Stripe requires amount in cents, not dollars
amount_cents = int(dollars * 100)

# GOOD: Document workarounds
# HACK: Sleep to avoid race condition in legacy API (see issue #1234)
time.sleep(0.1)

# BAD: Restating the code
# Increment counter by 1
counter += 1

# BAD: Obvious from context
# Check if user is None
if user is None:
```

### TODO/FIXME Format

```python
# TODO(username): Add retry logic for transient failures
# FIXME: This breaks when timezone is not UTC (issue #567)
# HACK: Temporary workaround until upstream fixes bug
# NOTE: This must run before database migrations
```

## README Structure

```markdown
# Project Name

One-line description of what this project does.

## Quick Start

Minimal steps to get running:

    pip install projectname
    projectname init
    projectname run

## Installation

Detailed installation for different environments.

## Usage

Common use cases with examples.

## Configuration

Environment variables, config files, and options.

## Development

Setup for contributors:

    git clone ...
    uv sync
    uv run pytest

## License

MIT License - see LICENSE file.
```

### README Principles

- **Lead with value** - What problem does this solve?
- **Quick start first** - Get users running in <2 minutes
- **Copy-pasteable commands** - Use code blocks for all commands
- **Link, don't duplicate** - Reference detailed docs instead of repeating

## API Documentation

### Endpoint Documentation

```python
@app.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    user: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Create a new user account.

    Creates a user with the provided email and name. Sends a welcome
    email asynchronously. Returns 409 if email already exists.

    Args:
        user: User creation payload with email and name.

    Returns:
        The created user with generated ID and timestamps.

    Raises:
        HTTPException: 409 if email already registered.
    """
```

### OpenAPI Enhancements

```python
from pydantic import BaseModel, Field

class UserCreate(BaseModel):
    """Payload for creating a new user."""

    email: str = Field(
        ...,
        description="User's email address",
        example="user@example.com",
    )
    name: str = Field(
        ...,
        description="User's display name",
        example="Jane Smith",
        min_length=1,
        max_length=100,
    )

class UserResponse(BaseModel):
    """User data returned from API."""

    id: int = Field(..., description="Unique user identifier")
    email: str = Field(..., description="User's email address")
    name: str = Field(..., description="User's display name")
    created_at: datetime = Field(..., description="Account creation timestamp")
```

## Architecture Decision Records (ADRs)

Use ADRs to document significant technical decisions.

```markdown
# ADR-001: Use PostgreSQL for Primary Database

## Status

Accepted

## Context

We need a primary database for user data, transactions, and application state.
Options considered: PostgreSQL, MySQL, MongoDB.

## Decision

Use PostgreSQL because:
- Strong ACID compliance for financial transactions
- JSONB support for flexible metadata without separate document store
- Excellent tooling and team familiarity

## Consequences

- Need PostgreSQL expertise for operations
- Some queries may need optimization vs document stores
- Gain transactional integrity and relational modeling
```

### ADR File Organization

```
docs/
└── decisions/
    ├── 001-postgresql-database.md
    ├── 002-fastapi-framework.md
    ├── 003-celery-background-jobs.md
    └── template.md
```

## Changelog

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- User profile photo upload

### Changed
- Increased rate limit to 1000 requests/hour

## [1.2.0] - 2024-01-15

### Added
- OAuth2 login with Google and GitHub
- Export user data as CSV

### Fixed
- Session timeout not respecting timezone

### Security
- Updated dependencies to patch CVE-2024-XXXXX
```

### Changelog Principles

- **User-focused** - What changed from the user's perspective
- **Group by type** - Added, Changed, Deprecated, Removed, Fixed, Security
- **Link to issues** - Reference tickets/PRs for details
- **Keep Unreleased section** - Accumulate changes between releases

## Review & Analysis

When reviewing existing comments and documentation (e.g., during a code review or PR audit), evaluate across these dimensions:

### 1. Factual Accuracy

Cross-reference every claim against the actual implementation:
- Function signatures match documented parameters and return types
- Described behavior aligns with actual code logic
- Referenced types, functions, and variables exist and are used correctly
- Edge cases mentioned are actually handled in the code
- Performance characteristics or complexity claims are accurate

### 2. Completeness

Evaluate whether comments provide sufficient context without being redundant:
- Critical assumptions or preconditions are documented
- Non-obvious side effects are mentioned
- Important error conditions are described
- Complex algorithms have their approach explained
- Business logic rationale is captured when not self-evident

### 3. Long-term Value

Consider utility over the codebase's lifetime:
- Comments that merely restate obvious code should be flagged for removal
- Comments explaining "why" are more valuable than those explaining "what"
- Comments that will become outdated with likely code changes should be reconsidered
- Avoid comments referencing temporary states or transitional implementations

### 4. Misleading Elements

Search for ways comments could be misinterpreted:
- Ambiguous language with multiple meanings
- Outdated references to refactored code
- Assumptions that may no longer hold true
- Examples that don't match current implementation
- TODOs or FIXMEs that may have already been addressed

### Review Output Format

```markdown
**Summary**: [Scope and findings overview]

**Critical Issues** — factually incorrect or highly misleading:
- `file:line` — [problem] → [fix]

**Improvement Opportunities** — could be enhanced:
- `file:line` — [what's lacking] → [suggestion]

**Recommended Removals** — add no value or create confusion:
- `file:line` — [rationale]

**Positive Findings** — well-written comments worth noting
```

**Scope**: Comment accuracy, documentation completeness, long-term maintainability. Out of scope: code correctness, security, test quality, performance.