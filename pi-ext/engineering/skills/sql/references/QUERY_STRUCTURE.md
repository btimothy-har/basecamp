# Query Structure

Structure SQL queries for clarity, maintainability, and testability.

## Common Table Expressions (CTEs)

CTEs break complex queries into logical, testable units. Each CTE should represent a single concept with a clear grain.

### Naming CTEs

CTE names are like variable names: **nouns** that describe *what* the result is, not *how* it's computed.

| Principle | Example |
|-----------|---------|
| Describe the grain and content | `active_users`, `monthly_totals` |
| Use 5 or fewer words in snake_case | `order_line_items` not `all_the_line_items_from_orders` |
| Avoid stop-words and prepositions | `region_sales` not `sales_by_region_for_quarter` |
| Final CTE can be generic | `result`, `records` for easy debugging |

```sql
-- BAD: Cryptic names
WITH t1 AS (...),
     t2 AS (...),
     final AS (...)
SELECT * FROM final

-- GOOD: Descriptive names
WITH pending_orders AS (...),
     completed_orders AS (...),
     all_orders AS (...)
SELECT * FROM all_orders
```

### Structuring with CTEs

Use CTEs to decompose complex operations into logical steps:

1. **One concept per CTE** — each CTE represents a logical entity
2. **Access to intermediate results** — smaller CTEs can be inspected independently
3. **Document aggregation logic** — explain what each step accomplishes

```sql
-- BAD: Monolithic aggregation
SELECT
  category,
  COUNT(DISTINCT id) AS total_items,
  COUNT(DISTINCT IF(is_featured, id, NULL)) AS featured_count,
  AVG(IF(is_active, price, NULL)) AS avg_active_price,
FROM products
GROUP BY category

-- GOOD: Logical decomposition
WITH enriched_products AS (
  -- Add computed fields at detail level
  SELECT
    *,
    created_at > CURRENT_DATE - 30 AS is_new,
    rating >= 4.5 AS is_highly_rated,
  FROM products
),

category_summaries AS (
  -- Aggregate by category
  SELECT
    category,
    COUNT(DISTINCT id) AS total_items,
    COUNT(DISTINCT IF(is_featured, id, NULL)) AS featured_count,
  FROM enriched_products
  GROUP BY 1
)

SELECT * FROM category_summaries
```

## SELECT Patterns

### Avoid SELECT * at Boundaries

Wildcard `SELECT *` is only acceptable **internally** within a query, never when reading source data or specifying final output.

| Use Case | SELECT * Allowed? |
|----------|-------------------|
| Reading from source table | ❌ No |
| Internal CTE transformations | ✅ Yes |
| Final query output | ❌ No (unless final CTE lists columns) |

```sql
-- BAD: SELECT * at input boundary
WITH source_data AS (
  SELECT * FROM schema.table_name  -- Don't do this
)
SELECT *, col_a || col_b AS combined,
FROM source_data

-- GOOD: Explicit column selection at boundaries
WITH source_data AS (
  SELECT
    id,
    col_a,
    col_b,
  FROM schema.table_name
)
SELECT
  id,
  col_a || col_b AS combined,
FROM source_data
```

**Exception**: `SELECT *` in internal CTEs (UNIONs, transformations) reduces cognitive load:

```sql
WITH source_a AS (
  SELECT id, type, created_at, FROM schema.table_a
),
source_b AS (
  SELECT id, type, created_at, FROM schema.table_b
),
-- SELECT * is acceptable here (internal transformation)
combined AS (
  SELECT * FROM source_a
  UNION ALL
  SELECT * FROM source_b
),
enriched AS (
  SELECT c.*, lkp.label,
  FROM combined AS c
  INNER JOIN schema.lookup_table AS lkp
    ON lkp.type = c.type
)
-- Final output is explicit
SELECT
  id,
  type,
  created_at,
  label,
FROM enriched
```

## Table Aliases

Aliases should be **short** and **mnemonic**: 2-3 characters, mnemonically tied to the table name.

| Table | Good Alias | Bad Alias |
|-------|------------|-----------|
| `dim_customers` | `dc`, `c` | `a`, `b`, `table1` |
| `fct_order_items` | `oi` | `l` (looks like 1/I) |

**Self-joins**: Use `snake_case` suffixes to disambiguate:

```sql
SELECT
  e.name,
  e_mgr.name AS manager_name,
  e_dir.name AS director_name,
FROM employees AS e
LEFT JOIN employees AS e_mgr
  ON e.manager_id = e_mgr.id
LEFT JOIN employees AS e_dir
  ON e_mgr.manager_id = e_dir.id
```

## JOINs

### Explicit JOIN Syntax

Always use explicit `INNER JOIN`, never implicit `JOIN`.

```sql
-- BAD: Implicit JOIN type
FROM orders o
JOIN users u ON o.user_id = u.id

-- GOOD: Explicit JOIN with meaningful aliases
FROM orders AS o
INNER JOIN users AS buyer
  ON o.user_id = buyer.id
LEFT JOIN users AS seller
  ON o.seller_id = seller.id
```

### JOIN Organization

1. **Order JOINs logically** — main tables first, lookups last
2. **Comment non-obvious JOINs** — explain the relationship
3. **Use meaningful aliases** — indicate the table's role in the query

```sql
FROM orders AS o
-- Get buyer details (always present)
INNER JOIN users AS buyer
  ON o.user_id = buyer.id
-- Get seller details (may be a platform sale)
LEFT JOIN users AS seller
  ON o.seller_id = seller.id
-- Get shipping address (optional)
LEFT JOIN addresses AS ship_addr
  ON o.shipping_address_id = ship_addr.id
```

## Set Operations

### UNION ALL vs UNION DISTINCT

Default to `UNION ALL`. Use `UNION DISTINCT` only when deduplication is explicitly needed.

| Operator | Use When |
|----------|----------|
| `UNION ALL` | Sets are mutually exclusive (default) |
| `UNION DISTINCT` | Duplicates are expected and need removal |

```sql
-- GOOD: UNION ALL for mutually exclusive sets
SELECT id, 'pending' AS status
FROM pending_orders
UNION ALL
SELECT id, 'completed' AS status
FROM completed_orders

-- GOOD: UNION DISTINCT with explanation
SELECT email
FROM customers
UNION DISTINCT  -- Some users may appear in both tables
SELECT email
FROM newsletter_subscribers
```
