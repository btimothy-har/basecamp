---
description: "Spell out INNER JOIN instead of a bare JOIN keyword"
condition:
  - "(?im)^[ \\t]*JOIN\\b"
scope: "tool:edit(*.sql), tool:write(*.sql)"
interruptMode: never
---

A bare `JOIN` is an `INNER JOIN` — the keywords are equivalent in every mainstream dialect. Spelling out `INNER JOIN` costs one word and removes the ambiguity a reader has to resolve, especially in queries that mix join types:

```sql
-- Less clear
FROM orders AS o
JOIN users AS u ON o.user_id = u.id
LEFT JOIN addresses AS a ON u.address_id = a.id

-- Clearer: every join states its type
FROM orders AS o
INNER JOIN users AS u ON o.user_id = u.id
LEFT JOIN addresses AS a ON u.address_id = a.id
```

## Exceptions

- `CROSS JOIN` is a distinct join type with no `INNER` spelling; leave it as is.
- Match the project: if the surrounding codebase and its lint config deliberately use bare `JOIN`, consistency with the existing style wins over this preference.
