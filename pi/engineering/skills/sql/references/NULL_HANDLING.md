# NULL Handling

SQL's three-valued logic (TRUE, FALSE, NULL) requires explicit handling. Be consistent and intentional about NULL behavior.

## Boolean Expressions

Use direct boolean expressions instead of wrapping in COALESCE or IF.

| Pattern | Use |
|---------|-----|
| `IS NULL`, `IS NOT NULL` | Existence checks |
| Direct boolean expression | `column IS NULL AS is_missing` |
| `COALESCE(bool_col, FALSE)` | Convert NULL to FALSE for a nullable boolean column |

```sql
-- BAD: Overly complex
SELECT
  COALESCE(is_active = TRUE, FALSE) AS is_active_flag,
  COALESCE(concluded_at IS NULL, FALSE) AS is_active_project,
  IF(score IS NOT NULL, TRUE, FALSE) AS has_score,
FROM projects

-- GOOD: Direct expressions
SELECT
  COALESCE(is_active, FALSE) AS is_active_flag,  -- Appropriate for nullable bool
  concluded_at IS NULL AS is_active_project,     -- Direct boolean
  score IS NOT NULL AS has_score,                -- Direct boolean
FROM projects
```

## Aggregations and NULLs

Different aggregate functions handle NULLs differently. Be explicit about your intentions.

| Function | NULL Behavior |
|----------|---------------|
| `COUNT(column)` | Ignores NULLs |
| `COUNT(*)` | Counts all rows including NULLs |
| `SUM`, `AVG` | Ignores NULLs |
| `MIN`, `MAX` | Ignores NULLs |

```sql
-- BAD: Inconsistent NULL handling
SELECT
  department,
  AVG(salary) AS avg_salary,
  SUM(bonus) / COUNT(*) AS avg_bonus,  -- Wrong if bonus can be NULL
  COUNT(worker_id) AS worker_count,     -- May not behave as expected
FROM employees
GROUP BY department

-- GOOD: Explicit NULL handling
SELECT
  department,
  AVG(salary) AS avg_salary,           -- NULLs ignored (document if intentional)
  AVG(bonus) AS avg_bonus,             -- Use AVG for nullable columns
  COUNT(worker_id) AS worker_count,    -- Won't count NULL worker_ids
  COUNT(*) AS total_rows,              -- Counts all rows
  -- When you need custom NULL handling
  SUM(COALESCE(bonus, 0)) / COUNT(*) AS avg_bonus_null_as_zero,
FROM employees
GROUP BY department
```

## COALESCE Patterns

### Simple Defaults

Use COALESCE for providing default values:

```sql
-- Direct default value
COALESCE(middle_name, '') AS middle_name

-- Chained fallbacks (evaluated left to right)
COALESCE(preferred_name, legal_name, 'Unknown') AS display_name
```

### Repeated Patterns

When using COALESCE repeatedly for the same default, consider extracting to a CTE:

```sql
-- BAD: Repetitive COALESCE
SELECT
  ticket_id,
  COALESCE(requester.level, 'Not Applicable') AS requester_level,
  COALESCE(requester.discipline, 'Not Applicable') AS requester_discipline,
  COALESCE(requester.subdiscipline, 'Not Applicable') AS requester_subdiscipline,
  COALESCE(requester.group_name, 'Not Applicable') AS requester_group,
FROM tickets

-- GOOD: Grouped in CTE with STRUCT
WITH enriched_tickets AS (
  SELECT
    ticket_id,
    STRUCT(
      COALESCE(requester.level, 'Not Applicable') AS level,
      COALESCE(requester.discipline, 'Not Applicable') AS discipline,
      COALESCE(requester.subdiscipline, 'Not Applicable') AS subdiscipline,
      COALESCE(requester.group_name, 'Not Applicable') AS group_name,
    ) AS requester_info,
  FROM tickets
)
SELECT
  ticket_id,
  requester_info.level AS requester_level,
  requester_info.discipline AS requester_discipline,
FROM enriched_tickets
```

## JSON NULL Handling

JSON operations require extra care due to nested NULLs and missing keys.

### SAFE Functions

Use `SAFE.` prefixed functions to handle invalid JSON gracefully:

```sql
-- BAD: Can fail on NULL or malformed JSON
SELECT
  sla_policy_id,
  JSON_VALUE(sla_target.priority) AS priority,
  CAST(JSON_VALUE(sla_target.respond_within) AS INT) / 3600 AS response_hours,
FROM policies

-- GOOD: Safe extraction with defaults
SELECT
  sla_policy_id,
  COALESCE(JSON_VALUE(sla_target, '$.priority'), 'default') AS priority,
  SAFE_CAST(JSON_VALUE(sla_target, '$.respond_within') AS INT64) / 3600 AS response_hours,
FROM policies
WHERE sla_target IS NOT NULL
```

### Key Patterns

| Scenario | Pattern |
|----------|---------|
| Missing key | `COALESCE(JSON_VALUE(...), 'default')` |
| Invalid type | `SAFE_CAST(JSON_VALUE(...) AS type)` |
| NULL JSON column | `WHERE json_col IS NOT NULL` |
| Nested NULLs | Check each level: `IF(obj IS NOT NULL, JSON_VALUE(...))` |

## NULL-Safe Comparisons

### Equality

Standard `=` returns NULL when either operand is NULL. Use NULL-safe alternatives:

```sql
-- Standard equality (NULL = NULL returns NULL, not TRUE)
WHERE a = b

-- NULL-safe equality (returns TRUE if both are NULL)
WHERE a IS NOT DISTINCT FROM b

-- Explicit NULL handling
WHERE (a = b OR (a IS NULL AND b IS NULL))
```

### NOT IN with NULLs

`NOT IN` returns NULL if any value in the list is NULL. Prefer `EXCEPT` or explicit handling:

```sql
-- BAD: NOT IN with potential NULLs
SELECT worker_id
FROM employees
WHERE worker_id NOT IN (
  SELECT worker_id FROM terminated_employees
)

-- GOOD: EXCEPT is NULL-safe
SELECT worker_id
FROM employees
EXCEPT DISTINCT
SELECT worker_id
FROM terminated_employees

-- GOOD: Explicit NULL handling
SELECT e.worker_id
FROM employees AS e
LEFT JOIN terminated_employees AS t
  ON e.worker_id = t.worker_id
WHERE t.worker_id IS NULL
```
