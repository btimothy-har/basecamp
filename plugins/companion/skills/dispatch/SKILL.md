---
name: dispatch
description: "Dispatch parallel Claude workers via terminal panes (Kitty or tmux). Invoke when work can be parallelized into independent tasks, or when the user calls /dispatch with a task description."
argument-hint: "<task description>"
---

# Dispatch

Launch a parallel Claude worker session in a new terminal pane.

## Input

$ARGUMENTS

## Process

### 1. Build the prompt

Task: $ARGUMENTS

Write a **self-contained brief** for the worker using the task above and relevant context from the current conversation. The worker has no conversation history — the prompt must carry everything:

- Clear, specific objective
- Relevant file paths, modules, or context already discovered
- Constraints or decisions already made
- What "done" looks like

### 2. Derive a task name

Short, kebab-case identifier from the task description. Appended to an auto-generated UUID prefix (e.g., `worker-a3f21b-fix-auth-bug`) which becomes the directory name and pane title.

Examples: `fix-auth-bug`, `add-unit-tests`, `update-docs`

### 3. Create and dispatch

```bash
basecamp task create --name <task-name> --dispatch <<'PROMPT'
<prompt content>
PROMPT
# or with opus: basecamp task create --name <task-name> --dispatch --model opus <<'PROMPT'
```

To stage a task without dispatching immediately (dispatch later with `basecamp task dispatch --name <task-name>`):

```bash
basecamp task create --name <task-name> <<'PROMPT'
<prompt content>
PROMPT
```

### 4. Verify

```bash
basecamp task list
```

## Model selection

Workers default to **sonnet** — sufficient for most tasks.

Use `--model opus` when the task requires deep reasoning:
- Complex architectural decisions or multi-file refactors with tricky dependencies
- Debugging subtle issues across a large codebase
- Tasks where getting it wrong means expensive rework

## Constraints

- **Terminal multiplexer required** — Kitty (with remote control) or tmux. `basecamp claude` wraps in tmux automatically when neither is detected
- **Workers are interactive** — the user can see and intervene in any pane
- **No shared state** — each worker operates independently; coordinate via filesystem if needed
- **Project scope** — workers run in the same project directory as the main session
