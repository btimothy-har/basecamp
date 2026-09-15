---
description: "Avoid NOT IN with a subquery that can produce NULLs; prefer NOT EXISTS, EXCEPT, or an anti-join"
condition:
  - "(?i)\\bNOT\\s+IN\\s*\\(\\s*(?:SELECT|WITH)\\b"
scope: "tool:edit(*.sql), tool:write(*.sql)"
interruptMode: never
---

Under three-valued logic, `x NOT IN (subquery)` evaluates to NULL — not TRUE — for every row whenever the subquery produces even one NULL, so the predicate filters out everything. This is a common source of silently empty result sets.

NULL-safe alternatives by dialect:

```sql
-- Portable: NOT EXISTS is NULL-safe in every dialect
SELECT e.worker_id
FROM employees AS e
WHERE NOT EXISTS (
  SELECT 1
  FROM terminated_employees AS t
  WHERE t.worker_id = e.worker_id
);

-- BigQuery / Snowflake / Postgres: EXCEPT (DISTINCT) is NULL-safe and reads flat
SELECT worker_id FROM employees
EXCEPT DISTINCT
SELECT worker_id FROM terminated_employees;

-- Portable: anti-join
SELECT e.worker_id
FROM employees AS e
LEFT JOIN terminated_employees AS t
  ON e.worker_id = t.worker_id
WHERE t.worker_id IS NULL;
```

If you keep `NOT IN`, exclude NULLs inside the subquery explicitly: `WHERE worker_id NOT IN (SELECT worker_id FROM t WHERE worker_id IS NOT NULL)`.

## Exceptions

- `NOT IN` with a literal list (`NOT IN (1, 2, 3)`) contains no NULLs and is fine.
- A subquery over a column constrained `NOT NULL` cannot produce NULLs; the rewrite is then a readability preference, not a correctness fix.
