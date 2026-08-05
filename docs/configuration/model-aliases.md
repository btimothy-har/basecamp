# Model aliases

Basecamp resolves model aliases through the `/model-aliases` in-session command, which lets you list, add, edit, and remove aliases.

```
/model-aliases          # TUI: list, add, edit, remove
```

Aliases are stored in the `model_aliases` section of `~/.pi/basecamp/config.json`. Pi reads them in-process, but Basecamp is the sole writer — the TUI persists each change by shelling out to `basecamp config alias set|remove`, so the file is always written through the same locked settings path the CLI uses.
