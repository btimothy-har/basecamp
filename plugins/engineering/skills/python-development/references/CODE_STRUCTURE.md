# Code Structure

## Function Design

- Single responsibility: one function does one thing
- Keep functions short: aim for ≤20 lines; consider splitting if longer
- Limit parameters: more than 4-5 suggests a need for a data class
- Pure functions when possible: same inputs → same outputs, no side effects

## Guard Clauses and Early Returns

Exit early to reduce nesting and improve readability.

```python
# GOOD: Guard clauses, flat structure
def process_order(order: Order) -> Result:
    if order is None:
        raise ValueError("Order cannot be None")
    if order.status != Status.PENDING:
        return Result.skipped("Order not pending")
    if not order.items:
        return Result.skipped("Order has no items")

    # Main logic at lowest nesting level
    total = calculate_total(order.items)
    return Result.success(total)

# BAD: Deep nesting, hard to follow
def process_order(order: Order) -> Result:
    if order is not None:
        if order.status == Status.PENDING:
            if order.items:
                total = calculate_total(order.items)
                return Result.success(total)
            else:
                return Result.skipped("Order has no items")
        else:
            return Result.skipped("Order not pending")
    else:
        raise ValueError("Order cannot be None")
```

## Cyclomatic Complexity

- Target: ≤10 per function
- Warning signs: deeply nested conditionals, many branches, long `if/elif` chains
- Remedies: extract functions, use dictionaries for dispatch, polymorphism

```python
# BAD: High complexity, hard to test
def get_discount(customer_type: str, amount: Decimal) -> Decimal:
    if customer_type == "gold":
        if amount > 1000:
            return Decimal("0.20")
        elif amount > 500:
            return Decimal("0.15")
        else:
            return Decimal("0.10")
    elif customer_type == "silver":
        # ... more nested conditions
        pass
    # ... continues

# GOOD: Data-driven, low complexity
DISCOUNT_TIERS: dict[str, list[tuple[Decimal, Decimal]]] = {
    "gold": [(Decimal("1000"), Decimal("0.20")), (Decimal("500"), Decimal("0.15")), (Decimal("0"), Decimal("0.10"))],
    "silver": [(Decimal("1000"), Decimal("0.10")), (Decimal("0"), Decimal("0.05"))],
}

def get_discount(customer_type: str, amount: Decimal) -> Decimal:
    tiers = DISCOUNT_TIERS.get(customer_type, [])
    for threshold, discount in tiers:
        if amount >= threshold:
            return discount
    return Decimal("0")
```

## Avoid Primitive Obsession

Group related data into structures rather than passing multiple primitives.

```python
# BAD: Many related parameters
def create_user(name: str, email: str, street: str, city: str, zip_code: str, country: str) -> User: ...

# GOOD: Grouped into meaningful structures
@dataclass
class Address:
    street: str
    city: str
    zip_code: str
    country: str

def create_user(name: str, email: str, address: Address) -> User: ...
```
