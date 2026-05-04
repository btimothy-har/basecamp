# Themes Reference

Themes are JSON files defining 51 color tokens for the pi TUI.

## Format

```json
{
  "$schema": "https://raw.githubusercontent.com/badlogic/pi-mono/main/packages/coding-agent/src/modes/interactive/theme/theme-schema.json",
  "name": "my-theme",
  "vars": {
    "primary": "#00aaff",
    "secondary": 242
  },
  "colors": {
    "accent": "primary",
    "border": "primary",
    ...all 51 tokens...
  }
}
```

- `name` — required, must be unique
- `vars` — optional reusable color definitions
- `colors` — all 51 tokens required
- `$schema` — enables editor auto-completion

## Color Values

| Format | Example | Description |
|--------|---------|-------------|
| Hex | `"#ff0000"` | 6-digit hex RGB |
| 256-color | `242` | xterm palette index (0-255) |
| Variable | `"primary"` | Reference to a `vars` entry |
| Default | `""` | Terminal's default color |

## Required Color Tokens (51 total)

### Core UI (11)

`accent`, `border`, `borderAccent`, `borderMuted`, `success`, `error`, `warning`, `muted`, `dim`, `text`, `thinkingText`

### Backgrounds & Content (11)

`selectedBg`, `userMessageBg`, `userMessageText`, `customMessageBg`, `customMessageText`, `customMessageLabel`, `toolPendingBg`, `toolSuccessBg`, `toolErrorBg`, `toolTitle`, `toolOutput`

### Markdown (10)

`mdHeading`, `mdLink`, `mdLinkUrl`, `mdCode`, `mdCodeBlock`, `mdCodeBlockBorder`, `mdQuote`, `mdQuoteBorder`, `mdHr`, `mdListBullet`

### Tool Diffs (3)

`toolDiffAdded`, `toolDiffRemoved`, `toolDiffContext`

### Syntax Highlighting (9)

`syntaxComment`, `syntaxKeyword`, `syntaxFunction`, `syntaxVariable`, `syntaxString`, `syntaxNumber`, `syntaxType`, `syntaxOperator`, `syntaxPunctuation`

### Thinking Level Borders (6)

`thinkingOff`, `thinkingMinimal`, `thinkingLow`, `thinkingMedium`, `thinkingHigh`, `thinkingXhigh`

### Bash Mode (1)

`bashMode`

### HTML Export (optional)

```json
{
  "export": {
    "pageBg": "#18181e",
    "cardBg": "#1e1e24",
    "infoBg": "#3c3728"
  }
}
```

## Locations

| Location | Scope |
|----------|-------|
| `~/.pi/agent/themes/*.json` | Global |
| `.pi/themes/*.json` | Project |
| Packages | Via `pi.themes` in `package.json` |
| Built-in | `dark`, `light` |

Select via `/settings` or `"theme": "my-theme"` in `settings.json`.

**Hot reload:** Editing the active custom theme file triggers immediate reload.

## Design Tips

- **Dark terminals:** Bright, saturated colors with higher contrast
- **Light terminals:** Darker, muted colors with lower contrast
- **Color harmony:** Start from a base palette (Nord, Gruvbox, Tokyo Night), define in `vars`, reference consistently
- **Test thoroughly:** Check with different message types, tool states, markdown, diffs, long wrapped text
- **VS Code:** Set `terminal.integrated.minimumContrastRatio` to `1` for accurate colors
