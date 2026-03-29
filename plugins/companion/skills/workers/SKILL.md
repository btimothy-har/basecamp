---
name: workers
description: "Manage dispatched worker sessions — communicate, monitor, and coordinate. Invoke when managing active workers: checking status, sending instructions, asking questions, or reading inbox messages."
---

# Task Management

Manage dispatched worker sessions: communicate, monitor status, and coordinate work.

## Communication

### ask — query a session's context (synchronous)

Fork the target's conversation history and get a response. The target session is not modified — they don't know you asked.

```bash
task ask --name <task-name> "What's your current progress?"
task ask --name parent "Which approach did the user choose?"
```

Returns the response text to stdout.

### send — deliver a message to a session's inbox (fire-and-forget)

Write a message to the target's inbox. Delivered by a hook on the target session.

```bash
task send --name <task-name> "Pivot to approach B instead."
task send --name parent "I've completed the refactor."
```

**`--immediate`** — deliver at the next tool call instead of next turn boundary:
```bash
task send --name <task-name> --immediate "Stop — critical bug found."
```

### inbox — check for incoming messages

```bash
task inbox              # read and consume all pending messages
task inbox --peek       # show message count without consuming
```

### When to use ask vs send

| Need | Use | Why |
|------|-----|-----|
| Get information from another session | `ask` | Synchronous, returns response, non-disruptive |
| Deliver an instruction or update | `send` | Fire-and-forget, delivered by hook |
| Urgent interruption | `send --immediate` | Delivered at next tool call |
| Check if anyone messaged you | `inbox --peek` | Quick count check |
| Read your messages | `inbox` | Consumes and prints all pending |

### Target resolution

- `--name <task-name>`: targets a worker by task name
- `--name parent`: targets the orchestrator session (only available in worker sessions)

## Monitoring

```bash
task list              # tasks for current session
task list --all        # all tasks across sessions for the project
```

### Lifecycle

```
staged → dispatched → closed
```

- **staged**: created but not yet spawned (`task create` without `--dispatch`)
- **dispatched**: terminal pane running
- **closed**: worker session ended

## Patterns

### Check on a worker

```bash
task ask --name worker-a3f21b-fix-auth "Are you blocked on anything?"
```

### Redirect a worker mid-task

```bash
task send --name worker-a3f21b-fix-auth "Requirements changed: use approach B instead of A."
```

### Worker reports back to orchestrator

From within a worker session:
```bash
task send --name parent "Completed the migration. 3 files changed, all tests passing."
```

### Poll for messages during long work

```bash
task inbox --peek  # 0 = no messages, continue working
task inbox         # read and act on messages
```
