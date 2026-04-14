---
name: recall
description: "Semantic memory over past coding sessions. Invoke when the agent needs to recall decisions, patterns, context, or actions from past sessions, or when the user asks about previous work."
---

# Recall

Semantic search over extracted knowledge from past coding sessions.

## Retrieval Modes

**Semantic search** (`recall search`): hybrid KNN+FTS retrieval over session summaries or artifacts. Requires a query string. Use when looking for sessions or knowledge related to a topic.

**Parametric list** (`recall list`): date-ordered browsing with strict filters. No query needed. Use when browsing by time range, session, or artifact type.

**Session detail** (`recall session`): full structured detail for a specific session ID.

## Commands

```bash
# Semantic search — find sessions by topic
recall search "<query>"
recall search "<query>" --type decisions
recall search "<query>" --type knowledge,decisions
recall search "<query>" --after 2026-03-01
recall search "<query>" --after 2026-03-01 --before 2026-03-15

# Parametric list — browse by date/filters (no query needed)
recall list --after 2026-03-01
recall list --after 2026-03-01 --before 2026-03-15
recall list --type decisions --after 2026-03-01
recall list --session <session_id>
recall list --session <session_id> --type decisions

# Session detail — full structured output
recall session <session_id>
```

## Flags

### `recall search`

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--type` | `-t` | — | Comma-separated: `knowledge`, `decisions`, `constraints`, `actions` |
| `--cross-project` | `-x` | off | Search across all projects (default: current project only) |
| `--top-k` | `-k` | 10 | Max results |
| `--threshold` | — | 0.3 | Minimum relevance score (0–1) |
| `--after` | — | — | Only include results after this date (YYYY-MM-DD or ISO datetime) |
| `--before` | — | — | Only include results before this date (YYYY-MM-DD or ISO datetime) |

### `recall list`

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--type` | `-t` | — | Comma-separated: `knowledge`, `decisions`, `constraints`, `actions` |
| `--cross-project` | `-x` | off | List across all projects |
| `--top-k` | `-k` | 10 | Max results |
| `--after` | — | — | Only include results after this date (YYYY-MM-DD or ISO datetime) |
| `--before` | — | — | Only include results before this date (YYYY-MM-DD or ISO datetime) |
| `--session` | — | — | Filter artifacts within a specific session |

## When to Use Each Mode

| Goal | Command |
|------|---------|
| "What sessions dealt with X?" | `recall search "X"` |
| "What did we decide about X?" | `recall search "X" --type decisions` |
| "What do we know about X?" | `recall search "X" --type knowledge` |
| "What did we do about X?" | `recall search "X" --type actions` |
| "What limitations exist for X?" | `recall search "X" --type constraints` |
| "What sessions happened this week?" | `recall list --after 2026-03-20` |
| "What decisions were made recently?" | `recall list --type decisions --after 2026-03-01` |
| "What artifacts exist for session X?" | `recall list --session <id>` |
| "Search only recent sessions" | `recall search "X" --after 2026-03-01` |
| Context might exist in other projects | add `--cross-project` |

## Two-Step Pattern

When you need full context, not just snippets:

1. `recall search "<query>"` → find relevant session IDs from summaries
2. `recall session <session_id>` → get the full structured session (summary, knowledge, decisions, constraints, actions)

## Output Format

All output is JSON.

**Search results** (semantic, scored):
```json
{
  "results": [
    {
      "session_id": "abc123",
      "text": "...",
      "title": "Short descriptive title",
      "type": "summary" | "decisions" | "knowledge" | "actions" | "constraints",
      "score": 0.82,
      "created_at": "2026-01-15T10:30:00"
    }
  ],
  "count": 3
}
```

**List results** (parametric, date-ordered, no score):
```json
{
  "results": [
    {
      "session_id": "abc123",
      "text": "...",
      "title": "Short descriptive title",
      "started_at": "2026-01-15T10:30:00",
      "ended_at": "2026-01-15T11:45:00"
    }
  ],
  "count": 3
}
```

**Session detail** (`recall session <id>`):
```json
{
  "session_id": "abc123",
  "started_at": "...",
  "ended_at": "...",
  "sections": {
    "summary": "...",
    "decisions": "...",
    "knowledge": "...",
    "actions": "...",
    "constraints": "..."
  }
}
```

## Automatic Behaviors

- **Project scoping** — searches and lists are automatically scoped to `BASECAMP_REPO` (current project)
- **Session exclusion** — the current session is automatically excluded from search results
