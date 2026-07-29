# Dimensional Modeling

Apply Kimball-style dimensional modeling techniques to create analytical data structures optimized for business intelligence workloads.

## Core Concepts

### Facts vs Dimensions

| Concept | Description | Examples |
|---------|-------------|----------|
| **Fact** | Measures business processes/events | Orders, page views, transactions |
| **Dimension** | Describes entities involved in facts | Customers, products, dates |

Facts contain **measures** (numeric, additive) and **foreign keys** to dimensions.
Dimensions contain **attributes** (descriptive, filterable) and a **surrogate primary key**.

### Surrogate Keys

Always use surrogate keys for dimension tables:

```sql
SELECT
    {{ dbt_utils.generate_surrogate_key(['customer_id']) }} AS customer_sk,
    customer_id,
    customer_name,
    -- ... attributes
FROM {{ ref('base__crm_customers') }}
```

**Why surrogate keys?**
- Enable Type-2 SCD tracking (same natural key, different surrogate)
- Provide stable join keys independent of source system changes
- Handle source systems without natural keys

---

## Dimension Patterns

### Type-1 Dimensions (Current State)

Type-1 dimensions maintain **one row per entity** representing current state only. History is not preserved.

| Characteristic | Value |
|----------------|-------|
| Grain | 1 row per entity |
| History | None (overwritten) |
| Materialization | Table (`CREATE OR REPLACE`) |
| Use case | Entities managed in authoritative source systems |

```sql
-- Type-1 dimension: Current customer state
{{ config(materialized='table') }}

SELECT
    {{ dbt_utils.generate_surrogate_key(['customer_id']) }} AS customer_sk,
    customer_id,
    customer_name,
    email,
    segment,
    created_at,
    updated_at,
FROM {{ ref('base__crm_customers') }}
```

### Type-2 Dimensions (Slowly Changing)

Type-2 dimensions maintain **multiple rows per entity** tracking historical state changes with validity intervals.

| Characteristic | Value |
|----------------|-------|
| Grain | 1 row per entity per change |
| History | Full (tracked via intervals) |
| Interval columns | `valid_from`, `valid_to` |
| Current record | `valid_to IS NULL` |

```sql
-- Type-2 dimension: Employee history with validity intervals
{{ config(materialized='table') }}

WITH changes AS (
    SELECT
        employee_id,
        department,
        title,
        salary_band,
        effective_date AS valid_from,
        LEAD(effective_date) OVER (
            PARTITION BY employee_id
            ORDER BY effective_date
        ) AS valid_to,
    FROM {{ ref('int_employee_changes') }}
)

SELECT
    {{ dbt_utils.generate_surrogate_key(['employee_id', 'valid_from']) }} AS employee_sk,
    employee_id,
    department,
    title,
    salary_band,
    valid_from,
    valid_to,  -- NULL for current record
    valid_to IS NULL AS is_current,
FROM changes
```

**Interval Convention**: Use half-open intervals `(valid_from, valid_to]` where:
- `valid_from` is inclusive (record is valid starting this date)
- `valid_to` is exclusive (record is valid until, but not including, this date)
- `NULL` in `valid_to` indicates the current/latest record

**Querying Type-2 Dimensions**:

```sql
-- Get employee's department on a specific date
SELECT e.*
FROM dim_employees AS e
WHERE e.employee_id = '12345'
  AND '2024-06-15' >= e.valid_from
  AND ('2024-06-15' < e.valid_to OR e.valid_to IS NULL)

-- Get current state for all employees
SELECT *
FROM dim_employees
WHERE is_current = TRUE
```

---

## Fact Table Patterns

### Transaction Facts

The simplest fact pattern: **one row per business event**.

| Characteristic | Value |
|----------------|-------|
| Grain | 1 row per event |
| Keys | Degenerate key + foreign keys |
| Measures | Event-specific metrics |

```sql
-- Transaction fact: One row per order
{{ config(materialized='table') }}

SELECT
    order_id,
    -- Foreign keys to dimensions
    {{ dbt_utils.generate_surrogate_key(['customer_id']) }} AS customer_sk,
    {{ dbt_utils.generate_surrogate_key(['product_id']) }} AS product_sk,
    -- Degenerate dimensions (no separate dim table needed)
    order_date,
    order_status,
    -- Measures
    quantity,
    unit_price,
    discount_amount,
    total_amount,
FROM {{ ref('int_orders_enriched') }}
```

### Periodic Snapshot Facts

