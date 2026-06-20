# Prompt Templates Reference

Prompt templates are reusable Markdown snippets that expand into full prompts via `/name` in the editor.

## Format

```markdown
---
description: Review staged git changes
---
Review the staged changes (`git diff --cached`). Focus on:
- Bugs and logic errors
- Security issues
- Error handling gaps
```

- Filename becomes the command: `review.md` → `/review`
- `description` is optional — if missing, first non-empty line is used
- Autocomplete shows available templates with descriptions

## Arguments

| Syntax | Meaning |
|--------|---------|
| `$1`, `$2`, ... | Positional arguments |
| `$@` or `$ARGUMENTS` | All arguments joined |
| `${@:N}` | Arguments from Nth position (1-indexed) |
| `${@:N:L}` | L arguments starting at N |

### Example

```markdown
---
description: Create a React component
---
Create a React component named $1 with features: ${@:2}
```

Usage: `/component Button "onClick handler" "disabled support"`

## Locations

| Location | Scope |
|----------|-------|
| `~/.pi/agent/prompts/*.md` | Global |
| `.pi/prompts/*.md` | Project |
| Packages | Via `pi.prompts` in `package.json` |

Discovery is **non-recursive**. For templates in subdirectories, add them explicitly via `prompts` settings or package manifest.

## Best Practices

- Keep descriptions concise but descriptive for autocomplete
- Use `$@` for flexible multi-argument patterns
- Use `${@:2}` when the first argument has a fixed role (e.g., component name)
- Place project-specific templates in `.pi/prompts/` and commit them
- Place personal templates in `~/.pi/agent/prompts/`
