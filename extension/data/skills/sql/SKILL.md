---
name: sql
description: "This skill should be used when writing or modifying .sql files, designing database schemas, or optimizing queries. Keywords: SQL query, CTE, BigQuery, PostgreSQL, schema, table."
---

# SQL Development

Write clear, performant SQL. Determine the target database (BigQuery, PostgreSQL, etc.) from the project context—check existing queries, dbt profiles, or connection configs.

## Principles

**Query Design**
- **CTEs for clarity** — Break complex queries into logical, named steps
- **Explicit columns** — Never `SELECT *` at input/output boundaries; list columns explicitly
- **Meaningful names** — CTEs and aliases should describe *what*, not *how*
- **Trailing commas** — Required by SQLFluff; enables cleaner diffs

**NULL Handling**
- **Be explicit** — Document three-valued logic; `NULL != NULL`
- **Direct expressions** — Prefer `col IS NULL` over `COALESCE(col IS NULL, FALSE)`
- **Understand aggregations** — `COUNT(*)` vs `COUNT(col)` behave differently with NULLs

**Performance**
- **Filter early** — Push WHERE clauses as close to source tables as possible
- **UNION ALL by default** — Use DISTINCT only when deduplication is needed
- **EXPLAIN first** — Profile before optimizing; don't guess at bottlenecks

**Formatting**
- **Keywords uppercase** — `SELECT`, `FROM`, `WHERE`, `INNER JOIN`
- **Explicit JOINs** — Always `INNER JOIN`, never bare `JOIN`
- **Primary keys first** — In SELECT and GROUP BY clauses

## Quick Reference

### Running SQL

Determine the database from project context (dbt profiles, connection configs, existing queries).

```bash
# PostgreSQL
psql -h localhost -U username -d database_name -f script.sql

# BigQuery (via bq CLI)
bq query --use_legacy_sql=false < script.sql
```

### Code Standards

- **Trailing commas**: Always before FROM
- **GROUP BY**: Numeric references (`GROUP BY 1, 2`), primary keys only
- **Aliases**: Short, mnemonic (2-3 chars), explicit `AS`
- **NULL safety**: `COALESCE`, `IFNULL`, `IS NOT DISTINCT FROM`

---

## Query Structure — read [QUERY_STRUCTURE.md](references/QUERY_STRUCTURE.md)

Structure queries with CTEs for clarity and testability.

| Pattern | Guideline |
|---------|-----------|
| **CTE naming** | Noun phrases describing grain/content: `completed_orders` |
| **One concept per CTE** | Each CTE is a logical unit of work |
| **SELECT *** | Only internally; explicit columns at boundaries |
| **Table aliases** | Short (2-3 chars), mnemonic: `fo` for `fct_orders` |
| **JOINs** | Explicit `INNER JOIN`/`LEFT JOIN`; meaningful aliases |

```sql
WITH completed_orders AS (
  SELECT order_id, customer_id, total_amount,
  FROM sales.fct_orders
  WHERE status = 'completed'
),
customer_totals AS (
  SELECT customer_id, SUM(total_amount) AS lifetime_value,
  FROM completed_orders
  GROUP BY 1
)
SELECT * FROM customer_totals
```

---

## NULL Handling — read [NULL_HANDLING.md](references/NULL_HANDLING.md)

Be explicit and consistent with NULL handling.

| Pattern | Use |
|---------|-----|
| `IS NULL` / `IS NOT NULL` | Existence checks |
| `COALESCE(bool_col, FALSE)` | Convert nullable boolean |
| `COUNT(col)` vs `COUNT(*)` | Ignore NULLs vs count all rows |
| `SAFE_CAST` | Graceful handling of invalid JSON/types |
| `EXCEPT DISTINCT` | NULL-safe alternative to `NOT IN` |

```sql
SELECT
  COALESCE(is_active, FALSE) AS is_active_flag,  -- Nullable bool to FALSE
  concluded_at IS NULL AS is_active_project,      -- Direct boolean
  score IS NOT NULL AS has_score,                 -- Direct boolean
FROM projects
```

