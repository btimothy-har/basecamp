---
description: "Prefer named CTEs over anonymous derived tables in FROM or JOIN clauses"
condition:
  - "(?is)\\b(?:FROM|JOIN)\\s*\\(\\s*(?:SELECT|WITH)\\b"
scope: "tool:edit(*.sql), tool:write(*.sql)"
interruptMode: never
---

Anonymous derived tables hide a logical query step inside `FROM (...)` or `JOIN (...)`. Give the step a name with a CTE when that name makes the query's grain, filtering, or purpose easier to follow.

```sql
-- Harder to scan: the intermediate relation has no durable name
SELECT recent_orders.customer_id
FROM (
  SELECT customer_id, created_at
  FROM orders
  WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
) AS recent_orders;

-- Prefer: the relation and its purpose are visible up front
WITH recent_orders AS (
  SELECT customer_id, created_at
  FROM orders
  WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
)
SELECT recent_orders.customer_id
FROM recent_orders;
```

A CTE is especially useful when the nested query establishes a grain, is referenced more than once, or needs a meaningful name to explain why its transformations belong together.

## Exceptions

- Keep `EXISTS` and `NOT EXISTS` subqueries when correlation to the outer row is the clearest expression of the predicate.
- Small scalar subqueries can remain inline when naming them would add more indirection than clarity.
- `LATERAL` joins and `APPLY` expressions may need nesting because they depend on the current outer row.
- Preserve nesting required by the target dialect, query planner, generated-SQL framework, or a measured performance constraint.
- If the derived table is genuinely clearer than a distant one-use CTE, retain it and make its alias describe the relation's grain or purpose.
