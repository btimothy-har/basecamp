---
name: recall
description: "Semantic memory over past Claude Code sessions. Invoke when Claude needs to recall decisions, patterns, context, or actions from past sessions, or when the user asks about previous work."
---

# Recall

Semantic search over extracted knowledge from past Claude Code sessions.

## Retrieval Modes

**Summary search** (default — no `--type`): searches session summaries. Use for orientation — finding which sessions dealt with a topic.

**Artifact search** (`--type`): searches specific extracted artifacts within sessions. Use when you need a particular kind of knowledge.

## Commands

```bash
# Find relevant sessions by topic
recall search "<query>"

# Drill into a session's full structured detail
recall session <session_id>

# Search for specific artifact types directly
recall search "<query>" --type decisions
recall search "<query>" --type knowledge,decisions
```

## Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--type` | `-t` | — | Comma-separated: `knowledge`, `decisions`, `constraints`, `actions` |
| `--cross-project` | `-x` | off | Search across all projects (default: current project only) |
| `--top-k` | `-k` | 10 | Max results |
| `--threshold` | — | 0.3 | Minimum relevance score (0–1) |

## When to Use Each Mode

| Goal | Command |
|------|---------|
| "What sessions dealt with X?" | `recall search "X"` |
| "What did we decide about X?" | `recall search "X" --type decisions` |
| "What do we know about X?" | `recall search "X" --type knowledge` |
| "What did we do about X?" | `recall search "X" --type actions` |
| "What limitations exist for X?" | `recall search "X" --type constraints` |
| Context might exist in other projects | add `--cross-project` |

## Two-Step Pattern

When you need full context, not just snippets:

1. `recall search "<query>"` → find relevant session IDs from summaries
2. `recall session <session_id>` → get the full structured session (summary, knowledge, decisions, constraints, actions)

## Output Format

All output is JSON.

**Summary/artifact search:**
```json
{
  "results": [
    {
      "session_id": "abc123",
      "text": "...",
      "type": "summary" | "decisions" | "knowledge" | "actions" | "constraints",
      "score": 0.82,
      "created_at": "2026-01-15T10:30:00"
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

- **Project scoping** — searches are automatically scoped to `BASECAMP_REPO` (current project)
- **Session exclusion** — the current session is automatically excluded from results
