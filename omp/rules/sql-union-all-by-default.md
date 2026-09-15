---
description: "Default to UNION ALL; write UNION DISTINCT explicitly only when deduplication is intended"
condition:
  - "(?i)\\bUNION\\b(?!\\s+(ALL|DISTINCT)\\b)"
scope: "tool:edit(*.sql), tool:write(*.sql)"
interruptMode: never
---

A bare `UNION` means `UNION DISTINCT`: the engine sorts or hashes the combined rows to remove duplicates — an expensive pass that is usually unintended, and one that can silently drop rows you expected to keep. Spell out what you mean:

```sql
-- Preferred default: no dedup pass, rows kept as-is
SELECT worker_id, 'active' AS status FROM active_workers
UNION ALL
SELECT worker_id, 'terminated' AS status FROM terminated_workers

-- When deduplication is genuinely required, say so and why
SELECT email FROM employees
UNION DISTINCT  -- employees and contractors overlap
SELECT email FROM contractors
```

`UNION ALL` is valid in every dialect. `UNION DISTINCT` is the explicit spelling in BigQuery, Snowflake, Postgres, and standard SQL; in dialects that don't accept the `DISTINCT` keyword (e.g. older MySQL), a bare `UNION` with a short comment stating that dedup is intended is the equivalent.

## Exceptions

- The two sets are provably disjoint by construction (e.g. partitioned by a literal status column): `UNION ALL` is still the right spelling — that's the point of the default.
- Duplicates are expected and unwanted: use `UNION DISTINCT` (or bare `UNION` where the keyword is unsupported) and add a comment explaining the overlap.
