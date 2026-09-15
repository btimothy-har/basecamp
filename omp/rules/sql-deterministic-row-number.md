---
description: "Give every ROW_NUMBER() window an ORDER BY so the numbering is deterministic"
condition:
  - "(?i)ROW_NUMBER\\s*\\(\\s*\\)\\s*OVER\\s*\\((?:(?!ORDER\\s+BY)(?:[^()]|\\([^()]*\\)))*\\)"
scope: "tool:edit(*.sql), tool:write(*.sql)"
interruptMode: never
---

`ROW_NUMBER()` without `ORDER BY` assigns numbers in whatever order the engine happens to read the partition. The result is nondeterministic: the same query can keep a different row on every run, which is exactly the failure mode when the numbering drives deduplication (`rn = 1`).

```sql
-- Bad: which row gets rn = 1 is arbitrary and unstable
ROW_NUMBER() OVER (PARTITION BY project_id, user_id) AS rn

-- Good: ordering states the keep-rule; a unique tiebreaker makes it total
ROW_NUMBER() OVER (
  PARTITION BY project_id, user_id
  ORDER BY created_at DESC, worker_id
) AS rn
```

Write the `ORDER BY` so it expresses the business rule (most recent, highest priority, …) and append a unique column as a tiebreaker so ties can't flip between runs.

## Exceptions

- When the numbering is used only to distinguish rows and no filter or downstream logic depends on which row gets which number, any ordering is semantically fine — but an explicit `ORDER BY` (or a comment stating the numbering is intentionally arbitrary) still documents that the choice was deliberate.
- Ordering by a constant to silence linters (e.g. `ORDER BY (SELECT NULL)`) declares "arbitrary on purpose"; prefer a real ordering when one exists.
