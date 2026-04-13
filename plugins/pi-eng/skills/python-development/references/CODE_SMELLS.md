# Code Smells

Patterns that indicate deeper problems. When you spot these, refactor.

## Magic Numbers and Strings

Unexplained literals scattered through code. Extract to named constants.

```python
# BAD: What do these mean?
if retry_count > 3:
    time.sleep(60)
if status == "A":
    ...

# GOOD: Self-documenting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 60

class Status(StrEnum):
    ACTIVE = "A"
    INACTIVE = "I"

if retry_count > MAX_RETRIES:
    time.sleep(RETRY_DELAY_SECONDS)
if status == Status.ACTIVE:
    ...
```

## Dead Code

Commented-out code, unreachable branches, unused functions. Delete it—version control remembers.

```python
# BAD: Commented code that "might be needed later"
def process(data):
    # old_result = legacy_process(data)
    # if USE_OLD_LOGIC:
    #     return old_result
    return new_process(data)

# GOOD: Clean, no dead weight
def process(data):
    return new_process(data)
```

## Redundant Comments

Comments that restate what the code already says. Comments should explain *why*, not *what*.

```python
# BAD: Comment restates the code
# Increment counter by 1
counter += 1

# Loop through users
for user in users:
    ...

# GOOD: Comment explains why
# Rate limit: max 100 requests per minute per client
counter += 1

# Process in reverse order to handle dependencies correctly
for user in reversed(users):
    ...
```

## Boolean Blindness

Passing raw `True`/`False` with no context at the call site.

```python
# BAD: What does True mean here?
process_file("data.csv", True, False, True)

# GOOD: Named arguments or enums
process_file("data.csv", has_header=True, validate=False, overwrite=True)

# BETTER: Use enums for mutually exclusive options
class WriteMode(StrEnum):
    APPEND = "append"
    OVERWRITE = "overwrite"

process_file("data.csv", mode=WriteMode.OVERWRITE)
```

## Silent Failures

Catching exceptions and doing nothing, or returning None without indication of failure.

```python
# BAD: Failure is invisible
def get_config(path: str) -> dict | None:
    try:
        return load_config(path)
    except Exception:
        return None  # Caller can't distinguish "empty config" from "load failed"

# GOOD: Explicit about failure
def get_config(path: str) -> dict:
    try:
        return load_config(path)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid config format: {e}")
```

## Assert for Validation

Using `assert` for runtime validation. Asserts can be disabled with `python -O`.

```python
# BAD: Disabled in optimized mode
def withdraw(account: Account, amount: Decimal) -> None:
    assert amount > 0, "Amount must be positive"
    assert account.balance >= amount, "Insufficient funds"
    ...

# GOOD: Always validates
def withdraw(account: Account, amount: Decimal) -> None:
    if amount <= 0:
        raise ValueError(f"Amount must be positive, got {amount}")
    if account.balance < amount:
        raise InsufficientFundsError(f"Balance {account.balance} < {amount}")
    ...
```

## Mutable Class Attributes

Class-level mutable defaults are shared across all instances.

```python
# BAD: All instances share the same list!
class User:
    permissions: list[str] = []  # Shared between ALL User instances

# GOOD: Initialize in __init__
class User:
    def __init__(self) -> None:
        self.permissions: list[str] = []

# GOOD: Use dataclass with field()
@dataclass
class User:
    permissions: list[str] = field(default_factory=list)
```

## Stringly Typed Code

Using strings where enums, types, or constants would be safer.

```python
# BAD: Typos won't be caught
def set_status(status: str) -> None:
    if status == "actve":  # Typo - silent bug
        ...

user.role = "amdin"  # Typo - no error

# GOOD: Typos are caught at definition time
class Status(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"

def set_status(status: Status) -> None:
    ...

user.role = Role.ADMIN
```

## God Functions

Functions that do too much—hundreds of lines, many responsibilities. Split by concern.

```python
# BAD: One massive function
def process_order(order):
    # 50 lines of validation
    # 30 lines of inventory check
    # 40 lines of payment processing
    # 60 lines of shipping calculation
    # 25 lines of notification
    ...

# GOOD: Composed of focused functions
def process_order(order: Order) -> OrderResult:
    validate_order(order)
    reserve_inventory(order.items)
    payment = process_payment(order.payment_info)
    shipping = calculate_shipping(order.address, order.items)
    notify_customer(order.customer, payment, shipping)
    return OrderResult(payment=payment, shipping=shipping)
```

## Unnecessary Extraction

The opposite of God Functions: extracting code into functions that add indirection without adding value. If a function is only called once, is trivial, and its name doesn't add clarity, inline it.

```python
# BAD: Trivial one-liner extracted for no reason
def get_user_email(user: User) -> str:
    return user.email

def get_full_name(user: User) -> str:
    return f"{user.first_name} {user.last_name}"

# Then elsewhere:
email = get_user_email(user)
name = get_full_name(user)

# GOOD: Just access the attribute or write inline
email = user.email
name = f"{user.first_name} {user.last_name}"
```

```python
# BAD: Wrapping a clear stdlib call adds noise
def is_empty(items: list) -> bool:
    return len(items) == 0

def contains_item(items: list, item: Any) -> bool:
    return item in items

# GOOD: Use the language directly
if not items:
    ...
if item in items:
    ...
```

**When extraction IS valuable:**
- Logic is reused in multiple places
- The function name explains *why*, not just *what*
- The extracted code is complex enough to benefit from isolation
- Testing the logic in isolation is valuable

```python
# GOOD: Extraction adds clarity about business intent
def is_eligible_for_discount(order: Order) -> bool:
    """Customer loyalty + minimum spend + not already discounted."""
    return (
        order.customer.loyalty_years >= 2
        and order.subtotal >= Decimal("100")
        and not order.has_discount
    )
```

## Feature Envy

A method that uses more from another class than its own. Move it or rethink the design.

```python
# BAD: This method belongs on Invoice, not ReportGenerator
class ReportGenerator:
    def format_invoice_line(self, invoice: Invoice) -> str:
        return f"{invoice.customer.name}: {invoice.total} ({invoice.currency})"

# GOOD: Method lives where the data is
class Invoice:
    def format_line(self) -> str:
        return f"{self.customer.name}: {self.total} ({self.currency})"
```
