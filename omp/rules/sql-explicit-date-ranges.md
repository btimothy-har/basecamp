---
description: "Prefer half-open range predicates (>= / <) over BETWEEN for date and timestamp bounds"
condition:
  - "(?i)\\bBETWEEN\\s+(DATE|DATETIME|TIMESTAMP)\\s+'"
  - "(?i)\\bBETWEEN\\s+'\\d{4}-\\d{2}-\\d{2}"
  - "(?i)\\bBETWEEN\\s+[\\w.()]+\\s+AND\\s+(DATE\\s+|DATETIME\\s+|TIMESTAMP\\s+)?'\\d{4}-\\d{2}-\\d{2}"
  - "(?i)\\b\\w+(_date|_at|_time|_timestamp)\\s+BETWEEN\\b"
scope: "tool:edit(*.sql), tool:write(*.sql)"
interruptMode: never
---

`BETWEEN` is inclusive on both ends. For timestamp and datetime columns that silently mis-buckets boundary rows: `BETWEEN '2024-01-01' AND '2024-12-31'` excludes everything after midnight on the 31st, and adjacent months spelled `... AND '2024-02-01'` double-count the boundary instant. Prefer a half-open range, which is exact for both dates and timestamps:

```sql
-- Bad: inclusive end misbehaves on timestamps
WHERE created_at BETWEEN '2024-01-01' AND '2024-01-31'

-- Good: half-open range, correct for DATE and TIMESTAMP alike
WHERE created_at >= '2024-01-01'
  AND created_at < '2024-02-01'
```

A half-open range also keeps index use: the predicate stays a plain comparison on the column, which every dialect's planner handles directly.

## Exceptions

- Numeric and lexical ranges (`BETWEEN 1 AND 10`, `BETWEEN 'A' AND 'M'`) are what `BETWEEN` is for — no change needed there.
- Pure `DATE` columns where both bounds are whole days and the inclusive end is exactly what you mean are correct as written; half-open is still preferred for consistency with the timestamp case.
- Some engines offer typed literals (`DATE '2024-01-01'` in BigQuery/Postgres/standard SQL) — the same half-open advice applies to them.