---

## Formatting — read [FORMATTING.md](references/FORMATTING.md)

Consistent formatting for readability and linter compliance.

| Rule | Example |
|------|---------|
| Trailing commas | `SELECT col1, col2,` (before FROM) |
| GROUP BY primary keys only | `GROUP BY 1, 2` + `ANY_VALUE()` for rest |
| CASE formatting | Multi-line with comments for complex logic |
| Column order | PK → FK → business → computed → audit |

```sql
-- Aggregate then hydrate pattern
WITH location_payments AS (
  SELECT
    location_id,
    DATE_TRUNC(payment_date, MONTH) AS month_start,
    SUM(amount) AS total_amount,
  FROM fct_payments
  GROUP BY 1, 2
)
SELECT
  p.*,
  loc.country,
  loc.state,
FROM location_payments AS p
INNER JOIN dim_locations AS loc USING (location_id)
```

---

## Performance — read [PERFORMANCE_BIGQUERY.md](references/PERFORMANCE_BIGQUERY.md) | [PERFORMANCE_POSTGRES.md](references/PERFORMANCE_POSTGRES.md)

Write performant SQL with platform-aware patterns. Choose the reference doc based on your project's database.

| Pattern | Recommendation |
|---------|----------------|
| `UNION ALL` | Default choice; `DISTINCT` only when needed |
| Window functions | Always specify `ORDER BY`; use named windows |
| Early filtering | Push WHERE as close to source as possible |

**BigQuery-specific:**

| Pattern | Recommendation |
|---------|----------------|
| `COUNTIF` | Single-pass conditional aggregation |
| `EXCEPT DISTINCT` | Prefer over `NOT IN` (NULL-safe) |
| Partitioning | Filter on partition columns for cost control |

**PostgreSQL-specific:**

| Pattern | Recommendation |
|---------|----------------|
| Indexing | Create indexes based on WHERE, JOIN, ORDER BY |
| `EXPLAIN ANALYZE` | Profile queries before optimizing |

---

## Query Patterns

### Basic CRUD

*PostgreSQL syntax shown; check project database for dialect differences.*

```sql
-- Insert with returning
INSERT INTO users (email, name)
VALUES ('user@example.com', 'Test User')
RETURNING id, created_at;

-- Upsert (insert or update)
INSERT INTO users (email, name)
VALUES ('user@example.com', 'Test User')
ON CONFLICT (email) DO UPDATE
SET name = EXCLUDED.name, updated_at = NOW();
```

### Window Functions

```sql
-- Row number for deduplication
SELECT
  id,
  name,
  ROW_NUMBER() OVER (
    PARTITION BY user_id
    ORDER BY created_at DESC
  ) AS rn,
FROM records
QUALIFY rn = 1  -- BigQuery: filter on window function

-- Running totals
SELECT
  date,
  amount,
  SUM(amount) OVER (ORDER BY date) AS running_total,
FROM transactions
```

### Conditional Aggregation

```sql
-- FILTER syntax (PostgreSQL)
SELECT
  COUNT(*) AS total_orders,
  COUNT(*) FILTER (WHERE status = 'completed') AS completed,
  SUM(total) FILTER (WHERE status = 'completed') AS completed_revenue,
FROM orders

-- COUNTIF/SUMIF (BigQuery)
SELECT
  COUNT(*) AS total_orders,
  COUNTIF(status = 'completed') AS completed,
  SUM(IF(status = 'completed', total, 0)) AS completed_revenue,
FROM orders
```

## Schema Patterns

*PostgreSQL-specific. For BigQuery/other warehouses, schema is typically managed via dbt or infrastructure-as-code.*

### Table Creation

```sql
CREATE TABLE users (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX ix_users_created_at ON users (created_at DESC);
CREATE INDEX ix_users_metadata ON users USING GIN (metadata);
```

### Enums

```sql
CREATE TYPE order_status AS ENUM ('pending', 'processing', 'completed', 'cancelled');

CREATE TABLE orders (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  status order_status DEFAULT 'pending' NOT NULL
);
```
