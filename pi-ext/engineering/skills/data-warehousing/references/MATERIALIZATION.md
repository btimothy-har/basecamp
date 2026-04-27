# Materialization Strategies

Choose the right dbt materialization based on data characteristics, query patterns, and freshness requirements.

## Strategy Overview

| Strategy | Description | Rebuild Behavior |
|----------|-------------|------------------|
| **View** | Virtual table; query re-executed each time | Always fresh |
| **Table** | Physical table; full rebuild on each run | `CREATE OR REPLACE` |
| **Incremental** | Physical table; append/merge new records | Partial rebuild |
| **Ephemeral** | CTE injected into downstream models | No physical artifact |
| **Snapshot** | Track Type-2 SCD from mutable sources | Append historical records |

---

## When to Use Each Strategy

### View

**Best for:**
- Base models (light wrappers on sources)
- Small reference tables (<10K rows)
- Data that changes frequently and must be fresh
- Models where query cost is acceptable

**Avoid when:**
- Query is expensive and run frequently
- Downstream models are sensitive to query time
- Data volume is large

```sql
-- Base model: Always use view
{{ config(materialized='view') }}

SELECT
    CAST(id AS STRING) AS customer_id,
    email,
    created_at,
FROM {{ source('crm', 'customers') }}
```

### Table

**Best for:**
- Dimension tables (any size)
- Small-to-medium fact tables (<1GB)
- Complex transformations that are expensive to recompute
- Models with stable query patterns

**Avoid when:**
- Table is very large and only recent data changes
- Full rebuild time exceeds acceptable thresholds

```sql
-- Type-1 dimension: Full rebuild is acceptable
{{ config(materialized='table') }}

SELECT
    {{ dbt_utils.generate_surrogate_key(['customer_id']) }} AS customer_sk,
    customer_id,
    customer_name,
    segment,
FROM {{ ref('int_customers_enriched') }}
```

### Incremental

**Best for:**
- Large fact tables (>1GB)
- Event streams and logs
- Append-mostly data patterns
- Tables with reliable timestamp columns

**Requirements:**
- Define `unique_key` for merge/upsert logic
- Handle late-arriving data with lookback windows
- Plan for full refresh scenarios

```sql
-- Large fact table: Incremental with lookback
{{ config(
    materialized='incremental',
    unique_key=['event_id'],
    partition_by={
        'field': 'event_date',
        'data_type': 'date',
        'granularity': 'day'
    },
    cluster_by=['customer_id'],
    incremental_strategy='merge'
) }}

SELECT
    event_id,
    customer_id,
    event_type,
    event_date,
    event_timestamp,
    event_data,
FROM {{ ref('int_events_parsed') }}
{% if is_incremental() %}
    -- Look back 3 days for late-arriving events
    WHERE event_date >= DATE_SUB(
        (SELECT MAX(event_date) FROM {{ this }}),
        INTERVAL 3 DAY
    )
{% endif %}
```

### Ephemeral

**Best for:**
- Intermediate CTEs used by multiple models
- Logic that doesn't need to be queryable directly
- Reducing warehouse storage costs

**Avoid when:**
- Model is useful for debugging/ad-hoc queries
- CTE is complex and would benefit from caching

```sql
-- Shared transformation: Ephemeral avoids redundant storage
{{ config(materialized='ephemeral') }}

SELECT
    order_id,
    customer_id,
    SUM(line_total) AS order_total,
FROM {{ ref('base__order_line_items') }}
GROUP BY 1, 2
```

### Snapshot

**Best for:**
- Type-2 SCD tracking from mutable source tables
- Capturing historical state when source doesn't preserve history
- Audit trails

**Requirements:**
- Reliable `unique_key` identifying the entity
- Strategy: `timestamp` (recommended) or `check`

