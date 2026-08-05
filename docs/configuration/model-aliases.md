# Model Aliases

Model aliases map a short name to a model, so you can refer to models by a stable label instead of a `provider/modelId` string. They live in the `model_aliases` section of `~/.pi/basecamp/config.json`:

```json
{
  "model_aliases": {
    "fast": "anthropic/claude-haiku-4-5",
    "title": "openai/gpt-5.6-sol"
  }
}
```

A model value is either a `provider/modelId` pair (e.g. `anthropic/claude-haiku-4-5`) or a bare model id the registry can resolve.

## Managing aliases

In a session:

```
/model-aliases
```

Opens a TUI to list, add, edit, rename, and delete aliases (it needs an interactive UI).

From the shell (the same write path the TUI uses):

```bash
basecamp config alias set fast anthropic/claude-haiku-4-5
basecamp config alias rename fast quick
basecamp config alias remove fast
basecamp config alias          # interactive menu
basecamp config edit           # hand-edit config.json directly
```

Basecamp (Python) is the sole writer of `config.json`. The Pi extension reads aliases in-process, but every change (from the TUI or the CLI) goes through one flock'd settings write, so the file is never written from two places at once.

## Aliases basecamp resolves itself

Two aliases aren't just convenience labels: basecamp looks them up for specific jobs:

- **`fast`**: the model the [bash reviewer](../architecture/bash-reviewer.md) uses to judge each gated `bash` command. It runs on every command, so point it at a cheap, fast model. Without a `fast` alias the reviewer can't reach a model and falls back to fail-closed: gated commands are blocked rather than judged.
- **`title`**: the model that generates session titles. Optional: if unset, title generation uses the active session model.
