# Performance (PostgreSQL)

PostgreSQL-specific optimizations for transactional databases.

## Indexing Principles

### Index for Access Patterns

Create indexes based on WHERE, JOIN, and ORDER BY usage:

```sql
-- Index for common query patterns
CREATE INDEX ix_users_created_at ON users (created_at DESC);
CREATE INDEX ix_posts_author_published ON posts (author_id, published_at DESC);

-- Partial index for specific conditions
CREATE INDEX ix_orders_pending ON orders (created_at)
WHERE status = 'pending';

-- Covering index (includes all needed columns)
CREATE INDEX ix_users_email_name ON users (email) INCLUDE (name);
```

### Composite Index Order

Place high-cardinality and equality columns first:

```sql
-- Query: WHERE user_id = ? AND created_at > ?
-- Index: equality column first, then range
CREATE INDEX ix_orders_user_created ON orders (user_id, created_at);

-- Query: WHERE status = ? ORDER BY created_at
-- Index: filter column first, then sort column
CREATE INDEX ix_orders_status_created ON orders (status, created_at);
```

### Avoid Functions on Indexed Columns

Functions prevent index usage:

```sql
-- BAD: Can't use index on created_at
WHERE created_at::date = '2024-01-01'
WHERE LOWER(email) = 'user@example.com'

-- GOOD: Range query uses index
WHERE created_at >= '2024-01-01' AND created_at < '2024-01-02'

-- GOOD: Expression index for function-based queries
CREATE INDEX ix_users_email_lower ON users (LOWER(email));
```

### Index Types

| Index Type | Use Case |
|------------|----------|
| B-tree (default) | Equality and range queries |
| GIN | JSONB, arrays, full-text search |
| GiST | Geometric data, full-text search |
| BRIN | Large tables with natural ordering |
| Hash | Equality-only (rare) |

```sql
-- GIN index for JSONB
CREATE INDEX ix_users_metadata ON users USING GIN (metadata);

-- GIN index for array containment
CREATE INDEX ix_posts_tags ON posts USING GIN (tags);

-- BRIN for time-series data (much smaller than B-tree)
CREATE INDEX ix_events_created ON events USING BRIN (created_at);
```

## Query Analysis

### EXPLAIN ANALYZE

Profile before optimizing:

```sql
EXPLAIN ANALYZE
SELECT u.name, COUNT(p.id)
FROM users AS u
LEFT JOIN posts AS p ON p.author_id = u.id
GROUP BY u.id;
```

Key metrics to watch:
- **Seq Scan** — full table scan (may need index)
- **Index Scan** — using index efficiently
- **Nested Loop** — can be slow for large datasets
- **Hash Join** — efficient for larger joins
- **Sort** — may spill to disk if `work_mem` too low

### EXPLAIN Options

```sql
-- Full analysis with buffers and timing
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT * FROM users WHERE email = 'test@example.com';

-- Output as JSON for tooling
EXPLAIN (ANALYZE, FORMAT JSON)
SELECT * FROM users WHERE id = 1;
```

## Connection and Memory

### Connection Pooling

Use connection pooling (PgBouncer, application-level) for high-concurrency workloads:

```sql
-- Check current connections
SELECT count(*) FROM pg_stat_activity;

-- Check max connections setting
SHOW max_connections;
```

### Work Memory

Increase `work_mem` for complex sorts and hash operations:

```sql
-- Session-level (for specific complex query)
SET work_mem = '256MB';

-- Check current setting
SHOW work_mem;
```

## Common Performance Issues

| Issue | Symptom | Fix |
|-------|---------|-----|
| Missing index | Seq Scan on large table | Add appropriate index |
| Index bloat | Slow index scans | REINDEX or VACUUM |
| Lock contention | Slow writes | Reduce transaction scope |
| N+1 queries | Many small queries | Batch with JOINs or CTEs |
| Slow sorts | Sort spilling to disk | Increase `work_mem` |

## Maintenance

```sql
-- Analyze table statistics (for query planner)
ANALYZE users;

-- Reclaim space and update statistics
VACUUM ANALYZE users;

-- Rebuild indexes
REINDEX INDEX ix_users_email;

-- Check index usage
SELECT 
  schemaname,
  tablename,
  indexname,
  idx_scan,
  idx_tup_read
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- Find missing indexes (sequential scans on large tables)
SELECT 
  schemaname,
  relname,
  seq_scan,
  seq_tup_read,
  idx_scan
FROM pg_stat_user_tables
WHERE seq_scan > 0
ORDER BY seq_tup_read DESC;
```
