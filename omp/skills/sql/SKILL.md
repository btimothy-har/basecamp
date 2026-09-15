---
name: sql
description: "SQL guidance for work involving .sql files, database schema design, or query optimization. Keywords: SQL query, CTE, BigQuery, PostgreSQL, schema, table."
---

# SQL Development

Write clear, performant SQL. Determine the target database (BigQuery, PostgreSQL, etc.) from the project context—check existing queries, dbt profiles, or connection configs.

## Principles

**Query Design**
- **CTEs for clarity** — Break complex queries into logical, named steps
- **Explicit columns** — Never `SELECT *` at input/output boundaries; list columns explicitly
- **Meaningful names** — CTEs and aliases should describe *what*, not *how*
- **Match project style** — Follow the existing lint configuration and formatting conventions (comma placement, casing) rather than imposing a new one

**NULL Handling**
- **Be explicit** — Document three-valued logic; `NULL != NULL`
- **Direct expressions** — Prefer `col IS NULL` over `COALESCE(col IS NULL, FALSE)`
- **Understand aggregations** — `COUNT(*)` vs `COUNT(col)` behave differently with NULLs

**Performance**
- **Filter early** — Push WHERE clauses as close to source tables as possible
- **UNION ALL by default** — Use DISTINCT only when deduplication is needed
- **EXPLAIN first** — Profile before optimizing; don't guess at bottlenecks

**Formatting**
- **Match project conventions** — Follow the repository's keyword casing, comma placement, aliasing, and column ordering
- **Explicit JOINs** — Prefer `INNER JOIN` over bare `JOIN`

## Quick Reference

### Running SQL

Determine the database from project context (dbt profiles, connection configs, existing queries) before choosing a client.

```bash
# PostgreSQL
psql -h localhost -U username -d database_name -f script.sql
```

For BigQuery, save SQL to a local `.sql` file and run it with the bq CLI. Always estimate cost first and redirect result rows to a temporary file outside the repository rather than streaming large result sets into the conversation:

```bash
# Estimate scan size first
bq query --use_legacy_sql=false --dry_run < query.sql

# Set RESULTS_FILE to an OS-temporary path outside the repository
bq query --use_legacy_sql=false --format=csv --max_rows=1000 \
  < query.sql > "$RESULTS_FILE"
```

Check the dry-run estimate (or `EXPLAIN` on other engines) before executing a large scan — for metered warehouses this is the only cost gate. Write large CLI output outside the repository in an OS temporary directory. Read it deliberately with the `read` tool's line selectors and use `wc -l` for row counts rather than dumping whole files into context. Summarize results concisely with the output path instead of pasting raw rows. `--max_rows` limits returned rows only, not scanned bytes.

### Code Standards

- **GROUP BY**: Name columns explicitly, or use numeric references (`GROUP BY 1, 2`) only where both the dialect and project style support them; group by primary keys where possible
- **Aliases**: Short, mnemonic (2-3 chars), explicit `AS`
- **NULL safety**: `COALESCE`, `IFNULL`, `IS NOT DISTINCT FROM`
- **Commas**: Match the project's existing convention (leading or trailing); do not introduce trailing commas in codebases that don't use them

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
  SELECT order_id, customer_id, total_amount
  FROM sales.fct_orders
  WHERE status = 'completed'
),
customer_totals AS (
  SELECT customer_id, SUM(total_amount) AS lifetime_value
  FROM completed_orders
  GROUP BY customer_id
)
SELECT customer_id, lifetime_value FROM customer_totals
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
  score IS NOT NULL AS has_score                  -- Direct boolean
FROM projects
```

---

## Formatting — read [FORMATTING.md](references/FORMATTING.md)

Consistent formatting for readability and linter compliance.

| Rule | Example |
|------|---------|
| Comma placement | Match the project's linter config; trailing commas (`SELECT col1, col2,`) only where the project already uses them |
| GROUP BY primary keys | BigQuery: `GROUP BY 1, 2` + `ANY_VALUE()` for the rest; elsewhere group by named columns |
| CASE formatting | Multi-line with comments for complex logic |
| Column order | PK → FK → business → computed → audit |

```sql
-- Aggregate then hydrate pattern
WITH location_payments AS (
  SELECT
    location_id,
    DATE_TRUNC(payment_date, MONTH) AS month_start,
    SUM(amount) AS total_amount
  FROM fct_payments
  GROUP BY location_id, month_start
)
SELECT
  p.location_id,
  p.month_start,
  p.total_amount,
  loc.country,
  loc.state
FROM location_payments AS p
INNER JOIN dim_locations AS loc USING (location_id)
```

---

## Performance — read [PERFORMANCE_BIGQUERY.md](references/PERFORMANCE_BIGQUERY.md) | [PERFORMANCE_POSTGRES.md](references/PERFORMANCE_POSTGRES.md)

Write performant SQL with platform-aware patterns. Choose the reference doc based on your project's database.

| Pattern | Recommendation |
|---------|----------------|
| `UNION ALL` | Default choice; `DISTINCT` only when needed |
| Window functions | Specify deterministic `ORDER BY` when ordering affects semantics |
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
  ) AS rn
FROM records
-- BigQuery/Snowflake: add QUALIFY rn = 1 here; other dialects: wrap in a subquery and filter on rn

-- Running totals
SELECT
  date,
  amount,
  SUM(amount) OVER (ORDER BY date) AS running_total
FROM transactions
```

### Conditional Aggregation

```sql
-- FILTER syntax (PostgreSQL)
SELECT
  COUNT(*) AS total_orders,
  COUNT(*) FILTER (WHERE status = 'completed') AS completed,
  SUM(total) FILTER (WHERE status = 'completed') AS completed_revenue
FROM orders

-- COUNTIF/SUMIF (BigQuery)
SELECT
  COUNT(*) AS total_orders,
  COUNTIF(status = 'completed') AS completed,
  SUM(IF(status = 'completed', total, 0)) AS completed_revenue
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
