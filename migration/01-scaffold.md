# 01 — Scaffold the Extension Package

## Goal

Create the `extension/` directory at the repo root with the pi package structure, entry point, and TypeScript configuration.

## Context

Pi extensions are TypeScript modules loaded via [jiti](https://github.com/unjs/jiti) — no compilation step needed. A pi package declares resources in `package.json` under the `pi` key. The entry point exports a default function receiving `ExtensionAPI`.

This extension will be passed to pi at launch time by basecamp's CLI (via `-e` flag or settings), so it does NOT need to be `pi install`-ed.

## What to Create

```
extension/
├── package.json
├── src/
│   └── index.ts           # Entry point — imports and registers all modules
├── skills/                 # Empty for now (populated by 08-skills.md)
│   └── .gitkeep
└── prompts/                # Empty for now (prompt templates can be added later)
    └── .gitkeep
```

### `package.json`

```json
{
  "name": "basecamp-extension",
  "version": "1.0.0",
  "description": "Basecamp extension for pi — session lifecycle, git protection, observer integration, engineering skills.",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./src"],
    "skills": ["./skills"],
    "prompts": ["./prompts"]
  },
  "peerDependencies": {
    "@mariozechner/pi-coding-agent": "*",
    "@sinclair/typebox": "*"
  }
}
```

### `src/index.ts`

Create the entry point with stub imports. Each module will be implemented by subsequent migration steps. For now, create placeholder functions that do nothing:

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

// Each module exports a registration function: (pi: ExtensionAPI) => void
// Uncomment as each migration step completes:
// import { registerLifecycle } from "./lifecycle";
// import { registerGitProtect } from "./git-protect";
// import { registerObserver } from "./observer";
// import { registerMessaging } from "./messaging";
// import { registerWorkers } from "./workers";
// import { registerNudges } from "./nudges";
// import { registerContext } from "./context";

export default function (pi: ExtensionAPI) {
  // registerLifecycle(pi);
  // registerGitProtect(pi);
  // registerContext(pi);
  // registerObserver(pi);
  // registerMessaging(pi);
  // registerWorkers(pi);
  // registerNudges(pi);
}
```

## Acceptance Criteria

- [ ] `extension/package.json` exists with valid `pi` manifest
- [ ] `extension/src/index.ts` exports a default function accepting `ExtensionAPI`
- [ ] `extension/skills/` and `extension/prompts/` directories exist
- [ ] The extension can be loaded by pi without errors: `pi -e ./extension`
- [ ] No dependencies on any existing plugin directory
