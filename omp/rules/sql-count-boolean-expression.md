---
description: "Avoid COUNT of a raw boolean comparison; use COUNTIF, FILTER, or SUM(CASE ...) instead"
condition:
  - "(?i)\\bCOUNT\\s*\\(\\s*[A-Za-z_][\\w.]*\\s*(<=|>=|<>|!=|=|<|>)"
scope: "tool:edit(*.sql), tool:write(*.sql)"
interruptMode: never
---

`COUNT(a > b)` counts the rows where the comparison evaluates to non-NULL — it silently ignores rows where either operand is NULL, and to most readers it looks like it counts TRUE results. The intent is clearer, and identical in result, when written as conditional aggregation:

```sql
-- Unclear: counts non-NULL comparison results
SELECT COUNT(status = 'completed') AS completed FROM orders

-- BigQuery
SELECT COUNTIF(status = 'completed') AS completed FROM orders

-- Postgres, Snowflake, DuckDB, standard SQL
SELECT COUNT(*) FILTER (WHERE status = 'completed') AS completed FROM orders

-- Portable fallback (MySQL, older dialects)
SELECT SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed FROM orders
```

All three forms preserve the same NULL semantics — a comparison that evaluates to NULL is not counted — while saying so explicitly.

## Exceptions

- `COUNTIF(...)`, `COUNT(*) FILTER (...)`, `COUNT(CASE WHEN ...)`, and `COUNT(DISTINCT ...)` are the preferred spellings, not the smell.
- `COUNT(column)` and `COUNT(*)` are ordinary aggregates; the `COUNT(col)` vs `COUNT(*)` NULL distinction is a separate, legitimate choice.
- If your dialect has none of the alternatives and `SUM(CASE ...)` is unavailable in context (rare), keep the comparison form with a comment noting that NULL comparisons are excluded.
