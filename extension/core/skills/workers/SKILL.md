---
name: workers
description: "Monitor and manage dispatched worker agents. Invoke when checking on workers, listing active sessions, or coordinating dispatched tasks."
---

# Worker Management

Monitor dispatched worker agents.

## List Workers

Use the `worker` tool:
```
worker({ action: "list" })
```

Or the slash command: `/workers`

## Browse Agents

Browse available agent definitions: `/agents`

## Worker Lifecycle

```
running → closed
```

- **running** — worker is active (Kitty pane or background process)
- **closed** — worker session ended (marked automatically on shutdown)

## Pane Workers

Pane workers run in visible Kitty windows. The user can:
- See the worker's output in real time
- Type into the worker's session to redirect or clarify
- Close the pane to terminate the worker

## Background Workers

Background workers run as headless `pi -p` processes. Check their output logs in the worker's temp directory (shown when dispatched).
