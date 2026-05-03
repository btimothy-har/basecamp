# TUI Components Reference

Components for building custom UI in extensions and tools.

Import from `@mariozechner/pi-tui`:

```typescript
import { Text, Box, Container, Spacer, Markdown, matchesKey, Key, truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";
```

## Component Interface

```typescript
interface Component {
  render(width: number): string[];    // Lines, each ≤ width
  handleInput?(data: string): void;   // Keyboard input when focused
  invalidate(): void;                 // Clear cached render state
}
```

**Critical:** Each line from `render()` must not exceed the `width` parameter.

## Built-in Components

| Component | Purpose |
|-----------|---------|
| `Text` | Multi-line text with word wrapping |
| `Box` | Container with padding and background |
| `Container` | Groups children vertically |
| `Spacer` | Empty vertical space |
| `Markdown` | Rendered markdown with syntax highlighting |
| `Image` | Terminal image rendering (Kitty, iTerm2, etc.) |

### Text

```typescript
const text = new Text("Hello", 1, 1);  // content, paddingX, paddingY
text.setText("Updated");
```

### Box

```typescript
const box = new Box(1, 1, (s) => bgGray(s));
box.addChild(new Text("Content", 0, 0));
```

### Container

```typescript
const container = new Container();
container.addChild(component1);
container.addChild(component2);
container.removeChild(component1);
```

## Keyboard Input

```typescript
import { matchesKey, Key } from "@mariozechner/pi-tui";

handleInput(data: string) {
  if (matchesKey(data, Key.up)) { ... }
  if (matchesKey(data, Key.enter)) { ... }
  if (matchesKey(data, Key.escape)) { ... }
  if (matchesKey(data, Key.ctrl("c"))) { ... }
  if (matchesKey(data, "shift+tab")) { ... }
}
```

## Common Patterns

### Pattern 1: Selection Dialog (SelectList)

```typescript
import { DynamicBorder } from "@mariozechner/pi-coding-agent";
import { Container, SelectList, Text, type SelectItem } from "@mariozechner/pi-tui";

const items: SelectItem[] = [
  { value: "a", label: "Option A", description: "First" },
  { value: "b", label: "Option B" },
];

const result = await ctx.ui.custom<string | null>((tui, theme, _kb, done) => {
  const container = new Container();
  container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));
  container.addChild(new Text(theme.fg("accent", theme.bold("Pick")), 1, 0));

  const list = new SelectList(items, Math.min(items.length, 10), {
    selectedPrefix: (t) => theme.fg("accent", t),
    selectedText: (t) => theme.fg("accent", t),
    description: (t) => theme.fg("muted", t),
    scrollInfo: (t) => theme.fg("dim", t),
    noMatch: (t) => theme.fg("warning", t),
  });
  list.onSelect = (item) => done(item.value);
  list.onCancel = () => done(null);
  container.addChild(list);
  container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));

  return {
    render: (w) => container.render(w),
    invalidate: () => container.invalidate(),
    handleInput: (data) => { list.handleInput(data); tui.requestRender(); },
  };
});
```

### Pattern 2: Async with Cancel (BorderedLoader)

```typescript
import { BorderedLoader } from "@mariozechner/pi-coding-agent";

const result = await ctx.ui.custom<string | null>((tui, theme, _kb, done) => {
  const loader = new BorderedLoader(tui, theme, "Loading...");
  loader.onAbort = () => done(null);
  fetchData(loader.signal).then(data => done(data)).catch(() => done(null));
  return loader;
});
```

### Pattern 3: Settings/Toggles (SettingsList)

```typescript
import { getSettingsListTheme } from "@mariozechner/pi-coding-agent";
import { SettingsList, type SettingItem } from "@mariozechner/pi-tui";

const items: SettingItem[] = [
  { id: "verbose", label: "Verbose", currentValue: "off", values: ["on", "off"] },
];

const list = new SettingsList(items, 15, getSettingsListTheme(),
  (id, val) => { /* handle change */ },
  () => done(undefined),
  { enableSearch: true },
);
```

### Pattern 4: Status & Widgets

```typescript
ctx.ui.setStatus("my-ext", theme.fg("accent", "● active"));  // footer
ctx.ui.setStatus("my-ext", undefined);                         // clear

ctx.ui.setWidget("id", ["Line 1", "Line 2"]);                 // above editor
ctx.ui.setWidget("id", lines, { placement: "belowEditor" });   // below editor
ctx.ui.setWidget("id", undefined);                              // clear
```

### Pattern 5: Custom Footer

```typescript
ctx.ui.setFooter((tui, theme, footerData) => ({
  invalidate() {},
  render(width) {
    return [`${ctx.model?.id} (${footerData.getGitBranch() || "no git"})`];
  },
  dispose: footerData.onBranchChange(() => tui.requestRender()),
}));
ctx.ui.setFooter(undefined);  // restore default
```

## Theme Colors

```typescript
// Foreground
theme.fg("accent", text)     theme.fg("success", text)
theme.fg("error", text)      theme.fg("warning", text)
theme.fg("muted", text)      theme.fg("dim", text)
theme.fg("toolTitle", text)

// Background
theme.bg("selectedBg", text)
theme.bg("toolSuccessBg", text)

// Styles
theme.bold(text)    theme.italic(text)    theme.strikethrough(text)

// Syntax highlighting
import { highlightCode, getLanguageFromPath } from "@mariozechner/pi-coding-agent";
const highlighted = highlightCode(code, "typescript", theme);
```

## Key Rules

1. **Always use theme from callback** — not imported directly
2. **Type DynamicBorder param** — `(s: string) => theme.fg("accent", s)`, not `(s) => ...`
3. **Call `tui.requestRender()`** after state changes in `handleInput`
4. **Return three-method object** — `{ render, invalidate, handleInput }`
5. **Use built-in components** — `SelectList`, `SettingsList`, `BorderedLoader` cover 90% of cases
6. **Line width** — never exceed `width` in render output
7. **Invalidate properly** — rebuild themed content on `invalidate()` for theme hot-reload