Capture entity state at **regular intervals** (daily, weekly, monthly).

| Characteristic | Value |
|----------------|-------|
| Grain | 1 row per entity per period |
| Requirements | Contiguous periods (no gaps) |
| Constraint | Only ONE snapshot per (entity, period grain) |

```sql
-- Periodic snapshot: Daily customer balance
{{ config(materialized='incremental', unique_key=['customer_id', 'snapshot_date']) }}

WITH date_spine AS (
    SELECT date
    FROM UNNEST(GENERATE_DATE_ARRAY('2020-01-01', CURRENT_DATE())) AS date
),

customers AS (
    SELECT DISTINCT customer_id, first_order_date
    FROM {{ ref('dim_customers') }}
)

SELECT
    c.customer_id,
    d.date AS snapshot_date,
    -- Resolve metrics as of this date
    COALESCE(b.account_balance, 0) AS account_balance,
    COALESCE(b.lifetime_orders, 0) AS lifetime_orders,
    COALESCE(b.lifetime_revenue, 0) AS lifetime_revenue,
FROM customers AS c
CROSS JOIN date_spine AS d
LEFT JOIN {{ ref('int_customer_daily_metrics') }} AS b
    ON c.customer_id = b.customer_id
    AND d.date = b.metric_date
WHERE d.date >= c.first_order_date
{% if is_incremental() %}
    AND d.date > (SELECT MAX(snapshot_date) FROM {{ this }})
{% endif %}
```

**Key Rules**:
- No gaps: Every entity must have a row for every period from its start date
- One per grain: Avoid multiple periodic snapshots at the same (entity, period) grain
- Contiguous: Fill forward or use `COALESCE` to handle missing periods

### Accumulating Snapshot Facts

Track **funnel or pipeline progression** with milestone dates.

| Characteristic | Value |
|----------------|-------|
| Grain | 1 row per funnel instance |
| Columns | Milestone dates, measures at each stage |
| Updates | Row is updated as milestones are reached |

```sql
-- Accumulating snapshot: Order fulfillment funnel
{{ config(materialized='table') }}

SELECT
    order_id,
    customer_sk,
    -- Milestone dates
    order_placed_at,
    payment_received_at,
    shipped_at,
    delivered_at,
    -- Milestone-to-milestone durations
    TIMESTAMP_DIFF(payment_received_at, order_placed_at, HOUR) AS hours_to_payment,
    TIMESTAMP_DIFF(shipped_at, payment_received_at, HOUR) AS hours_to_ship,
    TIMESTAMP_DIFF(delivered_at, shipped_at, HOUR) AS hours_to_deliver,
    -- Current funnel stage
    CASE
        WHEN delivered_at IS NOT NULL THEN 'delivered'
        WHEN shipped_at IS NOT NULL THEN 'shipped'
        WHEN payment_received_at IS NOT NULL THEN 'paid'
        ELSE 'pending_payment'
    END AS current_stage,
FROM {{ ref('int_order_milestones') }}
```

---

## Design Guidelines

### Normalization

Domain models should be **normalized by default**:

| Do | Don't |
|-----|-------|
| Store attributes on dimension tables | Duplicate attributes across fact tables |
| Use foreign keys in facts | Embed full dimension records in facts |
| Resolve attributes at query time | Create wide denormalized fact tables |

**Exception**: Periodic snapshot facts may include denormalized attributes for query convenience, as they represent point-in-time state.

### Grain Specification

Every model's grain must be:
1. **Documented** in the schema YAML
2. **Tested** with uniqueness constraints

```yaml
models:
  - name: fct_order_line_items
    description: |
      Transaction fact of order line items.
      
      **Grain**: One row per order_id, line_item_id combination
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: ['order_id', 'line_item_id']
```

### Foreign Key Integrity

All foreign key relationships should be tested:

```yaml
columns:
  - name: customer_sk
    description: Surrogate key to dim_customers
    tests:
      - not_null
      - relationships:
          to: ref('dim_customers')
          field: customer_sk
```

---

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| **Degenerate dimensions in facts** | Duplicated attributes | Normalize to dimension table |
| **Multiple periodic snapshots** | Confusion, maintenance burden | Consolidate to single snapshot per grain |
| **Missing history** | Can't analyze historical state | Use Type-2 dimensions |
| **Undocumented grain** | Misuse, incorrect joins | Document and test grain |
| **Natural keys as PKs** | Brittle to source changes | Use surrogate keys |
