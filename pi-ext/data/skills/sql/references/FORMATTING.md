# Formatting

Consistent formatting improves readability and reduces cognitive load. These conventions must align with SQLFluff linting.

## Trailing Commas

**Always use trailing commas** after the last item in a SELECT clause (before FROM).

```sql
-- BAD: Missing trailing comma (linter error)
SELECT
  worker_id,
  full_name,
  department
FROM employees

-- GOOD: Trailing comma required
SELECT
  worker_id,
  full_name,
  department,
FROM employees

-- Also applies to SELECT *
SELECT *,
FROM employees
```

**Benefits**:
- Cleaner diffs when adding/removing columns
- Consistent formatting across all SELECT statements
- BigQuery and modern SQL dialects support this

## GROUP BY

### Group by Primary Keys Only

Only `GROUP BY` columns that form the logical primary key of the result. Use `ANY_VALUE()` for non-key columns to explicitly indicate no aggregation.

```sql
-- BAD: Groups by non-key columns
SELECT
  loc.location_id,
  loc.country,
  loc.state,
  DATE_TRUNC(sp.payment_date, MONTH) AS payment_month_start,
  SUM(sp.amount) AS salary_payment_amount,
FROM dim_employees AS e
INNER JOIN dim_locations AS loc ON e.location_id = loc.location_id
INNER JOIN fct_salary_payments AS sp ON e.employee_id = sp.employee_id
GROUP BY 1, 2, 3, 4  -- country and state are not primary keys

-- GOOD: Group only by primary keys (location_id, payment_month_start)
SELECT
  loc.location_id,
  ANY_VALUE(loc.country) AS country,
  ANY_VALUE(loc.state) AS state,
  DATE_TRUNC(sp.payment_date, MONTH) AS payment_month_start,
  SUM(sp.amount) AS salary_payment_amount,
FROM dim_employees AS e
INNER JOIN dim_locations AS loc ON e.location_id = loc.location_id
INNER JOIN fct_salary_payments AS sp ON e.employee_id = sp.employee_id
GROUP BY 1, 2
```

### Numeric vs Named References

Prefer **numeric references** (`GROUP BY 1, 2`) for DRY. Rules:

| Guideline | Example |
|-----------|---------|
| Group in order of SELECT, no gaps | `GROUP BY 1, 2` ✅, `GROUP BY 2, 1` ❌ |
| Primary keys first in SELECT | Makes numeric grouping intuitive |
| Avoid grouping many columns | `GROUP BY 1, 2, 3, 4, 5, 6, 7, 8` ❌ |

### Recommended Pattern: Aggregate Then Hydrate

For complex queries, separate aggregation from attribute hydration:

```sql
-- GOOD: Clean separation of aggregation and dimension lookup
WITH location_payments AS (
  SELECT
    loc.location_id,
    DATE_TRUNC(sp.payment_date, MONTH) AS payment_month_start,
    SUM(sp.amount) AS salary_payment_amount,
  FROM dim_employees AS e
  INNER JOIN dim_locations AS loc ON e.location_id = loc.location_id
  INNER JOIN fct_salary_payments AS sp ON e.employee_id = sp.employee_id
  GROUP BY 1, 2
)
-- Hydrate attributes after aggregation (no GROUP BY needed)
SELECT
  p.location_id,
  p.payment_month_start,
  p.salary_payment_amount,
  loc.country,
  loc.state,
FROM location_payments AS p
INNER JOIN dim_locations AS loc ON p.location_id = loc.location_id
```

### When GROUP BY ALL is Acceptable

Use `GROUP BY ALL` sparingly, primarily for:
- Dashboard data cubes from periodic snapshot fact tables
- Ad-hoc analysis with many degenerate dimensions

Avoid in dimensional warehouse models where explicit grouping makes intent clear.

## CASE Statements

### Multi-line Formatting

Format complex CASE statements for readability:

```sql
-- BAD: Single line is hard to read
SELECT
  CASE WHEN auto_resolve_at < CURRENT_TIMESTAMP() THEN LEAST(COALESCE(hours_to_resolution, 0), 1440) WHEN is_resolved THEN COALESCE(hours_to_resolution, 0) END AS final_hours_to_resolution

-- GOOD: Multi-line with comments
SELECT
  CASE
    -- Auto-resolved tickets are capped at 1440 hours (60 days)
    WHEN auto_resolve_at < CURRENT_TIMESTAMP()
      THEN LEAST(COALESCE(hours_to_resolution, 0), 1440)
    -- Manually resolved tickets use actual resolution time
    WHEN is_resolved
      THEN COALESCE(hours_to_resolution, 0)
    -- Open tickets have NULL resolution time
    ELSE NULL
  END AS final_hours_to_resolution,
```

### Business Logic with Variables

Document magic numbers and business rules using dbt variables:

```sql
-- BAD: Magic numbers without context
SELECT
  worker_id,
  CASE
    WHEN tenure_days < 90 THEN 0
    WHEN tenure_days < 365 THEN 0.5
    WHEN tenure_days < 730 THEN 1
    ELSE 1.5
  END AS pto_factor,

-- GOOD: Documented with variables (dbt)
-- PTO accrual rates per HR Policy HR-POL-2023-15
{% set pto_rates = {
    'probation': {'days': 90, 'rate': 0},
    'first_year': {'days': 365, 'rate': 0.5},
    'second_year': {'days': 730, 'rate': 1.0},
    'senior': {'rate': 1.5}
} %}

SELECT
  worker_id,
  CASE
    WHEN tenure_days < {{ pto_rates.probation.days }}
      THEN {{ pto_rates.probation.rate }}  -- Probation period
    WHEN tenure_days < {{ pto_rates.first_year.days }}
      THEN {{ pto_rates.first_year.rate }}  -- First year
    WHEN tenure_days < {{ pto_rates.second_year.days }}
      THEN {{ pto_rates.second_year.rate }}  -- Standard rate
    ELSE {{ pto_rates.senior.rate }}         -- Senior bonus
  END AS pto_accrual_factor,
```

## Keyword Conventions

| Convention | Example |
|------------|---------|
| Keywords uppercase | `SELECT`, `FROM`, `WHERE`, `JOIN` |
| Functions uppercase | `COUNT()`, `COALESCE()`, `DATE_TRUNC()` |
| Explicit `INNER JOIN` | Never bare `JOIN` |
| Explicit `AS` for aliases | `FROM table AS t`, `column AS alias` |

## Column Order

Organize columns in a logical order:

1. **Primary key(s)** first
2. **Foreign keys** next
3. **Core business columns**
4. **Computed/derived columns**
5. **Audit columns** (`created_at`, `updated_at`) last

```sql
SELECT
  -- Primary key
  order_id,
  -- Foreign keys
  customer_id,
  product_id,
  -- Core business columns
  quantity,
  unit_price,
  -- Computed columns
  quantity * unit_price AS line_total,
  -- Audit columns
  created_at,
  updated_at,
FROM orders
```
