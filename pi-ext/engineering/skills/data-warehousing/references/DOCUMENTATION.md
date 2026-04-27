# Documentation Standards

Every dbt model requires comprehensive documentation in a co-located schema YAML file. Good documentation reduces support requests, prevents data misuse, and accelerates onboarding.

## File Organization

Each model has a corresponding YAML schema file in the same directory with the same basename:

```
models/sales/
├── fct_orders.sql
├── fct_orders.yml      # Documents fct_orders only
├── dim_customers.sql
└── dim_customers.yml   # Documents dim_customers only
```

**One model per schema file** — This simplifies navigation and reduces merge conflicts.

---

## Model-Level Documentation

### Required Elements

| Element | Description |
|---------|-------------|
| `name` | Model name (matches file basename) |
| `description` | Comprehensive model documentation |
| `tests` | Table-level tests (grain validation, business rules) |
| `columns` | Documentation for every column |

### Description Content

Model descriptions should include:

1. **Summary** — 1-2 sentence Kimball classification (e.g., "Type-1 dimension", "Transaction fact")
2. **Grain** — What a single row represents
3. **Update frequency** — How often the model refreshes
4. **Source** — Upstream systems that produce input data
5. **Caveats** — Gotchas or edge cases to be aware of

### Example

```yaml
models:
  - name: fct_order_transactions
    description: |
      Transaction fact table of completed customer orders.
      
      **Grain**: One row per order_id
      **Update Frequency**: Hourly via incremental refresh
      **Source**: E-commerce platform order events via Fivetran
      
      This table contains only completed orders (status = 'completed').
      Pending and cancelled orders are tracked in `fct_order_events`.
      
      **Caveats**:
      - Orders from the legacy system (pre-2020) have NULL shipping_address_id
      - Multi-currency orders are converted to USD at order_date exchange rate
      
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: ['order_id']
          severity: error
      - dbt_utils.expression_is_true:
          expression: "total_amount >= 0"
          severity: error
```

---

## Column-Level Documentation

### Required Elements

| Element | Description |
|---------|-------------|
| `name` | Column name |
| `description` | Meaning and business context |
| `data_type` | Explicit type (STRING, INT64, BOOLEAN, etc.) |
| `tests` | Data quality tests |

### Column Tests

| Test Type | When to Use |
|-----------|-------------|
| `not_null` | Primary keys, required fields |
| `unique` | Natural keys, surrogate keys |
| `relationships` | Foreign keys to dimension tables |
| `accepted_values` | Enum-like columns with known values |
| `dbt_utils.accepted_range` | Date bounds, numeric ranges |

### Example

```yaml
columns:
  - name: order_id
    description: Unique identifier for the order (natural key from source system)
    data_type: STRING
    tests:
      - not_null:
          severity: error
      - unique:
          severity: error

  - name: customer_sk
    description: |
      Surrogate key to `dim_customers`.
      Resolves to customer state as of order_date.
    data_type: STRING
    tests:
      - not_null:
          severity: error
      - relationships:
          to: ref('dim_customers')
          field: customer_sk
          severity: error

  - name: order_status
    description: |
      Current status of the order.
      - `pending`: Awaiting payment
      - `processing`: Payment received, preparing shipment
      - `shipped`: In transit
      - `completed`: Delivered to customer
      - `cancelled`: Order cancelled
    data_type: STRING
    tests:
      - not_null:
          severity: error
      - accepted_values:
          values: ['pending', 'processing', 'shipped', 'completed', 'cancelled']
          severity: error

  - name: order_date
    description: Date the order was placed (UTC)
    data_type: DATE
    tests:
      - not_null:
          severity: error
      - dbt_utils.accepted_range:
          min_value: "'2020-01-01'"
          max_value: "CURRENT_DATE()"
          severity: warn

  - name: total_amount
    description: |
      Total order value in USD after discounts.
      Multi-currency orders converted at order_date exchange rate.
    data_type: NUMERIC
    tests:
      - not_null:
          severity: error
```

---

## Reusable Documentation

### Using `{{ doc() }}` Macros

For columns that appear across multiple models, define reusable documentation blocks:

```markdown
<!-- docs/common_columns.md -->

{% docs customer_id %}
Unique identifier for the customer from the CRM system.
Format: UUID string (36 characters).
{% enddocs %}

{% docs created_at %}
Timestamp when the record was created in the source system (UTC).
{% enddocs %}

{% docs updated_at %}
Timestamp when the record was last modified in the source system (UTC).
May be NULL for records that have never been updated.
{% enddocs %}
```

Reference in schema files:

```yaml
columns:
  - name: customer_id
    description: "{{ doc('customer_id') }}"
    data_type: STRING
```

### Benefits

- Consistent definitions across models
- Single source of truth for common columns
- Easier maintenance when definitions change

---

## Documentation Anti-Patterns

### ❌ Minimal Documentation

```yaml
# BAD: Missing grain, context, and column details
models:
  - name: fct_orders
    description: Order fact table

    columns:
      - name: order_id
        description: Order ID
```

### ❌ Circular Definitions

```yaml
# BAD: Description doesn't add value
columns:
  - name: customer_name
    description: The name of the customer  # Just restates the column name
```

### ❌ Missing Data Types

```yaml
# BAD: No data_type specified
columns:
  - name: order_date
    description: When the order was placed
    # Missing: data_type: DATE
```

### ❌ Missing Tests

```yaml
# BAD: Primary key without uniqueness test
columns:
  - name: order_id
    description: Primary key
    tests:
      - not_null
    # Missing: unique test
```

---

## Complete Example

```yaml
version: 2

models:
  - name: dim_products
    description: |
      Type-1 dimension table of products in the catalog.
      
      **Grain**: One row per product_id (current state only)
      **Update Frequency**: Daily at 06:00 UTC
      **Source**: Product catalog service via CDC
      
      Products are soft-deleted in the source; deleted products have
      `is_active = FALSE` but remain in this table for historical joins.
      
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: ['product_id']
          severity: error

    columns:
      - name: product_sk
        description: Surrogate primary key
        data_type: STRING
        tests:
          - not_null:
              severity: error
          - unique:
              severity: error

      - name: product_id
        description: Natural key from product catalog service
        data_type: STRING
        tests:
          - not_null:
              severity: error
          - unique:
              severity: error

      - name: product_name
        description: Display name of the product
        data_type: STRING
        tests:
          - not_null:
              severity: error

      - name: category
        description: |
          Product category for reporting.
          See product_categories glossary for full taxonomy.
        data_type: STRING
        tests:
          - not_null:
              severity: error
          - accepted_values:
              values: ['Electronics', 'Clothing', 'Home', 'Sports', 'Other']
              severity: warn

      - name: unit_price
        description: Current list price in USD
        data_type: NUMERIC
        tests:
          - not_null:
              severity: error
          - dbt_utils.expression_is_true:
              expression: "unit_price >= 0"
              severity: error

      - name: is_active
        description: Whether the product is currently available for purchase
        data_type: BOOLEAN
        tests:
          - not_null:
              severity: error

      - name: created_at
        description: "{{ doc('created_at') }}"
        data_type: TIMESTAMP
        tests:
          - not_null:
              severity: error

      - name: updated_at
        description: "{{ doc('updated_at') }}"
        data_type: TIMESTAMP
```
