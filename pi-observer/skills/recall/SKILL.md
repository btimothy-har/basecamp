---
name: recall
description: "Semantic memory over past sessions. Use when you need prior decisions, context, constraints, patterns, or actions from earlier work."
---

# Recall

Use the `recall` tool to search semantic memory from past sessions.

## When to Use

Invoke recall when:

- The user asks what happened before or refers to prior work
- You need previous decisions, constraints, patterns, or implementation context
- You are about to change code that may have project-specific history
- Current context is insufficient but past sessions likely contain the answer

Do not use recall for information that is already available in the current conversation, repository files, or tool results.

## Modes

- `search` — topic search over past session summaries or artifacts
- `list` — browse recent/date-filtered memory without a query
- `session` — fetch full detail after finding a relevant session ID

## Common Patterns

Start broad, then fetch detail:

1. `recall({ mode: "search", query: "<topic>" })`
2. If a result looks relevant, call `recall({ mode: "session", sessionId: "<id>" })`

Use `types` when the user asks for a specific kind of memory:

- `decisions` — what was decided and why
- `knowledge` — facts, patterns, and implementation context
- `constraints` — limitations, requirements, and boundaries
- `actions` — what was done or planned

Use `crossProject: true` only when context may live outside the current project.

## Mode Selection

| Need | Mode |
|------|------|
| Find sessions or artifacts about a topic | `search` |
| Find decisions about a topic | `search` with `types: ["decisions"]` |
| Browse recent work or a date range | `list` |
| Inspect artifacts from a known session | `list` with `sessionId` |
| Read full structured detail for a session | `session` |

## Automatic Behaviors

- Searches and lists are scoped to the current project by default
- The current session is excluded from search results
