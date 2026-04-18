# Testing Strategies

Data warehouse models require thorough testing due to their business impact. Tests validate data quality, enforce business rules, and catch anomalies before they reach consumers.

## Test Categories

| Category | Purpose | Examples |
|----------|---------|----------|
| **Schema** | Validate structure and types | Column presence, data types |
| **Data quality** | Ensure integrity | Not null, uniqueness, referential integrity |
| **Business logic** | Validate rules and calculations | Expression tests, custom macros |
| **Threshold** | Detect anomalies | Row count ranges, value bounds |
| **Trend** | Monitor changes over time | Row count delta, metric drift |

---

## Severity Levels

Use severity levels to distinguish between blocking issues and monitoring alerts:

| Severity | When to Use | Pipeline Behavior |
|----------|-------------|-------------------|
| `error` | Critical issues that indicate data corruption | Blocks deployment |
| `warn` | Issues requiring investigation but not blocking | Passes with warning |

### Severity Guidelines

**Use `error` for:**
- Primary key uniqueness
- Foreign key relationships to critical dimensions
- Business-critical invariants (e.g., "end_date >= start_date")
- Required fields that should never be null

**Use `warn` for:**
- Threshold and trend monitoring
- Soft business rules with known exceptions
- Data quality metrics for investigation

```yaml
columns:
  - name: order_id
    tests:
      - unique:
          severity: error      # Critical: duplicate PKs break joins
      - not_null:
          severity: error      # Critical: PKs must exist

  - name: shipping_date
    tests:
      - not_null:
          severity: warn       # Some orders may not ship yet
      - dbt_utils.accepted_range:
          min_value: "'2020-01-01'"
          severity: warn       # Monitor for unusual dates
```

---

## Test Patterns

### Grain Validation

Every table's grain must be tested with uniqueness constraints:

```yaml
models:
  - name: fct_order_line_items
    tests:
      # Composite primary key test
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: ['order_id', 'line_item_id']
          severity: error
```

### Referential Integrity

Test foreign key relationships to ensure join integrity:

```yaml
columns:
  - name: customer_sk
    tests:
      - not_null:
          severity: error
      - relationships:
          to: ref('dim_customers')
          field: customer_sk
          severity: error

  - name: product_sk
    tests:
      - relationships:
          to: ref('dim_products')
          field: product_sk
          severity: error
          # Optional: Handle known orphans
          where: "product_sk IS NOT NULL"
```

### Business Logic Validation

Use `expression_is_true` to encode business rules:

```yaml
models:
  - name: fct_contracts
    tests:
      # Invariant: end must be after start
      - dbt_utils.expression_is_true:
          expression: "end_date >= start_date"
          severity: error

      # Business rule: active contracts have no end date
      - dbt_utils.expression_is_true:
          expression: "NOT (status = 'active' AND end_date IS NOT NULL)"
          severity: error

      # Sanity check: amounts should be positive
      - dbt_utils.expression_is_true:
          expression: "contract_value >= 0"
          severity: error
```

### Accepted Values

Constrain enum-like columns to known values:

```yaml
columns:
  - name: order_status
    tests:
      - accepted_values:
          values: ['pending', 'processing', 'shipped', 'completed', 'cancelled']
          severity: error
          # Quote string values if needed
          quote: true

  - name: priority_level
    tests:
      - accepted_values:
          values: [1, 2, 3, 4, 5]
          severity: warn
```

### Range Validation

Validate dates and numeric values fall within expected bounds:

```yaml
columns:
  - name: hire_date
    tests:
      - dbt_utils.accepted_range:
          min_value: "'2015-01-01'"    # Company founding
          max_value: "CURRENT_DATE()"
          severity: warn

  - name: discount_percentage
    tests:
      - dbt_utils.accepted_range:
          min_value: 0
          max_value: 100
          severity: error
```

### Conditional Tests

Apply tests only to specific subsets of data:

```yaml
columns:
  - name: termination_reason
    tests:
      # Only terminated employees should have a reason
      - not_null:
          where: "status = 'terminated'"
          severity: warn

  - name: shipped_at
    tests:
      # Shipped orders must have a ship date
      - not_null:
          where: "order_status IN ('shipped', 'completed')"
          severity: error
```

---

## Threshold and Trend Tests

### Row Count Monitoring

Detect unusual data volumes that may indicate pipeline issues:

```yaml
models:
  - name: fct_daily_events
    tests:
      # Expect reasonable daily event volume
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1000
          max_value: 1000000
          severity: warn

      # Alert on empty table
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
          severity: error
```

### Freshness Checks

Monitor data freshness:

```yaml
sources:
  - name: raw_events
    tables:
      - name: events
        loaded_at_field: _loaded_at
        freshness:
          warn_after: {count: 12, period: hour}
          error_after: {count: 24, period: hour}
```

---

## Custom Test Macros

For complex validation logic, create reusable test macros:

```sql
-- macros/tests/test_no_future_dates.sql
{% test no_future_dates(model, column_name, max_days_ahead=0) %}

SELECT *
FROM {{ model }}
WHERE {{ column_name }} > DATE_ADD(CURRENT_DATE(), INTERVAL {{ max_days_ahead }} DAY)

{% endtest %}
```

Usage:

```yaml
columns:
  - name: expected_delivery_date
    tests:
      - no_future_dates:
          max_days_ahead: 90  # Allow up to 90 days future
          severity: warn
```

---

## Test Organization

### Table-Level vs Column-Level

| Test Type | Location | Examples |
|-----------|----------|----------|
| Grain validation | Table-level | `unique_combination_of_columns` |
| Business rules spanning columns | Table-level | `expression_is_true` |
| Single column validation | Column-level | `not_null`, `unique`, `accepted_values` |
| Relationships | Column-level | `relationships` |

### Example Structure

```yaml
models:
  - name: fct_invoices
    description: Invoice fact table
    
    # Table-level tests
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: ['invoice_id']
          severity: error
      - dbt_utils.expression_is_true:
          expression: "due_date >= invoice_date"
          severity: error
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
          severity: error

    columns:
      - name: invoice_id
        tests:
          - not_null:
              severity: error
          - unique:
              severity: error

      - name: customer_sk
        tests:
          - not_null:
              severity: error
          - relationships:
              to: ref('dim_customers')
              field: customer_sk
              severity: error

      - name: invoice_amount
        tests:
          - not_null:
              severity: error
          - dbt_utils.accepted_range:
              min_value: 0
              severity: warn
```

---

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| **No PK tests** | Can't guarantee join integrity | Always test uniqueness on grain columns |
| **All errors** | Too many false positives block deployments | Use `warn` for monitoring, `error` for invariants |
| **All warnings** | Critical issues slip through | Use `error` for business-critical rules |
| **Missing relationship tests** | Orphan foreign keys cause NULL joins | Test all FK relationships |
| **Hardcoded thresholds** | Thresholds become stale | Use relative bounds or review periodically |