```sql
-- snapshots/customers_snapshot.sql
{% snapshot customers_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='customer_id',
        strategy='timestamp',
        updated_at='updated_at',
    )
}}

SELECT * FROM {{ source('crm', 'customers') }}

{% endsnapshot %}
```

---

## Incremental Strategies

### Merge (Default for BigQuery)

Updates existing rows and inserts new ones. Best for:
- Tables with reliable unique keys
- Mixed insert/update patterns

```sql
{{ config(
    materialized='incremental',
    unique_key=['order_id'],
    incremental_strategy='merge'
) }}
```

### Insert Overwrite

Replaces entire partitions. Best for:
- Partition-aligned data (daily, monthly)
- When partition data is always complete

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={
        'field': 'event_date',
        'data_type': 'date'
    }
) }}
```

### Append

Simple insert without deduplication. Best for:
- Immutable event streams
- When duplicates are handled downstream

```sql
{{ config(
    materialized='incremental',
    incremental_strategy='append'
) }}
```

---

## Configuration Patterns

### Partitioning (BigQuery)

Partition large tables for cost control and query performance:

```sql
{{ config(
    materialized='incremental',
    partition_by={
        'field': 'created_date',
        'data_type': 'date',
        'granularity': 'day'  -- or 'month', 'year'
    }
) }}
```

### Clustering (BigQuery)

Cluster on frequently filtered columns:

```sql
{{ config(
    materialized='table',
    cluster_by=['customer_id', 'product_category']
) }}
```

### Schema Change Handling

Choose how incremental models handle schema changes:

| Option | Behavior |
|--------|----------|
| `ignore` | Ignore new columns in source |
| `append_new_columns` | Add new columns, leave existing |
| `sync_all_columns` | Full schema sync (may fail on type changes) |
| `fail` | Fail on any schema change |

```sql
{{ config(
    materialized='incremental',
    on_schema_change='append_new_columns'
) }}
```

---

## Late-Arriving Data

Handle late-arriving records with lookback windows:

```sql
{{ config(
    materialized='incremental',
    unique_key=['event_id']
) }}

SELECT * FROM {{ ref('int_events') }}
{% if is_incremental() %}
    -- 7-day lookback for late events
    WHERE event_timestamp >= TIMESTAMP_SUB(
        (SELECT MAX(event_timestamp) FROM {{ this }}),
        INTERVAL 7 DAY
    )
{% endif %}
```

**Considerations:**
- Lookback window size depends on source system latency
- Longer windows = more reprocessing cost
- Document expected latency in model description

---

## Full Refresh Planning

All incremental models should handle full refresh gracefully:

```sql
{{ config(
    materialized='incremental',
    unique_key=['order_id'],
    -- Set to false if full refresh would be problematic
    full_refresh=true
) }}

SELECT * FROM {{ ref('int_orders') }}
{% if is_incremental() %}
    WHERE order_date >= DATE_SUB(
        (SELECT MAX(order_date) FROM {{ this }}),
        INTERVAL 3 DAY
    )
{% else %}
    -- Full refresh: limit historical data if needed
    WHERE order_date >= '2020-01-01'
{% endif %}
```

---

## Decision Matrix

| Criteria | View | Table | Incremental | Ephemeral |
|----------|------|-------|-------------|-----------|
| Data size | Small | Small-Medium | Large | Any |
| Change frequency | High | Low-Medium | Append-heavy | N/A |
| Query frequency | Low | High | High | N/A |
| Rebuild cost | Low | Acceptable | Prohibitive | N/A |
| Freshness need | Real-time | Batch OK | Batch OK | N/A |
| Debuggable | Yes | Yes | Yes | No |

---

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| **Large table as view** | Expensive repeated queries | Use table or incremental |
| **Small table as incremental** | Unnecessary complexity | Use table |
| **No lookback window** | Late data is lost | Add lookback for incremental |
| **No partition pruning** | Full table scans | Partition and filter appropriately |
| **Ephemeral for debugging** | Can't query intermediate results | Use table during development |
