---
name: data-warehousing
description: "This skill should be used when designing, building, or reviewing data warehouse models with dbt. Keywords: dbt, fact table, dimension, data warehouse, mart, schema."
---

# Data Warehousing

Build maintainable, well-documented data warehouses using dimensional modeling principles and dbt.

## Principles

**Layered Architecture**
- **Base → Intermediate → Domain → Mart** — Clear separation of concerns across model layers
- **Base models are views** — Light wrappers on raw data; no transformations
- **Intermediate is private** — Internal staging; not for ad-hoc queries
- **Domain models are public APIs** — Schema changes require downstream coordination

**Dimensional Modeling**
- **Facts and dimensions** — Clearly delineate business processes (facts) from entities (dimensions)
- **Surrogate keys** — Use `dbt_utils.generate_surrogate_key()` for dimension primary keys
- **Normalized by default** — Store attributes on dimension tables; resolve at query time
- **Grain is explicit** — Every model's grain must be documented and tested

**Documentation**
- **One model, one schema file** — `model_name.yml` alongside `model_name.sql`
- **Describe the grain** — What does a single row represent?
- **Document every column** — Name, type, description, and relevant tests
- **Use `{{ doc() }}` macros** — Consistent definitions for common columns

**Testing**
- **Test the grain** — Uniqueness tests on primary key columns
- **Test relationships** — Foreign key integrity to referenced tables
- **Test business rules** — Encode assumptions with `expression_is_true`
- **Use severity levels** — `error` for blockers, `warn` for monitoring

## Quick Reference

### Model Layer Structure

```
models/
├── base/                    # Views on raw source data
│   └── <domain>/
│       └── base__<source>_<entity>.sql
├── intermediate/            # Private staging models
│   └── <domain>/
│       └── <downstream_model>/
├── <domain>/                # Public dimensional models
│   ├── dim_<entity>.sql
│   └── fct_<process>.sql
└── marts/                   # Use-case specific presentations
    └── mart_<domain>/
        └── <consumer>_dashboard/
```

### Naming Conventions

| Layer | Pattern | Example |
|-------|---------|---------|
| Base | `base__<source>_<entity>` | `base__salesforce_accounts` |
| Intermediate | Descriptive, no `fct_`/`dim_` | `orders_with_line_items` |
| Domain | `fct_<process>` or `dim_<entity>` | `fct_order_transactions`, `dim_customers` |
| Mart | `<consumer>_<purpose>` | `finance_dashboard_revenue` |

### Dimensional Model Patterns

| Pattern | Grain | Use Case |
|---------|-------|----------|
| Type-1 Dimension | 1 row per entity | Current state only; no history |
| Type-2 Dimension | Multiple rows per entity | Historical state with `valid_from`/`valid_to` |
| Transaction Fact | 1 row per event | Individual business events |
| Periodic Snapshot | 1 row per entity per period | Regular state capture (daily, monthly) |
| Accumulating Snapshot | 1 row per funnel instance | Pipeline/funnel progression |

---

## Model Layers — read [MODEL_LAYERS.md](references/MODEL_LAYERS.md)

Organize models into distinct layers with clear responsibilities.

| Layer | Purpose | Materialization |
|-------|---------|-----------------|
| **Base** | Conform raw source data | View |
| **Intermediate** | Private staging/transformation | Table or Ephemeral |
| **Domain** | Public dimensional models | Table (incremental for large facts) |
| **Mart** | Consumer-specific presentations | Table |

```sql
-- Base: Light wrapper, no transformation
{{ config(materialized="view") }}

SELECT
    cast(id AS STRING) AS customer_id,
    email,
    created_at,
FROM {{ source('crm', 'customers') }}
```

---

## Dimensional Modeling — read [DIMENSIONAL_MODELING.md](references/DIMENSIONAL_MODELING.md)

Apply Kimball-style dimensional modeling for analytical workloads.

| Concept | Guideline |
|---------|-----------|
| **Surrogate keys** | Generate via `{{ dbt_utils.generate_surrogate_key() }}` |
| **Foreign keys** | Resolve to surrogate keys on dimension tables |
| **Type-2 intervals** | Use `(valid_from, valid_to]` with `NULL` for current |
| **Periodic snapshots** | One per (entity, period) — avoid duplicates |

```sql
-- Type-2 dimension with validity interval
SELECT
    {{ dbt_utils.generate_surrogate_key(['employee_id', 'valid_from']) }} AS employee_sk,
    employee_id,
    department,
    title,
    valid_from,
    valid_to,  -- NULL for current record
FROM {{ ref('int_employee_changes') }}
```

---

## Documentation — read [DOCUMENTATION.md](references/DOCUMENTATION.md)

Every model requires comprehensive schema documentation.

| Element | Requirement |
|---------|-------------|
| **Model description** | Purpose, grain, update frequency, source |
| **Table-level tests** | Grain uniqueness, business rules |
| **Column descriptions** | Meaning, data type, business context |
| **Column tests** | `not_null`, `unique`, `accepted_values`, `relationships` |

```yaml
models:
  - name: fct_orders
    description: |
      Transaction fact table of customer orders.
      
      **Grain**: One row per order_id
      **Update Frequency**: Hourly
      **Source**: E-commerce platform order events
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns: ['order_id']
```

---

## Testing — read [TESTING.md](references/TESTING.md)

Implement comprehensive testing with appropriate severity levels.

| Category | Purpose | Examples |
|----------|---------|----------|
| **Schema** | Structure validation | Data types, column presence |
| **Data quality** | Integrity checks | Not null, uniqueness, relationships |
| **Business logic** | Rule validation | `expression_is_true` tests |
| **Threshold** | Anomaly detection | Row count ranges, value bounds |

```yaml
columns:
  - name: order_date
    tests:
      - not_null:
          severity: error
      - dbt_utils.accepted_range:
          min_value: '2020-01-01'
          max_value: 'CURRENT_DATE()'
          severity: warn
```

---

## Materialization — read [MATERIALIZATION.md](references/MATERIALIZATION.md)

Choose materialization based on data characteristics and usage patterns.

| Strategy | When to Use |
|----------|-------------|
| **View** | Base models; small, frequently-changing reference data |
| **Table** | Dimensions; small-to-medium fact tables |
| **Incremental** | Large fact tables; event streams |
| **Ephemeral** | Intermediate CTEs reused across models |
| **Snapshot** | Type-2 SCD tracking from mutable sources |

```sql
-- Incremental fact table with late-arriving data handling
{{ config(
    materialized='incremental',
    unique_key=['order_id'],
    partition_by={'field': 'order_date', 'data_type': 'date'},
    incremental_strategy='merge'
) }}

SELECT * FROM {{ ref('int_orders') }}
{% if is_incremental() %}
    WHERE order_date >= DATE_SUB((SELECT MAX(order_date) FROM {{ this }}), INTERVAL 3 DAY)
{% endif %}
```
