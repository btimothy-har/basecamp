# Naming Conventions

Names describe **WHAT** something is, not **HOW** it was created or **WHY** it exists.

## The WHAT Principle

```python
# GOOD: Describes what the object IS
addresses = merge(billing, shipping)
users = fetch_active_from_db()
config = load_and_validate(path)

# BAD: Describes how it was created or implementation details
merged_addresses = merge(billing, shipping)
active_users_from_db = fetch_active_from_db()
validated_config = load_and_validate(path)
```

## Variables and Parameters

- Use nouns that describe the data: `users`, `orders`, `response`
- Pluralize collections: `items` not `item_list`
- Avoid type suffixes: `users` not `users_list`, `user_dict`, `user_set`
- Avoid process prefixes: `filtered_`, `sorted_`, `merged_`, `validated_`
- Scope informs length: `i` in a 3-line loop is fine; `user_account_balance` for module-level

```python
# GOOD
for user in users:
    orders = get_orders(user.id)
    total = sum(order.amount for order in orders)

# BAD
for user_item in user_list:
    filtered_orders = get_filtered_orders(user_item.id)
    calculated_total = sum(order.amount for order in filtered_orders)
```

## Booleans

- Use predicate-style names: `is_`, `has_`, `can_`, `should_`, `allow_`
- Name should read naturally in conditionals

```python
# GOOD
is_valid = check_format(email)
has_permission = user.role in allowed_roles
can_edit = document.owner_id == user.id

if is_valid and has_permission:
    ...

# BAD
valid = check_format(email)
permission_check = user.role in allowed_roles
edit_allowed = document.owner_id == user.id
```

## Functions and Methods

- Verbs for actions: `fetch_users()`, `calculate_total()`, `send_notification()`
- Questions for boolean returns: `is_valid()`, `has_access()`, `can_process()`
- Avoid redundant context: in a `UserService`, use `get()` not `get_user()`

```python
# GOOD
def fetch_orders(user_id: int) -> list[Order]: ...
def calculate_tax(amount: Decimal, rate: Decimal) -> Decimal: ...
def is_expired(token: Token) -> bool: ...

# BAD
def get_user_orders_from_database(user_id: int) -> list[Order]: ...
def do_tax_calculation(amount: Decimal, rate: Decimal) -> Decimal: ...
def check_if_token_is_expired(token: Token) -> bool: ...
```

## Classes

- Nouns that describe the entity: `User`, `OrderProcessor`, `ConfigLoader`
- Avoid suffixes that add no meaning: `Manager`, `Handler`, `Helper`, `Utils`
- Exception classes end with `Error`: `ValidationError`, `NotFoundError`

## Constants

- `SCREAMING_SNAKE_CASE` for module-level constants
- Group related constants in an `Enum` or `StrEnum`

```python
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30

class Status(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
```

## Private Members

- Single underscore `_` prefix for internal use: `_helper()`, `_cache`
- Avoid double underscore `__` (name mangling) unless truly necessary
