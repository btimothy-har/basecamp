# Performance (BigQuery)

BigQuery-specific optimizations and universal SQL performance patterns.

## BigQuery Optimizations

### EXCEPT over NOT IN

`NOT IN` is problematic with NULLs and less performant. Use `EXCEPT`:

```sql
-- BAD: NOT IN with subquery
SELECT worker_id
FROM employees
WHERE worker_id NOT IN (
  SELECT worker_id FROM terminated_employees
)

-- GOOD: EXCEPT is NULL-safe and performant
SELECT worker_id
FROM employees
EXCEPT DISTINCT
SELECT worker_id
FROM terminated_employees
```

### Conditional Aggregation

Use single-pass conditional aggregation instead of multiple subqueries:

```sql
-- BAD: Multiple passes
SELECT
  department,
  (SELECT COUNT(*) FROM employees e2 
   WHERE e2.department = e1.department AND is_manager) AS managers,
  (SELECT COUNT(*) FROM employees e2 
   WHERE e2.department = e1.department AND NOT is_manager) AS non_managers,
FROM employees AS e1
GROUP BY department

-- GOOD: Single pass with COUNTIF
SELECT
  department,
  COUNTIF(is_manager) AS managers,
  COUNTIF(NOT is_manager) AS non_managers,
FROM employees
GROUP BY department
```

### STRUCT for Related Fields

Group related aggregations with STRUCT:

```sql
SELECT
  department,
  STRUCT(
    COUNTIF(is_manager) AS managers,
    COUNTIF(NOT is_manager) AS individual_contributors,
    COUNT(*) AS total,
  ) AS headcount,
FROM employees
GROUP BY department
```

### APPROX Functions for Scale

For large datasets where exact precision isn't required:

| Function | Approximate Version |
|----------|---------------------|
| `COUNT(DISTINCT x)` | `APPROX_COUNT_DISTINCT(x)` |
| `PERCENTILE_CONT` | `APPROX_QUANTILES` |

```sql
-- Exact (slower on large datasets)
SELECT COUNT(DISTINCT user_id) AS unique_users
FROM events

-- Approximate (fast, ~1% margin of error)
SELECT APPROX_COUNT_DISTINCT(user_id) AS unique_users
FROM events
```

### Partitioning and Clustering

BigQuery uses partitioning and clustering instead of indexes:

```sql
-- Create partitioned and clustered table
CREATE TABLE project.dataset.events
PARTITION BY DATE(event_timestamp)
CLUSTER BY user_id, event_type
AS SELECT * FROM source_events;

-- Always filter on partition column for cost/performance
SELECT *
FROM project.dataset.events
WHERE DATE(event_timestamp) = '2024-01-15'  -- Partition pruning
  AND user_id = 'abc123'                     -- Cluster filtering
```

### Query Analysis

Use Query Execution Details in BigQuery Console. Look for:
- **Bytes shuffled** — high values indicate expensive JOINs/aggregations
- **Slot time** — total compute time across all workers
- **Stages** — identify bottleneck stages
- **Rows read vs rows returned** — filter effectiveness

## Window Functions

### Always Specify ORDER BY

Even when using the whole partition, specify ORDER BY for deterministic results:

```sql
-- BAD: Non-deterministic ordering
SELECT
  worker_id,
  ROW_NUMBER() OVER (PARTITION BY project_id, user_id) AS rn,
FROM assignments

-- GOOD: Explicit ordering
SELECT
  worker_id,
  ROW_NUMBER() OVER (
    PARTITION BY project_id, user_id
    ORDER BY created_at DESC  -- Most recent first
  ) AS rn,
FROM assignments
```

### Named Window Frames

Reuse window definitions with WINDOW clause:

```sql
-- BAD: Repeated window definition
SELECT
  worker_id,
  ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY added_at) AS rn,
  LEAD(sequence_num) OVER (PARTITION BY project_id ORDER BY added_at) AS next_seq,
  LAG(sequence_num) OVER (PARTITION BY project_id ORDER BY added_at) AS prev_seq,
FROM assignments

-- GOOD: Named window
SELECT
  worker_id,
  ROW_NUMBER() OVER w AS rn,
  LEAD(sequence_num) OVER w AS next_seq,
  LAG(sequence_num) OVER w AS prev_seq,
FROM assignments
WINDOW w AS (PARTITION BY project_id ORDER BY added_at)
```

### Document Complex Windows

Add comments explaining the business logic:

```sql
SELECT
  worker_id,
  -- Assign row numbers for deduplication (keep most recent)
  ROW_NUMBER() OVER (
    PARTITION BY project_id, user_id
    ORDER BY created_at DESC
  ) AS dedup_rn,
  -- Check if this is the last entry in a sequence
  LEAD(sequence_num) OVER w != sequence_num AS is_last_in_sequence,
FROM assignments
WINDOW w AS (
  PARTITION BY project_id, user_id, role
  ORDER BY added_at
)
```

## Set Operations

### UNION ALL by Default

`UNION ALL` is more performant than `UNION DISTINCT` (no sort/dedupe). Use DISTINCT only when needed:

```sql
-- GOOD: UNION ALL for mutually exclusive sets
SELECT worker_id, 'active' AS status
FROM active_workers
UNION ALL
SELECT worker_id, 'terminated' AS status
FROM terminated_workers

-- GOOD: UNION DISTINCT with explanation
SELECT email
FROM employees
UNION DISTINCT  -- Some employees may have multiple records
SELECT email
FROM contractors
```

## Early Filtering

Apply filters as early as possible, not just at the end:

```sql
-- BAD: Late filtering
WITH all_events AS (
  SELECT * FROM events
),
enriched AS (
  SELECT e.*, u.name
  FROM all_events AS e
  INNER JOIN users AS u ON e.user_id = u.id
)
SELECT * FROM enriched
WHERE event_date > '2024-01-01'  -- Filter should be earlier

-- GOOD: Early filtering
WITH filtered_events AS (
  SELECT *
  FROM events
  WHERE event_date > '2024-01-01'  -- Filter at source
),
enriched AS (
  SELECT e.*, u.name
  FROM filtered_events AS e
  INNER JOIN users AS u ON e.user_id = u.id
)
SELECT * FROM enriched
```

## Common Performance Issues

| Issue | Symptom | Fix |
|-------|---------|-----|
| Full table scan | High bytes scanned | Add partition filter, cluster by frequent filters |
| Cross join | Exponential row count | Fix JOIN conditions |
| Skewed partitions | Slow single workers | Repartition, use APPROX functions |
| Repeated calculations | Slow CTEs | Materialize intermediate results |
| Large shuffles | High bytes shuffled | Pre-aggregate before JOINs |
