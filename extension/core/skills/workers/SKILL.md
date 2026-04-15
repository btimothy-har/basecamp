---
name: workers
description: "Monitor and manage dispatched worker agents. Invoke when checking on workers or reviewing recent agent runs."
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
running → completed
running → failed
```

- **running** — subagent process is active
- **completed** — subagent finished successfully (exit code 0)
- **failed** — subagent exited with an error

Workers run synchronously — the `worker` tool blocks until the subagent completes and returns its output as the tool result.
